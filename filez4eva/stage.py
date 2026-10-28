"""Shared logic for the stage commands (transcribe, classify and review now;
stow later): which path to work on, which files in it are documents,
the prerequisite rule (ingest, then each earlier stage the command
requires), the `results` in each document's X.yml sidecar, and running a
stage over every document with per-file errors."""

from pathlib import Path

import yaml
from wizlib.parser import WizParser
from wizlib.ui.shell_ui import Emphasis

from filez4eva.command import Filez4EvaCommand
from filez4eva.command.ingest_command import (
    files, in_intake, ingest_file, intake_dir, is_companion, is_ingested,
    sidecar_path, top_level_documents, write_sidecar)
from filez4eva.error import Filez4EvaError


def resolve_path(arg, intake: Path) -> Path:
    """Return the path a stage command works on: the intake when no path is
    given, otherwise the path, expanded and absolute but not resolved, so
    messages and output name files the way the user and the configuration
    do (on macOS, for example, /var is a link to /private/var). Only the
    check below resolves the path in full (symbolic links and '..'), so a
    link to a subdirectory of the intake is seen for what it is. Raises
    Filez4EvaError if the path doesn't exist, or if it is in a subdirectory
    of the intake (such as archive/), which stage commands never touch."""
    if not arg:
        return intake
    path = Path(arg).expanduser().absolute()
    if not path.exists():
        raise Filez4EvaError(f"{path} must exist")
    home = (path if path.is_dir() else path.parent).resolve()
    top = intake.resolve()
    if home != top and home.is_relative_to(top):
        raise Filez4EvaError(
            f"{path} is in a subdirectory of the intake {intake}; only "
            "the top level of the intake holds documents")
    return path


def documents(path: Path, intake: Path) -> list:
    """Return the documents to work on for a path, in name order, listed
    once before anything moves.

    A file is the only document. In a directory, the documents are the
    non-hidden regular files at the top level; subdirectories, hidden files
    and symbolic links are left alone. In the intake, the sidecar (X.yml)
    and transcript (X.md) of a document X belong to X and are not documents
    themselves; a file with no sidecar was dropped in by hand and is a new
    document, as for ingest. Raises Filez4EvaError if a file given on its
    own is a sidecar or transcript in the intake."""
    if not path.is_dir():
        if in_intake(path, intake) and is_companion(path):
            raise Filez4EvaError(
                f"{path} is the sidecar or transcript of a document in the "
                "intake, not a document")
        return [path]
    ingested_ones, new = top_level_documents(path, intake)
    return sorted(ingested_ones + new)


def ingested(path: Path, intake: Path) -> bool:
    """True if path is a document already ingested: a file directly in the
    intake with its X.yml sidecar"""
    return in_intake(path, intake) and is_ingested(path)


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


def stage_result(path: Path, stage: str):
    """Return results.<stage> from a document's sidecar, or None if that
    stage hasn't run"""
    return load_sidecar(path)['results'].get(stage)


def record_result(path: Path, stage: str, result: dict):
    """Save results.<stage> in a document's sidecar, keeping the rest"""
    data = load_sidecar(path)
    data['results'][stage] = result
    write_sidecar(path, data)


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

    # File or directory; None for the intake
    path: str = None

    @classmethod
    def add_args(cls, parser: WizParser):
        super().add_args(parser)
        parser.add_argument('--only', action='store_true')
        parser.add_argument('path', nargs='?')

    def act(self, path: Path) -> str:  # pragma: no cover
        """Run the stage on an ingested document that hasn't had it yet,
        record results.<stage>, and return the line to print on stdout.
        May raise NotDone to leave the document without the stage, or
        StopRun to end the run."""
        raise NotImplementedError

    def skip(self, document: Path, reason: str, skipped: dict):
        """Leave a document alone under --only, with a note on stderr.
        reason is the earlier stage it lacks, e.g. 'ingested'."""
        skipped[reason] = skipped.get(reason, 0) + 1
        self.app.ui.send(f"Skipped {document}: not {reason} yet",
                         Emphasis.INFO)

    def run(self) -> str:
        """Run the stage on every document for the path argument, applying
        the prerequisite rule: a file not yet ingested is ingested, and each
        earlier stage in `requires` that a document hasn't had is run first
        (with --only, the document is skipped instead, with a note). Set the
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
        todo = documents(resolve_path(self.path, intake), intake)
        lines = []
        counts = {'Ingested': 0}
        counts.update({command.done: 0 for command in earlier})
        counts.update({self.done: 0, f"Already {self.done.lower()}": 0})
        # Skipped documents, by the earlier stage they lack
        skipped = {}
        failed = 0
        stopped = False
        for document in todo:
            current = document
            try:
                if not ingested(document, intake):
                    if self.only:
                        self.skip(document, 'ingested', skipped)
                        continue
                    current = ingest_file(document, intake, {})
                    counts['Ingested'] += 1
                if stage_result(current, self.stage) is not None:
                    counts[f"Already {self.done.lower()}"] += 1
                    continue
                missing = [command for command in earlier
                           if stage_result(current, command.stage) is None]
                if missing and self.only:
                    self.skip(document, missing[0].done.lower(), skipped)
                    continue
                for command in missing:
                    command.act(current)
                    counts[command.done] += 1
                lines.append(self.act(current))
                counts[self.done] += 1
            except NotDone as outcome:
                counts[outcome.label] = counts.get(outcome.label, 0) + 1
            except StopRun:
                stopped = True
                break
            except (Filez4EvaError, OSError) as error:
                failed += 1
                moved = f" (now {current})" if current != document else ''
                self.app.ui.send(
                    f"Failed to {self.name} {document}{moved}: {error}",
                    Emphasis.ERROR)
        if failed:
            if lines:
                print('\n'.join(lines))
            raise Filez4EvaError(
                f"{failed} of {files(len(todo))} failed to {self.name}")
        labels = [f"{label} {files(count)}"
                  for label, count in counts.items() if count]
        labels += [f"Skipped {files(count)} (not {reason})"
                   for reason, count in skipped.items()]
        if stopped:
            labels.append('Quit')
        self.status = ' | '.join(labels) or f"No files to {self.name}"
        return '\n'.join(lines)
