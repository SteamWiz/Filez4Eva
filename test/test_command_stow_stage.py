"""Tests for the stow command (Stower, the stow logic it uses, is in
test_stow.py)"""

from pathlib import Path
from unittest.mock import patch

import yaml

from filez4eva import Filez4EvaApp
from filez4eva.command.classify_command import ClassifyCommand
from filez4eva.command.review_command import ReviewCommand
from filez4eva.command.stow_command import StowCommand
from filez4eva.command.transcribe_command import TranscribeCommand
from filez4eva.error import Filez4EvaError
from filez4eva.fields import load_store

from kwark.ai import APIError

from test.test_command_review import (
    ANSWERS, AT, CLASSIFY, DATA, EXTRACT, PATTERN, SECOND, STAMP,
    TRANSCRIBE, ReviewTestCase)


REVIEW = {'at': AT, 'cabinet': 'default', 'data': DATA}

MEMORY = {'date': '20261002', 'event': 'grandma-bday', 'part': 'cake'}


def recording(calls: list, command_class):
    """Patch a stage command's act to note (stage, document name) in calls
    before running it"""
    original = command_class.act

    def act(self, path):
        calls.append((command_class.stage, Path(path).name))
        return original(self, path)
    return patch.object(command_class, 'act', act)


class StowTestCase(ReviewTestCase):
    """The review test setup, running stow"""

    command_class = StowCommand

    @property
    def stowed(self) -> Path:
        """Where the default document goes in the default cabinet"""
        return self.target / '2026' / 'amazon' / '20261002-receipt.pdf'

    @property
    def archive(self) -> Path:
        return self.intake / 'archive'

    def archived(self, name=f'{STAMP}.pdf') -> dict:
        """The results in an archived sidecar"""
        text = (self.archive / f'{name}.yml').read_text()
        return yaml.safe_load(text)['results']

    def run_command(self, path=None, stdin='', **kwargs):
        """Run stow with stdin text (none by default, so a record piped to
        the test run is never read); see ReviewTestCase.run_command"""
        with self.patch_stream(stdin):
            return super().run_command(path, **kwargs)

    def run_classify(self, path=None, **kwargs):
        self.command_class = ClassifyCommand
        try:
            return self.run_command(path, **kwargs)
        finally:
            self.command_class = StowCommand

    def memories_cabinets(self):
        return self.config(filez4eva_cabinets={
            'accounts': {'target': str(self.target), 'pattern': PATTERN},
            'memories': {'target': str(self.memories),
                         'pattern': '{date.year}/{event}/{date}-{part}'}})


class TestStowSelection(StowTestCase):
    """AC 1: a file, a directory (top level only) or the intake, running
    the missing earlier stages first"""

    def test_no_path_is_the_intake(self):
        self.make_document(review=REVIEW)
        out, command, gt, e, t = self.run_command()
        gt.assert_not_called()
        e.assert_not_called()
        t.assert_not_called()
        self.assertEqual(out, str(self.stowed))
        self.assertEqual(command.status, 'Stowed 1 file')

    def test_file_outside_intake_runs_every_stage(self):
        source = self.make('Scan 1.PDF')
        out, command, _, e, t = self.run_command(source, keys='c',
                                                 answers=ANSWERS)
        self.assertFalse(source.exists())
        t.assert_called_once()
        e.assert_called_once()
        self.assertEqual(out, str(self.stowed))
        self.assertEqual(list(self.archived()), [
            'ingest', 'transcribe', 'given', 'classify', 'review', 'stow'])
        self.assertEqual(
            command.status, 'Ingested 1 file | Transcribed 1 file | '
            'Classified 1 file | Reviewed 1 file | Stowed 1 file')

    def test_directory_top_level_only(self):
        self.make('a.pdf')
        self.make('b.pdf', content='other')
        self.make('.hidden')
        self.make('inner.pdf', where=self.source / 'sub')
        out, command, _, _, _ = self.run_command(
            self.source, keys='cc',
            answers=ANSWERS + ['20261003', 'amazon', 'receipt'])
        self.assertEqual(out.splitlines(), [
            str(self.stowed),
            str(self.target / '2026' / 'amazon' / '20261003-receipt.pdf')])
        self.assertEqual(sorted(p.name for p in self.source.iterdir()),
                         ['.hidden', 'sub'])
        self.assertEqual(sorted(p.name for p in self.archive.iterdir()),
                         [f'{STAMP}.pdf.yml', f'{SECOND}.pdf.yml'])

    def test_document_given_with_ingested(self):
        document = self.make_document(review=REVIEW)
        other = self.make_document(f'{SECOND}.pdf', review=REVIEW)
        out, _, _, _, _ = self.run_command(ingested=[document.name])
        self.assertEqual(out, str(self.stowed))
        self.assertTrue(other.is_file())
        self.assertNotIn('stow', self.results(other))

    def run_app(self, *args):
        """Run stow via the app with a configuration file; return (stdout,
        stderr, exit code)"""
        config = self.dir / 'config.yml'
        config.write_text(yaml.safe_dump({'filez4eva': {
            'intake': str(self.intake), 'target': str(self.target),
            'pattern': PATTERN}}))
        code = 0
        with patch(TRANSCRIBE) as t, patch(EXTRACT) as e, \
                self.patch_stream(''), self.patchout() as o, \
                self.patcherr() as err:
            try:
                Filez4EvaApp.start('--config', str(config), 'stow',
                                   *[str(a) for a in args])
            except SystemExit as exit:
                code = exit.code
            o.seek(0)
            err.seek(0)
            t.assert_not_called()
            e.assert_not_called()
            return o.read(), err.read(), code

    def test_reviewed_document_is_not_offered(self):
        self.make_document(review=REVIEW)
        _, command, gt, _, _ = self.run_command()
        gt.assert_not_called()
        self.assertNotIn('(c)onfirm', self.err)

    def test_unreviewed_document_is_offered_then_stowed(self):
        self.make_document()
        out, command, _, _, _ = self.run_command(keys='c', answers=ANSWERS)
        self.assertIn('(c)onfirm', self.err)
        self.assertEqual(out, str(self.stowed))
        self.assertEqual(command.status, 'Reviewed 1 file | Stowed 1 file')
        self.assertEqual(self.archived()['review'], REVIEW)

    def test_each_document_stowed_straight_after_review(self):
        self.make_document()
        self.make_document(f'{SECOND}.pdf')
        seen = []

        def answers():
            for answer in ANSWERS + ['20261003', 'amazon', 'receipt']:
                seen.append(self.stowed.is_file())
                yield answer

        self.run_command(keys='cc', answers=answers())
        # The first document is in the cabinet before the second is asked
        self.assertEqual(seen, [False] * 3 + [True] * 3)

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
                         f'Nothing to stow: no files in {self.source}')

    def test_archive_is_never_a_document(self):
        self.make('old.pdf', where=self.archive)
        out, command, _, _, _ = self.run_command()
        self.assertEqual(command.status,
                         'Nothing to stow: the intake is empty')
        with self.assertRaisesRegex(Filez4EvaError, 'in the intake'):
            self.run_command(self.archive)

    def test_no_path_ingests_nothing(self):
        self.make_document(review=REVIEW)
        stray = self.make('stray.pdf', where=self.intake)
        source = self.make('new.pdf')
        out, command, _, _, t = self.run_command()
        t.assert_not_called()
        self.assertEqual(out, str(self.stowed))
        self.assertEqual(command.status, 'Stowed 1 file')
        self.assertIn(f'Not ingested: {stray}', self.err)
        self.assertTrue(stray.is_file())
        self.assertTrue(source.is_file())
        self.assertEqual(self.intake_names(), ['archive', 'stray.pdf'])

    def test_path_run_leaves_intake_documents_alone(self):
        reviewed = self.make_document(review=REVIEW)
        transcribed = self.make_document(f'{SECOND}.pdf', classify=None,
                                         transcript=None)
        self.make('new.pdf', content='new')
        out, command, _, e, t = self.run_command(
            self.source, keys='c',
            answers=['20261003', 'amazon', 'receipt'])
        new = '20261025-140307-044.pdf'
        self.assertEqual(out, str(self.target / '2026' / 'amazon' /
                                  '20261003-receipt.pdf'))
        t.assert_called_once()
        self.assertEqual(t.call_args.args[0].name, new)
        e.assert_called_once()
        self.assertEqual(command.status,
                         'Ingested 1 file | Transcribed 1 file | '
                         'Classified 1 file | Reviewed 1 file | '
                         'Stowed 1 file')
        self.assertTrue(reviewed.is_file())
        self.assertNotIn('stow', self.results(reviewed))
        self.assertEqual(list(self.results(transcribed)), ['ingest'])

    def test_path_in_intake_is_an_error(self):
        document = self.make_document(review=REVIEW)
        out, err, code = self.run_app(document)
        self.assertEqual(code, 1)
        self.assertIn(f'{document} is in the intake', err)
        self.assertIn('--ingested NAME', err)
        self.assertTrue(document.is_file())
        self.assertFalse(self.stowed.exists())

    def test_ingested_with_path_is_an_error(self):
        document = self.make_document(review=REVIEW)
        source = self.make('a.pdf')
        out, err, code = self.run_app('--ingested', document.name, source)
        self.assertEqual(code, 1)
        self.assertIn("can't be combined with a path", err)
        self.assertTrue(document.is_file())
        self.assertTrue(source.is_file())

    def test_ingested_two_documents(self):
        first = self.make_document(review=REVIEW)
        second = self.make_document(f'{SECOND}.pdf', classify=None,
                                    transcript=None)
        other = self.make_document('20261025-140307-044.pdf',
                                   review=dict(REVIEW, data=dict(
                                       DATA, date='20261005')))
        calls = []
        with recording(calls, TranscribeCommand), \
                recording(calls, ClassifyCommand), \
                recording(calls, ReviewCommand), \
                recording(calls, StowCommand):
            out, command, _, _, _ = self.run_command(
                keys='c', answers=['20261003', 'amazon', 'receipt'],
                ingested=[second.name, str(first)])
        # In the order given, transcription first
        self.assertEqual(calls, [
            ('transcribe', second.name), ('classify', second.name),
            ('review', second.name), ('stow', second.name),
            ('stow', first.name)])
        self.assertEqual(out.splitlines(), [
            str(self.target / '2026' / 'amazon' / '20261003-receipt.pdf'),
            str(self.stowed)])
        self.assertTrue(other.is_file())
        self.assertNotIn('stow', self.results(other))

    def test_nothing_to_stow_from_app(self):
        out, err, code = self.run_app()
        self.assertEqual(code, 0)
        self.assertEqual(out, '')
        self.assertEqual(err, 'Nothing to stow: the intake is empty\n')


class TestStowing(StowTestCase):
    """AC 2: move the file and transcript, write results.stow, archive
    X.yml, never overwrite, use the reviewed cabinet and data"""

    def test_moves_file_and_transcript_and_archives_sidecar(self):
        document = self.make_document(review=REVIEW)
        self.run_command()
        self.assertEqual(self.stowed.read_text(), '%PDF fake')
        self.assertTrue(Path(f'{self.stowed}.md').is_file())
        self.assertFalse(document.exists())
        self.assertEqual(self.intake_names(), ['archive'])
        results = self.archived()
        self.assertEqual(results['stow'], {'at': AT,
                                           'location': str(self.stowed)})
        self.assertEqual(results['review'], REVIEW)
        self.assertEqual(results['classify'], CLASSIFY)

    def test_parallel_transcript(self):
        self.make_document(review=REVIEW)
        root = self.dir / 'transcripts'
        self.run_command(config=self.config(
            filez4eva_transcripts_location='parallel',
            filez4eva_transcripts_root=str(root)))
        self.assertTrue(self.stowed.is_file())
        self.assertTrue((root / 'default' / '2026' / 'amazon' /
                         '20261002-receipt.pdf.md').is_file())
        self.assertFalse(Path(f'{self.stowed}.md').exists())

    def test_only_needs_every_earlier_stage(self):
        self.make_document(transcript=None, review=REVIEW)
        _, command, _, _, t = self.run_command(only=True)
        t.assert_not_called()
        self.assertEqual(command.status, 'Skipped 1 file (not transcribed)')

    def test_records_learned_values(self):
        self.make_document(review=dict(REVIEW, data=dict(
            DATA, account='royal-bank')))
        self.run_command()
        self.assertIn('royal-bank', load_store(self.target)['account'])

    def test_uses_reviewed_cabinet_not_classified_one(self):
        # A sidecar from before results.given, whose cabinet was changed
        # at review
        self.make_document(
            classify=dict(CLASSIFY, cabinet='accounts'), given=None,
            review={'at': AT, 'cabinet': 'memories', 'data': MEMORY})
        out, _, _, _, _ = self.run_command(config=self.memories_cabinets(),
                                           cabinet='memories')
        expected = self.memories / '2026' / 'grandma-bday' / \
            '20261002-cake.pdf'
        self.assertEqual(out, str(expected))
        self.assertTrue(expected.is_file())
        self.assertFalse((self.target / '2026').exists())

    def test_old_shape_sidecar_is_reviewed_and_stowed(self):
        # Classified before results.given: the cabinet is in
        # results.classify, and review doesn't ask for it
        self.make_document(classify=dict(CLASSIFY, cabinet='memories'),
                           given=None)
        out, _, gt, e, _ = self.run_command(
            config=self.memories_cabinets(), keys='c',
            answers=['20261002', 'grandma-bday', 'cake'])
        e.assert_not_called()
        self.assertNotIn('Cabinet: ', [p[0] for p in self.prompts(gt)])
        expected = self.memories / '2026' / 'grandma-bday' / \
            '20261002-cake.pdf'
        self.assertEqual(out, str(expected))
        self.assertEqual(self.archived()['review']['cabinet'], 'memories')
        self.assertEqual(self.archived()['classify']['cabinet'], 'memories')

    def test_hand_edited_number_is_used_as_text(self):
        self.make_document(review=dict(REVIEW, data=dict(
            DATA, date=20261002)))
        out, _, _, _, _ = self.run_command()
        self.assertEqual(out, str(self.stowed))

    def test_existing_file_in_cabinet_is_not_overwritten(self):
        document = self.make_document(review=REVIEW)
        self.stowed.parent.mkdir(parents=True)
        self.stowed.write_text('already here')
        with self.assertRaisesRegex(Filez4EvaError, '1 of 1 file failed'):
            self.run_command()
        self.assertIn('File already exists', self.err)
        self.assertEqual(self.stowed.read_text(), 'already here')
        self.assertTrue(document.is_file())
        self.assertEqual(self.intake_names(), [
            f'{STAMP}.pdf', f'{STAMP}.pdf.md', f'{STAMP}.pdf.yml',
            'archive'])
        self.assertNotIn('stow', self.results(document))

    def test_existing_transcript_in_cabinet_is_not_overwritten(self):
        document = self.make_document(review=REVIEW)
        transcript = Path(f'{self.stowed}.md')
        transcript.parent.mkdir(parents=True)
        transcript.write_text('old')
        with self.assertRaises(Filez4EvaError):
            self.run_command()
        self.assertEqual(transcript.read_text(), 'old')
        self.assertFalse(self.stowed.exists())
        self.assertTrue(document.is_file())

    def test_existing_archived_sidecar_fails_before_moving(self):
        document = self.make_document(review=REVIEW)
        self.make(f'{STAMP}.pdf.yml', content='old', where=self.archive)
        with self.assertRaises(Filez4EvaError):
            self.run_command()
        self.assertIn(f'File already exists at {self.archive}', self.err)
        self.assertEqual((self.archive / f'{STAMP}.pdf.yml').read_text(),
                         'old')
        self.assertTrue(document.is_file())
        self.assertFalse(self.stowed.exists())

    def test_archive_failure_after_stowing_is_reported(self):
        self.make_document(review=REVIEW)
        with patch('filez4eva.command.stow_command.record_result',
                   side_effect=OSError('disk full')), \
                self.assertRaises(Filez4EvaError):
            self.run_command()
        self.assertIn(f'Stowed to {self.stowed}, but could not archive',
                      self.err)
        self.assertIn('disk full', self.err)
        self.assertTrue(self.stowed.is_file())

    def test_bad_review_results(self):
        for review, message in [
                ('yes', 'results.review must be a mapping'),
                ({'data': DATA}, 'results.review has no cabinet'),
                ({'cabinet': 'nope', 'data': DATA}, 'Unknown cabinet nope'),
                ({'cabinet': 'default', 'data': 'x'},
                 'results.review data must be a mapping'),
                ({'cabinet': 'default'}, 'Date must match'),
                ({'cabinet': 'default', 'data': dict(DATA, account=None)},
                 'No value for field account')]:
            with self.subTest(review=review):
                document = self.make_document(review=review)
                with self.assertRaises(Filez4EvaError):
                    self.run_command()
                self.assertIn(message, self.err)
                self.assertTrue(document.is_file())
                self.assertNotIn('stow', self.results(document))


class TestStowOnly(StowTestCase):
    """AC 3: --only stows only reviewed documents"""

    def test_only_skips_unreviewed(self):
        reviewed = self.make_document(review=REVIEW)
        unreviewed = self.make_document(f'{SECOND}.pdf')
        source = self.make('new.pdf')
        out, command, gt, e, t = self.run_command(only=True)
        gt.assert_not_called()
        e.assert_not_called()
        self.assertEqual(out, str(self.stowed))
        self.assertFalse(reviewed.exists())
        self.assertTrue(unreviewed.is_file())
        self.assertIn(f'Skipped {unreviewed}: not reviewed yet', self.err)
        self.assertEqual(command.status,
                         'Stowed 1 file | Skipped 1 file (not reviewed)')
        out, command, _, _, _ = self.run_command(source, only=True)
        self.assertIn(f'Skipped {source}: not ingested yet', self.err)
        self.assertTrue(source.is_file())


class TestStowErrors(StowTestCase):
    """AC 4: a failure is reported, the run carries on, and the exit code
    is non-zero"""

    def test_failure_carries_on(self):
        failing = self.make_document(review=REVIEW)
        self.make_document(f'{SECOND}.pdf', review=dict(REVIEW, data=dict(
            DATA, date='20261003')))
        self.stowed.parent.mkdir(parents=True)
        self.stowed.write_text('already here')
        with self.assertRaisesRegex(Filez4EvaError,
                                    '1 of 2 files failed to stow'):
            self.run_command()
        self.assertIn(f'Failed to stow {failing}', self.err)
        self.assertTrue(failing.is_file())
        self.assertTrue((self.target / '2026' / 'amazon' /
                         '20261003-receipt.pdf').is_file())
        self.assertTrue((self.archive / f'{SECOND}.pdf.yml').is_file())

    def test_failing_classification_carries_on(self):
        self.make_document(classify=None)
        self.make_document(f'{SECOND}.pdf', review=REVIEW)
        with self.assertRaises(Filez4EvaError):
            self.run_command(extract=Filez4EvaError('bad'))
        self.assertTrue(self.stowed.is_file())


class TestStowMenu(StowTestCase):
    """AC 5: skip, preview, delete and quit at review"""

    def test_skip_leaves_document_and_second_run_offers_it(self):
        document = self.make_document()
        _, command, _, _, _ = self.run_command(keys='x')
        self.assertEqual(command.status, 'Skipped 1 file')
        self.assertTrue(document.is_file())
        self.assertEqual(self.results(document)['classify'], CLASSIFY)
        self.assertNotIn('review', self.results(document))
        out, command, _, _, _ = self.run_command(keys='c', answers=ANSWERS)
        self.assertEqual(out, str(self.stowed))
        self.assertEqual(command.status, 'Reviewed 1 file | Stowed 1 file')

    def test_quit(self):
        first = self.make_document()
        second = self.make_document(f'{SECOND}.pdf')
        out, command, _, _, _ = self.run_command(keys='q')
        self.assertEqual(out, '')
        self.assertEqual(command.status, 'Quit')
        self.assertTrue(first.is_file())
        self.assertTrue(second.is_file())

    def test_delete(self):
        self.make_document()
        _, command, _, _, _ = self.run_command(keys='dY')
        self.assertEqual(command.status, 'Deleted 1 file')
        self.assertEqual(self.intake_names(), [])

    def test_preview(self):
        document = self.make_document()
        with patch('filez4eva.command.review_command.run') as run:
            out, _, _, _, _ = self.run_command(keys='pc', answers=ANSWERS)
        run.assert_called_once_with(['preview', document])
        self.assertEqual(out, str(self.stowed))


class TestStowOrder(StowTestCase):
    """The transcribe batch, then one document at a time, the most advanced
    first"""

    def test_every_transcription_before_the_first_classification(self):
        self.make('a.pdf')
        self.make('b.pdf', content='second')
        self.make('c.pdf', content='third')
        calls = []
        with recording(calls, TranscribeCommand), \
                recording(calls, ClassifyCommand), \
                recording(calls, ReviewCommand), \
                recording(calls, StowCommand):
            self.run_command(
                self.source, keys='ccc',
                answers=ANSWERS + ['20261003', 'amazon', 'receipt']
                + ['20261004', 'amazon', 'receipt'])
        third = '20261025-140307-044.pdf'
        documents = [f'{STAMP}.pdf', f'{SECOND}.pdf', third]
        self.assertEqual(calls, [('transcribe', d) for d in documents] + [
            (stage, d) for d in documents
            for stage in ['classify', 'review', 'stow']])

    def test_most_advanced_first(self):
        transcribed = self.make_document(classify=None)
        classified = self.make_document(f'{SECOND}.pdf')
        reviewed = self.make_document(
            '20261025-140307-044.pdf',
            review=dict(REVIEW, data=dict(DATA, date='20261005')))
        ingested = self.make_document('20261025-140307-045.pdf',
                                      classify=None, transcript=None)
        calls = []
        with recording(calls, TranscribeCommand), \
                recording(calls, ClassifyCommand), \
                recording(calls, ReviewCommand), \
                recording(calls, StowCommand):
            _, command, _, _, _ = self.run_command(
                keys='ccc',
                answers=['20261003', 'amazon', 'receipt'] + ANSWERS
                + ['20261006', 'amazon', 'receipt'])
        self.assertEqual(calls, [
            ('transcribe', ingested.name),
            ('stow', reviewed.name),
            ('review', classified.name), ('stow', classified.name),
            # Both transcribed by now: name order
            ('classify', transcribed.name), ('review', transcribed.name),
            ('stow', transcribed.name),
            ('classify', ingested.name), ('review', ingested.name),
            ('stow', ingested.name)])
        self.assertEqual(command.status,
                         'Transcribed 1 file | Classified 2 files | '
                         'Reviewed 3 files | Stowed 4 files')

    def test_only_transcribes_nothing(self):
        reviewed = self.make_document(review=REVIEW)
        untranscribed = self.make_document(f'{SECOND}.pdf', classify=None,
                                           transcript=None)
        out, command, gt, e, t = self.run_command(only=True)
        t.assert_not_called()
        e.assert_not_called()
        gt.assert_not_called()
        self.assertEqual(out, str(self.stowed))
        self.assertFalse(reviewed.exists())
        self.assertEqual(list(self.results(untranscribed)), ['ingest'])
        self.assertEqual(command.status,
                         'Stowed 1 file | Skipped 1 file (not transcribed)')

    def test_review_ingested_then_stow_only(self):
        first = self.make_document()
        second = self.make_document(f'{SECOND}.pdf')
        self.command_class = ReviewCommand
        self.run_command(keys='c', answers=ANSWERS, ingested=[first.name])
        self.command_class = StowCommand
        out, command, gt, _, _ = self.run_command(only=True)
        gt.assert_not_called()
        self.assertEqual(out, str(self.stowed))
        self.assertTrue(second.is_file())
        self.assertEqual(command.status,
                         'Stowed 1 file | Skipped 1 file (not reviewed)')

    def test_transcription_failure_drops_the_document(self):
        self.make('a.pdf')
        self.make('b.pdf', content='second')
        calls = iter([APIError('nope'), '# Hi'])

        def transcribe(*args, **kwargs):
            value = next(calls)
            if isinstance(value, Exception):
                raise value
            return value
        with self.assertRaisesRegex(Filez4EvaError, '1 of 2 files failed'):
            self.run_command(self.source, keys='c', answers=ANSWERS,
                             transcribe=transcribe)
        self.assertIn('Transcription failed: nope', self.err)
        failed = self.intake / f'{STAMP}.pdf'
        self.assertEqual(list(self.results(failed)), ['ingest'])
        self.assertTrue((self.archive / f'{SECOND}.pdf.yml').is_file())

    def test_bad_sidecar_is_reported_in_its_turn(self):
        bad = self.make_document()
        Path(f'{bad}.yml').write_text('- a list')
        self.make_document(f'{SECOND}.pdf', review=REVIEW)
        with self.assertRaisesRegex(Filez4EvaError, '1 of 2 files failed'):
            self.run_command(only=True)
        self.assertIn(f'Failed to stow {bad}', self.err)
        self.assertTrue((self.archive / f'{SECOND}.pdf.yml').is_file())


class TestMainUseCase(StowTestCase):
    """AC 5: classify a folder, then stow the intake"""

    def test_classify_then_stow(self):
        self.make('Scan 1.PDF')
        self.make('Scan 2.PDF', content='second')
        self.make('Scan 3.PDF', content='third')
        out, command, gt, _, _ = self.run_classify(self.source)
        gt.assert_not_called()
        self.assertEqual(command.status,
                         'Ingested 3 files | Transcribed 3 files | '
                         'Classified 3 files')
        self.assertEqual(list(self.source.iterdir()), [])
        third = f'{STAMP[:-3]}044.pdf'
        # Confirm the first, skip the second, edit the third
        out, command, _, e, t = self.run_command(
            keys='cxc', answers=ANSWERS + ['20261004', 'amazon', 'invoice'])
        e.assert_not_called()
        t.assert_not_called()
        self.assertEqual(out.splitlines(), [
            str(self.stowed),
            str(self.target / '2026' / 'amazon' / '20261004-invoice.pdf')])
        self.assertEqual(command.status,
                         'Reviewed 2 files | Stowed 2 files | '
                         'Skipped 1 file')
        self.assertEqual(self.intake_names(), [
            f'{SECOND}.pdf', f'{SECOND}.pdf.md', f'{SECOND}.pdf.yml',
            'archive'])
        self.assertEqual(sorted(p.name for p in self.archive.iterdir()),
                         [f'{STAMP}.pdf.yml', f'{third}.yml'])
        # The skipped one is offered again
        out, command, _, _, _ = self.run_command(
            keys='c', answers=['20261003', 'amazon', 'receipt'])
        self.assertEqual(out, str(self.target / '2026' / 'amazon' /
                                  '20261003-receipt.pdf'))
        self.assertEqual(self.intake_names(), ['archive'])
        self.assertEqual(self.archived(SECOND + '.pdf')['ingest'][
            'original-name'], 'Scan 2.PDF')


FLAGS = {'date': '20261002', 'field': ['account=amazon', 'part=receipt']}

INPUT = {'at': AT, 'input': True, 'cabinet': 'default', 'data': DATA}

STDIN = ('cabinet: default\n'
         'data:\n  date: 2026-10-02\n  account: amazon\n  part: receipt\n')


class StowInputTestCase(StowTestCase):
    """Run stow with input data"""

    def assert_stowed_with_input(self, review=INPUT):
        self.assertTrue(self.stowed.is_file())
        results = self.archived()
        self.assertEqual(list(results), [
            'ingest', 'transcribe', 'review', 'stow'])
        self.assertEqual(results['review'], review)
        self.assertEqual(results['stow'], {'at': AT,
                                           'location': str(self.stowed)})


class TestStowInput(StowInputTestCase):
    """AC 1-3: input data from flags or stdin skips classify and review"""

    def test_flags_skip_classify_and_review(self):
        source = self.make('Scan 1.PDF')
        out, command, gt, e, t = self.run_command(source, **FLAGS)
        t.assert_called_once()
        e.assert_not_called()
        gt.assert_not_called()
        self.assertNotIn('(c)onfirm', self.err)
        self.assertFalse(source.exists())
        self.assertEqual(out, str(self.stowed))
        self.assertEqual(Path(f'{self.stowed}.md').read_text().count('# Hi'),
                         1)
        self.assertEqual(self.intake_names(), ['archive'])
        self.assert_stowed_with_input()
        self.assertEqual(command.status, 'Ingested 1 file | '
                         'Transcribed 1 file | Stowed 1 file')

    def test_classify_config_not_needed(self):
        source = self.make('Scan 1.PDF')
        config = self.config()
        del config['filez4eva_doctypes']
        self.run_command(source, config=config, **FLAGS)
        self.assert_stowed_with_input()

    def test_stdin_record(self):
        source = self.make('Scan 1.PDF')
        out, _, gt, e, _ = self.run_command(source, stdin=STDIN)
        e.assert_not_called()
        gt.assert_not_called()
        self.assertEqual(out, str(self.stowed))
        self.assert_stowed_with_input()

    def test_flags_win_over_stdin(self):
        source = self.make('Scan 1.PDF')
        out, _, gt, _, _ = self.run_command(
            source, stdin=STDIN.replace('receipt', 'invoice').replace(
                '2026-10-02', '2026-10-09'),
            date='20261002', field=['part=receipt'])
        gt.assert_not_called()
        self.assert_stowed_with_input()

    def test_cabinet_from_flag(self):
        source = self.make('Scan 1.PDF')
        out, _, gt, e, _ = self.run_command(
            source, config=self.memories_cabinets(), cabinet='memories',
            date='20261002', field=['event=grandma-bday', 'part=cake'])
        gt.assert_not_called()
        e.assert_not_called()
        expected = self.memories / '2026' / 'grandma-bday' / \
            '20261002-cake.pdf'
        self.assertEqual(out, str(expected))
        self.assertEqual(self.archived()['review'], {
            'at': AT, 'input': True, 'cabinet': 'memories', 'data': MEMORY})

    def test_partial_record_prompts_for_the_rest(self):
        source = self.make('Scan 1.PDF')
        _, _, gt, e, t = self.run_command(
            source, stdin='data:\n  date: 20261002\n  account: amazon\n',
            answers=['receipt'])
        self.assertEqual([c[0] for c in self.prompts(gt)], ['Part: '])
        e.assert_not_called()
        self.assert_stowed_with_input()

    def test_cancel_at_prompt_moves_nothing(self):
        source = self.make('Scan 1.PDF')
        _, _, _, _, t = self.run_command(source, date='20261002',
                                         answers=[''])
        t.assert_not_called()
        self.assertTrue(source.is_file())
        self.assertEqual(self.intake_names(), [])

    def test_ingested_document_is_not_ingested_again(self):
        document = self.make_document(classify=None)
        out, command, _, e, t = self.run_command(
            ingested=[document.name], **FLAGS)
        t.assert_not_called()
        e.assert_not_called()
        self.assertEqual(out, str(self.stowed))
        self.assert_stowed_with_input()
        self.assertEqual(command.status, 'Stowed 1 file')

    def test_untranscribed_document_is_transcribed(self):
        document = self.make_document(classify=None, transcript=None)
        _, command, _, e, t = self.run_command(ingested=[document.name],
                                               **FLAGS)
        t.assert_called_once()
        e.assert_not_called()
        self.assertEqual(command.status,
                         'Transcribed 1 file | Stowed 1 file')

    def test_only_still_needs_transcript(self):
        document = self.make_document(classify=None, transcript=None)
        _, command, _, _, t = self.run_command(
            ingested=[document.name], only=True, **FLAGS)
        t.assert_not_called()
        self.assertTrue(document.is_file())
        self.assertEqual(command.status,
                         'Skipped 1 file (not transcribed)')

    def test_input_replaces_existing_review(self):
        document = self.make_document(review={
            'at': AT, 'cabinet': 'default',
            'data': dict(DATA, part='invoice')})
        self.run_command(ingested=[document.name], **FLAGS)
        results = self.archived()
        self.assertEqual(results['review'], INPUT)
        self.assertEqual(results['classify'], CLASSIFY)

    def test_existing_file_in_cabinet_is_not_overwritten(self):
        source = self.make('Scan 1.PDF')
        self.stowed.parent.mkdir(parents=True)
        self.stowed.write_text('already here')
        with self.assertRaisesRegex(Filez4EvaError, '1 of 1 file failed'):
            self.run_command(source, **FLAGS)
        self.assertIn('File already exists', self.err)
        self.assertEqual(self.stowed.read_text(), 'already here')
        document = self.intake / f'{STAMP}.pdf'
        self.assertTrue(document.is_file())
        self.assertEqual(list(self.results(document)),
                         ['ingest', 'transcribe'])

    def test_failed_stow_keeps_existing_review(self):
        document = self.make_document(review=REVIEW)
        self.stowed.parent.mkdir(parents=True)
        self.stowed.write_text('already here')
        with self.assertRaisesRegex(Filez4EvaError, '1 of 1 file failed'):
            self.run_command(ingested=[document.name], **FLAGS)
        self.assertEqual(self.results(document)['review'], REVIEW)
        self.assertNotIn('stow', self.results(document))

    def test_rerun_after_failed_stow(self):
        """A failed input stow leaves the document transcribed only, so
        stow runs classify and review as usual, and --only skips it"""
        source = self.make('Scan 1.PDF')
        self.stowed.parent.mkdir(parents=True)
        self.stowed.write_text('already here')
        with self.assertRaisesRegex(Filez4EvaError, '1 of 1 file failed'):
            self.run_command(source, **FLAGS)
        self.stowed.unlink()
        document = self.intake / f'{STAMP}.pdf'
        _, command, _, _, _ = self.run_command(ingested=[document.name],
                                               only=True)
        self.assertTrue(document.is_file())
        self.assertEqual(command.status, 'Skipped 1 file (not classified)')
        out, command, _, e, t = self.run_command(
            keys='c', answers=ANSWERS, ingested=[document.name])
        t.assert_not_called()
        e.assert_called_once()
        self.assertEqual(out, str(self.stowed))
        self.assertEqual(list(self.archived()), [
            'ingest', 'transcribe', 'given', 'classify', 'review', 'stow'])
        self.assertNotIn('input', self.archived()['review'])
        self.assertEqual(command.status,
                         'Classified 1 file | Reviewed 1 file | '
                         'Stowed 1 file')

    def test_rerun_with_input_after_failed_stow(self):
        source = self.make('Scan 1.PDF')
        self.stowed.parent.mkdir(parents=True)
        self.stowed.write_text('already here')
        with self.assertRaisesRegex(Filez4EvaError, '1 of 1 file failed'):
            self.run_command(source, **FLAGS)
        self.stowed.unlink()
        out, command, gt, e, t = self.run_command(
            ingested=[str(self.intake / f'{STAMP}.pdf')], **FLAGS)
        t.assert_not_called()
        e.assert_not_called()
        gt.assert_not_called()
        self.assertEqual(out, str(self.stowed))
        self.assert_stowed_with_input()
        self.assertEqual(command.status, 'Stowed 1 file')


class TestStowInputErrors(StowInputTestCase):
    """AC 4: input data needs a single file; bad input moves nothing"""

    def test_directory_is_an_error(self):
        source = self.make('Scan 1.PDF')
        for vals in [FLAGS, {'stdin': STDIN}]:
            with self.subTest(vals=vals):
                with self.assertRaisesRegex(
                        Filez4EvaError, 'needs a single document: one new '
                        'file, or one --ingested NAME, not a directory: '
                        f'{self.source}$'):
                    self.run_command(self.source, **vals)
                self.assertTrue(source.is_file())
                self.assertEqual(self.intake_names(), [])

    def test_no_path_is_an_error(self):
        document = self.make_document()
        for vals in [FLAGS, {'stdin': STDIN}]:
            with self.subTest(vals=vals):
                with self.assertRaisesRegex(
                        Filez4EvaError,
                        r'Input data \(--date, --field or a record on '
                        r'stdin\) needs a single document: one '
                        'new file, or one --ingested NAME, not every '
                        'document in the intake'):
                    self.run_command(**vals)
                self.assertTrue(document.is_file())
                self.assertNotIn('review', self.results(document))

    def test_bad_input_fails_before_anything_moves(self):
        source = self.make('Scan 1.PDF')
        for vals, message in [
                ({'cabinet': 'nope'}, 'Unknown cabinet nope'),
                (dict(FLAGS, date='20261332'), 'Date must match'),
                ({'stdin': 'data:\n  date: 2 Oct\n'}, 'Date from stdin'),
                (dict(FLAGS, field=['colour=red']), 'Unknown field colour'),
                (dict(FLAGS, field=['account']), '--field must be')]:
            with self.subTest(vals=vals):
                with self.assertRaisesRegex(Filez4EvaError, message):
                    self.run_command(source, **vals)
                self.assertTrue(source.is_file())
                self.assertEqual(self.intake_names(), [])

    def test_companion_file_is_an_error(self):
        document = self.make_document()
        with self.assertRaisesRegex(Filez4EvaError, 'in the intake'):
            self.run_command(f'{document}.yml', **FLAGS)
        with self.assertRaisesRegex(Filez4EvaError,
                                    'not a document ingested'):
            self.run_command(ingested=[f'{document.name}.yml'], **FLAGS)
        self.assertNotIn('review', self.results(document))

    def test_several_ingested_is_an_error(self):
        first = self.make_document()
        second = self.make_document(f'{SECOND}.pdf')
        with self.assertRaisesRegex(Filez4EvaError, 'not several'):
            self.run_command(ingested=[first.name, second.name], **FLAGS)
        for document in [first, second]:
            self.assertNotIn('review', self.results(document))

    def test_same_ingested_twice_is_one_document(self):
        document = self.make_document()
        out, _, _, _, _ = self.run_command(
            ingested=[document.name, str(document)], **FLAGS)
        self.assertEqual(out, str(self.stowed))


class TestStowWithoutInput(StowInputTestCase):
    """AC 5: no input data, or stdin that isn't a record, behaves as
    before"""

    def test_stdin_without_record_is_no_input(self):
        for stdin in ['', '   \n', 'just text', '- a\n- b\n', ': [',
                      'cabinet: ~\ndata: ~\n', 'other: x\n']:
            with self.subTest(stdin=stdin):
                self.make_document()
                out, command, _, _, _ = self.run_command(
                    stdin=stdin, keys='c', answers=ANSWERS)
                self.assertEqual(out, str(self.stowed))
                self.assertEqual(command.status,
                                 'Reviewed 1 file | Stowed 1 file')
                self.assertNotIn('input', self.archived()['review'])
                self.stowed.unlink()
                Path(f'{self.stowed}.md').unlink()
                (self.archive / f'{STAMP}.pdf.yml').unlink()


class TestStowInputCommandLine(StowInputTestCase):
    """AC 1: the flags and stdin from the command line"""

    def test_command_line(self):
        source = self.make('Scan 1.PDF')
        config = self.dir / 'config.yml'
        config.write_text(yaml.safe_dump({'filez4eva': {
            'intake': str(self.intake), 'target': str(self.target),
            'pattern': PATTERN}}))
        with patch(TRANSCRIBE, return_value='# Hi'), \
                patch(EXTRACT) as e, \
                self.patch_stream('data:\n  part: receipt\n'), \
                self.patch_ttyin(''), self.patchout(), self.patcherr():
            Filez4EvaApp.start('--config', str(config), 'stow',
                               str(source), '-d', '20261002',
                               '-f', 'account=amazon', debug=True)
        e.assert_not_called()
        self.assert_stowed_with_input()


class TestStowCabinet(StowTestCase):
    """#72: --cabinet on stow gives the cabinet of documents that have none
    saved, and is checked against the saved one"""

    def test_cabinet_alone_is_not_input_data(self):
        source = self.make('Scan 1.PDF')
        out, command, gt, e, t = self.run_command(
            source, config=self.memories_cabinets(), cabinet='accounts',
            keys='c', answers=ANSWERS)
        t.assert_called_once()
        e.assert_called_once()
        self.assertNotIn('Cabinet: ', [p[0] for p in self.prompts(gt)])
        self.assertEqual(out, str(self.stowed))
        results = self.archived()
        self.assertEqual(results['given'], {'at': AT, 'cabinet': 'accounts'})
        self.assertNotIn('input', results['review'])
        self.assertEqual(
            command.status, 'Ingested 1 file | Transcribed 1 file | '
            'Classified 1 file | Reviewed 1 file | Stowed 1 file')

    def test_prompt_before_classify_then_review_and_stow(self):
        source = self.make('Scan 1.PDF')
        out, _, gt, e, _ = self.run_command(
            source, config=self.memories_cabinets(), keys='c',
            answers=['accounts'] + ANSWERS)
        self.assertEqual(self.prompts(gt)[0],
                         ('Cabinet: ', ['accounts', 'memories']))
        self.assertEqual([p[0] for p in self.prompts(gt)[1:]],
                         ['Date: ', 'Account: ', 'Part: '])
        self.assertEqual(out, str(self.stowed))

    def test_classify_then_stow_with_another_cabinet(self):
        # classify -c accounts, then stow -c memories with no path
        first = self.make_document(classify=None)
        self.run_classify(config=self.memories_cabinets(), cabinet='accounts')
        self.assertEqual(self.results(first)['given']['cabinet'], 'accounts')
        second = self.make_document(f'{SECOND}.pdf', classify=None)
        with self.assertRaisesRegex(Filez4EvaError,
                                    '1 of 2 files failed to stow'):
            self.run_command(
                config=self.memories_cabinets(), cabinet='memories',
                keys='c', answers=['20261002', 'grandma-bday', 'cake'],
                result={'data': MEMORY, 'doctype': 'other',
                        'summary': 'Cake'})
        self.assertIn(f'Failed to stow {first}: Cabinet memories given, but '
                      f'{first.name} already has cabinet accounts', self.err)
        self.assertTrue(first.is_file())
        self.assertNotIn('review', self.results(first))
        self.assertEqual(self.archived(f'{SECOND}.pdf')['given']['cabinet'],
                         'memories')
        self.assertFalse(second.exists())
        # The same cabinet is fine
        out, command, _, _, _ = self.run_command(
            config=self.memories_cabinets(), cabinet='accounts', keys='c',
            answers=ANSWERS)
        self.assertEqual(out, str(self.stowed))

    def test_conflict_with_a_reviewed_document(self):
        document = self.make_document(review=REVIEW)
        with self.assertRaisesRegex(Filez4EvaError, '1 of 1 file failed'):
            self.run_command(config=self.memories_cabinets(),
                             cabinet='memories')
        self.assertIn('already has cabinet default', self.err)
        self.assertTrue(document.is_file())

    def test_unknown_cabinet_touches_nothing(self):
        source = self.make('scan.pdf')
        document = self.make_document()
        before = Path(f'{document}.yml').read_text()
        for path in [source, None]:
            with self.subTest(path=path), \
                    self.assertRaisesRegex(Filez4EvaError,
                                           'Unknown cabinet nope'):
                self.run_command(path, cabinet='nope')
        self.assertTrue(source.is_file())
        self.assertEqual(Path(f'{document}.yml').read_text(), before)

    def test_input_data_uses_the_saved_cabinet(self):
        document = self.make_document(classify=None, given=None)
        data = yaml.safe_load(Path(f'{document}.yml').read_text())
        data['results']['given'] = {'at': AT, 'cabinet': 'memories'}
        Path(f'{document}.yml').write_text(yaml.safe_dump(data))
        out, _, gt, _, _ = self.run_command(
            config=self.memories_cabinets(), ingested=[document.name],
            date='20261002', field=['event=grandma-bday', 'part=cake'])
        gt.assert_not_called()
        self.assertEqual(self.archived()['review'], {
            'at': AT, 'input': True, 'cabinet': 'memories', 'data': MEMORY})
        self.assertTrue(Path(out).is_file())

    def test_input_data_with_a_conflicting_cabinet(self):
        document = self.make_document(given='accounts')
        for vals in [{'cabinet': 'memories'},
                     {'stdin': 'cabinet: memories\n'}]:
            with self.subTest(vals=vals), \
                    self.assertRaisesRegex(
                        Filez4EvaError, 'Cabinet memories given, but '
                        f'{document.name} already has cabinet accounts'):
                self.run_command(
                    config=self.memories_cabinets(), ingested=[document.name],
                    date='20261002',
                    field=['event=grandma-bday', 'part=cake'], **vals)
        self.assertTrue(document.is_file())
        self.assertNotIn('review', self.results(document))
