import os
from pathlib import Path
from subprocess import run

from wizlib.command import CommandCancellation
from wizlib.ui import Chooser
from wizlib.ui.shell_ui import Emphasis

from filez4eva.command import Filez4EvaCommand
from filez4eva.command import ingest_command
from filez4eva.command.classify_command import ClassifyCommand
from filez4eva.command.ingest_command import sidecar_path, write_sidecar
from filez4eva.command.transcribe_command import (
    TranscribeCommand, transcript_path)
from filez4eva.error import Filez4EvaError
from filez4eva.fields import Field, normalize_value
from filez4eva.stage import (
    CLASSIFY, GIVEN, NotDone, StageCommand, StopRun, given_values,
    load_sidecar, record_result, saved_cabinet, stage_line)
from filez4eva.stow import Stower, remember_values, valid_date


def proposal(results: dict) -> dict:
    """Return results.classify from a document's results, checked, with
    the document's saved cabinet (see saved_cabinet; for sidecars from
    before results.given, the cabinet in results.classify) and the values
    given for it (`given`, from results.given.data, which win over the
    classified ones). Raises Filez4EvaError if it can't be used."""
    classify = results.get('classify')
    if not isinstance(classify, dict):
        raise Filez4EvaError("results.classify must be a mapping")
    cabinet = saved_cabinet(results)
    if cabinet is None:
        raise Filez4EvaError("No cabinet saved (results.given)")
    data = classify.get('data')
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise Filez4EvaError("results.classify data must be a mapping")
    given = given_values(results)
    data = dict(data, **given)
    return dict(classify, cabinet=cabinet, data=data, given=given)


class ReviewCommand(StageCommand):
    """Show the proposed record of new files (ingesting them first), the
    documents already in the intake, or the ones named with --ingested, to
    confirm as it is, update, or redo with another cabinet, transcribing
    and classifying them first if needed (choosing each one's cabinet
    before it is classified). Records results.review (the saved cabinet and
    data) in each document's X.yml. Never stows."""

    name = 'review'
    summary = 'confirm, update or redo the proposed records'
    description = """
        Show each classified document's proposed record, then choose:
        confirm (save it as it is), update (edit the field values at
        pre-filled prompts), redo (change the cabinet and classify the
        document again), skip, preview, delete or quit (which ends the
        run). A confirmed or updated record is saved as results.review in
        the document's X.yml sidecar, with the cabinet saved for the
        document, and the values of the cabinet's learned fields are
        recorded right away, so the next documents in the run can use
        them. Confirm refuses a record with a missing field value
        (e.g. no date found); use update. A document not classified yet
        is classified first, after its cabinet is chosen (see Cabinet
        below). Values given for a document (see Given data below) are
        shown marked (given): confirm accepts them, update can change them,
        and redo keeps those the new cabinet has. Nothing is stowed. Prints
        each reviewed document's path."""
    stage = 'review'
    done = 'Reviewed'
    doing = 'Reviewing'
    # show's heading is the stage line
    heading = True
    requires = (TranscribeCommand, ClassifyCommand)

    # No Enter default: every action takes its own key
    ACTION_CHOOSER = Chooser('', '', {'c': 'confirm', 'u': 'update',
                                      'r': 'redo', 'x': 'skip',
                                      'p': 'preview', 'd': 'delete',
                                      'q': 'quit'})

    # WizLib's Chooser resolves Enter to the *first* choice, not to the
    # default text, so the default ('No') must be listed first.
    DELETE_CHOOSER = Chooser('Delete?', 'No', {'N': 'No', 'Y': 'Yes'})

    # The classify command redo uses, built on first use (review also runs
    # inside stow's cycle, so it can't rely on run()'s earlier commands)
    _classifier = None

    def show(self, path: Path, results: dict, proposed: dict):
        """Show the document's name and its proposed record, with the
        given values marked (given). The heading, e.g. `Reviewing NAME
        (ORIGINAL NAME)`, is also the stage's progress line."""
        self.app.ui.send(stage_line(self.doing, path, results),
                         Emphasis.INFO)
        for key in ['summary', 'doctype']:
            if proposed.get(key):
                self.app.ui.send(f"{key.capitalize()}: {proposed[key]}")
        self.app.ui.send(f"Cabinet: {proposed['cabinet']}")
        given = proposed.get('given') or {}
        for name, value in proposed['data'].items():
            label = Field(str(name)).label
            mark = ' (given)' if str(name) in given else ''
            self.app.ui.send(
                f"{label}: {'(none)' if value is None else value}{mark}")

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

    def cabinet_of(self, proposed: dict):
        """The configured cabinet of the proposed record. Raises
        Filez4EvaError if it isn't configured."""
        name = proposed['cabinet']
        if name not in self.cabinets:
            raise Filez4EvaError(
                f"Unknown cabinet {name}; known: "
                + ', '.join(sorted(self.cabinets)))
        return self.cabinets[name]

    @staticmethod
    def review_record(cabinet, data: dict) -> dict:
        """results.review: now, the cabinet, and data (a value for each of
        its fields, date included, in pattern order)"""
        return {'at': ingest_command.now().isoformat(timespec='seconds'),
                'cabinet': cabinet.name,
                'data': {field.name: data[field.name]
                         for field in cabinet.fields}}

    def confirm(self, proposed: dict):
        """Return results.review for the proposed record as it is, without
        prompting: the document's saved cabinet and the proposed value of
        each of its fields (other fields normalized). If a field has no
        value, or one that can't be used, say so and return None."""
        cabinet = self.cabinet_of(proposed)
        missing, invalid, data = [], [], {}
        for field in cabinet.fields:
            value = proposed['data'].get(field.name)
            text = '' if value is None else str(value).strip()
            if not text:
                missing.append(field.name)
                continue
            if field.is_date:
                cleaned = text if valid_date(text) else None
            else:
                cleaned = normalize_value(text)
            if cleaned:
                data[field.name] = cleaned
            else:
                invalid.append(field.name)
        if missing or invalid:
            parts = [f"{label}: {', '.join(names)}." for label, names in
                     [('Missing', missing), ('Invalid', invalid)] if names]
            self.app.ui.send(' '.join(parts) + ' Use (u)pdate.',
                             Emphasis.PRINCIPAL)
            return None
        return self.review_record(cabinet, data)

    def update(self, proposed: dict) -> dict:
        """Edit the proposed record at pre-filled prompts, one for each
        field of the document's saved cabinet (no cabinet prompt). Return
        results.review. An empty answer raises CommandCancellation."""
        cabinet = self.cabinet_of(proposed)
        stow = Stower(self.app, use_stdin=False)
        values = stow.confirm_values(cabinet.name, proposed['data'])
        data = dict(values['data'])
        for field in cabinet.fields:
            if field.is_date:
                data[field.name] = values['date']
        return self.review_record(cabinet, data)

    @property
    def classifier(self) -> ClassifyCommand:
        """The classify command redo uses, its configuration checked"""
        if self._classifier is None:
            classifier = ClassifyCommand(self.app)
            classifier.handle_vals()
            self._classifier = classifier
        return self._classifier

    def redo(self, path: Path, proposed: dict) -> bool:
        """Change the document's cabinet and classify it again: with
        several cabinets, prompt for it (pre-filled with the current one);
        with one, use it. Save it as results.given, keeping the given
        values of fields the cabinet has, drop the old results.classify (in
        one write) and classify the document right away. Return False,
        changing nothing, on empty input."""
        if len(self.cabinets) == 1:
            name = next(iter(self.cabinets))
        else:
            name = self.prompt_cabinet(proposed['cabinet'])
            if name is None:
                return False
        data = load_sidecar(path)
        cabinet = self.cabinets[name]
        given = {field.name: proposed['given'][field.name]
                 for field in cabinet.fields
                 if field.name in proposed.get('given', {})}
        data['results'][GIVEN] = {
            'at': ingest_command.now().isoformat(timespec='seconds'),
            'cabinet': name}
        if given:
            data['results'][GIVEN]['data'] = given
        data['results'].pop(CLASSIFY, None)
        write_sidecar(path, data)
        self.app.ui.send(stage_line(self.classifier.doing, path),
                         Emphasis.INFO)
        self.classifier.act(path)
        return True

    def act(self, path: Path) -> str:
        """Show a classified document's proposed record and act on the
        operator's choice: confirm or update (record results.review, then
        the learned values, and return the document's path), redo
        (classify again, possibly for another cabinet, and show the new
        proposal), skip, preview, delete or quit"""
        results = load_sidecar(path)['results']
        proposed = proposal(results)
        self.show(path, results, proposed)
        while True:
            action = self.app.ui.get_option(self.ACTION_CHOOSER)
            if action == 'preview':
                self.preview(path)
                continue
            elif action == 'delete':
                if self.app.ui.get_option(self.DELETE_CHOOSER) == 'Yes':
                    self.delete(path)
                    self.app.ui.send('Deleted', Emphasis.INFO)
                    raise NotDone('Deleted')
                continue
            elif action == 'skip':
                self.app.ui.send('Skipped', Emphasis.INFO)
                raise NotDone('Skipped')
            elif action == 'quit':
                raise StopRun()
            elif action == 'redo':
                if self.redo(path, proposed):
                    results = load_sidecar(path)['results']
                    proposed = proposal(results)
                    self.show(path, results, proposed)
                else:
                    self.app.ui.send(path.name)
                continue
            elif action == 'update':
                try:
                    review = self.update(proposed)
                except CommandCancellation:
                    # Empty answer: back to the choice for this document
                    self.app.ui.send(path.name)
                    continue
            else:
                review = self.confirm(proposed)
                if review is None:
                    continue
            record_result(path, self.stage, review)
            # Counted once, now: after the review is saved, so a failure to
            # record the values can't lose it
            remember_values(self.app, self.cabinet_of(review), review['data'])
            self.app.ui.send('Reviewed', Emphasis.INFO)
            return str(path)

    @Filez4EvaCommand.wrap
    def execute(self):
        return self.run()
