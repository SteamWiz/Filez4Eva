from datetime import datetime, timedelta, timezone
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
    CONTEXT_NOTE, DEFAULT_MODEL, ClassifyCommand, build_schema,
    document_text, load_doctypes, transcript_body)
from filez4eva.command.ingest_command import read_sidecar, write_sidecar
from filez4eva.command.transcribe_command import format_transcript
from filez4eva.error import Filez4EvaError
from filez4eva.fields import values_path
from filez4eva.stow import Cabinet


EXTRACT = 'filez4eva.command.classify_command.extract'
TRANSCRIBE = 'filez4eva.command.transcribe_command.transcribe'
NOW = 'filez4eva.command.ingest_command.now'
TTYIN = 'wizlib.io.ttyin'

# A fixed local time with an offset, so names and `at` are predictable
CLOCK = datetime(2026, 10, 25, 14, 3, 7, 42000,
                 tzinfo=timezone(timedelta(hours=-7)))
AT = '2026-10-25T14:03:07-07:00'
STAMP = '20261025-140307-042'

PATTERN = '{date.year}/{account}/{date}-{part}'

DATA = {'date': '20261002', 'account': 'amazon', 'part': 'receipt'}

RESULT = {'data': DATA, 'doctype': 'receipt',
          'summary': 'Amazon.ca order receipt for a USB hub'}

DOCTYPES = {'receipt': {'description': 'Proof of purchase or payment'},
            'bill': {'description':
                     'A request for payment, usually with a due date'}}

MEMORY = {'data': {'date': '20261002', 'event': 'Grandma Bday'},
          'doctype': 'other', 'summary': 'Photo'}


def result(**data):
    """RESULT with some data values replaced ('DROP' removes one)"""
    values = {k: v for k, v in dict(DATA, **data).items() if v != 'DROP'}
    return dict(RESULT, data=values)


def write_store(target, store):
    path = values_path(Path(target))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(store))


def no_prompt(*args, **kwargs):
    raise AssertionError('classify prompted')


class ClassifyTestCase(WizLibTestCase):
    """A temporary intake (also set in FILEZ4EVA_INTAKE, so nothing ever
    touches the real one), a source directory, a cabinet target with
    learned values, and a frozen clock. Any prompt fails the test."""

    def setUp(self):
        super().setUp()
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.intake = self.dir / 'intake'
        self.source = self.dir / 'in'
        self.source.mkdir()
        self.target = self.dir / 'target'
        write_store(self.target, {
            'account': {'amazon': {'count': 3}, 'bank': {'count': 2},
                        'once': {'count': 1}},
            'part': {'receipt': {'count': 2}, 'refund': {'count': 4},
                     'statement': {'count': 1}}})
        self.memories = self.dir / 'memories'
        write_store(self.memories, {'event': {'grandma-bday': {'count': 2}}})
        for patcher in [patch(NOW, return_value=CLOCK),
                        patch(TTYIN, side_effect=no_prompt),
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

    def make_document(self, name=f'{STAMP}.pdf', results=None,
                      transcript='# Hi'):
        """Create an ingested document in the intake, with its sidecar, and
        (unless transcript is None) its transcript and results.transcribe"""
        path = self.make(name, where=self.intake)
        if results is None:
            results = {'ingest': {'at': AT, 'original-name': 'Scan 1.PDF',
                                  'source': {'scanner': 'brother'}}}
            if transcript is not None:
                results['transcribe'] = {
                    'at': AT, 'model': 'm', 'transcript': f'{name}.md',
                    'length': len(transcript)}
        if transcript is not None:
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            Path(f'{path}.md').write_text(format_transcript(
                name, sha, 'm', AT, transcript))
        write_sidecar(path, {'results': results})
        return path

    def config(self, **extra):
        values = {'filez4eva_intake': str(self.intake),
                  'filez4eva_target': str(self.target),
                  'filez4eva_pattern': PATTERN,
                  'filez4eva_doctypes': DOCTYPES}
        values.update(extra)
        return values

    def two_cabinets(self, **extra):
        return self.config(filez4eva_cabinets={
            'accounts': {'target': str(self.target), 'pattern': PATTERN,
                         'description': 'Personal account records'},
            'memories': {'target': str(self.memories),
                         'pattern': '{event}/{date}',
                         'description': 'Family photos'}}, **extra)

    def run_command(self, path=None, config=None, result=RESULT,
                    markdown='# Hi', extract=None, answers=None, **vals):
        """Run the command directly with fake config; return (output,
        command, stderr, extract mock, transcribe mock). answers are the
        answers to text prompts (or a function standing in for get_text);
        without them, any prompt fails the test."""
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(**(config or self.config()))
        command = ClassifyCommand(
            app, path=None if path is None else str(path), **vals)
        effect = {'side_effect': extract} if extract \
            else {'return_value': result}
        if answers is None:
            ask = no_prompt
        elif callable(answers):
            ask = answers
        else:
            answers = iter(answers)

            def ask(*args):
                return next(answers)
        with patch(EXTRACT, **effect) as e, \
                patch(TRANSCRIBE, return_value=markdown) as t, \
                patch.object(app.ui, 'get_text', side_effect=ask), \
                self.patchout(), self.patcherr() as err:
            try:
                out = command.execute()
            finally:
                err.seek(0)
                self.err = err.read()
            return out, command, self.err, e, t

    def run_app(self, config_text, *args, result=RESULT, extract=None,
                transcribe=None):
        """Run classify via the app; return (stdout, stderr, exit code,
        extract mock)"""
        code = 0
        effect = {'side_effect': extract} if extract \
            else {'return_value': result}
        teffect = {'side_effect': transcribe} if transcribe \
            else {'return_value': '# Hi'}
        with patch(EXTRACT, **effect) as x, \
                patch(TRANSCRIBE, **teffect), \
                self.patchout() as o, self.patcherr() as e, \
                self.patch_stream(''), \
                NamedTemporaryFile('w+', suffix='.yml') as cf:
            cf.write(config_text)
            cf.flush()
            try:
                Filez4EvaApp.start('--config', cf.name, 'classify',
                                   *[str(a) for a in args])
            except SystemExit as exit:
                code = exit.code
            o.seek(0)
            e.seek(0)
            return o.read(), e.read(), code, x

    def config_text(self):
        return (f"filez4eva:\n  intake: {self.intake}\n"
                f"  target: {self.target}\n"
                f"  pattern: '{PATTERN}'\n"
                "  doctypes:\n    receipt:\n      description: Proof\n")

    def classified(self, document):
        return read_sidecar(document)['results'].get('classify')

    def intake_names(self):
        return sorted(p.name for p in self.intake.iterdir())


class TestClassifySelection(ClassifyTestCase):
    """AC 1: a file, a directory (top level only) or the intake"""

    def test_file_outside_intake(self):
        source = self.make('Scan 1.PDF')
        out, command, _, e, t = self.run_command(source)
        document = self.intake / f'{STAMP}.pdf'
        self.assertFalse(source.exists())
        t.assert_called_once()
        e.assert_called_once()
        self.assertEqual(out, str(document))
        self.assertEqual(self.intake_names(), [
            f'{STAMP}.pdf', f'{STAMP}.pdf.md', f'{STAMP}.pdf.yml'])

    def test_directory_top_level_only(self):
        self.make('b.pdf')
        self.make('a.png')
        self.make('.hidden')
        self.make('inner.pdf', where=self.source / 'sub')
        (self.source / 'link.pdf').symlink_to(self.source / 'b.pdf')
        out, command, _, e, _ = self.run_command(self.source)
        first = self.intake / f'{STAMP}.png'
        second = self.intake / '20261025-140307-043.pdf'
        self.assertEqual(out.splitlines(), [str(first), str(second)])
        self.assertEqual(e.call_count, 2)
        self.assertEqual(sorted(p.name for p in self.source.iterdir()),
                         ['.hidden', 'link.pdf', 'sub'])
        self.assertTrue((self.source / 'sub' / 'inner.pdf').is_file())

    def test_no_path_is_the_intake(self):
        document = self.make_document()
        self.make('old.pdf', where=self.intake / 'archive')
        out, command, _, e, t = self.run_command()
        t.assert_not_called()
        e.assert_called_once()
        self.assertEqual(out, str(document))
        self.assertEqual(command.status, 'Classified 1 file')
        self.assertEqual(sorted(p.name for p in
                                (self.intake / 'archive').iterdir()),
                         ['old.pdf'])

    def test_document_in_intake_given_as_file_is_an_error(self):
        document = self.make_document()
        out, err, code, e = self.run_app(self.config_text(), document)
        self.assertEqual(code, 1)
        self.assertIn('is in the intake', err)
        self.assertIn('--ingested', err)
        e.assert_not_called()
        self.assertIsNone(self.classified(document))

    def test_intake_subdirectory_is_refused(self):
        old = self.make('old.pdf', where=self.intake / 'archive')
        with patch(TRANSCRIBE) as t, \
                self.assertRaisesRegex(Filez4EvaError, 'in the intake'):
            self.run_command(old.parent)
        t.assert_not_called()

    def test_companion_given_as_file_is_error(self):
        document = self.make_document()
        with self.assertRaisesRegex(Filez4EvaError, 'in the intake'):
            self.run_command(Path(f'{document}.md'))
        with self.assertRaisesRegex(Filez4EvaError,
                                    'not a document ingested'):
            self.run_command(ingested=[f'{document.name}.md'])

    def test_ingested_two_documents(self):
        first = self.make_document()
        second = self.make_document('20261025-140307-043.pdf',
                                    transcript=None)
        other = self.make_document('20261025-140307-044.pdf',
                                   transcript=None)
        out, command, _, e, t = self.run_command(
            ingested=[second.name, first.name])
        self.assertEqual(out.splitlines(), [str(second), str(first)])
        t.assert_called_once()
        self.assertEqual(t.call_args.args[0], second)
        self.assertEqual(e.call_count, 2)
        self.assertEqual(command.status,
                         'Transcribed 1 file | Classified 2 files')
        self.assertEqual(list(read_sidecar(other)['results']), ['ingest'])

    def test_ingested_with_path_is_an_error(self):
        document = self.make_document()
        source = self.make('a.pdf')
        with self.assertRaisesRegex(Filez4EvaError, "can't be combined"):
            self.run_command(source, ingested=[document.name])
        self.assertTrue(source.exists())
        self.assertIsNone(self.classified(document))

    def test_path_run_leaves_intake_documents_alone(self):
        document = self.make_document(transcript=None)
        self.make('a.pdf')
        out, command, _, e, t = self.run_command(self.source)
        new = self.intake / '20261025-140307-043.pdf'
        self.assertEqual(out, str(new))
        t.assert_called_once()
        self.assertEqual(t.call_args.args[0], new)
        e.assert_called_once()
        self.assertEqual(list(read_sidecar(document)['results']), ['ingest'])

    def test_missing_path(self):
        with self.assertRaisesRegex(Filez4EvaError, 'must exist'):
            self.run_command(self.source / 'missing.pdf')

    def test_empty_directory(self):
        out, command, _, _, _ = self.run_command(self.source)
        self.assertEqual(out, '')
        self.assertEqual(command.status,
                         f'Nothing to classify: no files in {self.source}')


class TestClassifyPrerequisites(ClassifyTestCase):
    """AC 2: ingest and transcribe first, never prompt"""

    def test_ingests_and_transcribes_first(self):
        source = self.make('Scan 1.PDF')
        _, command, _, e, t = self.run_command(source)
        document = self.intake / f'{STAMP}.pdf'
        t.assert_called_once()
        self.assertEqual(t.call_args.args[0], document)
        results = read_sidecar(document)['results']
        self.assertEqual(list(results),
                         ['ingest', 'transcribe', 'given', 'classify'])
        self.assertEqual(results['transcribe']['transcript'],
                         f'{STAMP}.pdf.md')
        self.assertIn('# Hi', e.call_args.args[0])
        self.assertEqual(
            command.status,
            'Ingested 1 file | Transcribed 1 file | Classified 1 file')

    def test_ingested_but_not_transcribed(self):
        document = self.make_document(transcript=None)
        _, command, _, e, t = self.run_command(markdown='Fresh text')
        t.assert_called_once()
        results = read_sidecar(document)['results']
        self.assertIn('transcribe', results)
        self.assertIn('Fresh text', e.call_args.args[0])
        self.assertEqual(command.status,
                         'Transcribed 1 file | Classified 1 file')

    def test_never_prompts_with_cabinet_flag(self):
        # TTYIN raises if anything is asked
        self.make('scan.pdf')
        out, command, _, _, _ = self.run_command(
            self.source, config=self.two_cabinets(), cabinet='memories',
            result=MEMORY)
        self.assertEqual(command.status, 'Ingested 1 file | Transcribed 1 '
                         'file | Classified 1 file')

    def test_transcript_is_x_md(self):
        document = self.make_document(transcript='Default name')
        data = read_sidecar(document)
        del data['results']['transcribe']['transcript']
        write_sidecar(document, data)
        _, _, _, e, _ = self.run_command()
        self.assertIn('Default name', e.call_args.args[0])

    def test_other_recorded_transcript_is_a_failure(self):
        document = self.make_document(transcript='Default name')
        # Hidden, so it isn't a document of its own
        other = self.intake / '.alt.md'
        other.write_text('Recorded name')
        data = read_sidecar(document)
        data['results']['transcribe']['transcript'] = other.name
        write_sidecar(document, data)
        with patch(EXTRACT) as e, \
                self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
            app = Filez4EvaApp()
            app.config = ConfigHandler.fake(**self.config())
            with self.patchout(), self.patcherr() as err:
                try:
                    ClassifyCommand(app).execute()
                finally:
                    err.seek(0)
                    self.assertIn("names transcript '.alt.md'", err.read())
        e.assert_not_called()
        self.assertNotIn('classify', read_sidecar(document)['results'])

    def test_transcription_failure_is_reported(self):
        source = self.make('scan.pdf')
        with patch(EXTRACT) as e, \
                patch(TRANSCRIBE, side_effect=APIError('nope')), \
                self.patchout(), self.patcherr() as err, \
                self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
            app = Filez4EvaApp()
            app.config = ConfigHandler.fake(**self.config())
            ClassifyCommand(app, path=str(source)).execute()
        e.assert_not_called()
        err.seek(0)
        self.assertIn('Transcription failed: nope', err.read())
        document = self.intake / f'{STAMP}.pdf'
        self.assertEqual(list(read_sidecar(document)['results']),
                         ['ingest'])

    def test_empty_transcript_is_a_failure(self):
        self.make_document(transcript='')
        with self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
            self.run_command()

    def test_unreadable_transcript_is_a_failure(self):
        document = self.make_document()
        Path(f'{document}.md').unlink()
        with patch(EXTRACT) as e, \
                self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
            app = Filez4EvaApp()
            app.config = ConfigHandler.fake(**self.config())
            with self.patchout(), self.patcherr() as err:
                try:
                    ClassifyCommand(app).execute()
                finally:
                    err.seek(0)
                    self.assertIn('Could not read transcript', err.read())
        e.assert_not_called()

    def test_transcript_body(self):
        text = format_transcript('a.pdf', 'abc', 'm', 't', '# Title\n\nBody')
        self.assertEqual(transcript_body(text), '# Title\n\nBody')
        self.assertEqual(
            transcript_body(f'<!-- {TRANSCRIBE_DISCLAIMER} -->\n\nx'), 'x')


class TestClassifyResult(ClassifyTestCase):
    """AC 3: results.classify in X.yml"""

    def test_saved_result(self):
        document = self.make_document()
        before = read_sidecar(document)['results']
        self.run_command()
        results = read_sidecar(document)['results']
        self.assertEqual(results['ingest'], before['ingest'])
        self.assertEqual(results['transcribe'], before['transcribe'])
        self.assertEqual(results['given'], {'at': AT, 'cabinet': 'default'})
        classify = results['classify']
        self.assertEqual(list(classify), [
            'at', 'model', 'doctype', 'summary', 'data'])
        self.assertEqual(classify, {
            'at': AT, 'model': DEFAULT_MODEL,
            'doctype': 'receipt',
            'summary': 'Amazon.ca order receipt for a USB hub',
            'data': DATA})
        self.assertEqual(list(classify['data']), ['date', 'account', 'part'])
        self.assertIn("    date: '20261002'",
                      Path(f'{document}.yml').read_text())

    def test_configured_model_recorded(self):
        document = self.make_document()
        _, _, _, e, _ = self.run_command(
            config=self.config(filez4eva_classify_model='claude-c',
                               filez4eva_anthropic_key='sk-test'))
        self.assertEqual(self.classified(document)['model'], 'claude-c')
        self.assertEqual(e.call_args.kwargs['model'], 'claude-c')
        self.assertEqual(e.call_args.kwargs['api_key'], 'sk-test')

    def test_transcribe_model_used_for_transcription(self):
        self.make('scan.pdf')
        _, _, _, e, t = self.run_command(
            self.source, config=self.config(
                filez4eva_transcribe_model='claude-t',
                filez4eva_classify_model='claude-c'))
        self.assertEqual(t.call_args.kwargs['model'], 'claude-t')
        self.assertEqual(e.call_args.kwargs['model'], 'claude-c')

    def test_values_normalized(self):
        document = self.make_document()
        self.run_command(result=result(account='Royal Bank of Canada',
                                       part='Visa  Stmt'))
        data = self.classified(document)['data']
        self.assertEqual(data['account'], 'royal-bank-of-canada')
        self.assertEqual(data['part'], 'visa-stmt')

    def test_summary_one_line(self):
        document = self.make_document()
        self.run_command(result=dict(
            RESULT, summary='  A long\nsummary\n\nhere ', doctype='other'))
        self.assertEqual(self.classified(document)['summary'],
                         'A long summary here')

    def test_default_fields(self):
        document = self.make_document()
        _, _, _, e, _ = self.run_command(
            config={'filez4eva_intake': str(self.intake),
                    'filez4eva_target': str(self.dir / 'new')},
            result={'data': {'date': '', 'title': 'USB Hub Receipt'},
                    'doctype': 'other', 'summary': 'x'})
        self.assertEqual(self.classified(document)['data'],
                         {'date': None, 'title': 'usb-hub-receipt'})
        text = e.call_args.kwargs['instructions']
        self.assertIn('"default"', text)
        self.assertNotIn('Existing values', text)

    def test_no_date_gives_null(self):
        for value in [result(date='<UNKNOWN>'), result(date=''),
                      result(date=None), result(date='DROP'),
                      result(date='2026-10-02'), result(date='20261302'),
                      result(date=20261002)]:
            with self.subTest(result=value):
                document = self.make_document()
                self.run_command(result=value)
                data = self.classified(document)['data']
                self.assertIsNone(data['date'])
                self.assertEqual(list(data), ['date', 'account', 'part'])
                self.assertIn('    date: null\n',
                              Path(f'{document}.yml').read_text())

    def test_date_padded_with_spaces(self):
        document = self.make_document()
        self.run_command(result=result(date=' 20261002 '))
        self.assertEqual(self.classified(document)['data']['date'],
                         '20261002')

    def test_extra_data_ignored(self):
        document = self.make_document()
        self.run_command(result=result(extra='x'))
        self.assertNotIn('extra', self.classified(document)['data'])

    def test_field_names_cannot_clash_with_result_keys(self):
        document = self.make_document()
        self.run_command(
            config=self.config(filez4eva_pattern='{date}-{summary}-{doctype}'),
            result={'data': {'date': '20261002', 'summary': 'short',
                             'doctype': 'x'},
                    'doctype': 'receipt', 'summary': 'Long summary'})
        classify = self.classified(document)
        self.assertEqual(classify['summary'], 'Long summary')
        self.assertEqual(classify['data']['summary'], 'short')

    def test_invalid_results_are_failures(self):
        bad = [(None, "result isn't a mapping"),
               (dict(RESULT, data=None), 'no data in result'),
               (result(account='../'),
                'Account must contain letters or digits'),
               (result(account=''), 'no account in result'),
               (result(part='DROP'), 'no part in result'),
               (dict(RESULT, doctype='bill'), "unknown doctype 'bill'"),
               (dict(RESULT, summary=''), 'no summary in result')]
        for value, message in bad:
            with self.subTest(result=value):
                document = self.make_document()
                out, err, code, _ = self.run_app(
                    self.config_text().replace(
                        '      description: Proof\n', ''), result=value)
                self.assertEqual(code, 1)
                self.assertIn(f'Classification failed: {message}', err)
                self.assertIsNone(self.classified(document))

    def test_kwark_error_is_a_failure(self):
        document = self.make_document()
        out, err, code, _ = self.run_app(self.config_text(),
                                         extract=APIError('boom'))
        self.assertEqual(code, 1)
        self.assertIn(f'Failed to classify {document}: Classification '
                      'failed: boom', err)


class TestClassifierInput(ClassifyTestCase):
    """AC 4: original name and source go with the transcript"""

    def test_original_name_and_source_passed(self):
        self.make_document(transcript='Body text')
        _, _, _, e, _ = self.run_command()
        text = e.call_args.args[0]
        self.assertIn('Original file name: Scan 1.PDF', text)
        self.assertIn('Source:\n  scanner: brother', text)
        self.assertTrue(text.endswith('Transcript:\n\nBody text'))
        self.assertIn(CONTEXT_NOTE, e.call_args.kwargs['instructions'])

    def test_name_and_source_from_ingest(self):
        source = self.make('My Receipt.PDF')
        _, _, _, e, _ = self.run_command(source)
        text = e.call_args.args[0]
        self.assertIn('Original file name: My Receipt.PDF', text)
        self.assertIn('Source: (none recorded)', text)

    def test_document_text_without_ingest(self):
        self.assertEqual(document_text('x', None),
                         'Original file name: (none)\n'
                         'Source: (none recorded)\n\nTranscript:\n\nx')


class TestClassifyAlreadyDone(ClassifyTestCase):
    """AC 5: no re-classifying"""

    def test_already_classified_is_skipped(self):
        document = self.make_document()
        data = read_sidecar(document)
        data['results']['classify'] = {'at': AT}
        write_sidecar(document, data)
        before = Path(f'{document}.yml').read_text()
        out, command, _, e, t = self.run_command()
        e.assert_not_called()
        t.assert_not_called()
        self.assertEqual(out, '')
        self.assertEqual(command.status,
                         'Nothing to classify (1 file already classified)')
        self.assertEqual(Path(f'{document}.yml').read_text(), before)

    def test_already_classified_counted_with_others(self):
        self.make_document(results={'ingest': {}, 'classify': {}},
                           transcript=None)
        self.make_document('20261025-140307-099.pdf')
        _, command, _, e, t = self.run_command()
        e.assert_called_once()
        t.assert_not_called()
        self.assertEqual(command.status,
                         'Classified 1 file | Already classified 1 file')

    def test_force_is_not_an_option(self):
        source = self.make('a.pdf')
        out, err, code, e = self.run_app(self.config_text(), '--force',
                                         source)
        self.assertEqual(code, 1)
        self.assertRegex(err, 'unrecognized arguments: .*--force')
        e.assert_not_called()
        self.assertTrue(source.exists())


class TestClassifyOnly(ClassifyTestCase):
    """AC 6: --only"""

    def test_only_skips_files_not_ingested(self):
        source = self.make('a.pdf')
        out, command, err, e, t = self.run_command(self.source, only=True)
        e.assert_not_called()
        t.assert_not_called()
        self.assertTrue(source.exists())
        self.assertEqual(out, '')
        self.assertIn(f'Skipped {source}: not ingested yet', err)
        self.assertEqual(command.status, 'Skipped 1 file (not ingested)')

    def test_only_skips_documents_not_transcribed(self):
        document = self.make_document(transcript=None)
        out, command, err, e, t = self.run_command(only=True)
        e.assert_not_called()
        t.assert_not_called()
        self.assertEqual(out, '')
        self.assertIn(f'Skipped {document}: not transcribed yet', err)
        self.assertEqual(command.status, 'Skipped 1 file (not transcribed)')
        self.assertEqual(list(read_sidecar(document)['results']),
                         ['ingest'])

    def test_only_classifies_transcribed_documents(self):
        done = self.make_document()
        self.make_document('20261025-140307-099.pdf', transcript=None)
        stray = self.make('stray.pdf', where=self.intake)
        out, command, _, e, t = self.run_command(only=True)
        t.assert_not_called()
        e.assert_called_once()
        self.assertEqual(out, str(done))
        self.assertTrue(stray.exists())
        self.assertEqual(command.status,
                         'Classified 1 file | Skipped 1 file (not '
                         'transcribed)')

    def test_only_from_app(self):
        self.make_document(transcript=None)
        out, err, code, e = self.run_app(self.config_text(), '--only')
        e.assert_not_called()
        self.assertEqual(code, 0)
        self.assertEqual(out, '')
        self.assertIn('Skipped 1 file (not transcribed)', err)


class TestClassifyFailures(ClassifyTestCase):
    """AC 7: report, carry on, exit non-zero"""

    def test_failure_is_reported_and_run_carries_on(self):
        self.make('a.pdf')
        self.make('b.pdf', 'bad')
        self.make('c.pdf')
        calls = []

        def fake(text, schema, **kwargs):
            calls.append(text)
            if len(calls) == 2:
                raise APIError('boom')
            return RESULT
        out, err, code, e = self.run_app(self.config_text(), self.source,
                                         extract=fake)
        self.assertEqual(e.call_count, 3)
        self.assertEqual(code, 1)
        failed = self.intake / '20261025-140307-043.pdf'
        self.assertIn(f"Failed to classify {self.source / 'b.pdf'} "
                      f"(now {failed}): Classification failed: boom", err)
        self.assertIn('1 of 3 files failed to classify', err)
        self.assertEqual(out.splitlines(), [
            str(self.intake / f'{STAMP}.pdf'),
            str(self.intake / '20261025-140307-044.pdf')])
        self.assertIsNone(self.classified(failed))
        self.assertIn('transcribe', read_sidecar(failed)['results'])

    def test_failed_document_is_classified_on_next_run(self):
        self.make_document()
        with self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
            self.run_command(extract=APIError('boom'))
        _, command, _, _, _ = self.run_command()
        self.assertEqual(command.status, 'Classified 1 file')

    def test_single_file_failure_exits_non_zero(self):
        source = self.make('scan.pdf')
        out, err, code, _ = self.run_app(self.config_text(), source,
                                         transcribe=APIError('nope'))
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertIn('Transcription failed: nope', err)

    def test_bad_sidecar_is_a_failure_and_left_alone(self):
        document = self.make_document()
        sidecar = Path(f'{document}.yml')
        sidecar.write_text('- a list')
        with patch(EXTRACT) as e, \
                self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
            app = Filez4EvaApp()
            app.config = ConfigHandler.fake(**self.config())
            with self.patchout(), self.patcherr():
                ClassifyCommand(app).execute()
        e.assert_not_called()
        self.assertEqual(sidecar.read_text(), '- a list')


class TestClassifyUseCase(ClassifyTestCase):
    """AC 8: classify a folder of scans, then walk away"""

    def test_folder_of_scans(self):
        for name in ['Scan 1.pdf', 'Scan 2.PDF', 'photo.jpg']:
            self.make(name)
        config = (f"filez4eva:\n  intake: {self.intake}\n"
                  f"  cabinets:\n"
                  f"    accounts:\n"
                  f"      target: {self.target}\n"
                  f"      pattern: '{PATTERN}'\n"
                  f"    memories:\n"
                  f"      target: {self.memories}\n"
                  f"      pattern: '{{event}}/{{date}}'\n"
                  f"      description: Family photos\n")
        out, err, code, _ = self.run_app(
            config, '-c', 'memories', self.source, result=MEMORY)
        self.assertEqual(code, 0)
        self.assertEqual(list(self.source.iterdir()), [])
        documents = [self.intake / f'{STAMP}.pdf',
                     self.intake / '20261025-140307-043.pdf',
                     self.intake / '20261025-140307-044.jpg']
        self.assertEqual(out.splitlines(), [str(d) for d in documents])
        names = []
        for document in documents:
            names += [document.name, f'{document.name}.md',
                      f'{document.name}.yml']
            results = read_sidecar(document)['results']
            self.assertEqual(list(results),
                             ['ingest', 'transcribe', 'given', 'classify'])
            self.assertEqual(results['given']['cabinet'], 'memories')
        self.assertEqual(self.intake_names(), sorted(names))
        self.assertEqual(err, 'Ingested 3 files | Transcribed 3 files | '
                         'Classified 3 files\n')


class TestClassifyCabinets(ClassifyTestCase):
    """AC 11, #72: the cabinet is chosen before classify, never by the
    model"""

    def test_cabinet_flag_applies_to_every_file(self):
        first = self.make_document()
        second = self.make_document('20261025-140307-099.pdf')
        _, _, _, e, _ = self.run_command(config=self.two_cabinets(),
                                         cabinet='memories', result=MEMORY)
        self.assertEqual(e.call_count, 2)
        for call in e.call_args_list:
            self.assertNotIn('cabinet', call.args[1]['properties'])
            text = call.kwargs['instructions']
            self.assertIn('Family photos', text)
            self.assertIn('grandma-bday', text)
            self.assertNotIn('amazon', text)
        for document in [first, second]:
            results = read_sidecar(document)['results']
            self.assertEqual(results['given'],
                             {'at': AT, 'cabinet': 'memories'})
            self.assertNotIn('cabinet', results['classify'])
            self.assertEqual(results['classify']['data'],
                             {'event': 'grandma-bday', 'date': '20261002'})

    def test_model_is_never_asked_for_a_cabinet(self):
        document = self.make_document(transcript='A birthday photo')
        _, _, _, e, _ = self.run_command(
            config=self.two_cabinets(), answers=['memories'], result=MEMORY)
        # One call, for that cabinet's fields, with its existing values
        e.assert_called_once()
        schema = e.call_args.args[1]
        self.assertEqual(set(schema['properties']),
                         {'data', 'doctype', 'summary'})
        self.assertEqual(list(schema['properties']['data']['properties']),
                         ['event', 'date'])
        self.assertIn('A birthday photo', e.call_args.args[0])
        text = e.call_args.kwargs['instructions']
        self.assertIn('"memories": Family photos', text)
        self.assertIn('grandma-bday', text)
        self.assertNotIn('Personal account records', text)
        self.assertNotIn('cabinet', self.classified(document))

    def test_unknown_cabinet_fails_before_any_file_is_touched(self):
        source = self.make('scan.pdf')
        with patch(TRANSCRIBE) as t, patch(EXTRACT) as e, \
                self.assertRaisesRegex(Filez4EvaError,
                                       'Unknown cabinet nope; known: '
                                       'accounts, memories'):
            app = Filez4EvaApp()
            app.config = ConfigHandler.fake(**self.two_cabinets())
            ClassifyCommand(app, path=str(source), cabinet='nope').execute()
        t.assert_not_called()
        e.assert_not_called()
        self.assertTrue(source.exists())
        self.assertFalse(self.intake.exists() and self.intake_names())

    def test_unknown_cabinet_from_app(self):
        source = self.make('scan.pdf')
        out, err, code, e = self.run_app(self.config_text(), '-c', 'nope',
                                         source)
        self.assertEqual(code, 1)
        self.assertIn('Unknown cabinet nope', err)
        e.assert_not_called()
        self.assertTrue(source.exists())

    def test_unknown_cabinet_touches_no_intake_document(self):
        document = self.make_document()
        before = Path(f'{document}.yml').read_text()
        with patch(EXTRACT) as e, \
                self.assertRaisesRegex(Filez4EvaError, 'Unknown cabinet'):
            self.run_command(config=self.two_cabinets(), cabinet='nope')
        e.assert_not_called()
        self.assertEqual(Path(f'{document}.yml').read_text(), before)

    def test_only_cabinet_is_used(self):
        # No prompt (TTYIN raises if anything is asked)
        document = self.make_document()
        config = self.config(filez4eva_cabinets={
            'accounts': {'target': str(self.target), 'pattern': PATTERN}})
        _, _, _, e, _ = self.run_command(config=config)
        e.assert_called_once()
        self.assertNotIn('cabinet', e.call_args.args[1]['properties'])
        self.assertEqual(read_sidecar(document)['results']['given'],
                         {'at': AT, 'cabinet': 'accounts'})

    def test_one_prompt_per_document_before_its_classification(self):
        self.make('a.pdf')
        self.make('b.pdf')
        events = []
        answers = iter(['memories', 'accounts'])

        def ask(prompt, choices=(), *default):
            events.append(('prompt', prompt, list(choices)))
            return next(answers)

        def fake(text, schema, **kwargs):
            fields = list(schema['properties']['data']['properties'])
            events.append(('model', fields))
            return MEMORY if 'event' in fields else RESULT
        out, command, err, e, t = self.run_command(
            self.source, config=self.two_cabinets(), extract=fake,
            answers=ask)
        names = ['accounts', 'memories']
        self.assertEqual(events, [
            ('prompt', 'Cabinet: ', names), ('model', ['event', 'date']),
            ('prompt', 'Cabinet: ', names),
            ('model', ['date', 'account', 'part'])])
        first = self.intake / f'{STAMP}.pdf'
        second = self.intake / '20261025-140307-043.pdf'
        # Each prompt names its document
        self.assertIn(f'{first.name} (a.pdf)', err)
        self.assertIn(f'{second.name} (b.pdf)', err)
        self.assertEqual(read_sidecar(first)['results']['given']['cabinet'],
                         'memories')
        self.assertEqual(read_sidecar(second)['results']['given']['cabinet'],
                         'accounts')
        self.assertEqual(command.status, 'Ingested 2 files | Transcribed 2 '
                         'files | Classified 2 files')

    def test_prompt_rejects_an_unknown_name(self):
        document = self.make_document()
        _, _, err, e, _ = self.run_command(
            config=self.two_cabinets(), answers=['nope', ' accounts '])
        self.assertIn('Cabinet must be one of: accounts, memories', err)
        e.assert_called_once()
        self.assertEqual(read_sidecar(document)['results']['given'],
                         {'at': AT, 'cabinet': 'accounts'})

    def test_empty_answer_skips_the_document_and_a_later_run_asks(self):
        first = self.make_document()
        second = self.make_document('20261025-140307-099.pdf')
        before = Path(f'{first}.yml').read_text()
        out, command, _, e, _ = self.run_command(
            config=self.two_cabinets(), answers=['', 'accounts'])
        e.assert_called_once()
        self.assertEqual(out, str(second))
        self.assertEqual(command.status,
                         'Classified 1 file | Skipped 1 file')
        # Nothing written for the skipped document
        self.assertEqual(Path(f'{first}.yml').read_text(), before)
        out, command, _, e, _ = self.run_command(
            config=self.two_cabinets(), answers=['accounts'])
        e.assert_called_once()
        self.assertEqual(out, str(first))
        self.assertEqual(command.status,
                         'Classified 1 file | Already classified 1 file')

    def test_saved_cabinet_is_used_without_asking(self):
        # Saved by an earlier run that failed to classify
        document = self.make_document()
        with self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
            self.run_command(config=self.two_cabinets(),
                             answers=['memories'], extract=APIError('boom'))
        self.assertEqual(read_sidecar(document)['results']['given'],
                         {'at': AT, 'cabinet': 'memories'})
        # TTYIN raises if anything is asked
        _, command, _, e, _ = self.run_command(config=self.two_cabinets(),
                                               result=MEMORY)
        self.assertEqual(list(e.call_args.args[1]['properties']['data']
                              ['properties']), ['event', 'date'])
        self.assertEqual(command.status, 'Classified 1 file')

    def test_saved_cabinet_wins_over_the_only_one(self):
        document = self.make_document()
        data = read_sidecar(document)
        data['results']['given'] = {'at': AT, 'cabinet': 'memories'}
        write_sidecar(document, data)
        with self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
            self.run_command()
        self.assertIn('Unknown cabinet memories', self.err)
        self.assertIsNone(self.classified(document))

    def test_saved_cabinet_no_longer_configured_is_a_failure(self):
        document = self.make_document()
        data = read_sidecar(document)
        data['results']['given'] = {'at': AT, 'cabinet': 'gone'}
        write_sidecar(document, data)
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(**self.two_cabinets())
        with patch(EXTRACT) as e, self.patchout(), \
                self.patcherr() as err, \
                self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
            ClassifyCommand(app).execute()
        e.assert_not_called()
        err.seek(0)
        self.assertIn(f'Unknown cabinet gone for {document.name}; known: '
                      'accounts, memories', err.read())

    def test_no_cabinet_given_is_a_failure(self):
        document = self.make_document()
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(**self.config())
        with self.assertRaisesRegex(Filez4EvaError,
                                    f'No cabinet given for {document.name}'):
            command = ClassifyCommand(app)
            command.handle_vals()
            command.act(document)

    def test_conflicting_cabinet_fails_that_document_only(self):
        first = self.make_document()
        data = read_sidecar(first)
        data['results']['given'] = {'at': AT, 'cabinet': 'accounts'}
        write_sidecar(first, data)
        second = self.make_document('20261025-140307-099.pdf')
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(**self.two_cabinets())
        with patch(EXTRACT, return_value=MEMORY) as e, \
                self.patchout() as o, self.patcherr() as err, \
                self.assertRaisesRegex(Filez4EvaError,
                                       '1 of 2 files failed to classify'):
            ClassifyCommand(app, cabinet='memories').execute()
        e.assert_called_once()
        err.seek(0)
        self.assertIn(f'Failed to classify {first}: Cabinet memories given, '
                      f'but {first.name} already has cabinet accounts',
                      err.read())
        o.seek(0)
        self.assertEqual(o.read().strip(), str(second))
        self.assertIsNone(self.classified(first))
        self.assertEqual(read_sidecar(first)['results']['given']['cabinet'],
                         'accounts')

    def test_conflict_with_an_already_classified_document(self):
        document = self.make_document()
        data = read_sidecar(document)
        data['results']['given'] = {'at': AT, 'cabinet': 'accounts'}
        data['results']['classify'] = {'at': AT, 'data': DATA}
        write_sidecar(document, data)
        with patch(EXTRACT) as e, \
                self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
            self.run_command(config=self.two_cabinets(), cabinet='memories')
        e.assert_not_called()
        # The same cabinet is fine
        _, command, _, e, _ = self.run_command(config=self.two_cabinets(),
                                               cabinet='accounts')
        e.assert_not_called()
        self.assertEqual(command.status, 'Already classified 1 file')

    def test_old_shape_cabinet_counts_as_saved(self):
        document = self.make_document()
        data = read_sidecar(document)
        data['results']['classify'] = {'at': AT, 'cabinet': 'memories',
                                       'data': {}}
        write_sidecar(document, data)
        with self.assertRaisesRegex(Filez4EvaError, '1 of 1 file'):
            self.run_command(config=self.two_cabinets(), cabinet='accounts')

    def test_cabinet_from_config_file_and_flag(self):
        document = self.make_document()
        config = (f"filez4eva:\n  intake: {self.intake}\n"
                  f"  cabinets:\n"
                  f"    accounts:\n"
                  f"      target: {self.target}\n"
                  f"      pattern: '{PATTERN}'\n"
                  f"    memories:\n"
                  f"      target: {self.memories}\n"
                  f"      pattern: '{{event}}/{{date}}'\n")
        out, err, code, _ = self.run_app(
            config, '-c', 'accounts', result=dict(RESULT, doctype='other'))
        self.assertEqual(err, 'Classified 1 file\n')
        self.assertEqual(code, 0)
        self.assertEqual(read_sidecar(document)['results']['given'],
                         {'at': AT, 'cabinet': 'accounts'})


class TestClassifyOutput(ClassifyTestCase):
    """AC 12: one intake path per classified document"""

    def test_stdout_and_status_from_app(self):
        source = self.make('scan.pdf')
        out, err, code, _ = self.run_app(self.config_text(), source)
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), str(self.intake / f'{STAMP}.pdf'))
        self.assertEqual(err, 'Ingested 1 file | Transcribed 1 file | '
                         'Classified 1 file\n')
        self.assertNotIn('summary', out)
        out, err, code, e = self.run_app(self.config_text())
        e.assert_not_called()
        self.assertEqual(out, '')
        self.assertEqual(
            err, 'Nothing to classify (1 file already classified)\n')


class TestClassifySchema(ClassifyTestCase):

    def test_schema(self):
        self.make_document()
        _, _, _, e, _ = self.run_command(config=self.config(
            filez4eva_fields={
                'account': {'guidance': 'The other party, never me'}}))
        schema = e.call_args.args[1]
        self.assertEqual(schema['type'], 'object')
        self.assertEqual(schema['required'], ['data', 'doctype', 'summary'])
        self.assertEqual(set(schema['properties']), set(schema['required']))
        self.assertFalse(schema['additionalProperties'])
        data = schema['properties']['data']
        self.assertFalse(data['additionalProperties'])
        self.assertEqual(data['required'], ['date', 'account', 'part'])
        props = data['properties']
        self.assertEqual(props['date']['pattern'], r'^(\d{8})?$')
        self.assertIn('YYYYMMDD', props['date']['description'])
        self.assertTrue(props['account']['description'].startswith(
            'The other party, never me. Use lowercase'))
        self.assertNotIn('pattern', props['part'])
        self.assertEqual(schema['properties']['doctype']['enum'],
                         ['receipt', 'bill', 'other'])

    def test_schema_without_doctypes(self):
        self.make_document()
        config = self.config()
        del config['filez4eva_doctypes']
        _, _, _, e, _ = self.run_command(
            config=config, result=dict(RESULT, doctype='other'))
        self.assertEqual(
            e.call_args.args[1]['properties']['doctype']['enum'], ['other'])

    def test_configured_other_not_duplicated(self):
        doctypes = {'other': {'description': 'Misc'}, 'bill': None}
        self.assertEqual(
            build_schema(Cabinet('x', '/x'), load_doctypes(ConfigHandler.fake(
                filez4eva_doctypes=doctypes)))['properties']['doctype']
            ['enum'], ['bill', 'other'])

    def test_instructions(self):
        self.make_document()
        config = self.config(
            filez4eva_fields={'date': {
                'guidance': 'The statement date, not the print date'}},
            filez4eva_doctypes={
                'receipt': {'description': 'Proof of purchase or payment'},
                'memo': None})
        _, _, _, e, _ = self.run_command(config=config)
        text = e.call_args.kwargs['instructions']
        self.assertIn('one-line summary', text)
        self.assertIn('- date: The statement date, not the print date. '
                      'Give it as YYYYMMDD.', text)
        self.assertIn('return an empty string', text)
        self.assertIn("do not use today's date", text)
        self.assertIn('- part: Use lowercase', text)
        # Common learned values, most-used first
        self.assertIn('reuse one when it fits', text)
        self.assertIn('): amazon, bank\n', text)
        self.assertIn('): refund, receipt\n', text)
        self.assertNotIn('once', text)
        self.assertIn('- receipt: Proof of purchase or payment', text)
        self.assertIn('- memo\n', text)
        self.assertIn('- other: ', text)

    def test_no_values_offered_for_unlearned_field(self):
        self.make_document()
        _, _, _, e, _ = self.run_command(config=self.config(
            filez4eva_fields={'account': {'values': 'none'}}))
        text = e.call_args.kwargs['instructions']
        self.assertNotIn('amazon', text)
        self.assertIn('refund', text)


class TestClassifySettings(ClassifyTestCase):

    def test_default_model(self):
        self.make_document()
        _, _, _, e, _ = self.run_command()
        self.assertEqual(e.call_args.kwargs['model'], 'claude-haiku-4-5')
        self.assertEqual(DEFAULT_MODEL, 'claude-haiku-4-5')
        self.assertIsNone(e.call_args.kwargs['api_key'])

    def test_configured_model_from_file(self):
        self.make_document()
        _, _, _, e = self.run_app(
            self.config_text() + "  classify:\n    model: claude-from-file\n")
        self.assertEqual(e.call_args.kwargs['model'], 'claude-from-file')

    def test_empty_classify_block_uses_default_model(self):
        self.make_document()
        _, _, _, e = self.run_app(self.config_text() + "  classify:\n")
        self.assertEqual(e.call_args.kwargs['model'], DEFAULT_MODEL)

    def test_bad_doctypes_config_fails_before_any_file(self):
        source = self.make('scan.pdf')
        for doctypes in [['receipt'], {'two words': None}, {1: None},
                         {'receipt': 'text'},
                         {'receipt': {'description': 5}}]:
            with self.subTest(doctypes=doctypes), \
                    self.assertRaises(Filez4EvaError):
                self.run_command(source, config=self.config(
                    filez4eva_doctypes=doctypes))
            self.assertTrue(source.exists())

    def test_bad_cabinets_config_fails_before_any_file(self):
        source = self.make('scan.pdf')
        with self.assertRaisesRegex(Filez4EvaError, 'must have a target'):
            self.run_command(source, config=self.config(
                filez4eva_cabinets={'a': {}}))
        self.assertTrue(source.exists())

    def test_empty_doctypes(self):
        self.assertEqual(list(load_doctypes(
            ConfigHandler.fake(filez4eva_doctypes=''))), ['other'])
