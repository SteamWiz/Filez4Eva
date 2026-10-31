from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unittest.mock import patch

import yaml
from kwark.ai import APIError
from wizlib.config_handler import ConfigHandler
from wizlib.test_case import WizLibTestCase

from filez4eva import Filez4EvaApp
from filez4eva.command.ingest_command import read_sidecar, write_sidecar
from filez4eva.command.review_command import ReviewCommand
from filez4eva.command.transcribe_command import format_transcript
from filez4eva.error import Filez4EvaError
from filez4eva.fields import values_path


EXTRACT = 'filez4eva.command.classify_command.extract'
TRANSCRIBE = 'filez4eva.command.transcribe_command.transcribe'
NOW = 'filez4eva.command.ingest_command.now'
TTYIN = 'wizlib.io.ttyin'
RUN = 'filez4eva.command.review_command.run'

CLOCK = datetime(2026, 10, 25, 14, 3, 7, 42000,
                 tzinfo=timezone(timedelta(hours=-7)))
AT = '2026-10-25T14:03:07-07:00'
STAMP = '20261025-140307-042'
SECOND = '20261025-140307-043'

PATTERN = '{date.year}/{account}/{date}-{part}'

DATA = {'date': '20261002', 'account': 'amazon', 'part': 'receipt'}

RESULT = {'data': DATA, 'doctype': 'receipt',
          'summary': 'Amazon.ca order receipt for a USB hub'}

CLASSIFY = {'at': AT, 'model': 'claude-haiku-4-5', 'doctype': 'receipt',
            'summary': 'Amazon.ca order receipt for a USB hub',
            'data': DATA}

# results.classify as written before results.given (#72): it held the
# cabinet
OLD_CLASSIFY = dict(CLASSIFY, cabinet='default')

ANSWERS = ['20261002', 'amazon', 'receipt']


def write_store(target, store):
    path = values_path(Path(target))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(store))


class ReviewTestCase(WizLibTestCase):
    """A temporary intake (also set in FILEZ4EVA_INTAKE, so nothing ever
    touches the real one), a source directory, a cabinet target with
    learned values, and a frozen clock"""

    # The stage command run_command runs
    command_class = ReviewCommand

    def setUp(self):
        super().setUp()
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.intake = self.dir / 'intake'
        self.intake.mkdir()
        self.source = self.dir / 'in'
        self.source.mkdir()
        self.target = self.dir / 'target'
        write_store(self.target, {'account': {'amazon': {'count': 3}}})
        self.memories = self.dir / 'memories'
        write_store(self.memories, {'event': {'grandma-bday': {'count': 2}}})
        for patcher in [patch(NOW, return_value=CLOCK),
                        patch.dict(os.environ,
                                   {'FILEZ4EVA_INTAKE': str(self.intake)})]:
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ['FILEZ4EVA_CLASSIFY_MODEL', 'FILEZ4EVA_ANTHROPIC_KEY',
                     'FILEZ4EVA_TRANSCRIBE_MODEL']:
            os.environ.pop(name, None)

    def make(self, name, content='%PDF fake', where=None):
        path = (where or self.source) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def make_document(self, name=f'{STAMP}.pdf', classify=CLASSIFY,
                      transcript='# Hi', review=None, given='default'):
        """Create an ingested document in the intake with its sidecar and
        transcript; classified unless classify is None (and transcribed
        unless transcript is None too). A classified document has
        results.given with the given cabinet, unless given is None (as in
        sidecars from before results.given)."""
        path = self.make(name, where=self.intake)
        results = {'ingest': {'at': AT, 'original-name': 'Scan 1.PDF',
                              'source': {}}}
        if transcript is not None:
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            Path(f'{path}.md').write_text(format_transcript(
                name, sha, 'm', AT, transcript))
            results['transcribe'] = {'at': AT, 'model': 'm',
                                     'transcript': f'{name}.md',
                                     'length': len(transcript)}
        if classify is not None:
            if given is not None:
                results['given'] = {'at': AT, 'cabinet': given}
            results['classify'] = classify
        if review is not None:
            results['review'] = review
        write_sidecar(path, {'results': results})
        return path

    def config(self, **extra):
        values = {'filez4eva_intake': str(self.intake),
                  'filez4eva_target': str(self.target),
                  'filez4eva_pattern': PATTERN,
                  'filez4eva_doctypes': {'receipt': None}}
        values.update(extra)
        return values

    def two_cabinets(self):
        return self.config(filez4eva_cabinets={
            'accounts': {'target': str(self.target), 'pattern': PATTERN},
            'memories': {'target': str(self.memories),
                         'pattern': '{date.year}/{event}/{date}-{part}'}})

    def run_command(self, path=None, keys='', answers=(), config=None,
                    result=RESULT, extract=None, transcribe=None, stdin='',
                    **vals):
        """Run command_class (review) directly with fake config, menu keys
        (one character each), answers to the text prompts and stdin text
        (none by default, so a record piped to the test run is never
        read). Return (output, command, get_text mock, extract mock,
        transcribe mock); stderr is kept in self.err, also when the command
        raises."""
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(**(config or self.config()))
        command = self.command_class(
            app, path=None if path is None else str(path), **vals)
        effect = {'side_effect': extract} if extract \
            else {'return_value': result}
        teffect = {'side_effect': transcribe} if transcribe \
            else {'return_value': '# Hi'}
        answers = iter(answers)
        self.err = ''
        with patch(EXTRACT, **effect) as e, \
                patch(TRANSCRIBE, **teffect) as t, \
                patch(TTYIN, side_effect=list(keys)), \
                self.patch_stream(stdin), \
                patch.object(app.ui, 'get_text',
                             side_effect=lambda *a: next(answers)) as gt, \
                self.patchout(), self.patcherr() as err:
            try:
                out = command.execute()
            finally:
                err.seek(0)
                self.err = err.read()
            return out, command, gt, e, t

    def results(self, document):
        return read_sidecar(document)['results']

    def intake_names(self):
        return sorted(p.name for p in self.intake.iterdir())

    @staticmethod
    def prompts(gt):
        return [c.args for c in gt.call_args_list]


class TestReviewSelection(ReviewTestCase):
    """AC 1: a file, a directory (top level only) or the intake, running
    the earlier stages first"""

    def test_no_path_is_the_intake(self):
        document = self.make_document()
        self.make('old.pdf', where=self.intake / 'archive')
        out, command, _, e, t = self.run_command(keys='c', answers=ANSWERS)
        e.assert_not_called()
        t.assert_not_called()
        self.assertEqual(out, str(document))
        self.assertEqual(command.status, 'Reviewed 1 file')
        self.assertTrue((self.intake / 'archive' / 'old.pdf').is_file())

    def test_file_outside_intake_runs_earlier_stages(self):
        source = self.make('Scan 1.PDF')
        out, command, _, e, t = self.run_command(source, keys='c',
                                                 answers=ANSWERS)
        document = self.intake / f'{STAMP}.pdf'
        self.assertFalse(source.exists())
        t.assert_called_once()
        e.assert_called_once()
        self.assertEqual(out, str(document))
        self.assertEqual(list(self.results(document)), [
            'ingest', 'transcribe', 'given', 'classify', 'review'])
        self.assertEqual(
            command.status, 'Ingested 1 file | Transcribed 1 file | '
            'Classified 1 file | Reviewed 1 file')

    def test_directory_top_level_only(self):
        self.make('a.pdf')
        self.make('b.pdf')
        self.make('.hidden')
        self.make('inner.pdf', where=self.source / 'sub')
        out, command, _, e, _ = self.run_command(
            self.source, keys='cc', answers=ANSWERS + ANSWERS)
        self.assertEqual(out.splitlines(), [
            str(self.intake / f'{STAMP}.pdf'),
            str(self.intake / f'{SECOND}.pdf')])
        self.assertEqual(e.call_count, 2)
        self.assertEqual(sorted(p.name for p in self.source.iterdir()),
                         ['.hidden', 'sub'])

    def test_ingested_but_not_classified(self):
        document = self.make_document(classify=None)
        _, command, _, e, t = self.run_command(keys='c', answers=ANSWERS)
        t.assert_not_called()
        e.assert_called_once()
        self.assertIn('classify', self.results(document))
        self.assertEqual(command.status,
                         'Classified 1 file | Reviewed 1 file')

    def test_document_given_with_ingested(self):
        document = self.make_document()
        self.make_document(f'{SECOND}.pdf')
        out, command, _, _, _ = self.run_command(
            keys='c', answers=ANSWERS, ingested=[document.name])
        self.assertEqual(out, str(document))
        self.assertNotIn('review', self.results(self.intake /
                                                f'{SECOND}.pdf'))

    def test_bad_config_fails_before_anything_moves(self):
        source = self.make('scan.pdf')
        with self.assertRaisesRegex(Filez4EvaError, 'No target'):
            self.run_command(source, config={
                'filez4eva_intake': str(self.intake)})
        self.assertTrue(source.is_file())

    def test_empty_directory(self):
        out, command, _, _, _ = self.run_command(self.source)
        self.assertEqual(out, '')
        self.assertEqual(command.status,
                         f'Nothing to review: no files in {self.source}')

    def test_everything_already_reviewed(self):
        review = {'at': AT, 'cabinet': 'default', 'data': DATA}
        self.make_document(review=review)
        self.make_document(f'{SECOND}.pdf', review=review)
        out, command, _, e, t = self.run_command()
        e.assert_not_called()
        t.assert_not_called()
        self.assertEqual(out, '')
        self.assertEqual(command.status,
                         'Nothing to review (2 files already reviewed)')


class TestReviewConfirm(ReviewTestCase):
    """AC 2, 3 and 5: show the proposed record, confirm or update it, save
    results.review, don't stow"""

    def test_shows_proposed_record(self):
        self.make_document()
        self.run_command(keys='c')
        for line in [f'{STAMP}.pdf (Scan 1.PDF)',
                     'Summary: Amazon.ca order receipt for a USB hub',
                     'Doctype: receipt', 'Cabinet: default',
                     'Date: 20261002', 'Account: amazon', 'Part: receipt',
                     '(c)onfirm (u)pdate (r)edo (x)skip (p)review '
                     '(d)elete (q)uit', 'Reviewed']:
            self.assertIn(line, self.err)

    def test_menu_prompt(self):
        self.assertEqual(
            ReviewCommand.ACTION_CHOOSER.prompt_string,
            '(c)onfirm (u)pdate (r)edo (x)skip (p)review (d)elete (q)uit: ')

    def test_update_prefilled(self):
        document = self.make_document()
        _, _, gt, _, _ = self.run_command(keys='u', answers=ANSWERS)
        # One cabinet: no cabinet prompt; fields pre-filled
        self.assertEqual(self.prompts(gt), [
            ('Date: ', [], '20261002'),
            ('Account: ', ['amazon'], 'amazon'),
            ('Part: ', [], 'receipt')])
        results = self.results(document)
        self.assertEqual(results['review'], {
            'at': AT, 'cabinet': 'default', 'data': DATA})
        self.assertEqual(list(results['review']['data']),
                         ['date', 'account', 'part'])
        self.assertEqual(results['classify'], CLASSIFY)

    def test_update_edited(self):
        document = self.make_document()
        self.run_command(keys='u', answers=['20261003', 'Royal Bank',
                                            'statement'])
        self.assertEqual(self.results(document)['review']['data'], {
            'date': '20261003', 'account': 'royal-bank',
            'part': 'statement'})
        self.assertEqual(self.results(document)['classify'], CLASSIFY)

    def test_no_date_prompt_starts_empty(self):
        document = self.make_document(
            classify=dict(CLASSIFY, data=dict(DATA, date=None)))
        _, _, gt, _, _ = self.run_command(keys='u', answers=ANSWERS)
        self.assertEqual(self.prompts(gt)[0], ('Date: ', []))
        self.assertIn('Date: (none)', self.err)
        self.assertEqual(self.results(document)['review']['data'], DATA)

    def test_hand_edited_number_prefilled_as_text(self):
        # An unquoted date in a hand-edited X.yml loads as a number
        self.make_document(classify=dict(CLASSIFY,
                                         data=dict(DATA, date=20261002)))
        _, _, gt, _, _ = self.run_command(keys='u', answers=ANSWERS)
        self.assertEqual(self.prompts(gt)[0], ('Date: ', [], '20261002'))

    def test_invalid_value_asks_again(self):
        document = self.make_document()
        self.run_command(keys='u', answers=['2026-13-01', '20261002', '//',
                                            'amazon', 'receipt'])
        self.assertIn('Date must match format YYYYMMDD', self.err)
        self.assertIn('Account must contain letters or digits', self.err)
        self.assertEqual(self.results(document)['review']['data'], DATA)

    def test_empty_answer_returns_to_menu(self):
        document = self.make_document()
        _, command, _, _, _ = self.run_command(
            keys='ux', answers=['20261002', ''])
        self.assertIn('Account required', self.err)
        self.assertNotIn('review', self.results(document))
        self.assertEqual(command.status, 'Skipped 1 file')

    def test_unknown_key_asks_again(self):
        self.make_document()
        _, command, _, _, _ = self.run_command(keys='z\nc', answers=ANSWERS)
        self.assertEqual(command.status, 'Reviewed 1 file')

    def test_does_not_stow(self):
        document = self.make_document()
        self.run_command(keys='c', answers=ANSWERS)
        self.assertEqual(self.intake_names(), [
            f'{STAMP}.pdf', f'{STAMP}.pdf.md', f'{STAMP}.pdf.yml'])
        self.assertTrue(document.is_file())
        self.assertFalse((self.target / '2026').exists())
        self.assertNotIn('stow', self.results(document))


class TestReviewMenu(ReviewTestCase):
    """AC 4 and 6: skip, preview, delete, quit; reviewed documents aren't
    offered again"""

    def test_skip_leaves_document_and_is_offered_again(self):
        document = self.make_document()
        before = Path(f'{document}.yml').read_text()
        _, command, _, _, _ = self.run_command(keys='x')
        self.assertEqual(command.status, 'Skipped 1 file')
        self.assertEqual(Path(f'{document}.yml').read_text(), before)
        _, command, _, _, _ = self.run_command(keys='c', answers=ANSWERS)
        self.assertEqual(command.status, 'Reviewed 1 file')

    def test_quit_leaves_the_rest(self):
        first = self.make_document()
        second = self.make_document(f'{SECOND}.pdf')
        third = self.make_document('20261025-140307-044.pdf')
        out, command, _, _, _ = self.run_command(keys='cq', answers=ANSWERS)
        self.assertEqual(out, str(first))
        self.assertIn('review', self.results(first))
        self.assertNotIn('review', self.results(second))
        self.assertNotIn('review', self.results(third))
        self.assertEqual(command.status, 'Reviewed 1 file | Quit')

    def test_quit_straight_away(self):
        self.make_document()
        out, command, _, _, _ = self.run_command(keys='q')
        self.assertEqual(out, '')
        self.assertEqual(command.status, 'Quit')

    def test_delete_removes_document_sidecar_and_transcript(self):
        self.make_document()
        other = self.make_document(f'{SECOND}.pdf')
        _, command, _, _, _ = self.run_command(keys='dYx')
        self.assertEqual(self.intake_names(), [
            f'{SECOND}.pdf', f'{SECOND}.pdf.md', f'{SECOND}.pdf.yml'])
        self.assertNotIn('review', self.results(other))
        self.assertEqual(command.status, 'Deleted 1 file | Skipped 1 file')

    def test_delete_ignores_recorded_transcript_name(self):
        document = self.make_document()
        other = self.make_document(f'{SECOND}.pdf')
        data = read_sidecar(document)
        data['results']['transcribe']['transcript'] = other.name
        write_sidecar(document, data)
        _, command, _, _, _ = self.run_command(keys='dYx')
        self.assertEqual(self.intake_names(), [
            f'{SECOND}.pdf', f'{SECOND}.pdf.md', f'{SECOND}.pdf.yml'])
        self.assertEqual(command.status, 'Deleted 1 file | Skipped 1 file')

    def test_delete_with_parent_as_recorded_transcript(self):
        document = self.make_document()
        data = read_sidecar(document)
        data['results']['transcribe']['transcript'] = '..'
        write_sidecar(document, data)
        _, command, _, _, _ = self.run_command(keys='dY')
        self.assertEqual(self.intake_names(), [])
        self.assertTrue(self.intake.is_dir())
        self.assertEqual(command.status, 'Deleted 1 file')

    def test_delete_without_transcript(self):
        document = self.make_document()
        Path(f'{document}.md').unlink()
        _, command, _, _, _ = self.run_command(keys='dY')
        self.assertEqual(self.intake_names(), [])
        self.assertEqual(command.status, 'Deleted 1 file')

    def test_delete_without_recorded_transcript_name(self):
        document = self.make_document()
        data = read_sidecar(document)
        del data['results']['transcribe']['transcript']
        write_sidecar(document, data)
        self.run_command(keys='dY')
        self.assertEqual(self.intake_names(), [])

    def test_delete_declined(self):
        document = self.make_document()
        _, command, _, _, _ = self.run_command(keys='d\ndNx')
        self.assertTrue(document.is_file())
        self.assertEqual(command.status, 'Skipped 1 file')

    def test_delete_prompt(self):
        self.assertEqual(ReviewCommand.DELETE_CHOOSER.prompt_string,
                         'Delete? [No] (Y)es: ')

    def test_preview(self):
        document = self.make_document()
        with patch(RUN) as run:
            _, command, _, _, _ = self.run_command(keys='pc',
                                                   answers=ANSWERS)
        run.assert_called_once_with(['preview', document])
        self.assertEqual(command.status, 'Reviewed 1 file')

    def test_preview_failure_is_reported(self):
        self.make_document()
        with patch(RUN, side_effect=FileNotFoundError('no preview')):
            _, command, _, _, _ = self.run_command(keys='px')
        self.assertIn('Could not preview', self.err)
        self.assertEqual(command.status, 'Skipped 1 file')

    def test_already_reviewed_not_offered(self):
        review = {'at': AT, 'cabinet': 'default', 'data': DATA}
        reviewed = self.make_document(review=review)
        self.make_document(f'{SECOND}.pdf')
        out, command, _, _, _ = self.run_command(keys='c', answers=ANSWERS)
        self.assertEqual(out, str(self.intake / f'{SECOND}.pdf'))
        self.assertEqual(self.results(reviewed)['review'], review)
        self.assertEqual(command.status,
                         'Reviewed 1 file | Already reviewed 1 file')


class TestReviewOnly(ReviewTestCase):
    """AC 7: --only reviews only classified documents"""

    def test_only_skips_with_notes(self):
        source = self.make('scan.pdf')
        self.make_document(classify=None, transcript=None)
        self.make_document(f'{SECOND}.pdf', classify=None)
        classified = self.make_document('20261025-140307-044.pdf')
        out, command, _, e, t = self.run_command(keys='c', answers=ANSWERS,
                                                 only=True)
        e.assert_not_called()
        t.assert_not_called()
        self.assertEqual(out, str(classified))
        self.assertTrue(source.is_file())
        self.assertIn('not transcribed yet', self.err)
        self.assertIn('not classified yet', self.err)
        # The most advanced first: classified, transcribed, ingested
        self.assertEqual(
            command.status, 'Reviewed 1 file | Skipped 1 file (not '
            'classified) | Skipped 1 file (not transcribed)')

    def test_only_skips_files_not_ingested(self):
        source = self.make('scan.pdf')
        _, command, _, _, _ = self.run_command(source, only=True)
        self.assertTrue(source.is_file())
        self.assertIn(f'Skipped {source}: not ingested yet', self.err)


class TestReviewFailures(ReviewTestCase):
    """AC 8: a failure is reported, the run carries on, and the exit code
    is non-zero"""

    def test_failure_carries_on(self):
        self.make('a.pdf')
        self.make('b.pdf')
        calls = iter([APIError('nope'), '# Hi'])

        def transcribe(*args, **kwargs):
            value = next(calls)
            if isinstance(value, Exception):
                raise value
            return value
        with self.assertRaisesRegex(Filez4EvaError, '1 of 2 files failed'):
            self.run_command(self.source, keys='c', answers=ANSWERS,
                             transcribe=transcribe)
        self.assertIn('Failed to review', self.err)
        self.assertIn('Transcription failed: nope', self.err)
        self.assertIn('review', self.results(self.intake / f'{SECOND}.pdf'))
        self.assertNotIn('classify',
                         self.results(self.intake / f'{STAMP}.pdf'))

    def test_bad_classify_result_is_a_failure(self):
        for classify, given, message in [
                ('text', 'default', 'must be a mapping'),
                (dict(CLASSIFY, cabinet=''), None, 'No cabinet saved'),
                (dict(CLASSIFY, data='x'), 'default',
                 'data must be a mapping')]:
            with self.subTest(message):
                for path in self.intake.iterdir():
                    path.unlink()
                self.make_document(classify=classify, given=given)
                with self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
                    self.run_command()
                self.assertIn(message, self.err)

    def test_classify_without_data_prompts_empty(self):
        document = self.make_document(
            classify={'data': None})
        _, _, gt, _, _ = self.run_command(keys='u', answers=ANSWERS)
        self.assertEqual(self.prompts(gt), [
            ('Date: ', []), ('Account: ', ['amazon']), ('Part: ', [])])
        self.assertEqual(self.results(document)['review']['data'], DATA)

    def test_exit_code_from_app(self):
        self.make('a.pdf')
        code = 0
        with patch(EXTRACT, return_value=RESULT), \
                patch(TRANSCRIBE, side_effect=APIError('nope')), \
                self.patchout(), self.patcherr() as e, \
                self.patch_stream(''), \
                NamedTemporaryFile('w+', suffix='.yml') as cf:
            cf.write(f"filez4eva:\n  intake: {self.intake}\n"
                     f"  target: {self.target}\n"
                     "  doctypes:\n    receipt:\n")
            cf.flush()
            try:
                Filez4EvaApp.start('--config', cf.name, 'review',
                                   str(self.source))
            except SystemExit as exit:
                code = exit.code
            e.seek(0)
            err = e.read()
        self.assertEqual(code, 1)
        self.assertIn('1 of 1 file failed to review', err)


class TestReviewCabinet(ReviewTestCase):
    """#72: review never prompts for the cabinet; it uses the one saved
    for the document, chosen before it is classified"""

    def test_saved_cabinet_no_prompt(self):
        document = self.make_document(given='accounts')
        _, _, gt, _, _ = self.run_command(keys='u', answers=ANSWERS,
                                          config=self.two_cabinets())
        self.assertEqual(self.prompts(gt), [
            ('Date: ', [], '20261002'),
            ('Account: ', ['amazon'], 'amazon'),
            ('Part: ', [], 'receipt')])
        self.assertEqual(self.results(document)['review'], {
            'at': AT, 'cabinet': 'accounts', 'data': DATA})

    def test_old_shape_sidecar(self):
        # Written before results.given: the cabinet is in results.classify
        classify = dict(CLASSIFY, cabinet='memories')
        document = self.make_document(classify=classify, given=None)
        _, _, gt, _, _ = self.run_command(
            keys='u', answers=['20261002', 'grandma-bday', 'receipt'],
            config=self.two_cabinets())
        self.assertEqual(self.prompts(gt), [
            ('Date: ', [], '20261002'),
            ('Event: ', ['grandma-bday']),
            ('Part: ', [], 'receipt')])
        results = self.results(document)
        self.assertEqual(results['review'], {
            'at': AT, 'cabinet': 'memories',
            'data': {'date': '20261002', 'event': 'grandma-bday',
                     'part': 'receipt'}})
        self.assertEqual(results['classify'], classify)
        self.assertNotIn('given', results)

    def test_saved_cabinet_no_longer_configured(self):
        document = self.make_document(given='old')
        with self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
            self.run_command(keys='c', answers=ANSWERS,
                             config=self.two_cabinets())
        self.assertIn('Unknown cabinet old', self.err)
        self.assertNotIn('review', self.results(document))

    def test_cabinet_flag_on_review(self):
        source = self.make('photo.jpg')
        memory = {'data': {'date': '20261002', 'event': 'Grandma Bday',
                           'part': 'photo'},
                  'doctype': 'other', 'summary': 'Photo'}
        _, command, gt, e, _ = self.run_command(
            source, keys='c', answers=['20261002', 'grandma-bday', 'photo'],
            config=self.two_cabinets(), result=memory, cabinet='memories')
        e.assert_called_once()
        self.assertNotIn('Cabinet: ', [p[0] for p in self.prompts(gt)])
        document = self.intake / f'{STAMP}.jpg'
        results = self.results(document)
        self.assertEqual(results['given'], {'at': AT, 'cabinet': 'memories'})
        self.assertEqual(results['review']['cabinet'], 'memories')

    def test_prompt_for_unclassified_before_classify(self):
        source = self.make('photo.jpg')
        memory = {'data': {'date': '20261002', 'event': 'Grandma Bday',
                           'part': 'photo'},
                  'doctype': 'other', 'summary': 'Photo'}
        _, _, gt, e, _ = self.run_command(
            source, keys='c',
            answers=['memories', '20261002', 'grandma-bday', 'photo'],
            config=self.two_cabinets(), result=memory)
        # The cabinet prompt has no pre-filled value: the model proposes
        # none
        self.assertEqual(self.prompts(gt)[0], (
            'Cabinet: ', ['accounts', 'memories']))
        e.assert_called_once()
        self.assertNotIn('cabinet', e.call_args.args[1]['properties'])
        document = self.intake / f'{STAMP}.jpg'
        self.assertEqual(self.results(document)['review']['cabinet'],
                         'memories')

    def test_empty_cabinet_skips_unclassified(self):
        document = self.make_document(classify=None)
        _, command, _, e, _ = self.run_command(
            answers=[''], config=self.two_cabinets())
        e.assert_not_called()
        self.assertEqual(command.status, 'Skipped 1 file')
        self.assertEqual(list(self.results(document)),
                         ['ingest', 'transcribe'])

    def test_conflicting_cabinet_fails_that_document_only(self):
        first = self.make_document(given='accounts')
        second = self.make_document(f'{SECOND}.pdf', given='memories')
        with self.assertRaisesRegex(Filez4EvaError,
                                    '1 of 2 files failed to review'):
            self.run_command(keys='u', config=self.two_cabinets(),
                             answers=['20261002', 'grandma-bday', 'x'],
                             cabinet='memories')
        self.assertIn(f'Failed to review {first}: Cabinet memories given, '
                      f'but {first.name} already has cabinet accounts',
                      self.err)
        self.assertNotIn('review', self.results(first))
        self.assertEqual(self.results(second)['review']['cabinet'],
                         'memories')

    def test_unknown_cabinet_flag_touches_nothing(self):
        source = self.make('scan.pdf')
        document = self.make_document()
        before = Path(f'{document}.yml').read_text()
        for path in [source, None]:
            with self.subTest(path=path), \
                    self.assertRaisesRegex(Filez4EvaError,
                                           'Unknown cabinet nope'):
                self.run_command(path, config=self.two_cabinets(),
                                 cabinet='nope')
        self.assertTrue(source.is_file())
        self.assertEqual(Path(f'{document}.yml').read_text(), before)


# What the model proposes for the memories cabinet
MEMORY = {'data': {'date': '20261002', 'event': 'Grandma Bday',
                   'part': 'cake'},
          'doctype': 'other', 'summary': 'Photo of a birthday cake'}

MEMORY_DATA = {'date': '20261002', 'event': 'grandma-bday', 'part': 'cake'}


class TestReviewActions(ReviewTestCase):
    """#73: (c)onfirm saves as is, (u)pdate edits, (r)edo changes the
    cabinet and classifies again"""

    def test_confirm_saves_without_prompting(self):
        document = self.make_document()
        out, command, gt, e, _ = self.run_command(keys='c')
        gt.assert_not_called()
        e.assert_not_called()
        self.assertEqual(out, str(document))
        results = self.results(document)
        self.assertEqual(results['review'], {
            'at': AT, 'cabinet': 'default', 'data': DATA})
        self.assertEqual(list(results['review']['data']),
                         ['date', 'account', 'part'])
        self.assertEqual(results['classify'], CLASSIFY)
        self.assertEqual(command.status, 'Reviewed 1 file')

    def test_confirm_with_saved_cabinet(self):
        document = self.make_document(given='accounts')
        _, _, gt, _, _ = self.run_command(keys='c',
                                          config=self.two_cabinets())
        gt.assert_not_called()
        self.assertEqual(self.results(document)['review'], {
            'at': AT, 'cabinet': 'accounts', 'data': DATA})

    def test_confirm_hand_edited_values_as_text(self):
        # An unquoted date in a hand-edited X.yml loads as a number; other
        # values are normalized
        document = self.make_document(classify=dict(
            CLASSIFY, data=dict(DATA, date=20261002, account='Amazon CA')))
        _, _, gt, _, _ = self.run_command(keys='c')
        gt.assert_not_called()
        self.assertEqual(self.results(document)['review']['data'],
                         dict(DATA, account='amazon-ca'))

    def test_confirm_with_missing_date_refuses_and_asks_again(self):
        document = self.make_document(
            classify=dict(CLASSIFY, data=dict(DATA, date=None)))
        _, command, gt, _, _ = self.run_command(keys='cx')
        gt.assert_not_called()
        self.assertIn('Missing: date. Use (u)pdate.', self.err)
        self.assertEqual(self.err.count('(c)onfirm'), 2)
        self.assertNotIn('review', self.results(document))
        self.assertEqual(command.status, 'Skipped 1 file')

    def test_confirm_refused_then_update(self):
        document = self.make_document(
            classify=dict(CLASSIFY, data={'date': '', 'account': 'amazon'}))
        _, command, gt, _, _ = self.run_command(
            keys='cu', answers=['20261002', 'amazon', 'receipt'])
        self.assertIn('Missing: date, part. Use (u)pdate.', self.err)
        self.assertEqual(self.prompts(gt), [
            ('Date: ', []), ('Account: ', ['amazon'], 'amazon'),
            ('Part: ', [])])
        self.assertEqual(self.results(document)['review']['data'], DATA)
        self.assertEqual(command.status, 'Reviewed 1 file')

    def test_confirm_with_invalid_values_refuses(self):
        document = self.make_document(classify=dict(
            CLASSIFY, data=dict(DATA, date='2026-13-01', account='//')))
        self.run_command(keys='cx')
        self.assertIn('Invalid: date, account. Use (u)pdate.', self.err)
        self.assertNotIn('review', self.results(document))

    def test_confirm_unknown_saved_cabinet_fails(self):
        document = self.make_document(given='old')
        with self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
            self.run_command(keys='c', config=self.two_cabinets())
        self.assertIn('Unknown cabinet old', self.err)
        self.assertNotIn('review', self.results(document))

    def test_update_prefills_and_saves_edited_values(self):
        document = self.make_document()
        _, command, gt, e, _ = self.run_command(
            keys='u', answers=['20261003', 'Royal Bank', 'statement'])
        e.assert_not_called()
        self.assertEqual(self.prompts(gt), [
            ('Date: ', [], '20261002'),
            ('Account: ', ['amazon'], 'amazon'),
            ('Part: ', [], 'receipt')])
        self.assertEqual(self.results(document)['review'], {
            'at': AT, 'cabinet': 'default',
            'data': {'date': '20261003', 'account': 'royal-bank',
                     'part': 'statement'}})
        self.assertEqual(command.status, 'Reviewed 1 file')

    def test_update_with_empty_input_saves_nothing(self):
        document = self.make_document()
        before = Path(f'{document}.yml').read_text()
        _, command, gt, _, _ = self.run_command(keys='ux', answers=[''])
        self.assertEqual(len(gt.call_args_list), 1)
        self.assertEqual(self.err.count('(c)onfirm'), 2)
        self.assertEqual(Path(f'{document}.yml').read_text(), before)
        self.assertEqual(command.status, 'Skipped 1 file')

    def test_redo_with_several_cabinets_changes_cabinet(self):
        document = self.make_document(given='accounts')
        _, command, gt, e, _ = self.run_command(
            keys='rc', answers=['memories'], config=self.two_cabinets(),
            result=MEMORY)
        # Pre-filled with the current cabinet, completing the names
        self.assertEqual(self.prompts(gt), [
            ('Cabinet: ', ['accounts', 'memories'], 'accounts')])
        # Classified again, for the new cabinet's fields
        e.assert_called_once()
        schema = e.call_args.args[1]
        self.assertEqual(list(schema['properties']['data']['properties']),
                         ['date', 'event', 'part'])
        self.assertIn('"memories"', e.call_args.kwargs['instructions'])
        results = self.results(document)
        self.assertEqual(results['given'], {'at': AT, 'cabinet': 'memories'})
        self.assertEqual(results['classify']['data'], MEMORY_DATA)
        self.assertNotIn('cabinet', results['classify'])
        # The new proposal is shown and the menu asked again
        self.assertIn('Cabinet: memories', self.err)
        self.assertIn('Event: grandma-bday', self.err)
        self.assertEqual(self.err.count('(c)onfirm'), 2)
        self.assertEqual(results['review'], {
            'at': AT, 'cabinet': 'memories', 'data': MEMORY_DATA})
        self.assertEqual(command.status, 'Reviewed 1 file')

    def test_redo_again(self):
        document = self.make_document(given='accounts')
        _, _, gt, e, _ = self.run_command(
            keys='rrc', answers=['memories', 'accounts'],
            config=self.two_cabinets(),
            extract=[MEMORY, RESULT])
        self.assertEqual(self.prompts(gt), [
            ('Cabinet: ', ['accounts', 'memories'], 'accounts'),
            ('Cabinet: ', ['accounts', 'memories'], 'memories')])
        self.assertEqual(e.call_count, 2)
        self.assertEqual(self.results(document)['review'], {
            'at': AT, 'cabinet': 'accounts', 'data': DATA})

    def test_redo_with_one_cabinet_reclassifies_without_prompt(self):
        document = self.make_document()
        result = dict(RESULT, data=dict(DATA, part='invoice'))
        _, command, gt, e, _ = self.run_command(keys='rc', result=result)
        gt.assert_not_called()
        e.assert_called_once()
        results = self.results(document)
        self.assertEqual(results['given'], {'at': AT, 'cabinet': 'default'})
        self.assertEqual(results['classify']['data']['part'], 'invoice')
        self.assertIn('Part: invoice', self.err)
        self.assertEqual(results['review']['data'],
                         dict(DATA, part='invoice'))
        self.assertEqual(command.status, 'Reviewed 1 file')

    def test_redo_with_empty_input_changes_nothing(self):
        document = self.make_document(given='accounts')
        before = Path(f'{document}.yml').read_text()
        _, command, gt, e, _ = self.run_command(
            keys='rx', answers=[''], config=self.two_cabinets())
        self.assertEqual(len(gt.call_args_list), 1)
        e.assert_not_called()
        self.assertEqual(self.err.count('(c)onfirm'), 2)
        self.assertEqual(Path(f'{document}.yml').read_text(), before)
        self.assertEqual(command.status, 'Skipped 1 file')

    def test_redo_unknown_cabinet_asks_again(self):
        document = self.make_document(given='accounts')
        _, _, gt, e, _ = self.run_command(
            keys='rc', answers=['nope', 'memories'],
            config=self.two_cabinets(), result=MEMORY)
        self.assertEqual(len(gt.call_args_list), 2)
        self.assertIn('Cabinet must be one of: accounts, memories',
                      self.err)
        e.assert_called_once()
        self.assertEqual(self.results(document)['review']['cabinet'],
                         'memories')

    def test_redo_replaces_unconfigured_saved_cabinet(self):
        document = self.make_document(given='old')
        _, _, gt, _, _ = self.run_command(
            keys='rc', answers=['memories'], config=self.two_cabinets(),
            result=MEMORY)
        self.assertEqual(self.prompts(gt), [
            ('Cabinet: ', ['accounts', 'memories'], 'old')])
        self.assertEqual(self.results(document)['review']['cabinet'],
                         'memories')

    def test_redo_old_shape_sidecar(self):
        # Written before results.given: the old results.classify held the
        # cabinet; redo saves results.given and replaces results.classify
        document = self.make_document(
            classify=dict(CLASSIFY, cabinet='accounts'), given=None)
        self.run_command(keys='rc', answers=['memories'],
                         config=self.two_cabinets(), result=MEMORY)
        results = self.results(document)
        self.assertEqual(results['given'], {'at': AT, 'cabinet': 'memories'})
        self.assertNotIn('cabinet', results['classify'])
        self.assertEqual(results['review']['cabinet'], 'memories')

    def test_redo_failure_fails_the_document(self):
        document = self.make_document(given='accounts')
        with self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
            self.run_command(keys='r', answers=['memories'],
                             config=self.two_cabinets(),
                             extract=APIError('nope'))
        self.assertIn('Classification failed: nope', self.err)
        results = self.results(document)
        self.assertEqual(results['given']['cabinet'], 'memories')
        self.assertNotIn('classify', results)
        self.assertNotIn('review', results)


class TestReviewGivenData(ReviewTestCase):
    """#74 behaviour 4: given values are shown marked (given); confirm
    accepts them, update can change them, redo keeps those the new cabinet
    has"""

    def given_document(self, data, given='default', **kwargs):
        """A classified document with values given for it"""
        document = self.make_document(given=given, **kwargs)
        results = self.results(document)
        results['given']['data'] = data
        write_sidecar(document, {'results': results})
        return document

    def test_classify_with_given_date_then_review_shows_given(self):
        source = self.make('Scan 1.PDF')
        out, command, gt, e, _ = self.run_command(
            source, keys='c', date='20240213', cabinet='default',
            result={'data': {'account': 'amazon', 'part': 'receipt'},
                    'doctype': 'receipt', 'summary': 'A receipt'})
        gt.assert_not_called()
        schema = e.call_args.args[1]['properties']['data']
        self.assertNotIn('date', schema['properties'])
        self.assertIn('Date: 20240213 (given)', self.err)
        self.assertIn('Account: amazon', self.err)
        self.assertNotIn('Account: amazon (given)', self.err)
        document = self.intake / f'{STAMP}.pdf'
        self.assertEqual(self.results(document)['review'], {
            'at': AT, 'cabinet': 'default',
            'data': dict(DATA, date='20240213')})
        self.assertEqual(command.status, 'Ingested 1 file | Transcribed 1 '
                         'file | Classified 1 file | Reviewed 1 file')

    def test_given_value_shown_over_a_classified_one(self):
        document = self.given_document({'part': 'visa'})
        self.run_command(keys='c')
        self.assertIn('Part: visa (given)', self.err)
        self.assertEqual(self.results(document)['review']['data'],
                         dict(DATA, part='visa'))

    def test_update_can_change_a_given_value(self):
        document = self.given_document({'date': '20261002'})
        _, _, gt, _, _ = self.run_command(
            keys='u', answers=['20240213', 'amazon', 'receipt'])
        # Pre-filled like any other value
        self.assertEqual(self.prompts(gt)[0], ('Date: ', [], '20261002'))
        results = self.results(document)
        self.assertEqual(results['review']['data'],
                         dict(DATA, date='20240213'))
        # What was given stays on record
        self.assertEqual(results['given']['data'], {'date': '20261002'})

    def test_redo_keeps_the_given_values_the_new_cabinet_has(self):
        document = self.given_document(
            {'date': '20261002', 'account': 'amazon'}, given='accounts')
        _, _, _, e, _ = self.run_command(
            keys='rc', answers=['memories'], config=self.two_cabinets(),
            result={'data': {'event': 'party', 'part': 'cake'},
                    'doctype': 'other', 'summary': 'Cake'})
        schema = e.call_args.args[1]['properties']['data']
        self.assertEqual(list(schema['properties']), ['event', 'part'])
        results = self.results(document)
        self.assertEqual(results['given'], {
            'at': AT, 'cabinet': 'memories', 'data': {'date': '20261002'}})
        self.assertEqual(results['review']['data'], {
            'date': '20261002', 'event': 'party', 'part': 'cake'})
        self.assertIn('Date: 20261002 (given)', self.err)

    def test_complete_data_needs_no_menu(self):
        document = self.make_document(classify=None)
        out, command, gt, e, _ = self.run_command(
            stdin='data:\n  date: 20261002\n  account: amazon\n'
            '  part: receipt\n')
        gt.assert_not_called()
        e.assert_not_called()
        self.assertNotIn('(c)onfirm', self.err)
        self.assertEqual(out, str(document))
        self.assertEqual(self.results(document)['review'], {
            'at': AT, 'input': True, 'cabinet': 'default', 'data': DATA})
        self.assertEqual(command.status, 'Given 1 file')

    def test_conflict_fails_only_that_document(self):
        first = self.given_document({'part': 'visa'})
        second = self.make_document(f'{SECOND}.pdf', classify=None)
        with self.assertRaisesRegex(Filez4EvaError,
                                    '1 of 2 files failed to review'):
            self.run_command(keys='c', field=['part=receipt'])
        self.assertIn(f'Failed to review {first}: Part receipt given, but '
                      f'{first.name} already has part visa', self.err)
        self.assertNotIn('review', self.results(first))
        self.assertEqual(self.results(second)['review']['data'], DATA)
