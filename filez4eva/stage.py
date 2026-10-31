"""Shared logic for the stage commands (transcribe, classify, review and
stow): which documents a run works on (new files from a path, the
documents already in the intake, or the ones named with --ingested), the
order of work (ingest, then a transcribe batch, then a per-file cycle
through the later stages), the `results` in each document's X.yml
sidecar, and per-file errors."""

from pathlib import Path
from textwrap import fill

import yaml
from wizlib.parser import WizParser
from wizlib.ui.shell_ui import Emphasis

from filez4eva.command import Filez4EvaCommand
from filez4eva.command import ingest_command
from filez4eva.command.ingest_command import (
    files, in_intake, ingest_file, intake_dir, is_ingested, sidecar_path,
    top_level_documents, write_sidecar)
from filez4eva.error import Filez4EvaError


# Every stage, in pipeline order. A document's progress is the latest one
# recorded in its results.
STAGES = ('ingest', 'transcribe', 'classify', 'review', 'stow')

# The stage before which a document's cabinet must be known
CLASSIFY = 'classify'

# Stage of the batch that runs on every selected document before any later
# stage starts on any of them
BATCH_STAGE = 'transcribe'

# Key under `results` of what is given for a document before it is
# classified: when, and its cabinet
GIVEN = 'given'

# Line width of the generated paragraphs of `filez4eva COMMAND --help`
HELP_WIDTH = 68

# How to point a stage command at documents already in the intake
INTAKE_HINT = ("to work on documents already in the intake, give no path "
               "(all of them) or --ingested NAME")


def resolve_path(arg: str, intake: Path) -> Path:
    """Return the path given to a stage command, expanded and absolute but
    not resolved, so messages and output name files the way the user and
    the configuration do (on macOS, for example, /var is a link to
    /private/var). A path is for new files only. Only the check below
    resolves the path in full (symbolic links and '..'), so a link into the
    intake is seen for what it is. Raises Filez4EvaError if the path doesn't
    exist, or if it is the intake, a file in it, or anything under it."""
    path = Path(arg).expanduser().absolute()
    if not path.exists():
        raise Filez4EvaError(f"{path} must exist")
    if path.resolve().is_relative_to(intake.resolve()):
        raise Filez4EvaError(
            f"{path} is in the intake {intake}; a path is for new files "
            f"only: {INTAKE_HINT}")
    return path


def new_files(path: Path, intake: Path) -> list:
    """Return the new files for a path outside the intake, in name order,
    listed once before anything moves: a file on its own, or the non-hidden
    regular files at the top level of a directory (subdirectories, hidden
    files and symbolic links are left alone)"""
    if not path.is_dir():
        return [path]
    return top_level_documents(path, intake)[1]


def find_ingested(name: str, intake: Path) -> Path:
    """Return the document in the intake named by --ingested: a file name in
    the intake, or a path to it. Raises Filez4EvaError if it isn't a
    document ingested in the intake (a non-hidden regular file directly in
    the intake, with its X.yml sidecar)."""
    given = Path(name).expanduser()
    if len(given.parts) == 1 and not given.is_absolute():
        path = intake / given
    else:
        path = given.absolute()
    if path.name.startswith('.') or path.is_symlink() \
            or not in_intake(path, intake) or not is_ingested(path):
        raise Filez4EvaError(
            f"--ingested {name}: not a document ingested in the intake "
            f"{intake}")
    return intake / path.name


def load_sidecar(path: Path) -> dict:
    """Return the sidecar of an ingested document, with `results` always a
    mapping. Unlike read_sidecar, raises Filez4EvaError if the sidecar can't
    be read or isn't a mapping, so a stage never overwrites it."""
    sidecar = sidecar_path(path)
    try:
        data = yaml.safe_load(sidecar.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise Filez4EvaError(
            f"Could not read sidecar {sidecar}: {error}") from error
    if not isinstance(data, dict):
        raise Filez4EvaError(f"Sidecar {sidecar} must be a YAML mapping")
    results = data.get('results')
    if results is None:
        results = data['results'] = {}
    if not isinstance(results, dict):
        raise Filez4EvaError(
            f"results in sidecar {sidecar} must be a mapping")
    return data


def saved_cabinet(results: dict):
    """Return the cabinet saved for a document, from its results: the
    cabinet given before classify (results.given.cabinet). Sidecars from
    before results.given have none; for them, the cabinet confirmed at
    review (results.review.cabinet), then the one chosen at classify
    (results.classify.cabinet), stand in for it. None if there is none."""
    for stage in (GIVEN, 'review', 'classify'):
        record = results.get(stage)
        cabinet = record.get('cabinet') if isinstance(record, dict) \
            else None
        if isinstance(cabinet, str) and cabinet.strip():
            return cabinet.strip()
    return None


def stage_result(path: Path, stage: str):
    """Return results.<stage> from a document's sidecar, or None if that
    stage hasn't run"""
    return load_sidecar(path)['results'].get(stage)


def record_result(path: Path, stage: str, result: dict):
    """Save results.<stage> in a document's sidecar, keeping the rest"""
    data = load_sidecar(path)
    data['results'][stage] = result
    write_sidecar(path, data)


def progress(path: Path) -> int:
    """The position in STAGES of the latest stage recorded for a document,
    or -1 if none is, or its sidecar can't be read (the run reports that
    when it gets to the document)"""
    try:
        results = load_sidecar(path)['results']
    except Filez4EvaError:
        return -1
    return max((index for index, stage in enumerate(STAGES)
                if results.get(stage) is not None), default=-1)


def has_stage(path: Path, stage: str) -> bool:
    """True if a document has results.<stage>; False if not, or if its
    sidecar can't be read"""
    try:
        return stage_result(path, stage) is not None
    except Filez4EvaError:
        return False


class NotDone(Exception):
    """Raised by act when a document was dealt with but the stage didn't
    run on it, e.g. the operator skipped or deleted it at review. The
    document gets no results.<stage>; label (e.g. 'Skipped') is counted in
    the status."""

    def __init__(self, label: str):
        super().__init__(label)
        self.label = label


class StopRun(Exception):
    """Raised by act to end the run early (the operator quit). The current
    document and the rest are left as they are; 'Quit' ends the status."""


class StageCommand(Filez4EvaCommand):
    """Base for the stage commands. A subclass sets `name`, `stage` (its
    key under `results`), `done` (the status label, e.g. 'Transcribed') and
    `requires` (the earlier stage commands, after ingest), and implements
    `act`."""

    # Key under `results` in X.yml
    stage: str = None

    # Status label for documents the stage acted on
    done: str = None

    # Earlier StageCommand classes, in order, whose results a document needs
    # before this stage runs (ingest always comes first)
    requires: tuple = ()

    # Act only on documents whose earlier stages are all done
    only: bool = False

    # New files: a file or directory outside the intake. None for documents
    # already in the intake.
    path: str = None

    # Names (or paths) of documents in the intake to work on, in order, from
    # repeated --ingested flags
    ingested: list = None

    # Cabinet given with --cabinet for every document in the run (stages
    # after transcribe only)
    cabinet: str = None

    @classmethod
    def selection_help(cls) -> str:
        """The part of `filez4eva COMMAND --help` on which documents a run
        works on and in what order, shared by the stage commands"""
        paragraphs = [
            "Which documents: given a path (a file, or a directory, top "
            "level only), the new files there, which are ingested first; "
            "a path in the intake is an error. With no path, the documents "
            "already in the intake; nothing is ingested, and a file there "
            "without an X.yml sidecar is left alone with a note. With "
            "--ingested NAME (repeatable), just those documents in the "
            "intake, in the order given."]
        if cls.stage != BATCH_STAGE:
            paragraphs.append(
                "Cabinet: each document's cabinet is chosen before it is "
                "classified, and saved in its X.yml sidecar: the cabinet "
                "already saved for it; otherwise --cabinet; otherwise the "
                "only cabinet, if just one is configured; otherwise a "
                "Cabinet prompt for that document (empty input skips it). "
                "The model never picks the cabinet. A --cabinet that "
                "differs from the one saved for a document fails that "
                "document.")
            later = [c.name for c in cls.requires
                     if c.stage != BATCH_STAGE] + [cls.name]
            paragraphs.append(
                "Order: every document that needs it is transcribed first, "
                "in one batch. Then the documents are taken one at a time "
                f"through the remaining stages ({', '.join(later)}), each "
                "one finishing before the next one starts. "
                "With no path, the most advanced documents come first (the "
                "latest stage they've had, then name order).")
        return '\n\n'.join(fill(text, HELP_WIDTH) for text in paragraphs)

    @classmethod
    def add_args(cls, parser: WizParser):
        super().add_args(parser)
        parser.description = (parser.description or '') + '\n\n' + \
            cls.selection_help()
        earlier = ', '.join(['ingest'] + [c.name for c in cls.requires])
        parser.add_argument(
            '--only', action='store_true',
            help="act only on documents that have had every earlier stage "
            f"({earlier}); skip the rest instead of running the missing "
            "stages")
        parser.add_argument(
            '--ingested', action='append', metavar='NAME',
            help="work on this document already in the intake (its file "
            "name there, or a path to it) and no other (repeatable; taken "
            "in the order given; not with a path)")
        if cls.stage != BATCH_STAGE:
            parser.add_argument(
                '--cabinet', '-c', metavar='NAME',
                help="the cabinet of every document in the run that has "
                "none saved yet, instead of a prompt for each one")
        parser.add_argument(
            'path', nargs='?',
            help="new files: a file, or a directory (top level only), "
            "outside the intake; they are ingested first. Default: the "
            "documents already in the intake")

    def handle_vals(self):
        super().handle_vals()
        if self.path and self.ingested:
            raise Filez4EvaError(
                "--ingested names documents already in the intake; it "
                "can't be combined with a path (new files)")
        if self.stage != BATCH_STAGE:
            # Imported here: filez4eva.stow imports the transcribe command,
            # which imports this module
            from filez4eva.stow import load_cabinets
            # Check the cabinets and the --cabinet name before any file is
            # touched
            self.cabinets = load_cabinets(self.app.config)
            if self.provided('cabinet') and \
                    self.cabinet not in self.cabinets:
                raise Filez4EvaError(
                    f"Unknown cabinet {self.cabinet}; known: "
                    + ', '.join(sorted(self.cabinets)))

    def check_cabinet(self, path: Path):
        """Raise Filez4EvaError if the run gives a cabinet (--cabinet)
        that differs from the one saved for the document"""
        if not self.provided('cabinet'):
            return
        saved = saved_cabinet(load_sidecar(path)['results'])
        if saved is not None and saved != self.cabinet:
            raise Filez4EvaError(
                f"Cabinet {self.cabinet} given, but {path.name} already has "
                f"cabinet {saved}")

    def ask_cabinet(self, path: Path, results: dict) -> str:
        """Prompt for a document's cabinet, with tab completion of the
        names, until a configured one is entered. Empty input skips the
        document (NotDone)."""
        ingest = results.get('ingest')
        original = ingest.get('original-name') \
            if isinstance(ingest, dict) else None
        self.app.ui.send(f"{path.name} ({original})" if original
                         else path.name)
        names = sorted(self.cabinets)
        while True:
            name = (self.app.ui.get_text('Cabinet: ', names) or '').strip()
            if not name:
                self.app.ui.send('Skipped', Emphasis.INFO)
                raise NotDone('Skipped')
            if name in self.cabinets:
                return name
            self.app.ui.send('Cabinet must be one of: ' + ', '.join(names),
                             Emphasis.PRINCIPAL)

    def give_cabinet(self, path: Path, missing: list):
        """Before a document is classified (by this command or an earlier
        one in missing), make sure its cabinet is saved as
        results.given: the cabinet already saved for it, otherwise
        --cabinet, otherwise the only cabinet, otherwise a prompt (empty
        input skips the document, writing nothing)"""
        if CLASSIFY not in [command.stage for command in missing] + \
                [self.stage]:
            return
        results = load_sidecar(path)['results']
        if saved_cabinet(results) is not None:
            return
        if self.provided('cabinet'):
            name = self.cabinet
        elif len(self.cabinets) == 1:
            name = next(iter(self.cabinets))
        else:
            name = self.ask_cabinet(path, results)
        record_result(path, GIVEN, {
            'at': ingest_command.now().isoformat(timespec='seconds'),
            'cabinet': name})

    def act(self, path: Path) -> str:  # pragma: no cover
        """Run the stage on an ingested document that hasn't had it yet,
        record results.<stage>, and return the line to print on stdout.
        May raise NotDone to leave the document without the stage, or
        StopRun to end the run."""
        raise NotImplementedError

    @property
    def already(self) -> str:
        """Status label for documents that already had the stage"""
        return f"Already {self.done.lower()}"

    def select(self, intake: Path) -> tuple:
        """Return (documents, message): the documents the run works on,
        listed before anything moves, and what to say if there are none.
        With --ingested, the named documents in the order given; with a
        path, the new files there, in name order; otherwise the documents
        already in the intake, in name order, with a note on stderr for
        each file there that isn't ingested (it is left alone)."""
        if self.ingested:
            todo = []
            for name in self.ingested:
                document = find_ingested(name, intake)
                if document not in todo:
                    todo.append(document)
            return todo, None
        if self.path:
            path = resolve_path(self.path, intake)
            return new_files(path, intake), \
                f"Nothing to {self.name}: no files in {path}"
        todo, strays = top_level_documents(intake, intake)
        for stray in strays:
            self.app.ui.send(
                f"Not ingested: {stray} (left alone; filez4eva ingest "
                f"{intake} ingests it)", Emphasis.INFO)
        reason = 'no documents ingested in the intake' if strays \
            else 'the intake is empty'
        return todo, f"Nothing to {self.name}: {reason}"

    def skip(self, document: Path, reason: str):
        """Leave a document alone under --only, with a note on stderr.
        reason is the earlier stage it lacks, e.g. 'ingested'."""
        self.skipped[reason] = self.skipped.get(reason, 0) + 1
        self.app.ui.send(f"Skipped {document}: not {reason} yet",
                         Emphasis.INFO)

    def fail(self, entry: list, error: Exception):
        """Report a document that failed; the run carries on without it"""
        document, current = entry
        self.failed += 1
        moved = f" (now {current})" if current != document else ''
        self.app.ui.send(
            f"Failed to {self.name} {document}{moved}: {error}",
            Emphasis.ERROR)

    def ingest_all(self, work: list, intake: Path) -> list:
        """Ingest every new file (under --only, skip them all instead).
        Return the entries that are now in the intake."""
        kept = []
        for entry in work:
            if self.only:
                self.skip(entry[0], 'ingested')
                continue
            try:
                entry[1] = ingest_file(entry[0], intake, {})
            except (Filez4EvaError, OSError) as error:
                self.fail(entry, error)
                continue
            self.counts['Ingested'] += 1
            kept.append(entry)
        return kept

    def transcribe_all(self, work: list, transcriber, lines: list) -> list:
        """The transcribe batch: transcribe every document that still needs
        it, before any later stage starts. For transcribe itself, that is
        the whole run. Under --only, a later stage transcribes nothing.
        Return the entries that didn't fail."""
        if transcriber is None or (self.only and transcriber is not self):
            return work
        kept = []
        for entry in work:
            current = entry[1]
            try:
                if stage_result(current, transcriber.stage) is not None:
                    if transcriber is self:
                        self.counts[self.already] += 1
                elif stage_result(current, self.stage) is None:
                    line = transcriber.act(current)
                    self.counts[transcriber.done] += 1
                    if transcriber is self:
                        lines.append(line)
            except (Filez4EvaError, OSError) as error:
                self.fail(entry, error)
                continue
            kept.append(entry)
        return kept

    def order(self, work: list) -> list:
        """The order of the per-file cycle: as given for --ingested, name
        order for new files, and for the documents in the intake the most
        advanced first (by the latest stage they've had), in name order
        within each group"""
        if self.ingested or self.path:
            return work
        return sorted(work, key=lambda entry: (-progress(entry[1]),
                                               entry[1].name))

    def cycle(self, work: list, earlier: list, lines: list):
        """The per-file cycle: take each document through the stages it
        still lacks, up to this one, before the next document starts (under
        --only, skip it with a note instead). A --cabinet that differs from
        the document's saved cabinet fails it (check_cabinet), and its
        cabinet is saved before it is classified (give_cabinet). StopRun
        from act ends the run."""
        for entry in work:
            document, current = entry
            try:
                self.check_cabinet(current)
                if stage_result(current, self.stage) is not None:
                    self.counts[self.already] += 1
                    continue
                missing = [command for command in earlier
                           if stage_result(current, command.stage) is None]
                if missing and self.only:
                    self.skip(document, missing[0].done.lower())
                    continue
                self.give_cabinet(current, missing)
                for command in missing:
                    command.act(current)
                    self.counts[command.done] += 1
                lines.append(self.act(current))
                self.counts[self.done] += 1
            except NotDone as outcome:
                self.counts[outcome.label] = \
                    self.counts.get(outcome.label, 0) + 1
            except (Filez4EvaError, OSError) as error:
                self.fail(entry, error)

    def run(self) -> str:
        """Run the stage on the selected documents (see select): ingest the
        new files, transcribe every document that needs it, then take each
        document in turn through the remaining stages up to this one (see
        cycle). If there is nothing to do, say so in the status. Set the
        status and return the lines from act. If any document fails, it is
        reported and the run carries on; at the end the lines are printed
        and Filez4EvaError is raised. act may leave a document without the
        stage (NotDone, counted under its label) or end the run early
        (StopRun)."""
        earlier = [command(self.app) for command in self.requires]
        # Check the earlier stages' configuration before any file is touched
        for command in earlier:
            command.handle_vals()
        intake = intake_dir(self.app.config)
        todo, empty = self.select(intake)
        if not todo:
            self.status = empty
            return ''
        # With --cabinet, every document is checked against it, even when
        # there is nothing else to do
        if not self.path and not self.provided('cabinet'):
            done = sum(has_stage(document, self.stage) for document in todo)
            if done == len(todo):
                self.status = (f"Nothing to {self.name} ({files(done)} "
                               f"already {self.done.lower()})")
                return ''
        transcriber = self if self.stage == BATCH_STAGE else next(
            (c for c in earlier if c.stage == BATCH_STAGE), None)
        self.counts = {'Ingested': 0}
        self.counts.update({command.done: 0 for command in earlier})
        self.counts.update({self.done: 0, self.already: 0})
        # Skipped documents, by the earlier stage they lack
        self.skipped = {}
        self.failed = 0
        lines = []
        # [document as selected, its current path]
        work = [[document, document] for document in todo]
        stopped = False
        if self.path:
            work = self.ingest_all(work, intake)
        work = self.transcribe_all(work, transcriber, lines)
        if transcriber is not self:
            try:
                self.cycle(self.order(work), earlier, lines)
            except StopRun:
                stopped = True
        if self.failed:
            if lines:
                print('\n'.join(lines))
            raise Filez4EvaError(
                f"{self.failed} of {files(len(todo))} failed to {self.name}")
        labels = [f"{label} {files(count)}"
                  for label, count in self.counts.items() if count]
        labels += [f"Skipped {files(count)} (not {reason})"
                   for reason, count in self.skipped.items()]
        if stopped:
            labels.append('Quit')
        self.status = ' | '.join(labels) or f"No files to {self.name}"
        return '\n'.join(lines)
