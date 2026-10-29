from pathlib import Path

from wizlib.parser import WizParser

from filez4eva.command import Filez4EvaCommand
from filez4eva.command import ingest_command
from filez4eva.command.classify_command import ClassifyCommand
from filez4eva.command.ingest_command import (
    archived_sidecar, intake_dir, sidecar_path)
from filez4eva.command.review_command import ReviewCommand
from filez4eva.command.transcribe_command import TranscribeCommand
from filez4eva.error import Filez4EvaError
from filez4eva.stage import (
    StageCommand, documents, load_sidecar, record_result, resolve_path)
from filez4eva.stow import Stower, load_cabinets, stdin_null


def confirmed(results: dict, cabinets: dict) -> dict:
    """Return results.review from a document's results, checked: a mapping
    with the name of a configured cabinet and data. Raises Filez4EvaError
    if it can't be used."""
    review = results.get('review')
    if not isinstance(review, dict):
        raise Filez4EvaError("results.review must be a mapping")
    cabinet = review.get('cabinet')
    if not isinstance(cabinet, str) or not cabinet.strip():
        raise Filez4EvaError("results.review has no cabinet")
    cabinet = cabinet.strip()
    if cabinet not in cabinets:
        raise Filez4EvaError(
            f"Unknown cabinet {cabinet} in results.review; known: "
            + ', '.join(sorted(cabinets)))
    data = review.get('data')
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise Filez4EvaError("results.review data must be a mapping")
    return dict(review, cabinet=cabinet, data=data)


def text(value):
    """A recorded value as text, or None if there is none"""
    return None if value is None else str(value)


class StowCommand(StageCommand):
    """Stow a file, the files in a directory, or the documents in the
    intake into their cabinets, ingesting, transcribing, classifying and
    reviewing them first if needed. Each document is stowed as soon as it
    is confirmed: the file and its transcript move to the cabinet chosen at
    review, results.stow is recorded, and X.yml moves to
    <intake>/archive/.

    With input data (--cabinet, --date, --field NAME=VALUE, or a record on
    stdin) for a single file, classify and review are skipped: missing
    values are prompted for, the record is saved as results.review with
    `input: true`, and the file is stowed with it."""

    name = 'stow'
    summary = 'move confirmed documents into their cabinets'
    description = """
        Move each reviewed document, with its transcript, into its cabinet,
        named by the cabinet's pattern, then record results.stow and move
        its X.yml sidecar to <intake>/archive/. A document not reviewed yet
        is reviewed first (and ingested, transcribed and classified where
        needed), and stowed as soon as it's confirmed. Prints each
        destination.

        Main use: `filez4eva classify ~/Scans`, then `filez4eva stow`.

        Input data (--cabinet, --date, --field, or a YAML record on stdin
        with `cabinet` and the fields under `data`) stows a single file with
        that record instead of classifying and reviewing it. Anything
        missing is prompted for."""
    stage = 'stow'
    done = 'Stowed'
    requires = (TranscribeCommand, ClassifyCommand, ReviewCommand)

    # Input data
    date: str = None
    # NAME=VALUE strings from repeated --field flags
    field: list = None
    cabinet: str = None

    # The supplied record, once checked: the cabinet name and data (every
    # field of the cabinet, date included). None without input data.
    input_record: dict = None

    @classmethod
    def add_args(cls, parser: WizParser):
        super().add_args(parser)
        parser.add_argument('--date', '-d',
                            help='input data: the date, as YYYYMMDD')
        parser.add_argument('--field', '-f', action='append',
                            metavar='NAME=VALUE',
                            help='input data: the value of a field '
                            '(repeatable)')
        parser.add_argument('--cabinet', '-c',
                            help='input data: the cabinet to stow into')

    def handle_vals(self):
        super().handle_vals()
        # Check the cabinets before any file is touched
        self.cabinets = load_cabinets(self.app.config)
        if self.input_supplied():
            self.input_record = self.read_input()
            # The supplied record stands in for classify and review
            self.requires = (TranscribeCommand,)

    def input_supplied(self) -> bool:
        """True if input data is supplied: any of --cabinet, --date or
        --field, or a record on stdin with a cabinet or data. Empty,
        malformed or non-mapping stdin is no input."""
        if any(self.provided(name) for name in ['cabinet', 'date', 'field']):
            return True
        record = self.stdin_mapping()
        return not (stdin_null(record.get('cabinet'))
                    and stdin_null(record.get('data')))

    def read_input(self) -> dict:
        """Check the path, then read the input data with a Stower (flags
        win over stdin; missing values are prompted for), all before any
        file is touched. Return the cabinet name and data (every field
        of the cabinet, date included, in pattern order). Raises
        Filez4EvaError if the path isn't a single file or a value is
        invalid."""
        rule = ("Input data (--cabinet, --date, --field or a record on "
                "stdin) needs a single file")
        if not self.path:
            raise Filez4EvaError(f"{rule}, not the intake")
        intake = intake_dir(self.app.config)
        path = resolve_path(self.path, intake)
        if path.is_dir():
            raise Filez4EvaError(f"{rule}, not a directory: {path}")
        # Fails on the sidecar or transcript of a document in the intake
        documents(path, intake)
        stower = Stower(self.app, use_stdin=True, file=str(path),
                        cabinet=self.cabinet, date=self.date,
                        field=self.field)
        stower.read_values()
        # Check every value (the date included) against the cabinet now,
        # so a bad one fails before anything moves
        data = stower.field_values()
        return {'cabinet': stower.resolve_cabinet().name, 'data': data}

    def stower(self, path: Path, review: dict) -> Stower:
        """A Stower for the document, with the reviewed cabinet, date and
        other fields, so it never prompts"""
        cabinet = self.cabinets[review['cabinet']]
        date = None
        data = {}
        for field in cabinet.fields:
            value = text(review['data'].get(field.name))
            if field.is_date:
                date = value
            else:
                data[field.name] = value
        return Stower(self.app, use_stdin=False, file=str(path),
                      cabinet=cabinet.name, date=date, data=data)

    def act(self, path: Path) -> str:
        """Stow a reviewed document with the cabinet and data from
        results.review: move the file and its transcript to the cabinet
        (never overwriting anything), record results.stow, then move X.yml
        to the archive. With input data, the file is stowed with it
        instead, and it is saved as results.review (with `input: true`,
        replacing any review there) only once the file has moved, so a
        failed stow leaves the sidecar as it was. Return the destination
        path."""
        if self.input_record is None:
            supplied = None
            review = confirmed(load_sidecar(path)['results'], self.cabinets)
        else:
            supplied = {
                'at': ingest_command.now().isoformat(timespec='seconds'),
                'input': True, **self.input_record}
            review = confirmed({'review': supplied}, self.cabinets)
        sidecar = sidecar_path(path)
        archived = archived_sidecar(path)
        # Checked before the file moves, so a stowed document's sidecar
        # always has somewhere to go
        if archived.exists():
            raise Filez4EvaError(f"File already exists at {archived}")
        archived.parent.mkdir(exist_ok=True)
        targetpath = self.stower(path, review).stow()
        try:
            if supplied is not None:
                record_result(path, 'review', supplied)
            record_result(path, self.stage, {
                'at': ingest_command.now().isoformat(timespec='seconds'),
                'location': str(targetpath)})
            sidecar.rename(archived)
        except (Filez4EvaError, OSError) as error:
            raise Filez4EvaError(
                f"Stowed to {targetpath}, but could not archive {sidecar}: "
                f"{error}") from error
        return str(targetpath)

    @Filez4EvaCommand.wrap
    def execute(self):
        return self.run()
