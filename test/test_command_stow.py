from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from filez4eva import Filez4EvaApp
from filez4eva.command.stow_file_command import StowFileCommand
from filez4eva.error import Filez4EvaError

from wizlib.stream_handler import StreamHandler
from wizlib.config_handler import ConfigHandler
from wizlib.test_case import WizLibTestCase


class TestStowCommand(WizLibTestCase):

    def test_file(self):
        sourcefn: str = 'b.txt'
        sourcecontent: str = 'a'
        date: str = '20240213'
        account: str = 'j'
        part: str = 't'
        stowedpath: str = '/2024/j/20240213-t.txt'
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n = Path(source) / sourcefn
            with open(n, 'w') as f:
                f.write(sourcecontent)
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(
                filez4eva_target=target)
            c = StowFileCommand(a, file=str(n), date=date, account=account,
                                part=part)
            with self.patchout() as o:
                c.execute()
            with open(target + stowedpath, 'r') as f:
                r = f.read()
        self.assertEqual(r, 'a')

    def test_returns_destination_path(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n = Path(source) / 'b.txt'
            with open(n, 'w') as f:
                f.write('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target)
            c = StowFileCommand(a, file=str(n), date='20240213', account='j',
                                part='t')
            with self.patchout():
                r = c.execute()
            expected = Path(target) / '2024/j/20240213-t.txt'
            self.assertTrue(Path(r).is_absolute())
            self.assertEqual(Path(r), expected)
            self.assertTrue(Path(r).is_file())

    def test_returns_absolute_path_for_relative_target(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as cwd, \
                patch('os.getcwd', return_value=cwd):
            n = Path(source) / 'b.txt'
            with open(n, 'w') as f:
                f.write('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target='.')
            c = StowFileCommand(a, file=str(n), date='20240213', account='j',
                                part='t')
            with self.patchout():
                r = c.execute()
            self.assertTrue(Path(r).is_absolute())
            self.assertEqual(Path(r), Path(cwd) / '2024/j/20240213-t.txt')
            self.assertTrue(Path(r).is_file())

    def test_error_if_no_source(self):
        sourcefn: str = 'b.txt'
        date: str = '20240213'
        account: str = 'j'
        part: str = 't'
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n = Path(source) / sourcefn
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(
                filez4eva_source=source,
                filez4eva_target=target)
            c = StowFileCommand(a,
                                file=str(n),
                                date=date,
                                account=account,
                                part=part)
            with self.patchout() as o, \
                    self.assertRaises(Filez4EvaError):
                c.execute()

    def test_error_if_file_already_exists(self):
        sourcefn: str = 'b.txt'
        sourcecontent: str = 'a'
        date: str = '20240213'
        account: str = 'j'
        part: str = 't'
        stowedpath: str = '2024/j/20240213-t.txt'
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n = Path(source) / sourcefn
            with open(n, 'w') as f:
                f.write(sourcecontent)
            n2 = Path(target) / stowedpath
            n2.parent.mkdir(parents=True)
            with open(n2, 'w') as f2:
                f2.write('-')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(
                filez4eva_source=source,
                filez4eva_target=target)
            c = StowFileCommand(a, file=str(n), date=date, account=account,
                                part=part)
            with patch('sys.stdout', o := StringIO()), \
                    self.assertRaises(Filez4EvaError):
                c.execute()

    def test_from_app(self):
        with TemporaryDirectory() as target, \
                TemporaryDirectory() as sd, \
                patch('sys.stderr', e := StringIO()), \
                patch('sys.stdout', StringIO()):
            sp = Path(sd) / 'b.txt'
            with open(sp, 'w') as sf:
                sf.write('a')
            with NamedTemporaryFile('w+') as cf:
                cf.writelines([
                    f"filez4eva:\n",
                    f"  target: {target}\n"])
                cf.seek(0)
                Filez4EvaApp.start('--config', cf.name, 'stow-file', str(sp),
                                   '--date', '20240213', '--account', 'j',
                                   '--part', 't', debug=True)
            with open(target + '/2024/j/20240213-t.txt') as of:
                r = of.read()
        self.assertEqual(r, 'a')

    def test_input_date(self):
        d = '20240213\n'
        with \
                TemporaryDirectory() as targetd, \
                TemporaryDirectory() as sourced, \
                self.patchout(), \
                self.patcherr() as e, \
                self.patch_ttyin(d):
            sourcep = Path(sourced) / 'b.txt'
            with open(sourcep, 'w') as sourcef:
                sourcef.write('a')
            with NamedTemporaryFile('w+') as cf:
                cf.writelines([
                    f"filez4eva:\n",
                    f"  target: {targetd}\n"])
                cf.seek(0)
                Filez4EvaApp.start('--config', cf.name, 'stow-file',
                                   str(sourcep), '--account', 'j',
                                   '--part', 't', debug=True)
            with open(targetd + '/2024/j/20240213-t.txt') as of:
                r = of.read()
        self.assertEqual(r, 'a')

    def test_input_all(self):
        d = '20240213\nj\nt\n'
        with \
                TemporaryDirectory() as targetd, \
                TemporaryDirectory() as sourced, \
                self.patchout(), \
                self.patcherr() as e, \
                self.patch_ttyin(d):
            sourcep = Path(sourced) / 'b.txt'
            with open(sourcep, 'w') as sourcef:
                sourcef.write('a')
            with NamedTemporaryFile('w+') as cf:
                cf.writelines([
                    f"filez4eva:\n",
                    f"  target: {targetd}\n"])
                cf.seek(0)
                Filez4EvaApp.start('--config', cf.name, 'stow-file',
                                   str(sourcep), debug=True)
            with open(targetd + '/2024/j/20240213-t.txt') as of:
                r = of.read()
        self.assertEqual(r, 'a')

    def test_date_format(self):
        d = '20240299\n20240317\n'
        with \
                TemporaryDirectory() as targetd, \
                TemporaryDirectory() as sourced, \
                self.patchout() as o, \
                self.patcherr() as e, \
                self.patch_ttyin(d):
            sourcep = Path(sourced) / 'b.txt'
            with open(sourcep, 'w') as sourcef:
                sourcef.write('a')
            with NamedTemporaryFile('w+') as cf:
                cf.writelines([
                    f"filez4eva:\n",
                    f"  target: {targetd}\n"])
                cf.seek(0)
                Filez4EvaApp.start('--config', cf.name, 'stow-file',
                                   str(sourcep), '--account', 'j',
                                   '--part', 't', debug=True)
            with open(targetd + '/2024/j/20240317-t.txt') as of:
                r = of.read()
        self.assertEqual(r, 'a')
        e.seek(0)
        self.assertIn('format', e.read())

    def test_output(self):
        with \
                TemporaryDirectory() as target, \
                TemporaryDirectory() as sd, \
                patch('sys.stderr', e := StringIO()), \
                patch('sys.stdout', StringIO()):
            sp = Path(sd) / 'b.txt'
            with open(sp, 'w') as sf:
                sf.write('a')
            with NamedTemporaryFile('w+') as cf:
                cf.writelines([
                    f"filez4eva:\n",
                    f"  target: {target}\n"])
                cf.seek(0)
                Filez4EvaApp.start('--config', cf.name, 'stow-file', str(sp),
                                   '--date', '20240213', '--account', 'j',
                                   '--part', 't', debug=True)
            e.seek(0)
            r = e.read()
        self.assertEqual(r, 'Done\n')

    def test_stdout_is_destination_path(self):
        with \
                TemporaryDirectory() as target, \
                TemporaryDirectory() as sd, \
                patch('sys.stderr', StringIO()), \
                patch('sys.stdout', o := StringIO()):
            sp = Path(sd) / 'b.txt'
            with open(sp, 'w') as sf:
                sf.write('a')
            with NamedTemporaryFile('w+') as cf:
                cf.writelines([
                    f"filez4eva:\n",
                    f"  target: {target}\n"])
                cf.seek(0)
                Filez4EvaApp.start('--config', cf.name, 'stow-file', str(sp),
                                   '--date', '20240213', '--account', 'j',
                                   '--part', 't', debug=True)
            printed = Path(o.getvalue().strip())
            actual = Path(target) / '2024/j/20240213-t.txt'
            self.assertTrue(printed.is_absolute())
            self.assertTrue(actual.is_file())
            self.assertEqual(printed.resolve(), actual.resolve())

    def test_parts(self):
        paths = [
            '2024/j/20240213-t.txt',
            '2022/j/20240815-c.txt',
            '2026/k/20240815-p.txt']
        with \
                TemporaryDirectory() as dir:
            for path in paths:
                p = Path(dir) / path
                p.parent.mkdir(parents=True, exist_ok=True)
                with open(p, 'w') as f:
                    f.write('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=dir)
            c = StowFileCommand(a)
            x = c.get_parts('j')
        self.assertEqual(x, ['c', 't'])
