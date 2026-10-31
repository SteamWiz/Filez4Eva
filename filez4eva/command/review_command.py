import os
from pathlib import Path
from subprocess import run

from wizlib.command import CommandCancellation
from wizlib.ui import Chooser
from wizlib.ui.shell_ui import Emphasis

from filez4eva.command import Filez4EvaCommand
from filez4eva.command import ingest_command
from filez4eva.command.classify_command import ClassifyCommand
from filez4eva.command.ingest_command import sidecar_path
from filez4eva.command.transcribe_command import (
    TranscribeCommand, transcript_path)
from filez4eva.error import Filez4EvaError
from filez4eva.fields import Field
from filez4eva.stage import (
    NotDone, StageCommand, StopRun, load_sidecar, record_result)
from filez4eva.stow import Stower


def proposal(results: dict) -> dict:
    """Return results.classify from a document's results, checked: a
    mapping with a cabinet name and data. Raises Filez4EvaError if it can't
    be used."""
    classify = results.get('classify')
    if not isinstance(classify, dict):
        raise Filez4EvaError("results.classify must be a mapping")
    cabinet = classify.get('cabinet')
    if not isinstance(cabinet, str) or not cabinet.strip():
        raise Filez4EvaError("results.classify has no cabinet")
    data = classify.get('data')
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise Filez4EvaError("results.classify data must be a mapping")
    return dict(classify, cabinet=cabinet.strip(), data=data)


class ReviewCommand(StageCommand):
    """Show the proposed record of new files (ingesting them first), the
    documents already in the intake, or the ones named with --ingested, to
    confirm or edit, transcribing and classifying them first if needed.
    Records results.review (cabinet and data) in each document's X.yml.
    Never stows."""

    name = 'review'
    summary = 'confirm or edit the proposed records'
    description = """
        Show each classified document's proposed record, then confirm (or
        edit), skip, preview, delete or quit (which ends the run). A
        confirmed record is saved as results.review in the document's X.yml
        sidecar. Nothing is stowed. Prints each reviewed document's
        path."""
    stage = 'review'
    done = 'Reviewed'
    requires = (TranscribeCommand, ClassifyCommand)

    # No Enter default: every action takes its own key
    ACTION_CHOOSER = Chooser('', '', {'c': 'confirm', 'x': 'skip',
                                      'p': 'preview', 'd': 'delete',
                                      'q': 'quit'})

    # WizLib's Chooser resolves Enter to the *first* choice, not to the
    # default text, so the default ('No') must be listed first.
    DELETE_CHOOSER = Chooser('Delete?', 'No', {'N': 'No', 'Y': 'Yes'})

    def show(self, path: Path, results: dict, proposed: dict):
        """Show the document's name and its proposed record"""
        ingest = results.get('ingest')
        original = ingest.get('original-name') \
            if isinstance(ingest, dict) else None
        self.app.ui.send(f"{path.name} ({original})" if original
                         else path.name)
        for key in ['summary', 'doctype']:
            if proposed.get(key):
                self.app.ui.send(f"{key.capitalize()}: {proposed[key]}")
        self.app.ui.send(f"Cabinet: {proposed['cabinet']}")
        for name, value in proposed['data'].items():
            label = Field(str(name)).label
            self.app.ui.send(
                f"{label}: {'(none)' if value is None else value}")

    def preview(self, path: Path):
        """Open the document with the preview command"""
        self.app.ui.send('Previewing...', Emphasis.INFO)
        try:
            run(['preview', path])
        except OSError as error:
            self.app.ui.send(f"Could not preview {path}: {error}",
                             Emphasis.ERROR)

    def delete(self, path: Path):
        """Remove the document, its transcript X.md and its sidecar X.yml
        (last, so a failure never leaves the document without its sidecar).
        The transcript name in the sidecar isn't used, so a bad sidecar
        can't make delete remove some other file."""
        os.remove(path)
        transcript_path(path).unlink(missing_ok=True)
        sidecar_path(path).unlink(missing_ok=True)

    def confirm(self, proposed: dict) -> dict:
        """Confirm the proposed record at pre-filled prompts, letting the
        operator change the cabinet when there are several. Return
        results.review: the confirmed cabinet, and data with a value for
        each of its fields (date included), in pattern order."""
        stow = Stower(self.app, use_stdin=False)
        values = stow.confirm_values(proposed['cabinet'], proposed['data'])
        cabinet = stow.cabinets[values['cabinet']]
        data = {field.name: values['date'] if field.is_date
                else values['data'][field.name] for field in cabinet.fields}
        return {'at': ingest_command.now().isoformat(timespec='seconds'),
                'cabinet': cabinet.name, 'data': data}

    def act(self, path: Path) -> str:
        """Show a classified document's proposed record and act on the
        operator's choice: confirm (record results.review and return the
        document's path), skip, preview, delete or quit"""
        results = load_sidecar(path)['results']
        proposed = proposal(results)
        self.show(path, results, proposed)
        while True:
            action = self.app.ui.get_option(self.ACTION_CHOOSER)
            if action == 'preview':
                self.preview(path)
            elif action == 'delete':
                if self.app.ui.get_option(self.DELETE_CHOOSER) == 'Yes':
                    self.delete(path)
                    self.app.ui.send('Deleted', Emphasis.INFO)
                    raise NotDone('Deleted')
            elif action == 'skip':
                self.app.ui.send('Skipped', Emphasis.INFO)
                raise NotDone('Skipped')
            elif action == 'quit':
                raise StopRun()
            else:
                try:
                    review = self.confirm(proposed)
                except CommandCancellation:
                    # Empty answer: back to the choice for this document
                    self.app.ui.send(path.name)
                    continue
                record_result(path, self.stage, review)
                self.app.ui.send('Reviewed', Emphasis.INFO)
                return str(path)

    @Filez4EvaCommand.wrap
    def execute(self):
        return self.run()
