from io import StringIO
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from filez4eva.command.scan_dir_command import ScanDirCommand
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
            c = ScanDirCommand(a, dir=str(source))
            c.execute()
            with open(target + stowedpath1, 'r') as f:
                r1 = f.read()
            with open(target + stowedpath2, 'r') as f:
                r2 = f.read()
        self.assertEqual(r1 + r2, 'aa')
        self.assertEqual(c.status, 'Stowed 2 files')

    def test_invalid_prompted_part_does_not_abort(self):
        # A typo at the part prompt re-asks; the session carries on to the
        # next file instead of ending.
        keys = 's20240213\nj\nbank statement\nt\ns20231211\nk\nu\n'
        with \
                TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                self.patchout(), \
                self.patcherr() as e, \
                self.patch_ttyin(keys):
            for fn in ['b.txt', 'c.txt']:
                (Path(source) / fn).write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target)
            c = ScanDirCommand(a, dir=str(source))
            c.execute()
            self.assertTrue(
                (Path(target) / '2024/j/20240213-t.txt').is_file())
            self.assertTrue(
                (Path(target) / '2023/k/20231211-u.txt').is_file())
            e.seek(0)
            self.assertIn('Part must contain only', e.read())
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
            c = ScanDirCommand(a, dir=str(source))
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
            c = ScanDirCommand(a, dir=str(source))
            c.execute()
            nx = [x.name for x in Path(source).iterdir()]
        self.assertEqual(nx, ['c.txt'])

    def _run_delete_declined(self, keys):
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
            c = ScanDirCommand(a, dir=str(source))
            c.execute()
            nx = [x.name for x in Path(source).iterdir()]
        self.assertEqual(nx, ['b.txt'])
        self.assertEqual(c.status, 'Skipped 1 file')

    def test_delete_declined_default(self):
        # Enter at the confirmation takes the default ('No')
        self._run_delete_declined('d\nx')

    def test_delete_declined_explicit(self):
        self._run_delete_declined('dNx')

    def test_delete_prompt(self):
        self.assertEqual(ScanDirCommand.DELETE_CHOOSER.prompt_string,
                         'Delete? [No] (Y)es: ')

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
            c = ScanDirCommand(a, dir=str(source))
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
            a.parse_run('scan-dir', source)
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
            a.parse_run('scan-dir')
            with open(target + stowedpath1, 'r') as f:
                r1 = f.read()
            with open(target + stowedpath2, 'r') as f:
                r2 = f.read()
        self.assertEqual(r1 + r2, 'aa')
        e.seek(0)
        self.assertIn('Stowed 2 files', e.read())

    def test_cabinet_prompted_per_file(self):
        # With several cabinets, each stowed file asks for its cabinet
        keys = 'smemories\n20240213\nj\nt\nsaccounts\n20231211\nk\nu\n'
        with \
                TemporaryDirectory() as source, \
                TemporaryDirectory() as a, \
                TemporaryDirectory() as b, \
                self.patchout(), \
                self.patcherr(), \
                self.patch_ttyin(keys):
            for fn in ['b.txt', 'c.txt']:
                (Path(source) / fn).write_text('a')
            app = Filez4EvaApp()
            app.config = ConfigHandler.fake(filez4eva_cabinets={
                'accounts': {'target': a}, 'memories': {'target': b}})
            c = ScanDirCommand(app, dir=str(source))
            c.execute()
            self.assertTrue((Path(b) / '2024/j/20240213-t.txt').is_file())
            self.assertTrue((Path(a) / '2023/k/20231211-u.txt').is_file())
        self.assertEqual(c.status, 'Stowed 2 files')

    def _run_scan(self, files, keys):
        with \
                TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                self.patchout() as o, \
                self.patcherr() as e, \
                self.patch_ttyin(keys):
            for fn in files:
                (Path(source) / fn).write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target)
            c = ScanDirCommand(a, dir=str(source))
            c.execute()
            remaining = sorted(x.name for x in Path(source).iterdir())
            e.seek(0)
            out = e.read()
        return c, remaining, out

    def test_transcript_skipped(self):
        c, remaining, out = self._run_scan(['b.txt', 'b.txt.md'], 'x')
        self.assertEqual(c.status, 'Skipped 1 file')
        self.assertNotIn('b.txt.md', out)
        self.assertEqual(remaining, ['b.txt', 'b.txt.md'])

    def test_standalone_md_offered(self):
        c, remaining, out = self._run_scan(['notes.md'], 'x')
        self.assertEqual(c.status, 'Skipped 1 file')
        self.assertIn('notes.md', out)

    def test_transcript_removed_on_delete(self):
        c, remaining, out = self._run_scan(['b.txt', 'b.txt.md'], 'dY')
        self.assertEqual(c.status, 'Deleted 1 file')
        self.assertEqual(remaining, [])

    def test_delete_without_transcript_keeps_other_md(self):
        c, remaining, out = self._run_scan(['b.txt', 'c.txt.md'], 'dYx')
        self.assertEqual(c.status, 'Deleted 1 file | Skipped 1 file')
        self.assertEqual(remaining, ['c.txt.md'])

    def test_transcript_not_offered_after_stow(self):
        c, remaining, out = self._run_scan(
            ['b.txt', 'b.txt.md'], 's20240213\nj\nt\n')
        self.assertEqual(c.status, 'Stowed 1 file')
        self.assertEqual(remaining, ['b.txt.md'])
