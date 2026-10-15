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
from filez4eva.command.stow_file_command import Cabinet
from filez4eva.command.transcribe_command import format_transcript
from filez4eva.error import Filez4EvaError
from filez4eva.fields import values_path


EXTRACT = 'filez4eva.command.classify_command.extract'
TRANSCRIBE = 'filez4eva.command.transcribe_command.transcribe'

PATTERN = '{date.year}/{account}/{date}-{part}'

DATA = {'date': '20261002', 'account': 'amazon', 'part': 'receipt'}

RESULT = {'data': DATA, 'doctype': 'receipt',
          'summary': 'Amazon.ca order receipt for a USB hub'}

DOCTYPES = {'receipt': {'description': 'Proof of purchase or payment'},
            'bill': {'description':
                     'A request for payment, usually with a due date'}}


def result(**data):
    """RESULT with some data values replaced ('DROP' removes one)"""
    values = {k: v for k, v in dict(DATA, **data).items() if v != 'DROP'}
    return dict(RESULT, data=values)


def write_store(target, store):
    path = values_path(Path(target))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(store))


class TestClassifyCommand(WizLibTestCase):

    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.dir = Path(self.tempdir.name)
        self.target = self.dir / 'target'
        write_store(self.target, {
            'account': {'amazon': {'count': 3}, 'bank': {'count': 2},
                        'once': {'count': 1}},
            'part': {'receipt': {'count': 2}, 'refund': {'count': 4},
                     'statement': {'count': 1}}})
        self.source = self.dir / 'in' / 'scan.pdf'
        self.source.parent.mkdir()
        self.source.write_bytes(b'%PDF fake')
        self.transcript = self.dir / 'in' / 'scan.pdf.md'

    def tearDown(self):
        self.tempdir.cleanup()

    def config(self, **extra):
        values = {'filez4eva_target': str(self.target),
                  'filez4eva_pattern': PATTERN,
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
        out, command, _, _ = self.run_command()
        record = yaml.safe_load(out)
        self.assertEqual(list(record), [
            'file', 'transcript', 'cabinet', 'doctype', 'summary', 'data'])
        self.assertEqual(record['file'], str(self.source))
        self.assertEqual(record['transcript'], str(self.transcript))
        self.assertEqual(record['cabinet'], 'default')
        self.assertEqual(record['doctype'], 'receipt')
        self.assertEqual(record['summary'],
                         'Amazon.ca order receipt for a USB hub')
        # Fields in pattern order
        self.assertEqual(list(record['data']), ['date', 'account', 'part'])
        self.assertEqual(record['data'], DATA)
        self.assertIn("  date: '20261002'", out)
        self.assertEqual(command.status, 'Transcribed | Classified')

    def test_record_on_stdout(self):
        out, err, _ = self.run_app(
            f"filez4eva:\n  target: {self.target}\n"
            f"  pattern: '{PATTERN}'\n"
            "  doctypes:\n    receipt:\n      description: Proof\n")
        record = yaml.safe_load(out)
        self.assertEqual(record['data']['account'], 'amazon')
        self.assertEqual(record['file'], str(self.source))
        self.assertEqual(err.strip(), 'Transcribed | Classified')

    def test_default_fields(self):
        out, _, e, _ = self.run_command(
            {'filez4eva_target': str(self.target)},
            result={'data': {'date': '20261002', 'title': 'USB Hub Receipt'},
                    'doctype': 'other', 'summary': 'x'})
        self.assertEqual(yaml.safe_load(out)['data'],
                         {'date': '20261002', 'title': 'usb-hub-receipt'})
        props = e.call_args.args[1]['properties']['data']['properties']
        self.assertEqual(list(props), ['date', 'title'])

    def test_values_normalized(self):
        out, _, _, _ = self.run_command(
            result=result(account='Royal Bank of Canada', part='Visa  Stmt'))
        data = yaml.safe_load(out)['data']
        self.assertEqual(data['account'], 'royal-bank-of-canada')
        self.assertEqual(data['part'], 'visa-stmt')

    def test_summary_one_line(self):
        out, _, _, _ = self.run_command(result=dict(
            RESULT, summary='  A long\nsummary\n\nhere ', doctype='other'))
        self.assertEqual(yaml.safe_load(out)['summary'], 'A long summary here')

    def test_long_unicode_summary_not_wrapped(self):
        summary = 'Reçu ' + 'très long ' * 20
        out, _, _, _ = self.run_command(
            result=dict(RESULT, summary=summary, doctype='other'))
        self.assertEqual(len(out.splitlines()), 9)
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
        _, _, e, _ = self.run_command(self.config(filez4eva_fields={
            'account': {'guidance': 'The other party, never me'}}))
        schema = e.call_args.args[1]
        self.assertEqual(schema['type'], 'object')
        self.assertEqual(schema['required'], ['data', 'doctype', 'summary'])
        self.assertEqual(set(schema['properties']), set(schema['required']))
        self.assertFalse(schema['additionalProperties'])
        data = schema['properties']['data']
        self.assertEqual(data['type'], 'object')
        self.assertFalse(data['additionalProperties'])
        self.assertEqual(data['required'], ['date', 'account', 'part'])
        props = data['properties']
        self.assertEqual(list(props), ['date', 'account', 'part'])
        for key in props:
            self.assertEqual(props[key]['type'], 'string')
        self.assertEqual(props['date']['pattern'], r'^(\d{8})?$')
        self.assertIn('YYYYMMDD', props['date']['description'])
        self.assertTrue(props['account']['description'].startswith(
            'The other party, never me. Use lowercase'))
        self.assertTrue(props['part']['description'].startswith(
            'Use lowercase'))
        self.assertNotIn('pattern', props['part'])
        doctype = schema['properties']['doctype']
        self.assertEqual(doctype['enum'], ['receipt', 'bill', 'other'])

    def test_field_names_cannot_clash_with_record_keys(self):
        out, _, e, _ = self.run_command(
            self.config(filez4eva_pattern='{date}-{summary}-{doctype}'),
            result={'data': {'date': '20261002', 'summary': 'short',
                             'doctype': 'x'},
                    'doctype': 'receipt', 'summary': 'Long summary'})
        record = yaml.safe_load(out)
        self.assertEqual(record['summary'], 'Long summary')
        self.assertEqual(record['data']['summary'], 'short')

    def test_schema_without_doctypes(self):
        _, _, e, _ = self.run_command(
            {'filez4eva_target': str(self.target),
             'filez4eva_pattern': PATTERN},
            result=dict(RESULT, doctype='other'))
        enum = e.call_args.args[1]['properties']['doctype']['enum']
        self.assertEqual(enum, ['other'])

    def test_configured_other_not_duplicated(self):
        doctypes = {'other': {'description': 'Misc'}, 'bill': None}
        self.assertEqual(
            build_schema(Cabinet('x', '/x'), load_doctypes(ConfigHandler.fake(
                filez4eva_doctypes=doctypes)))['properties']['doctype']
            ['enum'], ['bill', 'other'])

    # Instructions

    def test_instructions(self):
        config = (f"filez4eva:\n"
                  f"  fields:\n"
                  f"    date:\n"
                  f"      guidance: The statement date, not the print date\n"
                  f"  cabinets:\n"
                  f"    accounts:\n"
                  f"      target: {self.target}\n"
                  f"      pattern: '{PATTERN}'\n"
                  f"      description: Personal account records\n"
                  f"      fields:\n"
                  f"        account:\n"
                  f"          guidance: The organization on the other side\n"
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
        self.assertIn('one-line summary', text)
        self.assertIn('- account: The organization on the other side. Use '
                      'lowercase', text)
        # Configured date guidance replaces the default text, but the fixed
        # rules stay
        self.assertIn('- date: The statement date, not the print date. '
                      'Give it as YYYYMMDD.', text)
        self.assertNotIn("document's own date, such as", text)
        self.assertIn('- part: Use lowercase', text)
        # Common learned values, most-used first
        self.assertIn('reuse one when it fits', text)
        self.assertIn('): amazon, bank\n', text)
        self.assertIn('): refund, receipt\n', text)
        self.assertNotIn('once', text)
        self.assertNotIn('statement,', text)
        self.assertLess(text.index('- date:'), text.index('- account:'))
        self.assertLess(text.index('- account:'), text.index('- part:'))
        self.assertIn('- receipt: Proof of purchase or payment', text)
        self.assertIn('- bill: A request for payment', text)
        self.assertIn('- memo\n', text)
        self.assertIn('- other: ', text)
        self.assertLess(text.index('- receipt:'), text.index('- other:'))
        self.assertEqual(yaml.safe_load(out)['cabinet'], 'accounts')

    def test_instructions_default_fields(self):
        _, _, e, _ = self.run_command(
            {'filez4eva_target': str(self.dir / 'new')},
            result={'data': {'date': '', 'title': 't'}, 'doctype': 'other',
                    'summary': 'x'})
        text = e.call_args.kwargs['instructions']
        self.assertIn('"default"', text)
        self.assertIn("- date: The document's own date, such as its issue, "
                      "statement or transaction date. Give it as YYYYMMDD.",
                      text)
        self.assertIn('- title: A short title describing the document. Use '
                      'lowercase', text)
        self.assertNotIn('Existing values', text)

    def test_no_values_offered_for_unlearned_field(self):
        _, _, e, _ = self.run_command(self.config(
            filez4eva_fields={'account': {'values': 'none'}}))
        text = e.call_args.kwargs['instructions']
        self.assertNotIn('amazon', text)
        self.assertIn('refund', text)

    # Model

    def test_default_model(self):
        _, _, e, _ = self.run_command(result=dict(RESULT, doctype='other'))
        self.assertEqual(e.call_args.kwargs['model'], 'claude-haiku-4-5')
        self.assertEqual(DEFAULT_MODEL, 'claude-haiku-4-5')
        self.assertIsNone(e.call_args.kwargs['api_key'])

    def test_configured_model_from_file(self):
        _, _, e = self.run_app(
            f"filez4eva:\n  target: {self.target}\n"
            f"  pattern: '{PATTERN}'\n"
            "  classify:\n    model: claude-from-file\n",
            result=dict(RESULT, doctype='other'))
        self.assertEqual(e.call_args.kwargs['model'], 'claude-from-file')

    def test_empty_classify_block_uses_default_model(self):
        _, _, e = self.run_app(
            f"filez4eva:\n  target: {self.target}\n"
            f"  pattern: '{PATTERN}'\n  classify:\n",
            result=dict(RESULT, doctype='other'))
        self.assertEqual(e.call_args.kwargs['model'], DEFAULT_MODEL)

    # Cabinets

    def two_cabinets(self):
        other = self.dir / 'memories'
        write_store(other, {'event': {'grandma-bday': {'count': 2}}})
        return (f"filez4eva:\n"
                f"  cabinets:\n"
                f"    accounts:\n"
                f"      target: {self.target}\n"
                f"      pattern: '{PATTERN}'\n"
                f"    memories:\n"
                f"      target: {other}\n"
                f"      pattern: '{{event}}/{{date}}'\n"
                f"      description: Family photos\n")

    MEMORY = {'data': {'date': '20261002', 'event': 'Grandma Bday'},
              'doctype': 'other', 'summary': 'Photo'}

    def test_cabinet_flag(self):
        out, _, e = self.run_app(self.two_cabinets(), '--cabinet', 'memories',
                                 result=self.MEMORY)
        text = e.call_args.kwargs['instructions']
        self.assertIn('Family photos', text)
        self.assertIn('- event: ', text)
        self.assertIn('grandma-bday', text)
        self.assertNotIn('amazon', text)
        self.assertNotIn('- account', text)
        record = yaml.safe_load(out)
        self.assertEqual(record['cabinet'], 'memories')
        self.assertEqual(record['data'], {'event': 'grandma-bday',
                                          'date': '20261002'})

    def test_cabinet_prompted(self):
        out, _, e = self.run_app(self.two_cabinets(), ttyin='memories\n',
                                 result=self.MEMORY)
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
        bad = [(None, "result isn't a mapping"),
               (dict(RESULT, data=None), 'no data in result'),
               (dict(RESULT, data=['x']), 'no data in result'),
               (result(account='../'),
                'Account must contain letters or digits'),
               (result(account=''), 'no account in result'),
               (result(account=5), 'no account in result'),
               (result(part='DROP'), 'no part in result'),
               (dict(RESULT, doctype='bill'), "unknown doctype 'bill'"),
               (dict(RESULT, summary=''), 'no summary in result'),
               (result(date='<UNKNOWN>', part='//'), 'Part must contain')]
        for value, message in bad:
            with self.subTest(result=value), \
                    self.assertRaises(Filez4EvaError) as raised:
                self.run_command(self.config(
                    filez4eva_doctypes={'receipt': None}), result=value)
            self.assertIn(f'Classification failed: {message}',
                          str(raised.exception))

    def test_extra_data_ignored(self):
        out, _, _, _ = self.run_command(result=result(extra='x'))
        self.assertNotIn('extra', yaml.safe_load(out)['data'])

    # Documents without a date of their own

    def test_no_date_gives_null(self):
        for value in [result(date='<UNKNOWN>'), result(date=''),
                      result(date='  '), result(date=None),
                      result(date='DROP'), result(date='2026-10-02'),
                      result(date='20261302'), result(date=20261002)]:
            with self.subTest(result=value):
                out, command, _, _ = self.run_command(
                    self.config(filez4eva_doctypes={'receipt': None}),
                    result=value)
                record = yaml.safe_load(out)
                self.assertIsNone(record['data']['date'])
                self.assertIn('\n  date: null\n', out)
                self.assertEqual(record['data']['account'], 'amazon')
                self.assertEqual(list(record['data']),
                                 ['date', 'account', 'part'])
                self.assertTrue(command.status.endswith('Classified'))

    def test_no_date_record_from_classify(self):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(**self.config())
        command = ClassifyCommand(app, file=str(self.source))
        command.handle_vals()
        with patch(EXTRACT, return_value=result(date='<UNKNOWN>')), \
                patch(TRANSCRIBE, return_value='# Hi'):
            record = command.classify()
        self.assertIsNone(record['data']['date'])

    def test_date_padded_with_spaces(self):
        out, _, _, _ = self.run_command(result=result(date=' 20261002 '))
        self.assertEqual(yaml.safe_load(out)['data']['date'], '20261002')

    def test_instructions_allow_empty_date(self):
        _, _, e, _ = self.run_command()
        text = e.call_args.kwargs['instructions']
        self.assertIn('return an empty string', text)
        self.assertIn("do not use today's date", text)


class TestClassifyPipe(WizLibTestCase):
    """classify's output can be piped into stow-file"""

    def pipe(self, extract_result, ttyin=''):
        """Run classify, then pipe its output into stow-file. Return
        (record text, stow-file stdout, stow-file stderr, target)."""
        with TemporaryDirectory() as d:
            dir = Path(d)
            target = dir / 'target'
            source = dir / 'scan.pdf'
            source.write_bytes(b'%PDF')
            with NamedTemporaryFile('w+', suffix='.yml') as cf:
                cf.write(f"filez4eva:\n  target: {target}\n"
                         f"  pattern: '{PATTERN}'\n"
                         "  doctypes:\n    receipt:\n")
                cf.flush()
                with patch(EXTRACT, return_value=extract_result), \
                        patch(TRANSCRIBE, return_value='# Receipt'), \
                        self.patchout() as o, self.patcherr():
                    Filez4EvaApp.start('--config', cf.name, 'classify',
                                       str(source), debug=True)
                    o.seek(0)
                    record = o.read()
                with self.patch_stream(record), self.patchout() as o, \
                        self.patcherr() as e, self.patch_ttyin(ttyin):
                    Filez4EvaApp.start('--config', cf.name, 'stow-file',
                                       str(source), debug=True)
                    o.seek(0)
                    e.seek(0)
                    out, err = o.read(), e.read()
            stowed = sorted(str(p.relative_to(target))
                            for p in target.rglob('*') if p.is_file())
            self.assertFalse(source.exists())
            return record, out, err, stowed, target

    def test_pipe_into_stow_file(self):
        _, out, _, stowed, target = self.pipe(RESULT)
        self.assertEqual(stowed, [
            '.filez4eva/values.yaml',
            '2026/amazon/20261002-receipt.pdf',
            '2026/amazon/20261002-receipt.pdf.md'])
        self.assertEqual(out.strip(),
                         str(target / '2026/amazon/20261002-receipt.pdf'))

    def test_pipe_without_date_prompts_for_it(self):
        record, _, err, stowed, _ = self.pipe(result(date='<UNKNOWN>'),
                                              ttyin='20250704\n')
        self.assertIn('date: null', record)
        self.assertIn('Date: ', err)
        self.assertNotIn('Account: ', err)
        self.assertIn('2025/amazon/20250704-receipt.pdf', stowed)
