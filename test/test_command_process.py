import os
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unittest.mock import patch

from wizlib.config_handler import ConfigHandler
from wizlib.test_case import WizLibTestCase
from wizlib.ui.shell import S

from filez4eva import Filez4EvaApp
from filez4eva.command.process_command import ProcessCommand
from filez4eva.error import Filez4EvaError


EXTRACT = 'filez4eva.command.classify_command.extract'
TRANSCRIBE = 'filez4eva.command.transcribe_command.transcribe'

RESULT = {'date': '20261002', 'account': 'amazon', 'part': 'receipt',
          'doctype': 'receipt',
          'summary': 'Amazon.ca order receipt for a USB hub'}

# Clear the pre-filled default, then press Enter
CANCEL = S.BACKSPACE + S.RETURN


class TestProcessCommand(WizLibTestCase):

    def setUp(self):
        super().setUp()
        self.tempdir = TemporaryDirectory()
        self.dir = Path(self.tempdir.name)
        self.target = self.dir / 'target'
        p = self.target / '2026/amazon/20260301-refund.pdf'
        p.parent.mkdir(parents=True)
        p.write_text('x')
        self.source = self.dir / 'in' / 'scan.pdf'
        self.source.parent.mkdir()
        self.source.write_bytes(b'%PDF fake')
        self.transcript = self.dir / 'in' / 'scan.pdf.md'
        self.stowed = self.target / '2026/amazon/20261002-receipt.pdf'

    def tearDown(self):
        self.tempdir.cleanup()
        super().tearDown()

    def config(self):
        return (f"filez4eva:\n  target: {self.target}\n"
                "  doctypes:\n    receipt:\n      description: Proof\n")

    def two_cabinets(self):
        self.other = self.dir / 'memories'
        return (f"filez4eva:\n"
                f"  cabinets:\n"
                f"    accounts:\n"
                f"      target: {self.target}\n"
                f"    memories:\n"
                f"      target: {self.other}\n"
                "  doctypes:\n    receipt:\n")

    def run_app(self, config_text, *args, ttyin='', result=RESULT):
        """Run process via the app; return (stdout, stderr, extract mock,
        ttyin mock)"""
        with patch(EXTRACT, return_value=result) as x, \
                patch(TRANSCRIBE, return_value='# Receipt'), \
                patch.dict(os.environ), \
                self.patchout() as o, self.patcherr() as e, \
                self.patch_ttyin(ttyin) as t, \
                NamedTemporaryFile('w+', suffix='.yml') as cf:
            os.environ.pop('FILEZ4EVA_ANTHROPIC_KEY', None)
            cf.write(config_text)
            cf.flush()
            Filez4EvaApp.start('--config', cf.name, 'process',
                               str(self.source), *args, debug=True)
            o.seek(0)
            e.seek(0)
            return o.read(), e.read(), x, t

    def assert_not_moved(self):
        self.assertTrue(self.source.is_file())
        self.assertTrue(self.transcript.is_file())
        self.assertFalse(self.stowed.exists())

    def test_accept_all_defaults(self):
        out, err, _, t = self.run_app(self.config(), ttyin='\n\n\n')
        self.assertEqual(out.strip(), str(self.stowed))
        self.assertTrue(self.stowed.is_file())
        self.assertTrue(Path(str(self.stowed) + '.md').is_file())
        self.assertFalse(self.source.exists())
        self.assertFalse(self.transcript.exists())
        self.assertIn('Summary: Amazon.ca order receipt for a USB hub', err)
        self.assertIn('Doctype: receipt', err)
        self.assertIn('Date: ', err)
        self.assertIn('Account: ', err)
        self.assertIn('Part: ', err)
        self.assertNotIn('Cabinet: ', err)
        self.assertIn('Transcribed | Classified | Done', err)
        self.assertEqual(t.call_count, 3)

    def test_prompts_prefilled(self):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(filez4eva_target=str(self.target))
        command = ProcessCommand(app, file=str(self.source))
        answers = iter(['20261002', 'amazon', 'receipt'])
        with patch(EXTRACT, return_value=dict(RESULT, doctype='other')), \
                patch(TRANSCRIBE, return_value='# Receipt'), \
                patch.object(app.ui, 'get_text',
                             side_effect=lambda *a: next(answers)) as gt, \
                self.patchout(), self.patcherr():
            command.execute()
        self.assertEqual([c.args for c in gt.call_args_list], [
            ('Date: ', [], '20261002'),
            ('Account: ', ['amazon'], 'amazon'),
            ('Part: ', ['refund'], 'receipt')])
        self.assertTrue(self.stowed.is_file())

    def test_edit_one_value(self):
        out, err, _, _ = self.run_app(self.config(),
                                      ttyin='\n\ninvoice\n')
        stowed = self.target / '2026/amazon/20261002-invoice.pdf'
        self.assertEqual(out.strip(), str(stowed))
        self.assertTrue(stowed.is_file())
        self.assertTrue(Path(str(stowed) + '.md').is_file())
        self.assertFalse(self.stowed.exists())

    def test_edit_date(self):
        out, _, _, _ = self.run_app(self.config(),
                                    ttyin=S.BACKSPACE + '20250102\n\n\n')
        stowed = self.target / '2025/amazon/20250102-receipt.pdf'
        self.assertEqual(out.strip(), str(stowed))
        self.assertTrue(stowed.is_file())

    def test_invalid_value_reprompts(self):
        out, err, _, _ = self.run_app(self.config(),
                                      ttyin='\n\nbad part\n\n')
        self.assertIn('Part must contain only', err)
        self.assertEqual(out.strip(), str(self.stowed))
        self.assertTrue(self.stowed.is_file())

    def test_invalid_date_reprompts(self):
        out, err, _, _ = self.run_app(self.config(),
                                      ttyin='x\n\n\n\n')
        self.assertIn('Date must match format YYYYMMDD', err)
        self.assertTrue(self.stowed.is_file())

    def test_cancel_at_date(self):
        out, err, _, t = self.run_app(self.config(), ttyin=CANCEL)
        self.assertEqual(out.strip(), '')
        self.assertIn('Date required', err)
        self.assertNotIn('Account: ', err)
        self.assert_not_moved()

    def test_cancel_at_part(self):
        out, err, _, _ = self.run_app(self.config(), ttyin='\n\n' + CANCEL)
        self.assertEqual(out.strip(), '')
        self.assertIn('Part required', err)
        self.assert_not_moved()

    def test_dry_run(self):
        out, err, x, _ = self.run_app(self.config(), '--dry-run',
                                      ttyin='\n\n\n')
        x.assert_called_once()
        self.assertIn(f'Would stow {self.source} -> {self.stowed}', out)
        self.assertIn(f'Would stow {self.transcript} -> {self.stowed}.md',
                      out)
        self.assertIn('Transcribed | Classified | Dry run', err)
        self.assert_not_moved()

    def test_dry_run_without_transcript(self):
        # The transcript is removed between classifying and planning
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(filez4eva_target=str(self.target))
        command = ProcessCommand(app, file=str(self.source), dry_run=True)
        with patch(EXTRACT, return_value=dict(RESULT, doctype='other')), \
                patch(TRANSCRIBE, return_value='# Receipt'), \
                patch.object(ProcessCommand, 'confirm',
                             side_effect=self.drop_transcript), \
                self.patchout(), self.patcherr():
            out = command.execute()
        self.assertEqual(out, f'Would stow {self.source} -> {self.stowed}')
        self.assertTrue(self.source.is_file())

    def drop_transcript(self, record):
        self.transcript.unlink()
        return {k: record[k] for k in ['cabinet', 'date', 'account', 'part']}

    def test_dry_run_existing_destination(self):
        self.stowed.write_text('already')
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(filez4eva_target=str(self.target))
        command = ProcessCommand(app, file=str(self.source), dry_run=True)
        with patch(EXTRACT, return_value=dict(RESULT, doctype='other')), \
                patch(TRANSCRIBE, return_value='# Receipt'), \
                self.patch_ttyin('\n\n\n'), self.patchout(), \
                self.patcherr(), self.assertRaises(Filez4EvaError):
            command.execute()
        self.assertTrue(self.source.is_file())

    def test_cached_transcript_status(self):
        self.run_app(self.config(), '--dry-run', ttyin='\n\n\n')
        _, err, _, _ = self.run_app(self.config(), ttyin='\n\n\n')
        self.assertIn('Classified | Done', err)
        self.assertNotIn('Transcribed', err)
        self.assertTrue(self.stowed.is_file())

    # Cabinets

    def test_cabinet_prompt_prefilled(self):
        out, err, x, _ = self.run_app(self.two_cabinets(), '-c', 'accounts',
                                      ttyin='\n\n\n\n')
        self.assertIn('Cabinet: ', err)
        self.assertIn('"accounts"', x.call_args.kwargs['instructions'])
        self.assertEqual(out.strip(), str(self.stowed))
        self.assertTrue(self.stowed.is_file())

    def test_cabinet_changed_at_confirmation(self):
        out, err, _, t = self.run_app(
            self.two_cabinets(), '-c', 'accounts',
            ttyin=S.BACKSPACE + 'memories\n\n\n\n')
        stowed = self.other / '2026/amazon/20261002-receipt.pdf'
        self.assertEqual(out.strip(), str(stowed))
        self.assertTrue(stowed.is_file())
        self.assertFalse(self.stowed.exists())

    def test_cabinet_not_asked_twice(self):
        out, err, x, _ = self.run_app(self.two_cabinets(),
                                      ttyin='memories\n\n\n\n')
        self.assertEqual(err.count('Cabinet: '), 1)
        self.assertIn('"memories"', x.call_args.kwargs['instructions'])
        stowed = self.other / '2026/amazon/20261002-receipt.pdf'
        self.assertEqual(out.strip(), str(stowed))

    def test_cancel_at_cabinet_choice_before_ai(self):
        _, err, x, _ = self.run_app(self.two_cabinets(), ttyin='\n')
        x.assert_not_called()
        self.assertIn('Cabinet required', err)
        self.assertFalse(self.transcript.exists())
        self.assertTrue(self.source.is_file())

    def test_unknown_cabinet_raises_before_transcribing(self):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(filez4eva_target=str(self.target))
        with patch(TRANSCRIBE) as t, self.assertRaises(Filez4EvaError):
            ProcessCommand(app, file=str(self.source),
                           cabinet='nope').execute()
        t.assert_not_called()
