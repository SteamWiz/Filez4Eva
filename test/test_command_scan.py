from io import StringIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from filez4eva.command.scan_dir_command import StowDirCommand
from filez4eva.command import Filez4EvaCommand
from filez4eva import Filez4EvaApp

from wizlib.config_handler import ConfigHandler
from wizlib.app import AppCancellation
from wizlib.test_case import WizLibTestCase


class TestCommandScan(WizLibTestCase):

    def test_dir(self):
        sourcefn1: str = 'b.txt'
        sourcefn2: str = 'c.txt'
        sourcecontent: str = 'a'
        stowedpath1: str = '/2024/j/20240213-t.txt'
        stowedpath2: str = '/2023/k/20231211-u.txt'
        keys = 's20240213\nj\nt\ns20231211\nk\nu\n'
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
            c = StowDirCommand(a, dir=str(source))
            c.execute()
            with open(target + stowedpath1, 'r') as f:
                r1 = f.read()
            with open(target + stowedpath2, 'r') as f:
                r2 = f.read()
        self.assertEqual(r1 + r2, 'aa')
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
            c = StowDirCommand(a, dir=str(source))
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
            c = StowDirCommand(a, dir=str(source))
            c.execute()
            nx = [x.name for x in Path(source).iterdir()]
        self.assertEqual(nx, ['c.txt'])

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
            c = StowDirCommand(a, dir=str(source))
            c.execute()
            rm.assert_called_once()

    def test_from_app(self):
        sourcefn1: str = 'b.txt'
        sourcefn2: str = 'c.txt'
        sourcecontent: str = 'a'
        stowedpath1: str = '/2024/j/20240213-t.txt'
        stowedpath2: str = '/2023/k/20231211-u.txt'
        keys = 's20240213\nj\nt\ns20231211\nk\nu\n'
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
            a.parse_run('stow-dir', source)
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
        stowedpath1: str = '/2024/j/20240213-t.txt'
        stowedpath2: str = '/2023/k/20231211-u.txt'
        keys = 's20240213\nj\nt\ns20231211\nk\nu\n'
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
            a.parse_run('stow-dir')
            with open(target + stowedpath1, 'r') as f:
                r1 = f.read()
            with open(target + stowedpath2, 'r') as f:
                r2 = f.read()
        self.assertEqual(r1 + r2, 'aa')
        e.seek(0)
        self.assertIn('Stowed 2 files', e.read())
