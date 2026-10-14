from wizlib.parser import WizParser

from filez4eva.command import Filez4EvaCommand
from filez4eva.command.classify_command import ClassifyCommand
from filez4eva.command.stow_file_command import (
    ACCOUNT_RULE, DATE_RULE, PART_RULE, StowFileCommand, valid_account,
    valid_date, valid_part)


def confirm_record(app, classifier: ClassifyCommand, record: dict) -> dict:
    """Show the summary and doctype, then prompt for each value, pre-filled
    with the proposed one (the Date prompt starts empty if the record has
    no date). Return the confirmed cabinet, date, account and
    part. An empty answer raises CommandCancellation. classifier is the
    ClassifyCommand that produced the record."""
    app.ui.send(f"Summary: {record['summary']}")
    app.ui.send(f"Doctype: {record['doctype']}")
    stow = classifier.stow
    cabinet = record['cabinet']
    # Cabinet comes first, so account and part completion use the final
    # cabinet. Skip it if there is only one, or it was just chosen.
    if len(stow.cabinets) > 1 and not classifier.cabinet_prompted:
        names = sorted(stow.cabinets)
        cabinet = stow.prompt_value(
            'Cabinet', names, lambda v: v in stow.cabinets,
            'Cabinet must be one of: ' + ', '.join(names), cabinet)
        stow.cabinet = cabinet
    date = stow.prompt_value('Date', [], valid_date, DATE_RULE,
                             record['date'] or '')
    account = stow.prompt_value('Account', stow.get_accounts(),
                                valid_account, ACCOUNT_RULE,
                                record['account'])
    part = stow.prompt_value('Part', stow.get_parts(account), valid_part,
                             PART_RULE, record['part'])
    return {'cabinet': cabinet, 'date': date, 'account': account,
            'part': part}


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
        self.classifier = ClassifyCommand(self.app, file=self.file,
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
