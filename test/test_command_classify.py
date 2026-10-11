import hashlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unittest.mock import patch

import yaml
from kwark.ai import APIError, TRANSCRIBE_DISCLAIMER
from wizlib.config_handler import ConfigHandler
from wizlib.test_case import WizLibTestCase

from filez4eva import Filez4EvaApp
from filez4eva.command.classify_command import (
    DEFAULT_MODEL, ClassifyCommand, build_schema, load_doctypes,
    transcript_body)
from filez4eva.command.transcribe_command import format_transcript
from filez4eva.error import Filez4EvaError


EXTRACT = 'filez4eva.command.classify_command.extract'
TRANSCRIBE = 'filez4eva.command.transcribe_command.transcribe'

RESULT = {'date': '20261002', 'account': 'amazon', 'part': 'receipt',
          'doctype': 'receipt',
          'summary': 'Amazon.ca order receipt for a USB hub'}

DOCTYPES = {'receipt': {'description': 'Proof of purchase or payment'},
            'bill': {'description':
                     'A request for payment, usually with a due date'}}


class TestClassifyCommand(WizLibTestCase):

    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.dir = Path(self.tempdir.name)
        self.target = self.dir / 'target'
        for path in ['2025/amazon/20250101-receipt.pdf',
                     '2026/amazon/20260301-refund.pdf',
                     '2026/bank/20260131-statement.pdf',
                     '2026/empty/notes.txt']:
            p = self.target / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('x')
        self.source = self.dir / 'in' / 'scan.pdf'
        self.source.parent.mkdir()
        self.source.write_bytes(b'%PDF fake')
        self.transcript = self.dir / 'in' / 'scan.pdf.md'

    def tearDown(self):
        self.tempdir.cleanup()

    def config(self, **extra):
        values = {'filez4eva_target': str(self.target),
                  'filez4eva_doctypes': DOCTYPES}
        values.update(extra)
        return values

    def run_command(self, config=None, result=RESULT, markdown='# Hi',
                    **vals):
        """Run the command directly with fake config; return (output,
        command, extract mock, transcribe mock)"""
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(**(config or self.config()))
        command = ClassifyCommand(app, file=str(self.source), **vals)
        with patch(EXTRACT, return_value=result) as e, \
                patch(TRANSCRIBE, return_value=markdown) as t, \
                self.patchout(), self.patcherr():
            return command.execute(), command, e, t

    def run_app(self, config_text, *args, result=RESULT, ttyin=''):
        """Run classify via the app; return (stdout, stderr, extract mock)"""
        with patch(EXTRACT, return_value=result) as x, \
                patch(TRANSCRIBE, return_value='# Hi'), \
                patch.dict(os.environ), \
                self.patchout() as o, self.patcherr() as e, \
                self.patch_ttyin(ttyin), \
                NamedTemporaryFile('w+', suffix='.yml') as cf:
            os.environ.pop('FILEZ4EVA_CLASSIFY_MODEL', None)
            os.environ.pop('FILEZ4EVA_ANTHROPIC_KEY', None)
            cf.write(config_text)
            cf.flush()
            Filez4EvaApp.start('--config', cf.name, 'classify',
                               str(self.source), *args, debug=True)
            o.seek(0)
            e.seek(0)
            return o.read(), e.read(), x

    # Record

    def test_record(self):
        out, command, _, _ = self.run_command(
            self.config(filez4eva_doctypes=DOCTYPES))
        record = yaml.safe_load(out)
        self.assertEqual(list(record), [
            'file', 'transcript', 'cabinet', 'date', 'account', 'part',
            'doctype', 'summary'])
        self.assertEqual(record['file'], str(self.source))
        self.assertEqual(record['transcript'], str(self.transcript))
        self.assertEqual(record['cabinet'], 'default')
        self.assertEqual(record['date'], '20261002')
        self.assertEqual(record['account'], 'amazon')
        self.assertEqual(record['part'], 'receipt')
        self.assertEqual(record['doctype'], 'receipt')
        self.assertEqual(record['summary'],
                         'Amazon.ca order receipt for a USB hub')
        self.assertIn("date: '20261002'", out)
        self.assertEqual(command.status, 'Transcribed | Classified')

    def test_record_on_stdout(self):
        out, err, _ = self.run_app(
            f"filez4eva:\n  target: {self.target}\n"
            "  doctypes:\n    receipt:\n      description: Proof\n")
        record = yaml.safe_load(out)
        self.assertEqual(record['account'], 'amazon')
        self.assertEqual(record['file'], str(self.source))
        self.assertEqual(err.strip(), 'Transcribed | Classified')

    def test_summary_one_line(self):
        result = dict(RESULT, summary='  A long\nsummary\n\nhere ',
                      doctype='other')
        out, _, _, _ = self.run_command(result=result)
        self.assertEqual(yaml.safe_load(out)['summary'], 'A long summary here')

    def test_long_unicode_summary_not_wrapped(self):
        summary = 'Reçu ' + 'très long ' * 20
        out, _, _, _ = self.run_command(
            result=dict(RESULT, summary=summary, doctype='other'))
        self.assertEqual(len(out.splitlines()), 8)
        self.assertIn('Reçu', out)
        self.assertEqual(yaml.safe_load(out)['summary'], summary.strip())

    # Transcription

    def test_transcribes_first(self):
        _, _, e, t = self.run_command()
        t.assert_called_once()
        self.assertTrue(self.transcript.is_file())
        self.assertEqual(e.call_args.args[0], '# Hi')

    def test_cached_transcript_not_retranscribed(self):
        sha = hashlib.sha256(b'%PDF fake').hexdigest()
        self.transcript.write_text(format_transcript(
            'scan.pdf', sha, 'm', '2026-01-01T00:00:00+00:00', 'Cached'))
        _, command, e, t = self.run_command()
        t.assert_not_called()
        self.assertEqual(e.call_args.args[0], 'Cached')
        self.assertEqual(command.status, 'Classified')

    def test_transcribe_model_used_for_transcription(self):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(**self.config(
            filez4eva_transcribe_model='claude-t',
            filez4eva_classify_model='claude-c',
            filez4eva_anthropic_key='sk-test'))
        command = ClassifyCommand(app, file=str(self.source))
        with patch(EXTRACT, return_value=RESULT) as e, \
                patch(TRANSCRIBE, return_value='x') as t, \
                self.patchout(), self.patcherr():
            command.execute()
        self.assertEqual(t.call_args.kwargs,
                         {'model': 'claude-t', 'api_key': 'sk-test'})
        self.assertEqual(e.call_args.kwargs['model'], 'claude-c')
        self.assertEqual(e.call_args.kwargs['api_key'], 'sk-test')

    def test_transcription_error(self):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(**self.config())
        command = ClassifyCommand(app, file=str(self.source))
        with patch(EXTRACT) as e, \
                patch(TRANSCRIBE, side_effect=APIError('nope')), \
                self.assertRaises(Filez4EvaError) as raised:
            command.execute()
        e.assert_not_called()
        self.assertIn('Transcription failed', str(raised.exception))

    def test_missing_file(self):
        self.source = self.dir / 'missing.pdf'
        with self.assertRaises(Filez4EvaError):
            self.run_command()

    def test_empty_transcript_rejected(self):
        with self.assertRaises(Filez4EvaError) as raised:
            self.run_command(markdown='')
        self.assertIn('empty', str(raised.exception))

    def test_unreadable_transcript_rejected(self):
        with patch.object(Path, 'read_text', side_effect=OSError('no')), \
                self.assertRaises(Filez4EvaError) as raised:
            self.run_command()
        self.assertIn('Could not read', str(raised.exception))

    def test_transcript_body(self):
        text = format_transcript('a.pdf', 'abc', 'm', 't', '# Title\n\nBody')
        self.assertEqual(transcript_body(text), '# Title\n\nBody')
        self.assertEqual(transcript_body('plain\ntext\n'), 'plain\ntext')
        self.assertEqual(transcript_body('---\nunterminated'),
                         '---\nunterminated')
        self.assertEqual(
            transcript_body(f'<!-- {TRANSCRIBE_DISCLAIMER} -->\n\nx'), 'x')

    # Schema

    def test_schema(self):
        _, _, e, _ = self.run_command(
            self.config(filez4eva_doctypes=DOCTYPES))
        schema = e.call_args.args[1]
        self.assertEqual(schema['type'], 'object')
        self.assertEqual(set(schema['required']),
                         {'date', 'account', 'part', 'doctype', 'summary'})
        self.assertEqual(set(schema['properties']), set(schema['required']))
        self.assertFalse(schema['additionalProperties'])
        props = schema['properties']
        for key in props:
            self.assertEqual(props[key]['type'], 'string')
        self.assertEqual(props['date']['pattern'], r'^\d{8}$')
        self.assertEqual(props['part']['pattern'], r'^[a-zA-Z0-9-]+$')
        self.assertEqual(props['doctype']['enum'],
                         ['receipt', 'bill', 'other'])

    def test_schema_without_doctypes(self):
        _, _, e, _ = self.run_command(
            {'filez4eva_target': str(self.target)},
            result=dict(RESULT, doctype='other'))
        enum = e.call_args.args[1]['properties']['doctype']['enum']
        self.assertEqual(enum, ['other'])

    def test_configured_other_not_duplicated(self):
        doctypes = {'other': {'description': 'Misc'}, 'bill': None}
        self.assertEqual(
            build_schema(load_doctypes(ConfigHandler.fake(
                filez4eva_doctypes=doctypes)))['properties']['doctype']
            ['enum'], ['bill', 'other'])

    # Instructions

    def test_instructions(self):
        config = (f"filez4eva:\n"
                  f"  cabinets:\n"
                  f"    accounts:\n"
                  f"      target: {self.target}\n"
                  f"      description: Personal account records\n"
                  f"  doctypes:\n"
                  f"    receipt:\n"
                  f"      description: Proof of purchase or payment\n"
                  f"    bill:\n"
                  f"      description: A request for payment\n"
                  f"    memo:\n")
        out, _, e = self.run_app(config)
        text = e.call_args.kwargs['instructions']
        self.assertIn('Personal account records', text)
        self.assertIn('"accounts"', text)
        self.assertIn("document's own date", text)
        self.assertIn('YYYYMMDD', text)
        self.assertIn('one-line summary', text)
        self.assertIn('Reuse an existing account and part', text)
        self.assertIn('- amazon: receipt, refund\n', text)
        self.assertIn('- bank: statement\n', text)
        self.assertIn('- empty\n', text)
        self.assertIn('- receipt: Proof of purchase or payment', text)
        self.assertIn('- bill: A request for payment', text)
        self.assertIn('- memo\n', text)
        self.assertIn('- other: ', text)
        self.assertLess(text.index('- receipt:'), text.index('- other:'))
        self.assertEqual(yaml.safe_load(out)['cabinet'], 'accounts')

    def test_instructions_without_accounts(self):
        _, _, e, _ = self.run_command(
            {'filez4eva_target': str(self.dir / 'new')},
            result=dict(RESULT, doctype='other'))
        text = e.call_args.kwargs['instructions']
        self.assertIn('no existing accounts', text)
        self.assertIn('"default"', text)

    def test_custom_pattern_has_no_vocabulary(self):
        _, _, e, _ = self.run_command(
            self.config(filez4eva_pattern='{account}/{date}-{part}{ext}'),
            result=dict(RESULT, doctype='other'))
        self.assertIn('no existing accounts',
                      e.call_args.kwargs['instructions'])

    # Model

    def test_default_model(self):
        _, _, e, _ = self.run_command(result=dict(RESULT, doctype='other'))
        self.assertEqual(e.call_args.kwargs['model'], 'claude-haiku-4-5')
        self.assertEqual(DEFAULT_MODEL, 'claude-haiku-4-5')
        self.assertIsNone(e.call_args.kwargs['api_key'])

    def test_configured_model_from_file(self):
        _, _, e = self.run_app(
            f"filez4eva:\n  target: {self.target}\n"
            "  classify:\n    model: claude-from-file\n",
            result=dict(RESULT, doctype='other'))
        self.assertEqual(e.call_args.kwargs['model'], 'claude-from-file')

    def test_empty_classify_block_uses_default_model(self):
        _, _, e = self.run_app(
            f"filez4eva:\n  target: {self.target}\n  classify:\n",
            result=dict(RESULT, doctype='other'))
        self.assertEqual(e.call_args.kwargs['model'], DEFAULT_MODEL)

    # Cabinets

    def two_cabinets(self):
        other = self.dir / 'memories'
        (other / '2026' / 'grandma').mkdir(parents=True)
        return (f"filez4eva:\n"
                f"  cabinets:\n"
                f"    accounts:\n"
                f"      target: {self.target}\n"
                f"    memories:\n"
                f"      target: {other}\n"
                f"      description: Family photos\n")

    def test_cabinet_flag(self):
        out, _, e = self.run_app(self.two_cabinets(), '--cabinet', 'memories',
                                 result=dict(RESULT, doctype='other'))
        text = e.call_args.kwargs['instructions']
        self.assertIn('Family photos', text)
        self.assertIn('- grandma', text)
        self.assertNotIn('amazon', text)
        self.assertEqual(yaml.safe_load(out)['cabinet'], 'memories')

    def test_cabinet_prompted(self):
        out, _, e = self.run_app(self.two_cabinets(), ttyin='memories\n',
                                 result=dict(RESULT, doctype='other'))
        self.assertEqual(yaml.safe_load(out)['cabinet'], 'memories')

    def test_unknown_cabinet_raises_before_transcribing(self):
        with patch(TRANSCRIBE) as t, self.assertRaises(Filez4EvaError):
            app = Filez4EvaApp()
            app.config = ConfigHandler.fake(**self.config())
            ClassifyCommand(app, file=str(self.source),
                            cabinet='nope').execute()
        t.assert_not_called()

    # Doctype configuration

    def test_bad_doctypes_config(self):
        for doctypes in [['receipt'], {'two words': None}, {1: None},
                         {'receipt': 'text'},
                         {'receipt': {'description': 5}}]:
            with self.subTest(doctypes=doctypes), \
                    patch(TRANSCRIBE) as t, \
                    self.assertRaises(Filez4EvaError):
                self.run_command(self.config(filez4eva_doctypes=doctypes))

    def test_empty_doctypes(self):
        self.assertEqual(list(load_doctypes(
            ConfigHandler.fake(filez4eva_doctypes=''))), ['other'])

    # Errors from the model

    def test_kwark_error_wrapped(self):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(**self.config())
        command = ClassifyCommand(app, file=str(self.source))
        with patch(EXTRACT, side_effect=APIError('boom')), \
                patch(TRANSCRIBE, return_value='x'), \
                self.assertRaises(Filez4EvaError) as raised:
            command.execute()
        self.assertIn('Classification failed: boom', str(raised.exception))
        self.assertIsInstance(raised.exception.__cause__, APIError)

    def test_invalid_results_rejected(self):
        bad = [None, dict(RESULT, date='2026-10-02'),
               dict(RESULT, date='20261302'), dict(RESULT, account='../x'),
               dict(RESULT, part='a b'), dict(RESULT, doctype='bill'),
               dict(RESULT, summary=''), dict(RESULT, date=20261002),
               {k: v for k, v in RESULT.items() if k != 'part'}]
        for result in bad:
            with self.subTest(result=result), \
                    self.assertRaises(Filez4EvaError):
                self.run_command(self.config(
                    filez4eva_doctypes={'receipt': None}), result=result)


class TestClassifyPipe(WizLibTestCase):
    """classify's output can be piped into stow-file"""

    def test_pipe_into_stow_file(self):
        with TemporaryDirectory() as d:
            dir = Path(d)
            target = dir / 'target'
            source = dir / 'scan.pdf'
            source.write_bytes(b'%PDF')
            with NamedTemporaryFile('w+', suffix='.yml') as cf:
                cf.write(f"filez4eva:\n  target: {target}\n"
                         "  doctypes:\n    receipt:\n")
                cf.flush()
                with patch(EXTRACT, return_value=RESULT), \
                        patch(TRANSCRIBE, return_value='# Receipt'), \
                        self.patchout() as o, self.patcherr():
                    Filez4EvaApp.start('--config', cf.name, 'classify',
                                       str(source), debug=True)
                    o.seek(0)
                    record = o.read()
                with self.patch_stream(record), self.patchout() as o, \
                        self.patcherr(), self.patch_ttyin(''):
                    Filez4EvaApp.start('--config', cf.name, 'stow-file',
                                       str(source), debug=True)
                    o.seek(0)
                    out = o.read()
            stowed = target / '2026/amazon/20261002-receipt.pdf'
            self.assertEqual(out.strip(), str(stowed))
            self.assertTrue(stowed.is_file())
            self.assertTrue(Path(str(stowed) + '.md').is_file())
            self.assertFalse(source.exists())
