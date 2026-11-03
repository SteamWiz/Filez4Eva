"""Directory paths in the configuration (the top-level and cabinet
targets, the intake and FILEZ4EVA_INTAKE, the top-level and cabinet
transcripts roots) must be absolute or start with ~. A relative one is a
configuration error naming the key, raised before any file is touched or
any prompt."""

import os
from pathlib import Path
from unittest.mock import patch

import yaml
from wizlib.config_handler import ConfigHandler
from wizlib.test_case import WizLibTestCase

from filez4eva import Filez4EvaApp
from filez4eva.command.ingest_command import intake_dir, intake_path
from filez4eva.error import Filez4EvaError
from filez4eva.paths import absolute_path
from filez4eva.stow import load_cabinets


TRANSCRIBE = 'filez4eva.command.transcribe_command.transcribe'
EXTRACT = 'filez4eva.command.classify_command.extract'
RELATIVE = "must be an absolute path (or start with ~), not 'rel/dir'"


class TestAbsolutePath(WizLibTestCase):

    def test_absolute_is_kept(self):
        self.assertEqual(absolute_path('O', 'k', '/a/b'), Path('/a/b'))

    def test_home_is_expanded(self):
        home = os.environ['HOME']
        self.assertEqual(absolute_path('O', 'k', '~'), Path(home))
        self.assertEqual(absolute_path('O', 'k', '~/a'), Path(home) / 'a')

    def test_user_home_is_expanded(self):
        # pathlib expands just the ~user part
        with patch('os.path.expanduser', return_value='/home/someone'):
            self.assertEqual(absolute_path('O', 'k', '~someone/a'),
                             Path('/home/someone/a'))

    def test_relative_is_rejected(self):
        for value in ['rel/dir', './rel', '../rel', 'rel', '.']:
            with self.subTest(value=value), \
                    self.assertRaises(Filez4EvaError) as cm:
                absolute_path('Cabinet a', 'target', value)
            self.assertEqual(
                str(cm.exception),
                f"Cabinet a target must be an absolute path (or start "
                f"with ~), not {value!r}")

    def test_unknown_user_is_rejected(self):
        with self.assertRaises(Filez4EvaError) as cm:
            absolute_path('O', 'k', '~no-such-user-filez4eva/a')
        self.assertIn("O k must be an absolute path", str(cm.exception))


class TestTargets(WizLibTestCase):

    def load(self, **config):
        return load_cabinets(ConfigHandler.fake(**config))

    def test_top_target_relative_rejected(self):
        with self.assertRaises(Filez4EvaError) as cm:
            self.load(filez4eva_target='rel/dir')
        self.assertEqual(str(cm.exception),
                         f"Top-level filez4eva target {RELATIVE}")

    def test_top_target_relative_rejected_with_cabinets(self):
        # Unused when there are cabinets, but still checked
        with self.assertRaises(Filez4EvaError) as cm:
            self.load(filez4eva_target='rel/dir',
                      filez4eva_cabinets={'a': {'target': '/a'}})
        self.assertIn("Top-level filez4eva target", str(cm.exception))

    def test_top_target_absolute_and_home_accepted(self):
        home = os.environ['HOME']
        self.assertEqual(
            self.load(filez4eva_target='/a')['default'].targetdir,
            Path('/a'))
        cabinet = self.load(filez4eva_target='~/files')['default']
        self.assertEqual(cabinet.target, '~/files')
        self.assertEqual(cabinet.targetdir, Path(home) / 'files')

    def test_cabinet_target_relative_rejected(self):
        with self.assertRaises(Filez4EvaError) as cm:
            self.load(filez4eva_cabinets={'a': {'target': '/a'},
                                          'receipts': {'target': 'rel/dir'}})
        self.assertEqual(str(cm.exception),
                         f"Cabinet receipts target {RELATIVE}")

    def test_cabinet_target_absolute_and_home_accepted(self):
        home = os.environ['HOME']
        cabinets = self.load(filez4eva_cabinets={
            'a': {'target': '/a'}, 'b': {'target': '~/b'}})
        self.assertEqual(cabinets['a'].targetdir, Path('/a'))
        self.assertEqual(cabinets['b'].targetdir, Path(home) / 'b')


class TestTranscriptsRoots(WizLibTestCase):

    def load(self, **config):
        return load_cabinets(ConfigHandler.fake(**config))

    def test_top_root_relative_rejected(self):
        with self.assertRaises(Filez4EvaError) as cm:
            self.load(filez4eva_target='/a',
                      filez4eva_transcripts_location='parallel',
                      filez4eva_transcripts_root='rel/dir')
        self.assertEqual(str(cm.exception),
                         f"Top-level filez4eva transcripts root {RELATIVE}")

    def test_top_root_relative_rejected_when_adjacent(self):
        with self.assertRaises(Filez4EvaError) as cm:
            self.load(filez4eva_target='/a',
                      filez4eva_transcripts_root='rel/dir')
        self.assertIn("Top-level filez4eva transcripts root",
                      str(cm.exception))

    def test_top_root_absolute_and_home_accepted(self):
        home = os.environ['HOME']
        for root, wanted in [('/t', Path('/t')),
                             ('~/t', Path(home) / 't')]:
            with self.subTest(root=root):
                cabinet = self.load(
                    filez4eva_target='/a',
                    filez4eva_transcripts_location='parallel',
                    filez4eva_transcripts_root=root)['default']
                self.assertEqual(cabinet.transcripts_rootdir, wanted)

    def test_cabinet_root_relative_rejected(self):
        with self.assertRaises(Filez4EvaError) as cm:
            self.load(filez4eva_cabinets={
                'a': {'target': '/a'},
                'receipts': {'target': '/r',
                             'transcripts': {'root': 'rel/dir'}}})
        self.assertEqual(str(cm.exception),
                         f"Cabinet receipts transcripts root {RELATIVE}")

    def test_cabinet_root_absolute_and_home_accepted(self):
        home = os.environ['HOME']
        cabinets = self.load(filez4eva_cabinets={
            'a': {'target': '/a', 'transcripts': {
                'location': 'parallel', 'root': '/t'}},
            'b': {'target': '/b', 'transcripts': {
                'location': 'parallel', 'root': '~/t'}}})
        self.assertEqual(cabinets['a'].transcripts_rootdir, Path('/t'))
        self.assertEqual(cabinets['b'].transcripts_rootdir,
                         Path(home) / 't')


class TestIntake(WizLibTestCase):

    def test_config_relative_rejected(self):
        with self.assertRaises(Filez4EvaError) as cm:
            intake_dir(ConfigHandler.fake(filez4eva_intake='rel/dir'))
        self.assertEqual(
            str(cm.exception),
            f"filez4eva intake (or FILEZ4EVA_INTAKE) {RELATIVE}")

    def test_env_relative_rejected(self):
        with patch.dict(os.environ, {'FILEZ4EVA_INTAKE': 'rel/dir'}), \
                self.assertRaises(Filez4EvaError) as cm:
            intake_dir(ConfigHandler.fake())
        self.assertIn('FILEZ4EVA_INTAKE', str(cm.exception))

    def test_absolute_and_home_accepted(self):
        home = Path(os.environ['HOME'])
        self.assertEqual(
            intake_path(ConfigHandler.fake(filez4eva_intake='/i')),
            Path('/i'))
        self.assertEqual(
            intake_path(ConfigHandler.fake(filez4eva_intake='~/i')),
            home / 'i')
        with patch.dict(os.environ, {'FILEZ4EVA_INTAKE': '~/e'}):
            self.assertEqual(intake_dir(ConfigHandler.fake()), home / 'e')
        self.assertTrue((home / 'e').is_dir())

    def test_intake_path_creates_nothing(self):
        home = Path(os.environ['HOME'])
        intake_path(ConfigHandler.fake(filez4eva_intake='~/i'))
        self.assertFalse((home / 'i').exists())


class TestRejectedBeforeAnything(WizLibTestCase):
    """Through the app: a relative path fails the run before any file is
    touched, any intake is created or anything is asked"""

    def setUp(self):
        super().setUp()
        self.dir = Path(os.environ['HOME']).parent / 'work'
        self.dir.mkdir()
        self.source = self.dir / 'source'
        self.source.mkdir()
        self.file = self.source / 'a.pdf'
        self.file.write_text('%PDF-1.4 fake')
        self.intake = self.dir / 'intake'
        cwd = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, cwd)

    def run_app(self, settings, *args):
        """Run the app with a configuration file holding settings (under
        `filez4eva:`); return (stdout, stderr, exit code)"""
        config = self.dir / 'config.yml'
        config.write_text(yaml.safe_dump({'filez4eva': settings}))
        code = 0
        with patch(TRANSCRIBE) as t, patch(EXTRACT) as e, \
                patch('wizlib.io.ttyin') as tty, \
                self.patch_stream(''), self.patchout() as o, \
                self.patcherr() as err:
            try:
                Filez4EvaApp.start('--config', str(config), *args)
            except SystemExit as exit:
                code = exit.code
            o.seek(0)
            err.seek(0)
        t.assert_not_called()
        e.assert_not_called()
        tty.assert_not_called()
        return o.read(), err.read(), code

    def assert_untouched(self):
        self.assertTrue(self.file.is_file())
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         ['config.yml', 'source'])

    def assert_rejected(self, settings, message, commands=None):
        for command in commands or ['ingest', 'transcribe', 'classify',
                                    'review', 'stow']:
            with self.subTest(command=command):
                out, err, code = self.run_app(settings, command,
                                              str(self.file))
                self.assertEqual(code, 1)
                self.assertEqual(out, '')
                self.assertIn(message, err)
                self.assert_untouched()

    def test_relative_intake(self):
        self.assert_rejected({'intake': 'intake', 'target': '/t'},
                             "filez4eva intake (or FILEZ4EVA_INTAKE) must "
                             "be an absolute path")

    def test_relative_intake_from_env(self):
        with patch.dict(os.environ, {'FILEZ4EVA_INTAKE': 'intake'}):
            self.assert_rejected({'target': '/t'}, 'FILEZ4EVA_INTAKE')

    def test_relative_top_target(self):
        self.assert_rejected(
            {'intake': str(self.intake), 'target': 'target'},
            "Top-level filez4eva target must be an absolute path",
            ['classify', 'review', 'stow'])

    def test_relative_target_of_unused_cabinet(self):
        self.assert_rejected(
            {'intake': str(self.intake),
             'cabinets': {'a': {'target': str(self.dir / 'a')},
                          'b': {'target': 'b'}}},
            "Cabinet b target must be an absolute path",
            ['classify', 'review', 'stow'])
        # Even with --cabinet naming the other one
        out, err, code = self.run_app(
            {'intake': str(self.intake),
             'cabinets': {'a': {'target': str(self.dir / 'a')},
                          'b': {'target': 'b'}}},
            'stow', '-c', 'a', str(self.file))
        self.assertEqual(code, 1)
        self.assertIn("Cabinet b target must be an absolute path", err)
        self.assert_untouched()

    def test_relative_top_transcripts_root(self):
        self.assert_rejected(
            {'intake': str(self.intake), 'target': '/t',
             'transcripts': {'location': 'parallel', 'root': 'tr'}},
            "Top-level filez4eva transcripts root must be an absolute path",
            ['classify', 'review', 'stow'])

    def test_relative_cabinet_transcripts_root(self):
        self.assert_rejected(
            {'intake': str(self.intake),
             'cabinets': {'a': {'target': '/a',
                                'transcripts': {'root': 'tr'}}}},
            "Cabinet a transcripts root must be an absolute path",
            ['classify', 'review', 'stow'])
