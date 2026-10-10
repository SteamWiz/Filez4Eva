from datetime import datetime
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
from filez4eva.command.transcribe_command import (
    DEFAULT_MODEL, TranscribeCommand, read_front_matter, write_atomically)
from filez4eva.error import Filez4EvaError


TRANSCRIBE = 'filez4eva.command.transcribe_command.transcribe'


def split_transcript(text):
    """Return (front matter dict, rest of the file) for a transcript"""
    assert text.startswith('---\n')
    end = text.index('\n---\n', 4)
    return yaml.safe_load(text[4:end]), text[end + 5:]


class TestTranscribeCommand(WizLibTestCase):

    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.dir = Path(self.tempdir.name)
        self.source = self.dir / 'scan.pdf'
        self.source.write_bytes(b'%PDF-1.4 fake')
        self.sha = hashlib.sha256(b'%PDF-1.4 fake').hexdigest()
        self.target = self.dir / 'scan.pdf.md'

    def tearDown(self):
        self.tempdir.cleanup()

    def run_command(self, config=None, **vals):
        """Run the command directly with fake config; return its result"""
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(**(config or {}))
        command = TranscribeCommand(app, file=str(self.source), **vals)
        with self.patchout(), self.patcherr():
            return command.execute(), command

    def run_app(self, config_text='', *args, debug=True):
        """Run via the app with a config file; return (stdout, stderr)"""
        with self.patchout() as o, self.patcherr() as e, \
                NamedTemporaryFile('w+', suffix='.yml') as cf:
            cf.write(config_text)
            cf.flush()
            Filez4EvaApp.start('--config', cf.name, 'transcribe',
                               str(self.source), *args, debug=debug)
            o.seek(0)
            e.seek(0)
            return o.read(), e.read()

    def test_writes_transcript_with_front_matter(self):
        with patch(TRANSCRIBE, return_value='# Hello\n\nWorld\n') as t:
            result, command = self.run_command()
        self.assertEqual(Path(result), self.target)
        self.assertEqual(command.status, 'Transcribed')
        t.assert_called_once_with(self.source, model=DEFAULT_MODEL,
                                  api_key=None)
        front, rest = split_transcript(self.target.read_text())
        self.assertEqual(list(front), ['source', 'sha256', 'model',
                                       'transcribed'])
        self.assertEqual(front['source'], 'scan.pdf')
        self.assertEqual(front['sha256'], self.sha)
        self.assertEqual(front['model'], DEFAULT_MODEL)
        stamp = datetime.fromisoformat(front['transcribed'])
        self.assertIsNotNone(stamp.tzinfo)
        self.assertEqual(
            rest, f"<!-- {TRANSCRIBE_DISCLAIMER} -->\n\n# Hello\n\nWorld\n")

    def test_adds_trailing_newline(self):
        with patch(TRANSCRIBE, return_value='Text'):
            self.run_command()
        self.assertTrue(self.target.read_text().endswith('\n\nText\n'))

    def test_odd_file_name_is_valid_yaml(self):
        self.source = self.dir / "it's: #1 - 'odd'\".pdf"
        self.source.write_bytes(b'x')
        with patch(TRANSCRIBE, return_value='x'):
            result, _ = self.run_command()
        front = read_front_matter(Path(result))
        self.assertEqual(front['source'], self.source.name)

    def test_cache_hit_skips_transcription(self):
        with patch(TRANSCRIBE, return_value='first'):
            self.run_command()
        before = self.target.read_text()
        with patch(TRANSCRIBE, return_value='second') as t:
            result, command = self.run_command()
        t.assert_not_called()
        self.assertEqual(Path(result), self.target)
        self.assertEqual(command.status, 'Unchanged')
        self.assertEqual(self.target.read_text(), before)

    def test_force_retranscribes(self):
        with patch(TRANSCRIBE, return_value='first'):
            self.run_command()
        with patch(TRANSCRIBE, return_value='second') as t:
            self.run_command(force=True)
        t.assert_called_once()
        self.assertTrue(self.target.read_text().endswith('\nsecond\n'))

    def test_force_flag_from_app(self):
        with patch(TRANSCRIBE, return_value='first'):
            self.run_app()
        with patch(TRANSCRIBE, return_value='second') as t:
            self.run_app('', '--force')
        t.assert_called_once()
        self.assertTrue(self.target.read_text().endswith('\nsecond\n'))

    def test_sha_mismatch_retranscribes(self):
        with patch(TRANSCRIBE, return_value='first'):
            self.run_command()
        self.source.write_bytes(b'changed')
        with patch(TRANSCRIBE, return_value='second') as t:
            self.run_command()
        t.assert_called_once()
        front, rest = split_transcript(self.target.read_text())
        self.assertEqual(front['sha256'],
                         hashlib.sha256(b'changed').hexdigest())
        self.assertTrue(rest.endswith('\nsecond\n'))

    def test_unparseable_transcript_retranscribes(self):
        for content in ['no front matter', '---\n: [bad\n---\nx',
                        '---\nunterminated', '---\n- a list\n---\n', '']:
            self.target.write_text(content)
            with patch(TRANSCRIBE, return_value='new') as t:
                self.run_command()
            t.assert_called_once()
            self.assertTrue(self.target.read_text().endswith('\nnew\n'))

    def test_read_front_matter_missing_file(self):
        self.assertEqual(read_front_matter(self.dir / 'missing.md'), {})

    def test_default_model(self):
        with patch(TRANSCRIBE, return_value='x') as t:
            self.run_command()
        self.assertEqual(t.call_args.kwargs['model'], 'claude-opus-4-6')

    def test_configured_model(self):
        with patch(TRANSCRIBE, return_value='x') as t:
            self.run_command({'filez4eva_transcribe_model': 'claude-x'})
        self.assertEqual(t.call_args.kwargs['model'], 'claude-x')
        front, _ = split_transcript(self.target.read_text())
        self.assertEqual(front['model'], 'claude-x')

    def test_configured_key(self):
        with patch(TRANSCRIBE, return_value='x') as t:
            self.run_command({'filez4eva_anthropic_key': 'sk-test'})
        self.assertEqual(t.call_args.kwargs['api_key'], 'sk-test')

    def test_empty_key_is_none(self):
        with patch(TRANSCRIBE, return_value='x') as t:
            self.run_command({'filez4eva_anthropic_key': ''})
        self.assertIsNone(t.call_args.kwargs['api_key'])

    def test_model_and_key_from_config_file(self):
        config = ("filez4eva:\n"
                  "  transcribe:\n"
                  "    model: claude-from-file\n"
                  "  anthropic:\n"
                  "    key: $(echo sk-from-command)\n")
        with patch.dict(os.environ), \
                patch(TRANSCRIBE, return_value='x') as t:
            os.environ.pop('FILEZ4EVA_ANTHROPIC_KEY', None)
            os.environ.pop('FILEZ4EVA_TRANSCRIBE_MODEL', None)
            self.run_app(config)
        t.assert_called_once_with(self.source, model='claude-from-file',
                                  api_key='sk-from-command')

    def test_key_from_environment(self):
        with patch.dict(os.environ,
                        {'FILEZ4EVA_ANTHROPIC_KEY': 'sk-env'}), \
                patch(TRANSCRIBE, return_value='x') as t:
            self.run_app("filez4eva:\n  anthropic:\n    key: sk-file\n")
        self.assertEqual(t.call_args.kwargs['api_key'], 'sk-env')

    def test_key_unset_from_app(self):
        with patch.dict(os.environ), \
                patch(TRANSCRIBE, return_value='x') as t:
            os.environ.pop('FILEZ4EVA_ANTHROPIC_KEY', None)
            self.run_app("filez4eva:\n  target: /tmp\n")
        self.assertIsNone(t.call_args.kwargs['api_key'])
        self.assertEqual(t.call_args.kwargs['model'], DEFAULT_MODEL)

    def test_stdout_is_transcript_path(self):
        with patch(TRANSCRIBE, return_value='x'):
            out, err = self.run_app()
        self.assertEqual(out.strip(), str(self.target))
        self.assertEqual(err, 'Transcribed\n')
        with patch(TRANSCRIBE, return_value='x'):
            out, err = self.run_app()
        self.assertEqual(out.strip(), str(self.target))
        self.assertEqual(err, 'Unchanged\n')

    def test_kwark_error_raises(self):
        with patch(TRANSCRIBE, side_effect=APIError('boom')), \
                self.assertRaises(Filez4EvaError) as raised:
            self.run_command()
        self.assertIn('boom', str(raised.exception))
        self.assertIsInstance(raised.exception.__cause__, APIError)
        self.assertFalse(self.target.exists())

    def test_kwark_error_exits_non_zero(self):
        with patch(TRANSCRIBE, side_effect=APIError('boom')), \
                self.assertRaises(SystemExit) as raised:
            out, err = self.run_app(debug=False)
        self.assertEqual(raised.exception.code, 1)
        self.assertFalse(self.target.exists())

    def test_kwark_error_message_on_stderr(self):
        with patch(TRANSCRIBE, side_effect=APIError('boom')), \
                self.patchout() as o, self.patcherr() as e, \
                NamedTemporaryFile('w+', suffix='.yml') as cf, \
                self.assertRaises(SystemExit):
            Filez4EvaApp.start('--config', cf.name, 'transcribe',
                               str(self.source))
        e.seek(0)
        o.seek(0)
        self.assertIn('boom', e.read())
        self.assertEqual(o.read(), '')

    def test_kwark_error_keeps_existing_transcript(self):
        self.target.write_text('old')
        with patch(TRANSCRIBE, side_effect=APIError('boom')), \
                self.assertRaises(Filez4EvaError):
            self.run_command(force=True)
        self.assertEqual(self.target.read_text(), 'old')

    def test_missing_file(self):
        self.source = self.dir / 'missing.pdf'
        with patch(TRANSCRIBE) as t, self.assertRaises(Filez4EvaError):
            self.run_command()
        t.assert_not_called()

    def test_directory_is_not_a_file(self):
        self.source = self.dir
        with patch(TRANSCRIBE) as t, self.assertRaises(Filez4EvaError):
            self.run_command()
        t.assert_not_called()

    def test_write_atomically_cleans_up_on_write_error(self):
        target = self.dir / 'out.md'
        with self.assertRaises(TypeError):
            write_atomically(target, None)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         ['scan.pdf'])

    def test_write_atomically_cleans_up_on_replace_error(self):
        target = self.dir / 'out.md'
        with patch('os.replace', side_effect=OSError('nope')), \
                self.assertRaises(OSError):
            write_atomically(target, 'x')
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         ['scan.pdf'])
