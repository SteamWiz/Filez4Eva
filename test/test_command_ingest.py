from datetime import datetime, timedelta, timezone
import errno
import fcntl
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unittest.mock import patch

import yaml
from wizlib.config_handler import ConfigHandler
from wizlib.test_case import WizLibTestCase

from filez4eva import Filez4EvaApp
from filez4eva.command.ingest_command import (
    DEFAULT_INTAKE, IngestCommand, extensions, file_time, in_intake,
    ingest_file, ingest_record,
    intake_dir, intake_lock, is_companion, is_ingested, now, parse_meta,
    read_sidecar, sidecar_path, stamp_name, write_sidecar)
from filez4eva.error import Filez4EvaError
from test import plain


NOW = 'filez4eva.command.ingest_command.now'

# A fixed local time with an offset, so names and `at` are predictable
CLOCK = datetime(2026, 10, 25, 14, 3, 7, 42000,
                 tzinfo=timezone(timedelta(hours=-7)))
STAMP = '20261025-140307-042'
NEXT_STAMP = '20261025-140307-043'


# File times for the original file: modified and created (birth)
MTIME = 1759400000
BIRTHTIME = 1759300000


def local_time(timestamp):
    """A timestamp as the sidecar records it: local ISO-8601 with offset"""
    return datetime.fromtimestamp(timestamp).astimezone().isoformat(
        timespec='seconds')


def stat_of(path, birthtime=None):
    """Patch os.stat so that, for path only, the result has st_birthtime
    set to birthtime, or none at all when birthtime is None (as on most
    Linux filesystems)"""
    real_stat = os.stat
    path = str(path)

    def fake_stat(target, *args, **kwargs):
        result = real_stat(target, *args, **kwargs)
        if os.fspath(target) != path:
            return result
        fields = {name: getattr(result, name) for name in dir(result)
                  if name.startswith('st_') and name != 'st_birthtime'}
        if birthtime is not None:
            fields['st_birthtime'] = birthtime
        return SimpleNamespace(**fields)
    return patch('os.stat', fake_stat)


def ingest_worker(barrier, source, intake):
    """Run in a forked process (which keeps the frozen clock): wait for the
    other workers, then ingest every file in source"""
    intake.mkdir(parents=True, exist_ok=True)
    barrier.wait()
    for path in sorted(source.iterdir()):
        ingest_file(path, intake, {})


class TestIngestHelpers(WizLibTestCase):

    def test_extensions(self):
        cases = {
            'Report.DOCX.pdf': '.docx.pdf',
            'Scan 10.14.03.pdf': '.pdf',
            'README': '',
            'x.123': '',
            'archive.tar.gz': '.tar.gz',
            'photo.JPEG': '.jpeg',
            'mp3.mp3': '.mp3',
            'a.toolong': '',
            'a..pdf': '.pdf',
            'trailing.': '',
            'name.v2.pdf': '.v2.pdf',
            '.bashrc': '',
            '.config.yml': '.yml',
            'r\u00e9sum\u00e9.\u00e9t\u00e9': '',
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(extensions(name), expected)

    def test_now_is_local_with_offset(self):
        self.assertIsNotNone(now().tzinfo)

    def test_stamp_name(self):
        self.assertEqual(stamp_name(CLOCK, '.pdf'), STAMP + '.pdf')
        self.assertEqual(stamp_name(CLOCK), STAMP)

    def test_sidecar_path(self):
        self.assertEqual(sidecar_path(Path('/a/b.pdf')), Path('/a/b.pdf.yml'))

    def test_parse_meta(self):
        self.assertEqual(parse_meta(['a=1', ' b =x=y', 'c=']),
                         {'a': '1', 'b': 'x=y', 'c': ''})
        self.assertEqual(parse_meta(None), {})
        for bad in ['novalue', '=x', ' =x']:
            with self.subTest(flag=bad), self.assertRaises(Filez4EvaError):
                parse_meta([bad])

    def test_read_sidecar_tolerates_bad_files(self):
        with TemporaryDirectory() as d:
            doc = Path(d) / 'x'
            self.assertEqual(read_sidecar(doc), {})
            sidecar_path(doc).write_text('- a list\n')
            self.assertEqual(read_sidecar(doc), {})
            sidecar_path(doc).write_text(': [bad\n')
            self.assertEqual(read_sidecar(doc), {})

    def test_write_sidecar_replaces_unless_exclusive(self):
        with TemporaryDirectory() as d:
            doc = Path(d) / 'x'
            write_sidecar(doc, {'a': 1})
            write_sidecar(doc, {'a': 2})
            self.assertEqual(read_sidecar(doc), {'a': 2})
            with self.assertRaises(FileExistsError):
                write_sidecar(doc, {'a': 3}, exclusive=True)
            self.assertEqual(read_sidecar(doc), {'a': 2})

    def test_write_sidecar_exclusive_cleans_up_on_error(self):
        with TemporaryDirectory() as d:
            doc = Path(d) / 'x'
            with patch('filez4eva.command.ingest_command.format_sidecar',
                       return_value=None), self.assertRaises(TypeError):
                write_sidecar(doc, {}, exclusive=True)
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_is_companion(self):
        with TemporaryDirectory() as d:
            d = Path(d)
            (d / 'a.pdf').write_text('x')
            (d / 'a.pdf.yml').write_text('x')
            (d / 'a.pdf.md').write_text('x')
            (d / 'b.pdf.md').write_text('x')
            (d / 'b.pdf').write_text('x')
            (d / 'orphan.yml').write_text('x')
            self.assertTrue(is_ingested(d / 'a.pdf'))
            self.assertTrue(is_companion(d / 'a.pdf.yml'))
            self.assertTrue(is_companion(d / 'a.pdf.md'))
            self.assertFalse(is_companion(d / 'b.pdf.md'))
            self.assertFalse(is_companion(d / 'orphan.yml'))
            self.assertFalse(is_companion(d / 'a.pdf'))

    def test_intake_dir_default(self):
        with TemporaryDirectory() as home, \
                patch.dict(os.environ, {'HOME': home}):
            os.environ.pop('FILEZ4EVA_INTAKE', None)
            path = intake_dir(ConfigHandler.fake())
            self.assertEqual(path, Path(home) / '.filez4eva' / 'intake')
            self.assertTrue(path.is_dir())
        self.assertEqual(DEFAULT_INTAKE, '~/.filez4eva/intake')

    def test_intake_dir_configured_and_created(self):
        with TemporaryDirectory() as d:
            wanted = Path(d) / 'deep' / 'intake'
            path = intake_dir(ConfigHandler.fake(filez4eva_intake=str(wanted)))
            self.assertEqual(path, wanted)
            self.assertTrue(wanted.is_dir())

    def test_intake_dir_not_text_is_error(self):
        for setting in [5, ['a'], {'a': 'b'}]:
            with self.subTest(setting=setting), \
                    self.assertRaisesRegex(Filez4EvaError, 'intake must be'):
                intake_dir(ConfigHandler.fake(filez4eva_intake=setting))

    def test_in_intake(self):
        with TemporaryDirectory() as d:
            d = Path(d)
            (d / 'intake').mkdir()
            self.assertTrue(in_intake(d / 'intake' / 'a.pdf', d / 'intake'))
            self.assertFalse(in_intake(d / 'a.pdf', d / 'intake'))
            self.assertFalse(in_intake(d / 'missing' / 'a', d / 'intake'))

    def test_intake_dir_error(self):
        with TemporaryDirectory() as d:
            blocker = Path(d) / 'file'
            blocker.write_text('x')
            with self.assertRaises(Filez4EvaError):
                intake_dir(ConfigHandler.fake(filez4eva_intake=str(blocker)))


class TestIngestCommand(WizLibTestCase):

    def setUp(self):
        super().setUp()
        self.intake_tmp = TemporaryDirectory()
        self.source_tmp = TemporaryDirectory()
        self.intake = Path(self.intake_tmp.name) / 'intake'
        self.source = Path(self.source_tmp.name)
        patcher = patch(NOW, return_value=CLOCK)
        self.now = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.intake_tmp.cleanup()
        self.source_tmp.cleanup()
        super().tearDown()

    def make(self, name, content='data'):
        path = self.source / name
        path.write_text(content)
        return path

    def run_command(self, path, stdin='', **vals):
        """Run the command directly with fake config; return (result,
        command, stderr)"""
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(filez4eva_intake=str(self.intake))
        command = IngestCommand(app, path=str(path), **vals)
        with self.patchout(), self.patcherr() as e, \
                self.patch_stream(stdin):
            result = command.execute()
            e.seek(0)
            return result, command, e.read()

    def run_app(self, *args, stdin='', debug=False):
        """Run via the app with a config file; return (stdout, stderr,
        exit code)"""
        config = f"filez4eva:\n  intake: {self.intake}\n"
        code = 0
        with self.patchout() as o, self.patcherr() as e, \
                self.patch_stream(stdin), \
                NamedTemporaryFile('w+', suffix='.yml') as cf, \
                patch.dict(os.environ):
            os.environ.pop('FILEZ4EVA_INTAKE', None)
            cf.write(config)
            cf.flush()
            try:
                Filez4EvaApp.start('--config', cf.name, 'ingest', *args,
                                   debug=debug)
            except SystemExit as exit:
                code = exit.code
            o.seek(0)
            e.seek(0)
            return o.read(), e.read(), code

    def intake_names(self):
        return sorted(p.name for p in self.intake.iterdir())

    def test_moves_and_renames(self):
        source = self.make('Report.DOCX.pdf', 'pdf bytes')
        result, command, _ = self.run_command(source)
        target = self.intake / (STAMP + '.docx.pdf')
        self.assertEqual(Path(result), target)
        self.assertEqual(command.status, 'Ingested')
        self.assertFalse(source.exists())
        self.assertEqual(target.read_text(), 'pdf bytes')
        self.assertEqual(self.intake_names(),
                         [STAMP + '.docx.pdf', STAMP + '.docx.pdf.yml'])

    def test_name_with_dotted_numbers(self):
        result, _, _ = self.run_command(self.make('Scan 10.14.03.pdf'))
        self.assertEqual(Path(result).name, STAMP + '.pdf')

    def test_name_without_extension(self):
        result, _, _ = self.run_command(self.make('README'))
        self.assertEqual(Path(result).name, STAMP)
        self.assertTrue((self.intake / (STAMP + '.yml')).is_file())

    def test_digit_suffix_is_not_extension(self):
        result, _, _ = self.run_command(self.make('x.123'))
        self.assertEqual(Path(result).name, STAMP)

    def test_sidecar(self):
        source = self.make("it's: #1.PDF")
        os.utime(source, (MTIME, MTIME))
        with stat_of(source):
            result, _, _ = self.run_command(source)
        text = sidecar_path(Path(result)).read_text()
        data = yaml.safe_load(text)
        self.assertEqual(data, {'results': {'ingest': {
            'at': '2026-10-25T14:03:07-07:00',
            'original-name': "it's: #1.PDF",
            'modified': local_time(MTIME),
            'source': {}}}})
        self.assertEqual(list(data['results']['ingest']),
                         ['at', 'original-name', 'modified', 'source'])
        self.assertIsNotNone(
            datetime.fromisoformat(data['results']['ingest']['at']).tzinfo)
        self.assertEqual(read_sidecar(Path(result)), data)

    def test_sidecar_with_creation_time(self):
        source = self.make('photo.jpg')
        os.utime(source, (MTIME, MTIME))
        with stat_of(source, BIRTHTIME):
            result, _, _ = self.run_command(source)
        ingest = read_sidecar(Path(result))['results']['ingest']
        self.assertEqual(list(ingest), ['at', 'original-name', 'created',
                                        'modified', 'source'])
        self.assertEqual(ingest['created'], local_time(BIRTHTIME))
        self.assertEqual(ingest['modified'], local_time(MTIME))

    def test_file_times_are_local_iso_to_the_second(self):
        value = file_time(MTIME + 0.75)
        parsed = datetime.fromisoformat(value)
        self.assertIsNotNone(parsed.tzinfo)
        self.assertEqual(parsed.timestamp(), MTIME)
        self.assertRegex(
            value, r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$')

    def test_ingest_record_file_times(self):
        without = ingest_record(CLOCK, 'a.pdf', {},
                                SimpleNamespace(st_mtime=MTIME))
        self.assertEqual(without['results']['ingest'], {
            'at': '2026-10-25T14:03:07-07:00', 'original-name': 'a.pdf',
            'modified': local_time(MTIME), 'source': {}})
        with_birth = ingest_record(
            CLOCK, 'a.pdf', {},
            SimpleNamespace(st_mtime=MTIME, st_birthtime=BIRTHTIME))
        self.assertEqual(with_birth['results']['ingest']['created'],
                         local_time(BIRTHTIME))
        self.assertNotIn('created', ingest_record(
            CLOCK, 'a.pdf', {}, None)['results']['ingest'])
        self.assertNotIn('modified', ingest_record(
            CLOCK, 'a.pdf', {})['results']['ingest'])

    def test_file_times_taken_before_the_move(self):
        source = self.make('a.pdf')
        os.utime(source, (MTIME, MTIME))
        real_rename = os.rename

        def touching_rename(src, dst):
            os.utime(src, (MTIME + 86400, MTIME + 86400))
            real_rename(src, dst)
        with patch('os.rename', touching_rename):
            result, _, _ = self.run_command(source)
        self.assertEqual(
            read_sidecar(Path(result))['results']['ingest']['modified'],
            local_time(MTIME))

    def test_collision_uses_next_millisecond(self):
        self.intake.mkdir(parents=True)
        (self.intake / (STAMP + '.pdf')).write_text('existing')
        result, _, _ = self.run_command(self.make('a.pdf', 'new'))
        self.assertEqual(Path(result).name, NEXT_STAMP + '.pdf')
        self.assertEqual((self.intake / (STAMP + '.pdf')).read_text(),
                         'existing')
        self.assertFalse((self.intake / (STAMP + '.pdf.yml')).exists())

    def test_existing_sidecar_takes_the_name(self):
        self.intake.mkdir(parents=True)
        (self.intake / (STAMP + '.pdf.yml')).write_text('orphan')
        result, _, _ = self.run_command(self.make('a.pdf'))
        self.assertEqual(Path(result).name, NEXT_STAMP + '.pdf')
        self.assertEqual((self.intake / (STAMP + '.pdf.yml')).read_text(),
                         'orphan')

    def test_sidecar_race_moves_on(self):
        # The sidecar appears after the check but before it is written
        real_open = open
        target = str(self.intake / (STAMP + '.pdf.yml'))

        def racing_open(file, mode='r', *args, **kwargs):
            if str(file) == target and mode == 'x':
                raise FileExistsError(file)
            return real_open(file, mode, *args, **kwargs)
        with patch('builtins.open', racing_open):
            result, _, _ = self.run_command(self.make('a.pdf'))
        self.assertEqual(Path(result).name, NEXT_STAMP + '.pdf')
        self.assertEqual(self.intake_names(),
                         [NEXT_STAMP + '.pdf', NEXT_STAMP + '.pdf.yml'])

    def test_name_race_moves_on(self):
        # The file appears after the stamp check but before the O_EXCL claim
        self.intake.mkdir(parents=True)
        existing = self.intake / (STAMP + '.pdf')
        existing.write_text('raced in')
        with patch('filez4eva.command.ingest_command.stamp_taken',
                   return_value=False):
            result, _, _ = self.run_command(self.make('a.pdf'))
        self.assertEqual(Path(result).name, NEXT_STAMP + '.pdf')
        self.assertEqual(existing.read_text(), 'raced in')

    def test_archived_sidecar_takes_the_name(self):
        # A document stowed earlier left STAMP.pdf.yml in the archive
        archive = self.intake / 'archive'
        archive.mkdir(parents=True)
        (archive / (STAMP + '.pdf.yml')).write_text('stowed')
        result, _, _ = self.run_command(self.make('a.pdf'))
        self.assertEqual(Path(result).name, NEXT_STAMP + '.pdf')
        # Another extension under the same stamp is free
        result, _, _ = self.run_command(self.make('b.jpg'))
        self.assertEqual(Path(result).name, STAMP + '.jpg')

    def test_repeated_collisions(self):
        self.intake.mkdir(parents=True)
        for ms in range(42, 45):
            (self.intake / f'20261025-140307-{ms:03d}').write_text('x')
        result, _, _ = self.run_command(self.make('plain'))
        self.assertEqual(Path(result).name, '20261025-140307-045')

    def test_one_stamp_per_document(self):
        # With the clock frozen, notes.md must not take STAMP + '.md', the
        # transcript name of notes
        self.make('notes', 'n')
        self.make('notes.md', 'user markdown')
        result, command, _ = self.run_command(self.source)
        self.assertEqual([Path(p).name for p in result.split('\n')],
                         [STAMP, NEXT_STAMP + '.md'])
        self.assertEqual(self.intake_names(), [
            STAMP, STAMP + '.yml', NEXT_STAMP + '.md',
            NEXT_STAMP + '.md.yml'])
        self.assertEqual((self.intake / (NEXT_STAMP + '.md')).read_text(),
                         'user markdown')

    def test_one_stamp_per_document_single_files(self):
        self.run_command(self.make('notes', 'n'))
        result, _, _ = self.run_command(self.make('notes.md', 'm'))
        self.assertEqual(Path(result).name, NEXT_STAMP + '.md')

    def test_existing_transcript_takes_the_stamp(self):
        # An existing document's transcript <stamp>.md (with or without the
        # document itself) makes the stamp taken for any extension
        self.intake.mkdir(parents=True)
        (self.intake / (STAMP + '.md')).write_text('# transcript')
        result, _, _ = self.run_command(self.make('a.pdf'))
        self.assertEqual(Path(result).name, NEXT_STAMP + '.pdf')
        self.assertEqual((self.intake / (STAMP + '.md')).read_text(),
                         '# transcript')

    def test_document_next_to_transcript_moves_on(self):
        first, _, _ = self.run_command(self.make('scan.pdf'))
        Path(first + '.md').write_text('# transcript')
        result, _, _ = self.run_command(self.make('other.pdf'))
        self.assertEqual(Path(result).name, NEXT_STAMP + '.pdf')
        result, _, _ = self.run_command(self.make('plain'))
        self.assertEqual(Path(result).name, '20261025-140307-044')

    def test_stamp_with_other_extension_is_taken(self):
        self.intake.mkdir(parents=True)
        (self.intake / (STAMP + '.docx.pdf')).write_text('existing')
        result, _, _ = self.run_command(self.make('plain'))
        self.assertEqual(Path(result).name, NEXT_STAMP)

    def test_similar_names_do_not_take_the_stamp(self):
        # Only `<stamp>` and `<stamp>.*` count, not e.g. `<stamp>0`
        self.intake.mkdir(parents=True)
        (self.intake / (STAMP + '0')).write_text('x')
        (self.intake / ('.' + STAMP + '.pdf')).write_text('x')
        result, _, _ = self.run_command(self.make('a.pdf'))
        self.assertEqual(Path(result).name, STAMP + '.pdf')

    def test_intake_lock_excludes_others(self):
        # While one holder has the lock, another open of the intake (as a
        # second process would make) can't take it
        self.intake.mkdir(parents=True)
        fd = os.open(self.intake, os.O_RDONLY)
        try:
            with intake_lock(self.intake):
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
        self.assertEqual(self.intake_names(), [])

    def test_reserve_holds_the_lock(self):
        # The stamp check runs under the intake lock
        self.intake.mkdir(parents=True)
        held = []

        def checking_stamp_taken(intake, stamp):
            fd = os.open(intake, os.O_RDONLY)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held.append(False)
            except BlockingIOError:
                held.append(True)
            finally:
                os.close(fd)
            return False
        with patch('filez4eva.command.ingest_command.stamp_taken',
                   checking_stamp_taken):
            self.run_command(self.make('a.pdf'))
        self.assertEqual(held, [True])

    def assert_one_stamp_per_document(self, expected):
        """Every file in the intake is a document or its sidecar, there are
        `expected` documents, and no two share a stamp"""
        names = self.intake_names()
        docs = [n for n in names if not n.endswith('.yml')
                or n[:-len('.yml')] not in names]
        self.assertEqual(len(docs), expected)
        self.assertEqual(sorted(n + '.yml' for n in docs),
                         sorted(set(names) - set(docs)))
        stamps = [n[:len(STAMP)] for n in docs]
        self.assertEqual(len(set(stamps)), len(stamps),
                         'two documents share a stamp')

    def test_concurrent_processes_get_unique_stamps(self):
        # Several processes ingest at once with the same frozen clock, so
        # every stamp they try is contested. Without the lock, documents
        # from different processes end up sharing stamps.
        context = multiprocessing.get_context('fork')
        workers, count = 6, 25
        barrier = context.Barrier(workers)
        processes = []
        for worker in range(workers):
            source = self.source / f'w{worker}'
            source.mkdir()
            for i in range(count):
                name = ['f{}', 'f{}.md', 'f{}.pdf'][i % 3].format(i)
                (source / name).write_text(f'{worker}/{name}')
            processes.append(context.Process(
                target=ingest_worker,
                args=(barrier, source, self.intake)))
        for process in processes:
            process.start()
        for process in processes:
            process.join(60)
            self.assertEqual(process.exitcode, 0)
        self.assert_one_stamp_per_document(workers * count)
        contents = sorted((self.intake / n).read_text()
                          for n in self.intake_names()
                          if not n.endswith('.yml')
                          or n[:-4] not in self.intake_names())
        self.assertEqual(len(set(contents)), workers * count)

    def test_concurrent_cli_runs_get_unique_stamps(self):
        # Separate `filez4eva ingest` runs, with the real clock, into one
        # intake
        runs, count = 4, 40
        env = dict(os.environ, HOME=str(self.source),
                   FILEZ4EVA_INTAKE=str(self.intake))
        commands = []
        for run in range(runs):
            source = self.source / f'r{run}'
            source.mkdir()
            for i in range(count):
                name = ['f{}', 'f{}.md', 'f{}.pdf', 'f{}.pdf.md'][i % 4]
                (source / name.format(i)).write_text(f'{run}/{i}')
            commands.append(subprocess.Popen(
                [sys.executable, '-m', 'filez4eva', 'ingest', str(source)],
                env=env, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL))
        for command in commands:
            self.assertEqual(command.wait(120), 0)
        self.assert_one_stamp_per_document(runs * count)

    def test_meta_flags(self):
        result, _, _ = self.run_command(
            self.make('a.pdf'), meta=['from=desktop', 'note=a=b'])
        self.assertEqual(
            read_sidecar(Path(result))['results']['ingest']['source'],
            {'from': 'desktop', 'note': 'a=b'})

    def test_stdin_and_flags_merge_with_flags_winning(self):
        stdin = "from: email\nsubject: Your bill\nid: 0123\n"
        result, _, _ = self.run_command(
            self.make('a.pdf'), stdin=stdin, meta=['from=desktop'])
        self.assertEqual(
            read_sidecar(Path(result))['results']['ingest']['source'],
            {'from': 'desktop', 'subject': 'Your bill', 'id': '0123'})

    def test_stdin_not_a_mapping_is_ignored(self):
        for stdin in ['- a\n- b\n', 'just text', ': [bad', '   ']:
            with self.subTest(stdin=stdin):
                source = self.make('a.pdf')
                result, _, _ = self.run_command(source, stdin=stdin)
                self.assertEqual(
                    read_sidecar(Path(result))['results']['ingest']
                    ['source'], {})
                self.now.return_value += timedelta(seconds=1)

    def test_bad_meta_is_error_and_moves_nothing(self):
        source = self.make('a.pdf')
        with self.assertRaises(Filez4EvaError):
            self.run_command(source, meta=['oops'])
        self.assertTrue(source.exists())

    def test_meta_from_app(self):
        source = self.make('a.pdf')
        out, err, code = self.run_app(
            '--meta', 'k=v', '-m', 'x=y', str(source), stdin='s: 1\n')
        self.assertEqual(code, 0)
        target = self.intake / (STAMP + '.pdf')
        self.assertEqual(out.strip(), str(target))
        self.assertEqual(plain(err), f'Ingesting {source}\nIngested\n')
        self.assertEqual(
            read_sidecar(target)['results']['ingest']['source'],
            {'s': '1', 'k': 'v', 'x': 'y'})

    def test_directory(self):
        self.make('b.pdf', 'b')
        self.make('a.pdf', 'a')
        self.make('.hidden', 'h')
        (self.source / 'sub').mkdir()
        (self.source / 'sub' / 'inner.pdf').write_text('i')
        (self.source / 'link.pdf').symlink_to(self.source / 'b.pdf')
        result, command, err = self.run_command(
            self.source, stdin='via: dir\n')
        # Each file is named on stderr before it is ingested
        self.assertEqual(plain(err).splitlines(), [
            f'Ingesting {self.source / "a.pdf"}',
            f'Ingesting {self.source / "b.pdf"}'])
        paths = [Path(p) for p in result.split('\n')]
        # Sorted order: a.pdf first, then b.pdf (1 ms later, since the
        # clock is frozen)
        self.assertEqual([p.name for p in paths],
                         [STAMP + '.pdf', NEXT_STAMP + '.pdf'])
        self.assertEqual(paths[0].read_text(), 'a')
        self.assertEqual(paths[1].read_text(), 'b')
        for path, name in zip(paths, ['a.pdf', 'b.pdf']):
            ingest = read_sidecar(path)['results']['ingest']
            self.assertEqual(ingest['original-name'], name)
            self.assertEqual(ingest['source'], {'via': 'dir'})
        self.assertEqual(command.status, 'Ingested 2 files')
        self.assertEqual(sorted(p.name for p in self.source.iterdir()),
                         ['.hidden', 'link.pdf', 'sub'])
        self.assertTrue((self.source / 'sub' / 'inner.pdf').is_file())

    def test_empty_directory(self):
        result, command, _ = self.run_command(self.source)
        self.assertEqual(result, '')
        self.assertEqual(command.status, 'No files to ingest')

    def in_intake(self, name, content='data'):
        self.intake.mkdir(parents=True, exist_ok=True)
        path = self.intake / name
        path.write_text(content)
        return path

    def test_already_ingested_file(self):
        doc = self.in_intake('20250101-000000-000.pdf')
        sidecar_path(doc).write_text('results: {}\n')
        result, command, _ = self.run_command(doc)
        self.assertIsNone(result)
        self.assertEqual(command.status, 'Already ingested')
        self.assertTrue(doc.is_file())
        self.assertEqual(sidecar_path(doc).read_text(), 'results: {}\n')
        self.assertEqual(self.intake_names(),
                         ['20250101-000000-000.pdf',
                          '20250101-000000-000.pdf.yml'])

    def test_already_ingested_exit_code_zero(self):
        doc = self.in_intake('d.pdf')
        sidecar_path(doc).write_text('results: {}\n')
        out, err, code = self.run_app(str(doc))
        self.assertEqual((out, err, code), ('', 'Already ingested\n', 0))

    def test_sidecar_file_argument_left_alone(self):
        doc = self.in_intake('d.pdf')
        sidecar = sidecar_path(doc)
        sidecar.write_text('results: {}\n')
        _, command, _ = self.run_command(sidecar)
        self.assertEqual(command.status, 'Already ingested')
        self.assertTrue(sidecar.is_file())

    def test_pair_outside_intake_is_ingested(self):
        # Outside the intake, X and X.yml are two new documents
        config = self.make('config', 'c')
        self.make('config.yml', 'y')
        self.make('config.md', 'm')
        result, command, _ = self.run_command(self.source)
        paths = [Path(p) for p in result.split('\n')]
        self.assertEqual(command.status, 'Ingested 3 files')
        self.assertEqual([read_sidecar(p)['results']['ingest']
                          ['original-name'] for p in paths],
                         ['config', 'config.md', 'config.yml'])
        # Each document gets its own stamp, so nothing lands on config's
        # sidecar or transcript name
        self.assertEqual([p.name for p in paths],
                         [STAMP, NEXT_STAMP + '.md',
                          '20261025-140307-044.yml'])
        self.assertEqual(list(self.source.iterdir()), [])
        self.assertFalse(config.exists())

    def test_single_file_with_pair_outside_intake_is_ingested(self):
        for name in ['config', 'config.yml']:
            with self.subTest(name=name):
                self.make('config', 'c')
                self.make('config.yml', 'y')
                source = self.source / name
                result, command, _ = self.run_command(source)
                self.assertEqual(command.status, 'Ingested')
                self.assertFalse(source.exists())
                self.assertEqual(
                    read_sidecar(Path(result))['results']['ingest']
                    ['original-name'], name)
                for leftover in self.source.iterdir():
                    leftover.unlink()
                self.now.return_value += timedelta(seconds=1)

    def test_ingesting_the_intake_skips_documents(self):
        # First ingest one file, then add a stray file to the intake and
        # ingest the intake itself
        first, _, _ = self.run_command(self.make('a.pdf'))
        first = Path(first)
        transcript = Path(str(first) + '.md')
        transcript.write_text('# text')
        (self.intake / 'Stray.PDF').write_text('stray')
        self.now.return_value = CLOCK + timedelta(seconds=1)
        result, command, _ = self.run_command(self.intake)
        self.assertEqual(Path(result).name, '20261025-140308-042.pdf')
        self.assertEqual(command.status,
                         'Ingested 1 file | Already ingested 1 file')
        self.assertEqual(self.intake_names(), sorted([
            first.name, first.name + '.yml', first.name + '.md',
            '20261025-140308-042.pdf', '20261025-140308-042.pdf.yml']))
        self.assertEqual(
            read_sidecar(first)['results']['ingest']['original-name'],
            'a.pdf')

    def test_directory_carries_on_after_failure(self):
        self.make('a.pdf', 'a')
        self.make('b.pdf', 'b')
        self.make('c.pdf', 'c')
        real_rename = os.rename

        def failing_rename(src, dst):
            if Path(src).name == 'b.pdf':
                raise PermissionError(errno.EACCES, 'denied', str(src))
            return real_rename(src, dst)
        with patch('os.rename', failing_rename):
            out, err, code = self.run_app(str(self.source))
        self.assertEqual(code, 1)
        lines = out.split()
        # b.pdf's reserved name was released, so c.pdf takes it
        self.assertEqual([Path(p).name for p in lines],
                         [STAMP + '.pdf', NEXT_STAMP + '.pdf'])
        self.assertIn('b.pdf', err)
        self.assertIn('denied', err)
        self.assertIn('1 of 3 files failed', err)
        # b.pdf stays put with nothing left behind in the intake for it
        self.assertEqual(sorted(p.name for p in self.source.iterdir()),
                         ['b.pdf'])
        self.assertEqual(self.intake_names(), [
            STAMP + '.pdf', STAMP + '.pdf.yml',
            NEXT_STAMP + '.pdf', NEXT_STAMP + '.pdf.yml'])

    def test_single_file_failure_exits_non_zero(self):
        source = self.make('a.pdf')
        with patch('os.rename', side_effect=PermissionError('denied')):
            out, err, code = self.run_app(str(source))
        self.assertEqual(code, 1)
        self.assertEqual(out, '')
        self.assertIn('denied', err)
        self.assertTrue(source.is_file())
        self.assertEqual(self.intake_names(), [])

    def test_failure_raises_in_debug(self):
        source = self.make('a.pdf')
        with patch('os.rename', side_effect=PermissionError('denied')), \
                self.assertRaises(PermissionError):
            self.run_command(source)

    def test_sidecar_write_failure_moves_nothing(self):
        source = self.make('a.pdf')
        with patch('filez4eva.command.ingest_command.format_sidecar',
                   side_effect=OSError('disk full')), \
                self.assertRaises(OSError):
            self.run_command(source)
        self.assertTrue(source.is_file())
        self.assertEqual(self.intake_names(), [])

    def test_cross_filesystem_move(self):
        source = self.make('a.pdf', 'content')
        os.chmod(source, 0o640)
        with patch('os.rename',
                   side_effect=OSError(errno.EXDEV, 'cross-device')):
            result, _, _ = self.run_command(source)
        target = Path(result)
        self.assertEqual(target.read_text(), 'content')
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        self.assertFalse(source.exists())
        self.assertTrue(sidecar_path(target).is_file())

    def test_cross_filesystem_copy_failure_cleans_up(self):
        source = self.make('a.pdf')
        with patch('os.rename',
                   side_effect=OSError(errno.EXDEV, 'cross-device')), \
                patch('shutil.copy2', side_effect=OSError('no space')), \
                self.assertRaises(OSError):
            self.run_command(source)
        self.assertTrue(source.is_file())
        self.assertEqual(self.intake_names(), [])

    def test_missing_path(self):
        with self.assertRaises(Filez4EvaError):
            self.run_command(self.source / 'missing.pdf')
        out, err, code = self.run_app(str(self.source / 'missing.pdf'))
        self.assertEqual(code, 1)
        self.assertIn('must exist', err)

    def test_symlink_argument_is_error(self):
        target = self.make('real.pdf')
        link = self.source / 'link.pdf'
        link.symlink_to(target)
        with self.assertRaises(Filez4EvaError):
            self.run_command(link)
        self.assertTrue(link.is_symlink())
