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
from filez4eva.fields import DATE_FIELD, FIELD_NAME, Field, check_value


# Every stage, in pipeline order. A document's progress is the latest one
# recorded in its results.
STAGES = ('ingest', 'transcribe', 'classify', 'review', 'stow')

# The stage before which a document's cabinet must be known
CLASSIFY = 'classify'

# Stage of the batch that runs on every selected document before any later
# stage starts on any of them
BATCH_STAGE = 'transcribe'

# Key under `results` of what is given for a document before it is
# classified: when, its cabinet, and the field values given for it (data)
GIVEN = 'given'

# Stages that given data can stand in for: a document with its cabinet and
# every field given is recorded as reviewed without the model or the menu
GIVEN_STAGES = (CLASSIFY, 'review')

# Status label for documents recorded straight from complete given data
GIVEN_DONE = 'Given'

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


def given_values(results: dict) -> dict:
    """Return the field values given for a document (results.given.data),
    by field name, as text; empty if there are none"""
    given = results.get(GIVEN)
    data = given.get('data') if isinstance(given, dict) else None
    if not isinstance(data, dict):
        return {}
    return {str(name): str(value) for name, value in data.items()
            if value is not None}


def reached(results: dict, stage: str) -> bool:
    """True if a document has results.<stage>, or, for classify, a review:
    a record from complete given data is a review with no classify"""
    if results.get(stage) is not None:
        return True
    return stage == CLASSIFY and results.get('review') is not None


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
    """True if a document has results.<stage> (see reached); False if
    not, or if its sidecar can't be read"""
    try:
        return reached(load_sidecar(path)['results'], stage)
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

    # Cabinet given with --cabinet (or `cabinet` on stdin) for every
    # document in the run (stages after transcribe only)
    cabinet: str = None

    # Given data for every document in the run (stages after transcribe
    # only): the date, as YYYYMMDD, from --date
    date: str = None

    # NAME=VALUE strings from repeated --field flags
    field: list = None

    # The field values given for every document in the run, by name (date
    # included), checked and normalized; set by read_given
    given_data: dict = None

    # Names in given_data from flags, which the document's cabinet must
    # have; names only on stdin that its cabinet lacks are ignored
    flagged: tuple = ()

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
            paragraphs.append(
                "Given data: --cabinet, --date, --field NAME=VALUE "
                "(repeatable) and a YAML record on stdin (`cabinet`, and "
                "the fields under `data`) apply to every document in the "
                "run; flags win over stdin. The values are saved with each "
                "document before it is classified, and the model is asked "
                "only for the cabinet's other fields. Review shows them "
                "marked (given). With the cabinet and every field given, "
                "the record is saved as reviewed with no model call and no "
                "menu. A value that differs from one already given for a "
                "document, or any value for a document already classified, "
                "fails that document (equal values are fine).")
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
                '--date', '-d', metavar='DATE',
                help="given data: the date of every document in the run, as "
                "YYYYMMDD")
            parser.add_argument(
                '--field', '-f', action='append', metavar='NAME=VALUE',
                help="given data: the value of a field for every document "
                "in the run (repeatable)")
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
            # Check the cabinets before any file is touched (read_given
            # checks the --cabinet name, also before)
            self.cabinets = load_cabinets(self.app.config)

    def read_given(self):
        """Read the given data for the run, before any file is touched:
        the cabinet (--cabinet, else `cabinet` on stdin) and the field
        values (--date and --field, else `data` on stdin; flags win), into
        self.cabinet, self.given_data and self.flagged. Raises
        Filez4EvaError on an unknown cabinet, a malformed flag, an invalid
        date, a value with nothing left once normalized, or, when the
        run's cabinet is known (given, or the only one), a --field name it
        doesn't have."""
        # Imported here: filez4eva.stow imports the transcribe command,
        # which imports this module
        from filez4eva.stow import DATE_RULE, Stower, stdin_null, valid_date
        record = self.stdin_mapping()
        cabinet = record.get('cabinet')
        if not self.provided('cabinet') and not stdin_null(cabinet):
            if not isinstance(cabinet, str):
                raise Filez4EvaError(
                    "Cabinet from stdin must be a single value")
            self.cabinet = cabinet.strip()
        if self.provided('cabinet') and self.cabinet not in self.cabinets:
            raise Filez4EvaError(
                f"Unknown cabinet {self.cabinet}; known: "
                + ', '.join(sorted(self.cabinets)))
        values = {}
        data = record.get('data')
        if not stdin_null(data):
            if not isinstance(data, dict):
                raise Filez4EvaError("Data from stdin must be a mapping")
            for name, value in data.items():
                if stdin_null(value) or not isinstance(name, str) \
                        or not FIELD_NAME.fullmatch(name):
                    continue
                if not isinstance(value, str):
                    raise Filez4EvaError(
                        f"Field {name} from stdin must be a single value")
                if name == DATE_FIELD:
                    values[name] = Stower.normalize_stdin_date(value.strip())
                else:
                    values[name] = check_value(Field(name), value,
                                               'from stdin')
        flagged = []
        if self.provided('date'):
            if not valid_date(self.date):
                raise Filez4EvaError(f"{DATE_RULE}: {self.date!r}")
            values[DATE_FIELD] = self.date
            flagged.append(DATE_FIELD)
        for flag in self.field or []:
            name, equals, value = flag.partition('=')
            name = name.strip()
            if not equals or not FIELD_NAME.fullmatch(name):
                raise Filez4EvaError(f"--field must be NAME=VALUE: {flag!r}")
            if name == DATE_FIELD:
                raise Filez4EvaError("Use --date for the date")
            values[name] = check_value(Field(name), value, 'from --field')
            flagged.append(name)
        self.given_data = values
        self.flagged = tuple(flagged)
        known = self.cabinet if self.provided('cabinet') else (
            next(iter(self.cabinets)) if len(self.cabinets) == 1 else None)
        if known is not None:
            self.given_for(self.cabinets[known])

    def given_for(self, cabinet) -> dict:
        """The run's given field values that are fields of the cabinet, by
        name. Raises Filez4EvaError if a flag names a field the cabinet
        doesn't have (names only on stdin are ignored)."""
        values = {}
        for name, value in (self.given_data or {}).items():
            if cabinet.field(name) is not None:
                values[name] = value
            elif name in self.flagged:
                raise Filez4EvaError(
                    f"Unknown field {name} for cabinet {cabinet.name}; "
                    "known: " + ', '.join(f.name for f in cabinet.fields
                                          if not f.is_date))
        return values

    def check_given(self, path: Path, results: dict):
        """Raise Filez4EvaError if the run's given data conflicts with the
        document: a cabinet (--cabinet or stdin) that differs from the one
        saved for it, a value that differs from one already given for it,
        or a value for a document already classified that differs from
        (or is missing in) its record. Equal values are fine."""
        saved = saved_cabinet(results)
        if self.provided('cabinet') and saved is not None \
                and saved != self.cabinet:
            raise Filez4EvaError(
                f"Cabinet {self.cabinet} given, but {path.name} already has "
                f"cabinet {saved}")
        if not self.given_data:
            return
        values = self.given_data
        if saved in self.cabinets:
            values = self.given_for(self.cabinets[saved])
        before = given_values(results)
        done = next((stage for stage in ('review', CLASSIFY)
                     if isinstance(results.get(stage), dict)), None)
        record = results[done].get('data') if done else None
        record = record if isinstance(record, dict) else {}
        for name, value in values.items():
            label = Field(name).label
            if name in before:
                if before[name] != value:
                    raise Filez4EvaError(
                        f"{label} {value} given, but {path.name} already "
                        f"has {name} {before[name]}")
            elif done is not None:
                had = record.get(name)
                if had is None or str(had) != value:
                    state = 'reviewed' if done == 'review' else 'classified'
                    had = '' if had is None else f" with {name} {had}"
                    raise Filez4EvaError(
                        f"{label} {value} given, but {path.name} is already "
                        f"{state}{had}")

    def ask_cabinet(self, path: Path, results: dict) -> str:
        """Prompt for a document's cabinet, with tab completion of the
        names, until a configured one is entered. Empty input skips the
        document (NotDone)."""
        ingest = results.get('ingest')
        original = ingest.get('original-name') \
            if isinstance(ingest, dict) else None
        self.app.ui.send(f"{path.name} ({original})" if original
                         else path.name)
        name = self.prompt_cabinet()
        if name is None:
            self.app.ui.send('Skipped', Emphasis.INFO)
            raise NotDone('Skipped')
        return name

    def prompt_cabinet(self, default: str = None):
        """Prompt `Cabinet: ` with tab completion of the names (pre-filled
        with default, if given) until a configured one is entered, and
        return it. Empty input returns None."""
        names = sorted(self.cabinets)
        # Only pass a default when there is one
        extra = (default,) if default else ()
        while True:
            name = (self.app.ui.get_text('Cabinet: ', names, *extra)
                    or '').strip()
            if not name:
                return None
            if name in self.cabinets:
                return name
            self.app.ui.send('Cabinet must be one of: ' + ', '.join(names),
                             Emphasis.PRINCIPAL)

    def known_cabinet(self, results: dict):
        """The document's cabinet if it is known without asking: the one
        saved for it, else the run's (--cabinet or stdin), else the only
        one; None otherwise"""
        saved = saved_cabinet(results)
        if saved is not None:
            return saved
        if self.provided('cabinet'):
            return self.cabinet
        if len(self.cabinets) == 1:
            return next(iter(self.cabinets))
        return None

    def complete(self, name, values: dict) -> bool:
        """True if name is a configured cabinet and values has every one of
        its fields"""
        cabinet = self.cabinets.get(name)
        return cabinet is not None and \
            all(field.name in values for field in cabinet.fields)

    def given_complete(self, results: dict) -> bool:
        """True if the document's cabinet is known without asking (see
        known_cabinet) and every one of its fields is given, by this run or
        before"""
        name = self.known_cabinet(results)
        if name not in self.cabinets:
            return False
        values = dict(given_values(results),
                      **self.given_for(self.cabinets[name]))
        return self.complete(name, values)

    def give(self, path: Path, results: dict) -> bool:
        """Before a document is classified, save what is given for it as
        results.given: its cabinet (the one already saved for it, otherwise
        --cabinet or stdin, otherwise the only cabinet, otherwise a prompt,
        where empty input skips the document, writing nothing) and the
        run's given values for that cabinet's fields, merged with any given
        before. With the cabinet and every field given, also save the
        record as results.review (with `input: true`), in the same write,
        then record the values of the cabinet's learned fields (if the
        document had no review yet), and return True. Raises Filez4EvaError
        if a --field names a field the cabinet doesn't have, writing
        nothing: a cabinet chosen at the prompt isn't saved then, so the
        next run asks again (a mistyped choice is not kept)."""
        name = saved_cabinet(results)
        if name is None:
            if self.provided('cabinet'):
                name = self.cabinet
            elif len(self.cabinets) == 1:
                name = next(iter(self.cabinets))
            else:
                name = self.ask_cabinet(path, results)
        cabinet = self.cabinets.get(name)
        if cabinet is None:
            if self.given_data:
                raise Filez4EvaError(
                    f"Unknown cabinet {name} for {path.name}; known: "
                    + ', '.join(sorted(self.cabinets)))
            # Left for classify to report
            return False
        before = given_values(results)
        merged = dict(before, **self.given_for(cabinet))
        data = {field.name: merged[field.name] for field in cabinet.fields
                if field.name in merged}
        sidecar = load_sidecar(path)
        now = ingest_command.now().isoformat(timespec='seconds')
        changed = False
        if not isinstance(results.get(GIVEN), dict) or data != before:
            record = {'at': now, 'cabinet': name}
            if data:
                record['data'] = data
            sidecar['results'][GIVEN] = record
            changed = True
        full = self.complete(name, data)
        # Learned values count once per document: only when this write
        # creates the review
        new_review = full and sidecar['results'].get('review') is None
        if full:
            sidecar['results']['review'] = {
                'at': now, 'input': True, 'cabinet': name, 'data': data}
            changed = True
        if changed:
            write_sidecar(path, sidecar)
        if new_review:
            # Imported here: filez4eva.stow imports the transcribe command,
            # which imports this module
            from filez4eva.stow import remember_values
            remember_values(self.app, cabinet, data)
        return full

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
        --only, skip it with a note instead). Given data that conflicts
        with the document fails it (check_given), and what is given is
        saved before it is classified (give). With complete given data, the
        record stands in for classify and review (also under --only), and
        for review alone on a document already classified with the same
        values.
        StopRun from act ends the run."""
        for entry in work:
            document, current = entry
            try:
                results = load_sidecar(current)['results']
                self.check_given(current, results)
                if reached(results, self.stage):
                    self.counts[self.already] += 1
                    continue
                missing = [command for command in earlier
                           if not reached(results, command.stage)]
                stages = [command.stage for command in missing] + \
                    [self.stage]
                if missing and self.only and not (
                        missing[0].stage in GIVEN_STAGES
                        and self.given_complete(results)):
                    self.skip(document, missing[0].done.lower())
                    continue
                # A classified document still needing review gets the
                # record too when its given data is complete (check_given
                # passed, so it equals the classified values)
                gives = CLASSIFY in stages or (
                    'review' in stages and self.given_complete(results))
                if gives and self.give(current, results):
                    self.counts[GIVEN_DONE] += 1
                    missing = [command for command in missing
                               if command.stage not in GIVEN_STAGES]
                    if self.stage in GIVEN_STAGES:
                        lines.append(str(current))
                        continue
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
        if self.stage != BATCH_STAGE:
            self.read_given()
        intake = intake_dir(self.app.config)
        todo, empty = self.select(intake)
        if not todo:
            self.status = empty
            return ''
        # With given data (--cabinet included), every document is checked
        # against it, even when there is nothing else to do
        if not self.path and not self.provided('cabinet') \
                and not self.given_data:
            done = sum(has_stage(document, self.stage) for document in todo)
            if done == len(todo):
                self.status = (f"Nothing to {self.name} ({files(done)} "
                               f"already {self.done.lower()})")
                return ''
        transcriber = self if self.stage == BATCH_STAGE else next(
            (c for c in earlier if c.stage == BATCH_STAGE), None)
        self.counts = {'Ingested': 0}
        for command in earlier + [self]:
            # Documents recorded from complete given data come before the
            # stages that record stands in for
            if command.stage == CLASSIFY:
                self.counts[GIVEN_DONE] = 0
            self.counts[command.done] = 0
        self.counts[self.already] = 0
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
