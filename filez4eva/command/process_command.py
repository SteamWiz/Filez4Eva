from wizlib.parser import WizParser

from filez4eva.command import Filez4EvaCommand
from filez4eva.command.classify_command import Classifier
from filez4eva.command.stow_file_command import StowFileCommand


def confirm_record(app, classifier: Classifier, record: dict) -> dict:
    """Show the summary and doctype, then prompt for the cabinet and each
    of its fields in pattern order, pre-filled with the proposed value (a
    prompt starts empty if the record has no value for it, such as a
    document without a date). Return the confirmed cabinet, date and data
    (the other fields). An empty answer raises CommandCancellation.
    classifier is the Classifier that produced the record."""
    app.ui.send(f"Summary: {record['summary']}")
    app.ui.send(f"Doctype: {record['doctype']}")
    # Cabinet comes first, so the fields and completion are the final
    # cabinet's. Skip it if there is only one, or it was just chosen.
    return classifier.stow.confirm_values(
        record['cabinet'], record.get('data') or {},
        ask_cabinet=not classifier.cabinet_prompted)


class ProcessCommand(Filez4EvaCommand):
    """Transcribe and classify a file, confirm the proposed values in the
    shell, then stow it with its transcript"""

    name = 'process'

    cabinet: str = None
    dry_run: bool = False

    @classmethod
    def add_args(cls, parser: WizParser):
        super().add_args(parser)
        parser.add_argument('--cabinet', '-c')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('file')

    def handle_vals(self):
        super().handle_vals()
        # Check all the configuration (and choose the cabinet) before any
        # call to the model
        self.classifier = Classifier(self.app, file=self.file,
                                     cabinet=self.cabinet)
        self.classifier.handle_vals()

    def confirm(self, record: dict) -> dict:
        """Confirm the proposed values; see confirm_record"""
        return confirm_record(self.app, self.classifier, record)

    @Filez4EvaCommand.wrap
    def execute(self):
        record = self.classifier.classify()
        statuses = [self.classifier.status]
        values = self.confirm(record)
        stow = StowFileCommand(self.app, file=record['file'],
                               use_stdin=False, **values)
        if self.dry_run:
            source, target, source_transcript, target_transcript = \
                stow.plan()
            lines = [f"Would stow {source} -> {target}"]
            if target_transcript:
                lines.append(
                    f"Would stow {source_transcript} -> {target_transcript}")
            self.status = ' | '.join(statuses + ['Dry run'])
            return '\n'.join(lines)
        result = stow.execute()
        self.status = ' | '.join(statuses + [stow.status])
        return result
