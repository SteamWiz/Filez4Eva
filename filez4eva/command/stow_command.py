from pathlib import Path

from filez4eva.command import Filez4EvaCommand
from filez4eva.command import ingest_command
from filez4eva.command.classify_command import ClassifyCommand
from filez4eva.command.ingest_command import archived_sidecar, sidecar_path
from filez4eva.command.review_command import ReviewCommand
from filez4eva.command.stow_file_command import (
    StowFileCommand, load_cabinets)
from filez4eva.command.transcribe_command import TranscribeCommand
from filez4eva.error import Filez4EvaError
from filez4eva.stage import StageCommand, load_sidecar, record_result


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
    <intake>/archive/."""

    name = 'stow'
    stage = 'stow'
    done = 'Stowed'
    requires = (TranscribeCommand, ClassifyCommand, ReviewCommand)

    def handle_vals(self):
        super().handle_vals()
        # Check the cabinets before any file is touched
        self.cabinets = load_cabinets(self.app.config)

    def stower(self, path: Path, review: dict) -> StowFileCommand:
        """A stow-file command for the document, with the reviewed cabinet,
        date and other fields, so it never prompts"""
        cabinet = self.cabinets[review['cabinet']]
        date = None
        data = {}
        for field in cabinet.fields:
            value = text(review['data'].get(field.name))
            if field.is_date:
                date = value
            else:
                data[field.name] = value
        return StowFileCommand(self.app, use_stdin=False, file=str(path),
                               cabinet=cabinet.name, date=date, data=data)

    def act(self, path: Path) -> str:
        """Stow a reviewed document with the cabinet and data from
        results.review: move the file and its transcript to the cabinet
        (never overwriting anything), record results.stow, then move X.yml
        to the archive. Return the destination path."""
        review = confirmed(load_sidecar(path)['results'], self.cabinets)
        sidecar = sidecar_path(path)
        archived = archived_sidecar(path)
        # Checked before the file moves, so a stowed document's sidecar
        # always has somewhere to go
        if archived.exists():
            raise Filez4EvaError(f"File already exists at {archived}")
        archived.parent.mkdir(exist_ok=True)
        targetpath = self.stower(path, review).stow()
        try:
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
