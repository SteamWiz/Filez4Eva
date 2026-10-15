from io import StringIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from filez4eva.command.scan_dir_command import ScanDirCommand
from filez4eva.command import Filez4EvaCommand
from filez4eva import Filez4EvaApp
from filez4eva.fields import values_path

from kwark.ai import APIError
from wizlib.config_handler import ConfigHandler
from wizlib.app import AppCancellation
from wizlib.test_case import WizLibTestCase
from wizlib.ui.shell import S


EXTRACT = 'filez4eva.command.classify_command.extract'
TRANSCRIBE = 'filez4eva.command.transcribe_command.transcribe'


class TestCommandScan(WizLibTestCase):
    """Without AI: transcription fails, so stowing falls back to empty
    prompts (the behaviour before AI pre-filling)"""

    def setUp(self):
        super().setUp()
        patcher = patch(TRANSCRIBE, side_effect=APIError('offline'))
        self.transcribe = patcher.start()
        self.addCleanup(patcher.stop)

    def test_dir(self):
        sourcefn1: str = 'b.txt'
        sourcefn2: str = 'c.txt'
        sourcecontent: str = 'a'
        stowedpath1: str = '/20240213-t.txt'
        stowedpath2: str = '/20231211-u.txt'
        keys = 's20240213\nt\ns20231211\nu\n'
        with \
                TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                self.patchout() as o, \
                self.patcherr() as e, \
                self.patch_ttyin(keys):
            for fn in [sourcefn1, sourcefn2]:
                n = Path(source) / fn
                with open(n, 'w') as f:
                    f.write(sourcecontent)
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(
                filez4eva_target=target)
            c = ScanDirCommand(a, dir=str(source))
            c.execute()
            with open(target + stowedpath1, 'r') as f:
                r1 = f.read()
            with open(target + stowedpath2, 'r') as f:
                r2 = f.read()
        self.assertEqual(r1 + r2, 'aa')
        self.assertEqual(c.status, 'Stowed 2 files')

    def test_invalid_prompted_part_does_not_abort(self):
        # A value with no letters or digits re-asks; the session carries on
        # to the next file instead of ending.
        keys = 's20240213\n//\nt\ns20231211\nu\n'
        with \
                TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                self.patchout(), \
                self.patcherr() as e, \
                self.patch_ttyin(keys):
            for fn in ['b.txt', 'c.txt']:
                (Path(source) / fn).write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target)
            c = ScanDirCommand(a, dir=str(source))
            c.execute()
            self.assertTrue(
                (Path(target) / '20240213-t.txt').is_file())
            self.assertTrue(
                (Path(target) / '20231211-u.txt').is_file())
            e.seek(0)
            self.assertIn('Title must contain letters or digits', e.read())
        self.assertEqual(c.status, 'Stowed 2 files')

    def test_quit(self):
        keys = 'q'
        with \
                TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                self.patchout() as o, \
                self.patcherr() as e, \
                self.patch_ttyin(keys):
            n = Path(source) / 'b.txt'
            with open(n, 'w') as f:
                f.write('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(
                filez4eva_target=target)
            c = ScanDirCommand(a, dir=str(source))
            with self.assertRaises(AppCancellation):
                c.execute()

    def test_delete(self):
        sourcefn1: str = 'b.txt'
        sourcefn2: str = 'c.txt'
        sourcecontent: str = 'a'
        keys = 'dYx'
        with \
                TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                self.patchout() as o, \
                self.patcherr() as e, \
                self.patch_ttyin(keys):
            for fn in [sourcefn1, sourcefn2]:
                n = Path(source) / fn
                with open(n, 'w') as f:
                    f.write(sourcecontent)
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(
                filez4eva_target=target)
            c = ScanDirCommand(a, dir=str(source))
            c.execute()
            nx = [x.name for x in Path(source).iterdir()]
        self.assertEqual(nx, ['c.txt'])

    def _run_delete_declined(self, keys):
        with \
                TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                self.patchout() as o, \
                self.patcherr() as e, \
                self.patch_ttyin(keys):
            n = Path(source) / 'b.txt'
            with open(n, 'w') as f:
                f.write('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(
                filez4eva_target=target)
            c = ScanDirCommand(a, dir=str(source))
            c.execute()
            nx = [x.name for x in Path(source).iterdir()]
        self.assertEqual(nx, ['b.txt'])
        self.assertEqual(c.status, 'Skipped 1 file')

    def test_delete_declined_default(self):
        # Enter at the confirmation takes the default ('No')
        self._run_delete_declined('d\nx')

    def test_delete_declined_explicit(self):
        self._run_delete_declined('dNx')

    def test_delete_prompt(self):
        self.assertEqual(ScanDirCommand.DELETE_CHOOSER.prompt_string,
                         'Delete? [No] (Y)es: ')

    def test_preview(self):
        sourcefn1: str = 'b.txt'
        sourcecontent: str = 'a'
        keys = 'px'
        with \
                TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                self.patchout() as o, \
                self.patcherr() as e, \
                self.patch_ttyin(keys), \
                patch('filez4eva.command.scan_dir_command.run', rm := Mock()):
            for fn in [sourcefn1]:
                n = Path(source) / fn
                with open(n, 'w') as f:
                    f.write(sourcecontent)
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(
                filez4eva_target=target)
            c = ScanDirCommand(a, dir=str(source))
            c.execute()
            rm.assert_called_once()

    def test_from_app(self):
        sourcefn1: str = 'b.txt'
        sourcefn2: str = 'c.txt'
        sourcecontent: str = 'a'
        stowedpath1: str = '/20240213-t.txt'
        stowedpath2: str = '/20231211-u.txt'
        keys = 's20240213\nt\ns20231211\nu\n'
        with \
                TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                self.patchout() as o, \
                self.patcherr() as e, \
                self.patch_ttyin(keys):
            for fn in [sourcefn1, sourcefn2]:
                n = Path(source) / fn
                with open(n, 'w') as f:
                    f.write(sourcecontent)
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(
                filez4eva_target=target,
                filez4eva_source=source)
            a.parse_run('scan-dir', source)
            with open(target + stowedpath1, 'r') as f:
                r1 = f.read()
            with open(target + stowedpath2, 'r') as f:
                r2 = f.read()
        self.assertEqual(r1 + r2, 'aa')
        e.seek(0)
        self.assertIn('Stowed 2 files', e.read())

    def test_config_source(self):
        sourcefn1: str = 'b.txt'
        sourcefn2: str = 'c.txt'
        sourcecontent: str = 'a'
        stowedpath1: str = '/20240213-t.txt'
        stowedpath2: str = '/20231211-u.txt'
        keys = 's20240213\nt\ns20231211\nu\n'
        with \
                TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                self.patchout() as o, \
                self.patcherr() as e, \
                self.patch_ttyin(keys):
            for fn in [sourcefn1, sourcefn2]:
                n = Path(source) / fn
                with open(n, 'w') as f:
                    f.write(sourcecontent)
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(
                filez4eva_target=target,
                filez4eva_source=source)
            a.parse_run('scan-dir')
            with open(target + stowedpath1, 'r') as f:
                r1 = f.read()
            with open(target + stowedpath2, 'r') as f:
                r2 = f.read()
        self.assertEqual(r1 + r2, 'aa')
        e.seek(0)
        self.assertIn('Stowed 2 files', e.read())

    def test_cabinet_prompted_per_file(self):
        # With several cabinets, each stowed file asks for its cabinet
        keys = 'smemories\n20240213\nt\nsaccounts\n20231211\nu\n'
        with \
                TemporaryDirectory() as source, \
                TemporaryDirectory() as a, \
                TemporaryDirectory() as b, \
                self.patchout(), \
                self.patcherr(), \
                self.patch_ttyin(keys):
            for fn in ['b.txt', 'c.txt']:
                (Path(source) / fn).write_text('a')
            app = Filez4EvaApp()
            app.config = ConfigHandler.fake(filez4eva_cabinets={
                'accounts': {'target': a}, 'memories': {'target': b}})
            c = ScanDirCommand(app, dir=str(source))
            c.execute()
            self.assertTrue((Path(b) / '20240213-t.txt').is_file())
            self.assertTrue((Path(a) / '20231211-u.txt').is_file())
        self.assertEqual(c.status, 'Stowed 2 files')

    def _run_scan(self, files, keys):
        with \
                TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                self.patchout() as o, \
                self.patcherr() as e, \
                self.patch_ttyin(keys):
            for fn in files:
                (Path(source) / fn).write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target)
            c = ScanDirCommand(a, dir=str(source))
            c.execute()
            remaining = sorted(x.name for x in Path(source).iterdir())
            e.seek(0)
            out = e.read()
        return c, remaining, out

    def test_transcript_skipped(self):
        c, remaining, out = self._run_scan(['b.txt', 'b.txt.md'], 'x')
        self.assertEqual(c.status, 'Skipped 1 file')
        self.assertNotIn('b.txt.md', out)
        self.assertEqual(remaining, ['b.txt', 'b.txt.md'])

    def test_standalone_md_offered(self):
        c, remaining, out = self._run_scan(['notes.md'], 'x')
        self.assertEqual(c.status, 'Skipped 1 file')
        self.assertIn('notes.md', out)

    def test_transcript_removed_on_delete(self):
        c, remaining, out = self._run_scan(['b.txt', 'b.txt.md'], 'dY')
        self.assertEqual(c.status, 'Deleted 1 file')
        self.assertEqual(remaining, [])

    def test_delete_without_transcript_keeps_other_md(self):
        c, remaining, out = self._run_scan(['b.txt', 'c.txt.md'], 'dYx')
        self.assertEqual(c.status, 'Deleted 1 file | Skipped 1 file')
        self.assertEqual(remaining, ['c.txt.md'])

    def test_transcript_not_offered_after_stow(self):
        c, remaining, out = self._run_scan(
            ['b.txt', 'b.txt.md'], 's20240213\nt\n')
        self.assertEqual(c.status, 'Stowed 1 file')
        self.assertEqual(remaining, [])


PATTERN = '{date.year}/{account}/{date}-{part}'

RESULT = {'data': {'date': '20261002', 'account': 'amazon',
                   'part': 'receipt'},
          'doctype': 'other', 'summary': 'Amazon.ca order receipt'}


def result(**data):
    return dict(RESULT, data=dict(RESULT['data'], **data))


# Clear the pre-filled default, then press Enter
CANCEL = S.BACKSPACE + S.RETURN


class TestCommandScanAI(WizLibTestCase):
    """Stowing with the AI calls mocked"""

    def setUp(self):
        super().setUp()
        self.tempdir = TemporaryDirectory()
        self.dir = Path(self.tempdir.name)
        self.source = self.dir / 'in'
        self.source.mkdir()
        self.file = self.source / 'scan.pdf'
        self.file.write_bytes(b'%PDF fake')
        self.transcript = self.source / 'scan.pdf.md'
        self.target = self.dir / 'target'
        store = values_path(self.target)
        store.parent.mkdir(parents=True)
        store.write_text('account:\n  amazon:\n    count: 2\n'
                         'part:\n  refund:\n    count: 2\n')
        self.stowed = self.target / '2026/amazon/20261002-receipt.pdf'

    def tearDown(self):
        self.tempdir.cleanup()
        super().tearDown()

    def two_cabinets(self):
        self.other = self.dir / 'memories'
        return {'filez4eva_pattern': PATTERN, 'filez4eva_cabinets': {
            'accounts': {'target': str(self.target)},
            'memories': {'target': str(self.other)}}}

    def run_scan(self, answers, options='s', config=None,
                 extract=None, transcribe=None):
        """Run scan-dir with get_text answers and get_option keys mocked.
        Return (command, get_text mock, stderr, extract mock)."""
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(
            **(config or {'filez4eva_target': str(self.target),
                          'filez4eva_pattern': PATTERN}))
        answers = iter(answers)
        extract = extract or {'return_value': RESULT}
        transcribe = transcribe or {'return_value': '# Receipt'}
        command = ScanDirCommand(app, dir=str(self.source))
        with patch(EXTRACT, **extract) as x, \
                patch(TRANSCRIBE, **transcribe), \
                patch.object(app.ui, 'get_text',
                             side_effect=lambda *a: next(answers)) as gt, \
                self.patchout(), self.patcherr() as e, \
                self.patch_ttyin(options):
            command.execute()
            e.seek(0)
            return command, gt, e.read(), x

    @staticmethod
    def prompts(gt):
        return [c.args for c in gt.call_args_list]

    def test_prompts_prefilled(self):
        c, gt, err, _ = self.run_scan(['20261002', 'amazon', 'receipt'])
        self.assertEqual(self.prompts(gt), [
            ('Date: ', [], '20261002'),
            ('Account: ', ['amazon'], 'amazon'),
            ('Part: ', ['refund'], 'receipt')])
        self.assertIn('Summary: Amazon.ca order receipt', err)
        self.assertIn('Transcribed | Classified', err)
        self.assertTrue(self.stowed.is_file())
        self.assertTrue(Path(str(self.stowed) + '.md').is_file())
        self.assertEqual(sorted(self.source.iterdir()), [])
        self.assertEqual(c.status, 'Stowed 1 file')

    def test_prefilled_value_edited(self):
        c, _, _, _ = self.run_scan(['20261002', 'amazon', 'invoice'])
        stowed = self.target / '2026/amazon/20261002-invoice.pdf'
        self.assertTrue(stowed.is_file())
        self.assertTrue(Path(str(stowed) + '.md').is_file())
        self.assertEqual(c.status, 'Stowed 1 file')

    def assert_fallback(self, c, gt, err, message):
        self.assertIn(message, err)
        self.assertEqual(self.prompts(gt), [
            ('Date: ', []),
            ('Account: ', ['amazon']),
            ('Part: ', ['refund'])])
        stowed = self.target / '2025/acme/20250101-bill.pdf'
        self.assertTrue(stowed.is_file())
        self.assertEqual(c.status, 'Stowed 1 file')

    def test_extract_failure_falls_back(self):
        c, gt, err, _ = self.run_scan(
            ['20250101', 'acme', 'bill'],
            extract={'side_effect': APIError('boom')})
        self.assert_fallback(c, gt, err, 'Classification failed: boom')
        # The transcript was written before classifying failed, and moves
        # with the file
        self.assertTrue(
            (self.target / '2025/acme/20250101-bill.pdf.md').is_file())

    def test_transcribe_failure_falls_back(self):
        c, gt, err, x = self.run_scan(
            ['20250101', 'acme', 'bill'],
            transcribe={'side_effect': APIError('nope')})
        self.assert_fallback(c, gt, err, 'Transcription failed: nope')
        x.assert_not_called()

    def test_bad_result_falls_back(self):
        c, gt, err, _ = self.run_scan(
            ['20250101', 'acme', 'bill'],
            extract={'return_value': result(part='//')})
        self.assert_fallback(c, gt, err, 'Part must contain letters')

    def test_no_date_prompt_starts_empty(self):
        c, gt, err, _ = self.run_scan(
            ['20250704', 'amazon', 'receipt'],
            extract={'return_value': result(date='<UNKNOWN>')})
        self.assertEqual(self.prompts(gt), [
            ('Date: ', []),
            ('Account: ', ['amazon'], 'amazon'),
            ('Part: ', ['refund'], 'receipt')])
        self.assertNotIn('Classification failed', err)
        self.assertIn('Summary: Amazon.ca order receipt', err)
        stowed = self.target / '2025/amazon/20250704-receipt.pdf'
        self.assertTrue(stowed.is_file())
        self.assertEqual(c.status, 'Stowed 1 file')

    def test_bad_doctypes_falls_back(self):
        c, gt, err, x = self.run_scan(
            ['20250101', 'acme', 'bill'],
            config={'filez4eva_target': str(self.target),
                    'filez4eva_pattern': PATTERN,
                    'filez4eva_doctypes': ['receipt']})
        self.assert_fallback(c, gt, err, 'doctypes must be a mapping')
        x.assert_not_called()

    def test_cancel_at_prefilled_prompt(self):
        # An empty part returns to the chooser; then skip the file
        c, gt, err, _ = self.run_scan(['20261002', 'amazon', ''],
                                      options='sx')
        self.assertIn('Part required', err)
        self.assertEqual(err.count('scan.pdf'), 2)
        self.assertTrue(self.file.is_file())
        self.assertFalse(self.stowed.exists())
        self.assertEqual(c.status, 'Skipped 1 file')

    def test_cancel_then_stow_again(self):
        # The transcript from the first attempt is reused
        c, gt, err, x = self.run_scan(
            ['', '20261002', 'amazon', 'receipt'], options='ss')
        self.assertIn('Date required', err)
        self.assertEqual(x.call_count, 2)
        self.assertTrue(self.stowed.is_file())
        self.assertEqual(c.status, 'Stowed 1 file')

    def test_cancel_in_fallback(self):
        c, _, err, _ = self.run_scan(
            [''], options='sx', extract={'side_effect': APIError('boom')})
        self.assertIn('Date required', err)
        self.assertTrue(self.file.is_file())
        self.assertEqual(c.status, 'Skipped 1 file')

    def test_cabinet_asked_once(self):
        c, gt, _, x = self.run_scan(
            ['accounts', '20261002', 'amazon', 'receipt'],
            config=self.two_cabinets())
        self.assertEqual(self.prompts(gt)[0][0], 'Cabinet: ')
        self.assertEqual(
            [p[0] for p in self.prompts(gt)].count('Cabinet: '), 1)
        self.assertIn('"accounts"', x.call_args.kwargs['instructions'])
        self.assertTrue(self.stowed.is_file())
        self.assertEqual(c.status, 'Stowed 1 file')

    def test_cabinet_asked_once_in_fallback(self):
        c, gt, err, _ = self.run_scan(
            ['memories', '20250101', 'acme', 'bill'],
            config=self.two_cabinets(),
            extract={'side_effect': APIError('boom')})
        self.assertIn('Classification failed: boom', err)
        self.assertEqual(
            [p[0] for p in self.prompts(gt)].count('Cabinet: '), 1)
        self.assertTrue(
            (self.other / '2025/acme/20250101-bill.pdf').is_file())
        self.assertEqual(c.status, 'Stowed 1 file')

    def test_cancel_at_cabinet(self):
        c, gt, _, x = self.run_scan([''], options='sx',
                                    config=self.two_cabinets())
        x.assert_not_called()
        self.assertFalse(self.transcript.exists())
        self.assertTrue(self.file.is_file())
        self.assertEqual(c.status, 'Skipped 1 file')
