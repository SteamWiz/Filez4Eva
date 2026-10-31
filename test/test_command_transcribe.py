from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unittest.mock import patch

import yaml
from kwark.ai import APIError, TRANSCRIBE_DISCLAIMER
from wizlib.config_handler import ConfigHandler
from wizlib.error import ConfigHandlerError
from wizlib.test_case import WizLibTestCase

from filez4eva import Filez4EvaApp
from filez4eva.command.ingest_command import read_sidecar, write_sidecar
from filez4eva.command.transcribe_command import (
    DEFAULT_MODEL, TranscribeCommand, format_transcript, read_front_matter,
    transcribe_file, transcript_body, write_atomically)
from filez4eva.error import Filez4EvaError
from filez4eva.stage import find_ingested, new_files, resolve_path
from test import plain


TRANSCRIBE = 'filez4eva.command.transcribe_command.transcribe'
OP_RUN = 'wizlib.config_handler.subprocess.run'
NOW = 'filez4eva.command.ingest_command.now'

# A fixed local time with an offset, so names and `at` are predictable
CLOCK = datetime(2026, 10, 25, 14, 3, 7, 42000,
                 tzinfo=timezone(timedelta(hours=-7)))
AT = '2026-10-25T14:03:07-07:00'
STAMP = '20261025-140307-042'


def split_transcript(text):
    """Return (front matter dict, rest of the file) for a transcript"""
    assert text.startswith('---\n')
    end = text.index('\n---\n', 4)
    return yaml.safe_load(text[4:end]), text[end + 5:]


class TestTranscribeFile(WizLibTestCase):
    """The in-place transcription with the sha256 cache, used by the
    transcribe stage"""

    def setUp(self):
        self.tempdir = TemporaryDirectory()
        self.dir = Path(self.tempdir.name)
        self.source = self.dir / 'scan.pdf'
        self.source.write_bytes(b'%PDF-1.4 fake')
        self.sha = hashlib.sha256(b'%PDF-1.4 fake').hexdigest()
        self.target = self.dir / 'scan.pdf.md'

    def tearDown(self):
        self.tempdir.cleanup()

    def run_file(self, model=DEFAULT_MODEL, api_key=None):
        return transcribe_file(self.source, model, api_key)

    def test_writes_transcript_with_front_matter(self):
        with patch(TRANSCRIBE, return_value='# Hello\n\nWorld\n') as t:
            target, status = self.run_file()
        self.assertEqual(target, self.target)
        self.assertEqual(status, 'Transcribed')
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

    def test_model_and_key_passed(self):
        with patch(TRANSCRIBE, return_value='x') as t:
            self.run_file('claude-x', 'sk-test')
        t.assert_called_once_with(self.source, model='claude-x',
                                  api_key='sk-test')
        front, _ = split_transcript(self.target.read_text())
        self.assertEqual(front['model'], 'claude-x')

    def test_adds_trailing_newline(self):
        with patch(TRANSCRIBE, return_value='Text'):
            self.run_file()
        self.assertTrue(self.target.read_text().endswith('\n\nText\n'))

    def test_odd_file_name_is_valid_yaml(self):
        self.source = self.dir / "it's: #1 - 'odd'\".pdf"
        self.source.write_bytes(b'x')
        with patch(TRANSCRIBE, return_value='x'):
            target, _ = self.run_file()
        self.assertEqual(read_front_matter(target)['source'],
                         self.source.name)

    def test_cache_hit_skips_transcription(self):
        with patch(TRANSCRIBE, return_value='first'):
            self.run_file()
        before = self.target.read_text()
        with patch(TRANSCRIBE, return_value='second') as t:
            target, status = self.run_file()
        t.assert_not_called()
        self.assertEqual(target, self.target)
        self.assertEqual(status, 'Unchanged')
        self.assertEqual(self.target.read_text(), before)

    def test_sha_mismatch_retranscribes(self):
        with patch(TRANSCRIBE, return_value='first'):
            self.run_file()
        self.source.write_bytes(b'changed')
        with patch(TRANSCRIBE, return_value='second') as t:
            self.run_file()
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
                self.run_file()
            t.assert_called_once()
            self.assertTrue(self.target.read_text().endswith('\nnew\n'))

    def test_read_front_matter_missing_file(self):
        self.assertEqual(read_front_matter(self.dir / 'missing.md'), {})

    def test_kwark_error_raises(self):
        with patch(TRANSCRIBE, side_effect=APIError('boom')), \
                self.assertRaises(Filez4EvaError) as raised:
            self.run_file()
        self.assertIn('boom', str(raised.exception))
        self.assertIsInstance(raised.exception.__cause__, APIError)
        self.assertFalse(self.target.exists())

    def test_kwark_error_keeps_existing_transcript(self):
        self.target.write_text('old')
        with patch(TRANSCRIBE, side_effect=APIError('boom')), \
                self.assertRaises(Filez4EvaError):
            self.run_file()
        self.assertEqual(self.target.read_text(), 'old')

    def test_missing_file(self):
        self.source = self.dir / 'missing.pdf'
        with patch(TRANSCRIBE) as t, self.assertRaises(Filez4EvaError):
            self.run_file()
        t.assert_not_called()

    def test_directory_is_not_a_file(self):
        self.source = self.dir
        with patch(TRANSCRIBE) as t, self.assertRaises(Filez4EvaError):
            self.run_file()
        t.assert_not_called()

    def test_transcript_body(self):
        text = format_transcript('a.pdf', 'abc', 'm', 't', '# Title\n\nBody')
        self.assertEqual(transcript_body(text), '# Title\n\nBody')
        self.assertEqual(transcript_body('plain\ntext\n'), 'plain\ntext')

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


class TranscribeTestCase(WizLibTestCase):
    """A temporary intake (also set in FILEZ4EVA_INTAKE, so nothing ever
    touches the real one), a temporary source directory and a frozen
    clock"""

    def setUp(self):
        super().setUp()
        intake_tmp = TemporaryDirectory()
        source_tmp = TemporaryDirectory()
        self.addCleanup(intake_tmp.cleanup)
        self.addCleanup(source_tmp.cleanup)
        self.intake = Path(intake_tmp.name) / 'intake'
        self.source = Path(source_tmp.name)
        for patcher in [patch(NOW, return_value=CLOCK),
                        patch.dict(os.environ,
                                   {'FILEZ4EVA_INTAKE': str(self.intake)})]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def make(self, name, content='%PDF-1.4 fake', where=None):
        path = (where or self.source) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def make_document(self, name, results=None, content='%PDF-1.4 fake'):
        """Create an ingested document in the intake, with its sidecar"""
        path = self.make(name, content, self.intake)
        write_sidecar(path, {'results': results or {
            'ingest': {'at': AT, 'original-name': 'orig.pdf',
                       'source': {}}}})
        return path

    def run_command(self, path=None, config=None, **vals):
        """Run the command directly with fake config; return (result,
        command, stderr)"""
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(filez4eva_intake=str(self.intake),
                                        **(config or {}))
        command = TranscribeCommand(
            app, path=None if path is None else str(path), **vals)
        with self.patchout(), self.patcherr() as e:
            result = command.execute()
            e.seek(0)
            return result, command, e.read()

    def run_app(self, *args, config_text='', debug=False):
        """Run via the app with a config file; return (stdout, stderr,
        exit code)"""
        code = 0
        with self.patchout() as o, self.patcherr() as e, \
                self.patch_stream(''), \
                NamedTemporaryFile('w+', suffix='.yml') as cf:
            cf.write(config_text)
            cf.flush()
            try:
                Filez4EvaApp.start('--config', cf.name, 'transcribe',
                                   *[str(a) for a in args], debug=debug)
            except SystemExit as exit:
                code = exit.code
            o.seek(0)
            e.seek(0)
            return o.read(), e.read(), code

    def intake_names(self):
        return sorted(p.name for p in self.intake.iterdir())


class TestTranscribeCommand(TranscribeTestCase):

    def test_file_outside_intake_is_ingested_then_transcribed(self):
        source = self.make('Scan 1.PDF')
        with patch(TRANSCRIBE, return_value='# Hello\n\nWorld\n') as t:
            result, command, _ = self.run_command(source)
        document = self.intake / f'{STAMP}.pdf'
        transcript = self.intake / f'{STAMP}.pdf.md'
        self.assertFalse(source.exists())
        t.assert_called_once_with(document, model=DEFAULT_MODEL,
                                  api_key=None)
        self.assertEqual(result, str(transcript))
        self.assertEqual(command.status,
                         'Ingested 1 file | Transcribed 1 file')
        self.assertEqual(self.intake_names(), [
            f'{STAMP}.pdf', f'{STAMP}.pdf.md', f'{STAMP}.pdf.yml'])
        front, rest = split_transcript(transcript.read_text())
        self.assertEqual(front['source'], f'{STAMP}.pdf')
        self.assertTrue(rest.endswith('\n# Hello\n\nWorld\n'))
        results = read_sidecar(document)['results']
        self.assertEqual(list(results), ['ingest', 'transcribe'])
        self.assertEqual(results['ingest']['original-name'], 'Scan 1.PDF')
        self.assertEqual(results['transcribe'], {
            'at': AT, 'model': DEFAULT_MODEL,
            'transcript': f'{STAMP}.pdf.md',
            'length': len('# Hello\n\nWorld')})

    def test_directory_outside_intake(self):
        self.make('b.pdf')
        self.make('a.png')
        self.make('.hidden')
        self.make('inner.pdf', where=self.source / 'sub')
        (self.source / 'link.pdf').symlink_to(self.source / 'b.pdf')
        with patch(TRANSCRIBE, return_value='x') as t:
            result, command, _ = self.run_command(self.source)
        first = self.intake / f'{STAMP}.png'
        second = self.intake / '20261025-140307-043.pdf'
        self.assertEqual([c.args[0] for c in t.call_args_list],
                         [first, second])
        self.assertEqual(result.splitlines(),
                         [f'{first}.md', f'{second}.md'])
        self.assertEqual(command.status,
                         'Ingested 2 files | Transcribed 2 files')
        self.assertEqual(sorted(p.name for p in self.source.iterdir()),
                         ['.hidden', 'link.pdf', 'sub'])
        for document in [first, second]:
            self.assertIn('transcribe', read_sidecar(document)['results'])

    def test_no_path_is_the_intake(self):
        document = self.make_document(f'{STAMP}.pdf')
        archived = self.make('old.pdf.yml', 'x', self.intake / 'archive')
        self.make('old.pdf', where=self.intake / 'archive')
        with patch(TRANSCRIBE, return_value='Body') as t:
            result, command, _ = self.run_command()
        t.assert_called_once_with(document, model=DEFAULT_MODEL,
                                  api_key=None)
        self.assertEqual(result, f'{document}.md')
        self.assertEqual(command.status, 'Transcribed 1 file')
        self.assertEqual(sorted(p.name for p in archived.parent.iterdir()),
                         ['old.pdf', 'old.pdf.yml'])
        self.assertEqual(archived.read_text(), 'x')
        results = read_sidecar(document)['results']
        self.assertEqual(results['ingest']['original-name'], 'orig.pdf')
        self.assertEqual(results['transcribe']['length'], 4)

    def test_path_in_intake_is_an_error(self):
        document = self.make_document(f'{STAMP}.pdf')
        stray = self.make('stray.pdf', where=self.intake)
        sub = self.intake / 'sub'
        inner = self.make('inner.pdf', where=sub)
        for path in [self.intake, document, stray, sub, inner,
                     Path(f'{document}.yml')]:
            with self.subTest(path=path.name), patch(TRANSCRIBE) as t, \
                    self.assertRaisesRegex(Filez4EvaError,
                                           'is in the intake .*--ingested'):
                self.run_command(path)
            t.assert_not_called()
        self.assertEqual(self.intake_names(), [
            f'{STAMP}.pdf', f'{STAMP}.pdf.yml', 'stray.pdf', 'sub'])
        self.assertEqual(list(read_sidecar(document)['results']), ['ingest'])

    def test_companions_in_intake_are_not_documents(self):
        document = self.make_document(f'{STAMP}.txt')
        transcript = self.make(f'{STAMP}.txt.md', 'stale', self.intake)
        self.make('.hidden', where=self.intake)
        with patch(TRANSCRIBE, return_value='x') as t:
            self.run_command()
        t.assert_called_once_with(document, model=DEFAULT_MODEL,
                                  api_key=None)
        self.assertTrue(transcript.read_text().endswith('\nx\n'))
        self.assertEqual(self.intake_names(), [
            '.hidden', f'{STAMP}.txt', f'{STAMP}.txt.md', f'{STAMP}.txt.yml'])

    def test_no_path_ingests_nothing(self):
        document = self.make_document(f'{STAMP}.pdf')
        stray = self.make('Dropped.PDF', where=self.intake)
        with patch(TRANSCRIBE, return_value='x') as t:
            _, command, err = self.run_command()
        t.assert_called_once_with(document, model=DEFAULT_MODEL,
                                  api_key=None)
        self.assertTrue(stray.exists())
        self.assertFalse(Path(f'{stray}.yml').exists())
        self.assertIn(f'Not ingested: {stray}', err)
        self.assertEqual(command.status, 'Transcribed 1 file')

    def test_no_path_with_only_strays(self):
        stray = self.make('Dropped.PDF', where=self.intake)
        with patch(TRANSCRIBE) as t:
            out, err, code = self.run_app()
        t.assert_not_called()
        self.assertEqual(code, 0)
        self.assertEqual(out, '')
        self.assertIn(f'Not ingested: {stray}', err)
        self.assertIn('Nothing to transcribe: no documents ingested in the '
                      'intake', err)
        self.assertTrue(stray.exists())

    def test_empty_intake(self):
        with patch(TRANSCRIBE) as t:
            out, err, code = self.run_app()
        t.assert_not_called()
        self.assertEqual(code, 0)
        self.assertEqual(out, '')
        self.assertEqual(err, 'Nothing to transcribe: the intake is empty\n')

    def test_ingested_documents(self):
        first = self.make_document(f'{STAMP}.pdf')
        second = self.make_document('20261025-140307-043.pdf')
        third = self.make_document('20261025-140307-044.pdf')
        with patch(TRANSCRIBE, return_value='x') as t:
            result, command, _ = self.run_command(
                ingested=[third.name, str(first)])
        self.assertEqual([c.args[0] for c in t.call_args_list],
                         [third, first])
        self.assertEqual(result.splitlines(), [f'{third}.md', f'{first}.md'])
        self.assertEqual(command.status, 'Transcribed 2 files')
        self.assertNotIn('transcribe', read_sidecar(second)['results'])

    def test_ingested_given_twice_is_done_once(self):
        document = self.make_document(f'{STAMP}.pdf')
        with patch(TRANSCRIBE, return_value='x') as t:
            _, command, _ = self.run_command(
                ingested=[document.name, document.name])
        t.assert_called_once()
        self.assertEqual(command.status, 'Transcribed 1 file')

    def test_ingested_from_app(self):
        document = self.make_document(f'{STAMP}.pdf')
        self.make_document('20261025-140307-043.pdf')
        with patch(TRANSCRIBE, return_value='x') as t:
            out, err, code = self.run_app('--ingested', document.name)
        self.assertEqual(code, 0)
        t.assert_called_once_with(document, model=DEFAULT_MODEL,
                                  api_key=None)
        self.assertEqual(out.strip(), f'{document}.md')
        self.assertEqual(plain(err), f'Transcribing {document.name} '
                         '(orig.pdf)\nTranscribed 1 file\n')

    def test_ingested_that_is_not_a_document_is_an_error(self):
        document = self.make_document(f'{STAMP}.pdf')
        good = document.name
        stray = self.make('stray.pdf', where=self.intake)
        transcript = self.make(f'{STAMP}.pdf.md', 'x', self.intake)
        outside = self.make('outside.pdf', where=self.source)
        Path(f'{outside}.yml').write_text('results: {}')
        archive = self.intake / 'archive'
        old = self.make('old.pdf', where=archive)
        self.make('old.pdf.yml', 'x', archive)
        hidden = self.make('.hidden.pdf', where=self.intake)
        self.make('.hidden.pdf.yml', 'x', self.intake)
        for name in ['missing.pdf', stray.name, str(stray),
                     f'{good}.yml', transcript.name, str(outside),
                     str(old), 'archive', hidden.name, '..']:
            with self.subTest(name=name), patch(TRANSCRIBE) as t, \
                    self.assertRaisesRegex(Filez4EvaError,
                                           'not a document ingested'):
                self.run_command(ingested=[good, name])
            t.assert_not_called()
        self.assertNotIn('transcribe', read_sidecar(document)['results'])

    def test_ingested_with_path_is_an_error(self):
        document = self.make_document(f'{STAMP}.pdf')
        source = self.make('a.pdf')
        with patch(TRANSCRIBE) as t:
            out, err, code = self.run_app('--ingested', document.name, source)
        t.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("can't be combined with a path", err)
        self.assertTrue(source.exists())
        self.assertNotIn('transcribe', read_sidecar(document)['results'])

    def test_path_run_leaves_intake_documents_alone(self):
        document = self.make_document(f'{STAMP}.pdf')
        self.make('a.pdf')
        with patch(TRANSCRIBE, return_value='x') as t:
            _, command, _ = self.run_command(self.source)
        new = self.intake / '20261025-140307-043.pdf'
        t.assert_called_once_with(new, model=DEFAULT_MODEL, api_key=None)
        self.assertEqual(command.status,
                         'Ingested 1 file | Transcribed 1 file')
        self.assertEqual(list(read_sidecar(document)['results']), ['ingest'])
        self.assertFalse(Path(f'{document}.md').exists())

    def test_already_transcribed_is_skipped(self):
        document = self.make_document(f'{STAMP}.pdf', {
            'ingest': {'at': AT}, 'transcribe': {'at': AT}})
        before = Path(f'{document}.yml').read_text()
        with patch(TRANSCRIBE) as t:
            result, command, _ = self.run_command()
        t.assert_not_called()
        self.assertEqual(result, '')
        self.assertEqual(command.status,
                         'Nothing to transcribe (1 file already transcribed)')
        self.assertEqual(Path(f'{document}.yml').read_text(), before)
        self.assertEqual(self.intake_names(),
                         [f'{STAMP}.pdf', f'{STAMP}.pdf.yml'])

    def test_already_transcribed_counted_with_others(self):
        self.make_document(f'{STAMP}.pdf', {'ingest': {}, 'transcribe': {}})
        self.make_document('20261025-140307-099.pdf')
        with patch(TRANSCRIBE, return_value='x') as t:
            _, command, _ = self.run_command()
        t.assert_called_once()
        self.assertEqual(command.status,
                         'Transcribed 1 file | Already transcribed 1 file')

    def test_existing_transcript_with_matching_sha_is_reused(self):
        document = self.make_document(f'{STAMP}.pdf')
        sha = hashlib.sha256(document.read_bytes()).hexdigest()
        Path(f'{document}.md').write_text(format_transcript(
            document.name, sha, 'claude-earlier', 'then', 'Cached text'))
        with patch(TRANSCRIBE) as t:
            result, command, _ = self.run_command(
                config={'filez4eva_transcribe_model': 'claude-now'})
        t.assert_not_called()
        self.assertEqual(result, f'{document}.md')
        self.assertEqual(command.status, 'Transcribed 1 file')
        transcribe = read_sidecar(document)['results']['transcribe']
        self.assertEqual(transcribe['model'], 'claude-earlier')
        self.assertEqual(transcribe['length'], len('Cached text'))

    def test_only_skips_files_not_ingested(self):
        source = self.make('a.pdf')
        with patch(TRANSCRIBE) as t:
            result, command, err = self.run_command(self.source, only=True)
        t.assert_not_called()
        self.assertTrue(source.exists())
        self.assertFalse(self.intake.exists() and self.intake_names())
        self.assertEqual(result, '')
        self.assertEqual(command.status, 'Skipped 1 file (not ingested)')
        self.assertIn(f'Skipped {source}: not ingested yet', err)

    def test_only_in_intake(self):
        document = self.make_document(f'{STAMP}.pdf')
        stray = self.make('stray.pdf', where=self.intake)
        with patch(TRANSCRIBE, return_value='x') as t:
            _, command, err = self.run_command(only=True)
        t.assert_called_once_with(document, model=DEFAULT_MODEL,
                                  api_key=None)
        self.assertTrue(stray.exists())
        self.assertIn(f'Not ingested: {stray}', err)
        self.assertEqual(command.status, 'Transcribed 1 file')

    def test_only_from_app(self):
        self.make('a.pdf')
        with patch(TRANSCRIBE) as t:
            out, err, code = self.run_app('--only', self.source)
        t.assert_not_called()
        self.assertEqual(code, 0)
        self.assertEqual(out, '')
        self.assertIn('Skipped 1 file (not ingested)', err)

    def test_failure_is_reported_and_run_carries_on(self):
        self.make('a.pdf')
        self.make('b.zip')
        self.make('c.pdf')

        def fake(path, **kwargs):
            if path.suffix == '.zip':
                raise APIError('unsupported')
            return 'x'
        with patch(TRANSCRIBE, side_effect=fake) as t:
            out, err, code = self.run_app(self.source)
        self.assertEqual(t.call_count, 3)
        self.assertEqual(code, 1)
        failed = self.intake / '20261025-140307-043.zip'
        self.assertIn(f"Failed to transcribe {self.source / 'b.zip'} "
                      f"(now {failed}): Transcription failed: unsupported",
                      err)
        self.assertIn('1 of 3 files failed to transcribe', err)
        self.assertEqual(out.splitlines(), [
            str(self.intake / f'{STAMP}.pdf.md'),
            str(self.intake / '20261025-140307-044.pdf.md')])
        self.assertNotIn('transcribe', read_sidecar(failed)['results'])
        self.assertFalse(Path(f'{failed}.md').exists())

    def test_failed_document_is_done_on_next_run(self):
        self.make_document(f'{STAMP}.pdf')
        with patch(TRANSCRIBE, side_effect=APIError('boom')), \
                self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
            self.run_command()
        with patch(TRANSCRIBE, return_value='x'):
            _, command, _ = self.run_command()
        self.assertEqual(command.status, 'Transcribed 1 file')

    def test_single_file_failure_exits_non_zero(self):
        source = self.make('scan.pdf')
        with patch(TRANSCRIBE, side_effect=APIError('boom')):
            out, err, code = self.run_app(source)
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertIn('boom', err)

    def test_ingest_failure_is_reported(self):
        self.make('a.pdf')
        with patch('filez4eva.stage.ingest_file',
                   side_effect=OSError('disk full')), \
                patch(TRANSCRIBE) as t, \
                self.patchout(), self.patcherr() as e, \
                self.assertRaises(Filez4EvaError):
            app = Filez4EvaApp()
            app.config = ConfigHandler.fake(
                filez4eva_intake=str(self.intake))
            TranscribeCommand(app, path=str(self.source)).execute()
        t.assert_not_called()
        e.seek(0)
        self.assertIn(f"Failed to transcribe {self.source / 'a.pdf'}: "
                      "disk full", e.read())

    def test_bad_sidecar_is_a_failure_and_left_alone(self):
        for content in [': [bad', '- a list', 'results: [1]', b'\xff']:
            with self.subTest(content=content):
                document = self.make_document(f'{STAMP}.pdf')
                sidecar = Path(f'{document}.yml')
                if isinstance(content, bytes):
                    sidecar.write_bytes(content)
                else:
                    sidecar.write_text(content)
                with patch(TRANSCRIBE, return_value='x') as t, \
                        self.assertRaises(Filez4EvaError):
                    self.run_command()
                t.assert_not_called()
                self.assertEqual(sidecar.read_bytes(),
                                 content if isinstance(content, bytes)
                                 else content.encode())

    def test_sidecar_with_empty_results(self):
        document = self.make_document(f'{STAMP}.pdf')
        Path(f'{document}.yml').write_text('results:\nnote: kept\n')
        with patch(TRANSCRIBE, return_value='x'):
            self.run_command()
        data = read_sidecar(document)
        self.assertEqual(data['note'], 'kept')
        self.assertIn('transcribe', data['results'])

    def test_unreadable_transcript_is_a_failure(self):
        document = self.make_document(f'{STAMP}.pdf')
        missing = self.intake / 'missing.md'
        with patch('filez4eva.command.transcribe_command.transcribe_file',
                   return_value=(missing, 'Transcribed')), \
                self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
            self.run_command()
        self.assertNotIn('transcribe', read_sidecar(document)['results'])

    def test_empty_directory(self):
        result, command, _ = self.run_command(self.source)
        self.assertEqual(result, '')
        self.assertEqual(command.status,
                         f'Nothing to transcribe: no files in {self.source}')

    def test_missing_path(self):
        with patch(TRANSCRIBE) as t, \
                self.assertRaisesRegex(Filez4EvaError, 'must exist'):
            self.run_command(self.source / 'missing.pdf')
        t.assert_not_called()

    def test_missing_path_from_app(self):
        out, err, code = self.run_app(self.source / 'missing.pdf')
        self.assertEqual(code, 1)
        self.assertIn('must exist', err)

    def test_intake_subdirectory_is_never_touched(self):
        self.make_document(f'{STAMP}.pdf')
        archive = self.intake / 'archive'
        old = self.make('old.pdf', where=archive)
        for path in [archive, old]:
            with self.subTest(path=path.name), patch(TRANSCRIBE) as t, \
                    self.assertRaisesRegex(Filez4EvaError, 'in the intake'):
                self.run_command(path)
            t.assert_not_called()
        self.assertEqual(sorted(p.name for p in archive.iterdir()),
                         ['old.pdf'])

    def test_symlink_to_intake_subdirectory_is_never_touched(self):
        archive = self.intake / 'archive'
        old = self.make('old.pdf', where=archive)
        self.make('old.pdf.yml', 'x', archive)
        link = self.source / 'link'
        link.symlink_to(archive, target_is_directory=True)
        with patch(TRANSCRIBE) as t, \
                self.assertRaisesRegex(Filez4EvaError, 'in the intake'):
            self.run_command(link)
        t.assert_not_called()
        self.assertEqual(sorted(p.name for p in archive.iterdir()),
                         ['old.pdf', 'old.pdf.yml'])
        self.assertEqual(sorted(p.name for p in self.intake.iterdir()),
                         ['archive'])
        self.assertTrue(old.is_file())

    def test_intake_through_dot_dot_is_an_error(self):
        document = self.make_document(f'{STAMP}.pdf')
        (self.intake / 'archive').mkdir()
        with patch(TRANSCRIBE) as t, \
                self.assertRaisesRegex(Filez4EvaError, 'in the intake'):
            self.run_command(self.intake / 'archive' / '..')
        t.assert_not_called()
        self.assertFalse(Path(f'{document}.md').exists())

    def test_symlink_to_intake_document_is_an_error(self):
        document = self.make_document(f'{STAMP}.pdf')
        link = self.source / 'link.pdf'
        link.symlink_to(document)
        with patch(TRANSCRIBE) as t, \
                self.assertRaisesRegex(Filez4EvaError, 'in the intake'):
            self.run_command(link)
        t.assert_not_called()

    def test_force_is_not_an_option(self):
        source = self.make('a.pdf')
        with patch(TRANSCRIBE) as t:
            out, err, code = self.run_app('--force', source)
        self.assertEqual(code, 1)
        self.assertRegex(err, 'unrecognized arguments: .*--force')
        t.assert_not_called()
        self.assertTrue(source.exists())

    def test_stdout_and_status_from_app(self):
        source = self.make('scan.pdf')
        with patch(TRANSCRIBE, return_value='x'):
            out, err, code = self.run_app(source)
        self.assertEqual(code, 0)
        # stdout has only the result path; progress goes to stderr
        self.assertEqual(out, str(self.intake / f'{STAMP}.pdf.md'))
        self.assertEqual(plain(err), f'Ingesting {source}\n'
                         f'Transcribing {STAMP}.pdf (scan.pdf)\n'
                         'Ingested 1 file | Transcribed 1 file\n')
        with patch(TRANSCRIBE) as t:
            out, err, code = self.run_app()
        t.assert_not_called()
        self.assertEqual(out, '')
        self.assertEqual(
            err, 'Nothing to transcribe (1 file already transcribed)\n')


class TestTranscribeThroughSymlink(TranscribeTestCase):
    """Source and intake reached through a symbolic link, as the macOS
    temporary directory is (/var is a link to /private/var): messages and
    output use the paths as given, never a mix of resolved and unresolved
    ones. Holds without the symlinked temporary directory of conftest.py."""

    def setUp(self):
        super().setUp()
        real = self.source / 'real'
        (real / 'in').mkdir(parents=True)
        link = self.source / 'link'
        link.symlink_to(real, target_is_directory=True)
        self.source = link / 'in'
        self.intake = link / 'intake'
        os.environ['FILEZ4EVA_INTAKE'] = str(self.intake)

    def test_failure_names_source_and_intake_as_given(self):
        self.make('a.pdf')
        self.make('b.zip')

        def fake(path, **kwargs):
            if path.suffix == '.zip':
                raise APIError('unsupported')
            return 'x'
        with patch(TRANSCRIBE, side_effect=fake):
            out, err, code = self.run_app(self.source)
        self.assertEqual(code, 1)
        failed = self.intake / '20261025-140307-043.zip'
        self.assertIn(f"Failed to transcribe {self.source / 'b.zip'} "
                      f"(now {failed}): Transcription failed: unsupported",
                      err)
        self.assertEqual(out.strip(), str(self.intake / f'{STAMP}.pdf.md'))

    def test_skip_names_source_as_given(self):
        source = self.make('a.pdf')
        with patch(TRANSCRIBE) as t:
            _, _, err = self.run_command(self.source, only=True)
        t.assert_not_called()
        self.assertIn(f'Skipped {source}: not ingested yet', err)

    def test_intake_given_as_path_through_link_is_an_error(self):
        self.make_document(f'{STAMP}.pdf')
        with patch(TRANSCRIBE) as t, \
                self.assertRaisesRegex(Filez4EvaError, 'in the intake'):
            self.run_command(self.intake)
        t.assert_not_called()

    def test_ingested_names_document_as_given(self):
        document = self.make_document(f'{STAMP}.pdf')
        with patch(TRANSCRIBE, return_value='x'):
            result, _, _ = self.run_command(ingested=[str(document)])
        self.assertEqual(result, f'{document}.md')

    def test_resolve_path_keeps_the_path_given(self):
        self.intake.mkdir()
        source = self.make('a.pdf')
        self.assertEqual(resolve_path(str(self.source), self.intake),
                         self.source)
        self.assertEqual(resolve_path(str(source), self.intake), source)


class TestStageHelpers(TranscribeTestCase):

    def test_resolve_path(self):
        self.intake.mkdir()
        source = self.make('a.pdf')
        self.assertEqual(resolve_path(str(source), self.intake), source)
        stray = self.make('b.pdf', where=self.intake)
        for path in [stray, self.intake]:
            with self.subTest(path=path), \
                    self.assertRaisesRegex(Filez4EvaError, 'in the intake'):
                resolve_path(str(path), self.intake)

    def test_new_files(self):
        self.intake.mkdir()
        a = self.make('a.pdf')
        self.make('a.pdf.yml')
        self.assertEqual(new_files(self.source, self.intake),
                         [a, self.source / 'a.pdf.yml'])
        self.assertEqual(new_files(a, self.intake), [a])

    def test_find_ingested(self):
        document = self.make_document(f'{STAMP}.pdf')
        self.assertEqual(find_ingested(document.name, self.intake), document)
        self.assertEqual(find_ingested(str(document), self.intake), document)
        with self.assertRaisesRegex(Filez4EvaError,
                                    'not a document ingested'):
            find_ingested('nope.pdf', self.intake)


class TestTranscribeSettings(TranscribeTestCase):

    def setUp(self):
        super().setUp()
        self.file = self.make('scan.pdf')
        self.document = self.intake / f'{STAMP}.pdf'

    def test_default_model(self):
        with patch(TRANSCRIBE, return_value='x') as t:
            self.run_command(self.file)
        self.assertEqual(t.call_args.kwargs['model'], 'claude-opus-4-6')

    def test_configured_model(self):
        with patch(TRANSCRIBE, return_value='x') as t:
            self.run_command(self.file,
                             {'filez4eva_transcribe_model': 'claude-x'})
        self.assertEqual(t.call_args.kwargs['model'], 'claude-x')
        front, _ = split_transcript(Path(f'{self.document}.md').read_text())
        self.assertEqual(front['model'], 'claude-x')
        self.assertEqual(
            read_sidecar(self.document)['results']['transcribe']['model'],
            'claude-x')

    def test_configured_key(self):
        with patch(TRANSCRIBE, return_value='x') as t:
            self.run_command(self.file,
                             {'filez4eva_anthropic_key': 'sk-test'})
        self.assertEqual(t.call_args.kwargs['api_key'], 'sk-test')

    def test_empty_key_is_none(self):
        with patch(TRANSCRIBE, return_value='x') as t:
            self.run_command(self.file, {'filez4eva_anthropic_key': ''})
        self.assertIsNone(t.call_args.kwargs['api_key'])

    def test_model_and_key_from_config_file(self):
        config = ("filez4eva:\n"
                  "  transcribe:\n"
                  "    model: claude-from-file\n"
                  "  anthropic:\n"
                  "    key: op://vault/anthropic/credential\n")
        done = CompletedProcess([], returncode=0, stdout='sk-from-op\n')
        with patch.dict(os.environ), \
                patch(OP_RUN, return_value=done) as op, \
                patch(TRANSCRIBE, return_value='x') as t:
            os.environ.pop('FILEZ4EVA_ANTHROPIC_KEY', None)
            os.environ.pop('FILEZ4EVA_TRANSCRIBE_MODEL', None)
            self.run_app(self.file, config_text=config, debug=True)
        t.assert_called_once_with(self.document, model='claude-from-file',
                                  api_key='sk-from-op')
        op.assert_called_once()
        self.assertEqual(op.call_args.args[0],
                         ['op', 'read', 'op://vault/anthropic/credential'])

    def test_command_substitution_in_config_is_literal(self):
        config = "filez4eva:\n  anthropic:\n    key: $(echo sk-cmd)\n"
        with patch.dict(os.environ), \
                patch(OP_RUN) as run, \
                patch(TRANSCRIBE, return_value='x') as t:
            os.environ.pop('FILEZ4EVA_ANTHROPIC_KEY', None)
            self.run_app(self.file, config_text=config, debug=True)
        self.assertEqual(t.call_args.kwargs['api_key'], '$(echo sk-cmd)')
        run.assert_not_called()

    def test_op_reference_in_environment_is_not_resolved(self):
        ref = 'op://vault/anthropic/credential'
        with patch.dict(os.environ, {'FILEZ4EVA_ANTHROPIC_KEY': ref}), \
                patch(OP_RUN) as run, \
                patch(TRANSCRIBE, return_value='x') as t:
            self.run_app(self.file, config_text="filez4eva:\n  target: /tmp\n",
                         debug=True)
        self.assertEqual(t.call_args.kwargs['api_key'], ref)
        run.assert_not_called()

    def test_op_failure_is_config_error(self):
        config = ("filez4eva:\n  anthropic:\n"
                  "    key: op://vault/anthropic/credential\n")
        failed = CompletedProcess([], returncode=1, stdout='',
                                  stderr='not signed in')
        with patch.dict(os.environ), \
                patch(OP_RUN, return_value=failed), \
                patch(TRANSCRIBE, return_value='x') as t, \
                self.assertRaises(ConfigHandlerError) as raised:
            os.environ.pop('FILEZ4EVA_ANTHROPIC_KEY', None)
            self.run_app(self.file, config_text=config, debug=True)
        self.assertIn('not signed in', str(raised.exception))
        self.assertIn('anthropic', str(raised.exception))
        t.assert_not_called()
        self.assertFalse(Path(f'{self.document}.md').exists())

    def test_key_from_environment(self):
        with patch.dict(os.environ,
                        {'FILEZ4EVA_ANTHROPIC_KEY': 'sk-env'}), \
                patch(TRANSCRIBE, return_value='x') as t:
            self.run_app(self.file, debug=True, config_text=(
                "filez4eva:\n  anthropic:\n    key: sk-file\n"))
        self.assertEqual(t.call_args.kwargs['api_key'], 'sk-env')

    def test_key_unset_from_app(self):
        with patch.dict(os.environ), \
                patch(TRANSCRIBE, return_value='x') as t:
            os.environ.pop('FILEZ4EVA_ANTHROPIC_KEY', None)
            self.run_app(self.file, config_text="filez4eva:\n  target: /tmp\n",
                         debug=True)
        self.assertIsNone(t.call_args.kwargs['api_key'])
        self.assertEqual(t.call_args.kwargs['model'], DEFAULT_MODEL)

    def test_intake_from_config_file(self):
        other = self.intake.parent / 'other'
        with patch.dict(os.environ), patch(TRANSCRIBE, return_value='x'):
            os.environ.pop('FILEZ4EVA_INTAKE', None)
            out, _, code = self.run_app(
                self.file, config_text=f"filez4eva:\n  intake: {other}\n")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), str(other / f'{STAMP}.pdf.md'))
