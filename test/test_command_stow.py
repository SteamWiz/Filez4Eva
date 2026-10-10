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


class TestStowFileStdin(WizLibTestCase):
    """stow-file reads date, account and part from a YAML mapping on stdin"""

    def stow(self, stdin, *args, ttyin=''):
        """Run stow-file via the app with the given stdin text and typed
        input; return (destination files under target, stderr text)"""
        with \
                TemporaryDirectory() as targetd, \
                TemporaryDirectory() as sourced, \
                self.patchout(), \
                self.patcherr() as e, \
                self.patch_stream(stdin), \
                self.patch_ttyin(ttyin) as t:
            sourcep = Path(sourced) / 'b.txt'
            sourcep.write_text('a')
            with NamedTemporaryFile('w+') as cf:
                cf.write(f"filez4eva:\n  target: {targetd}\n")
                cf.seek(0)
                Filez4EvaApp.start('--config', cf.name, 'stow-file',
                                   str(sourcep), *args, debug=True)
            files = sorted(str(p.relative_to(targetd))
                           for p in Path(targetd).rglob('*') if p.is_file())
            e.seek(0)
            return files, e.read(), t

    def test_all_values_from_stdin(self):
        files, _, t = self.stow('date: 20240213\naccount: j\npart: t\n')
        self.assertEqual(files, ['2024/j/20240213-t.txt'])
        t.assert_not_called()

    def test_iso_date_from_stdin(self):
        files, _, _ = self.stow('date: 2024-02-13\naccount: j\npart: t\n')
        self.assertEqual(files, ['2024/j/20240213-t.txt'])

    def test_quoted_date_from_stdin(self):
        files, _, _ = self.stow("date: '20240213'\naccount: j\npart: t\n")
        self.assertEqual(files, ['2024/j/20240213-t.txt'])

    def test_unknown_keys_ignored(self):
        files, _, t = self.stow(
            'date: 20240213\naccount: j\npart: t\nsummary: x\ntags: [a]\n')
        self.assertEqual(files, ['2024/j/20240213-t.txt'])
        t.assert_not_called()

    def test_flags_override_stdin(self):
        files, _, t = self.stow('date: 20240213\naccount: j\npart: t\n',
                                '--date', '20230101', '--account', 'k',
                                '--part', 'u')
        self.assertEqual(files, ['2023/k/20230101-u.txt'])
        t.assert_not_called()

    def test_one_flag_overrides_stdin(self):
        files, _, _ = self.stow('date: 20240213\naccount: j\npart: t\n',
                                '--account', 'k')
        self.assertEqual(files, ['2024/k/20240213-t.txt'])

    def test_partial_stdin_prompts_for_rest(self):
        files, _, _ = self.stow('date: 20240213\n', ttyin='j\nt\n')
        self.assertEqual(files, ['2024/j/20240213-t.txt'])

    def test_blank_stdin_values_prompted(self):
        files, _, _ = self.stow("date: 20240213\naccount: ''\npart:\n",
                                ttyin='j\nt\n')
        self.assertEqual(files, ['2024/j/20240213-t.txt'])

    def test_empty_stdin_prompts_as_before(self):
        files, _, _ = self.stow('', ttyin='20240213\nj\nt\n')
        self.assertEqual(files, ['2024/j/20240213-t.txt'])

    def test_non_mapping_stdin_ignored(self):
        files, _, _ = self.stow('- a\n- b\n', ttyin='20240213\nj\nt\n')
        self.assertEqual(files, ['2024/j/20240213-t.txt'])

    def test_malformed_stdin_ignored(self):
        files, _, _ = self.stow('date: [unclosed\n',
                                ttyin='20240213\nj\nt\n')
        self.assertEqual(files, ['2024/j/20240213-t.txt'])

    def test_bad_stdin_date_raises(self):
        with self.assertRaises(Filez4EvaError):
            self.stow('date: 20240299\naccount: j\npart: t\n')

    def test_no_stream_handler(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n = Path(source) / 'b.txt'
            n.write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target)
            del a.stream
            c = StowFileCommand(a, file=str(n), date='20240213', account='j',
                                part='t')
            with self.patchout():
                c.execute()
            self.assertTrue((Path(target) / '2024/j/20240213-t.txt').is_file())

    # YAML 1.1 scalars must stay as typed (no octal, booleans, etc.)

    def test_leading_zero_part_kept(self):
        files, _, _ = self.stow('date: 20240213\naccount: j\npart: 0123\n')
        self.assertEqual(files, ['2024/j/20240213-0123.txt'])

    def test_leading_zero_account_kept(self):
        files, _, _ = self.stow('date: 20240213\naccount: 0042\npart: t\n')
        self.assertEqual(files, ['2024/0042/20240213-t.txt'])

    def test_yes_no_kept(self):
        files, _, _ = self.stow('date: 20240213\naccount: yes\npart: no\n')
        self.assertEqual(files, ['2024/yes/20240213-no.txt'])

    def test_non_scalar_stdin_value_raises(self):
        with self.assertRaises(Filez4EvaError):
            self.stow('date: 20240213\naccount: [a, b]\npart: t\n')

    # Stdin is untrusted: account and part must be one safe path segment

    def assert_rejected(self, stdin):
        with TemporaryDirectory() as outside:
            with self.assertRaises(Filez4EvaError):
                self.stow(stdin.replace('OUTSIDE', outside))
            self.assertEqual(list(Path(outside).rglob('*')), [])

    def test_account_traversal_rejected(self):
        self.assert_rejected('date: 20240213\naccount: ../../escaped\n'
                             'part: t\n')

    def test_account_absolute_rejected(self):
        self.assert_rejected('date: 20240213\naccount: OUTSIDE\npart: t\n')

    def test_account_dot_rejected(self):
        self.assert_rejected('date: 20240213\naccount: "."\npart: t\n')

    def test_account_dotdot_rejected(self):
        self.assert_rejected('date: 20240213\naccount: ..\npart: t\n')

    def test_account_backslash_rejected(self):
        self.assert_rejected('date: 20240213\naccount: a\\b\npart: t\n')

    def test_part_traversal_rejected(self):
        self.assert_rejected('date: 20240213\naccount: j\n'
                             'part: ../../../pwned\n')

    def test_part_bad_characters_rejected(self):
        self.assert_rejected('date: 20240213\naccount: j\npart: a.b\n')

    def test_bad_stdin_rejected_before_prompting(self):
        # With no typed input, a date prompt would cancel instead of raising
        with self.assertRaises(Filez4EvaError):
            self.stow('account: ../x\n')

    # The same checks apply to flags and prompts

    def test_flag_account_traversal_rejected(self):
        with self.assertRaises(Filez4EvaError):
            self.stow('', '--date', '20240213', '--account', '../x',
                      '--part', 't')

    def test_prompted_part_traversal_rejected(self):
        with self.assertRaises(Filez4EvaError):
            self.stow('', ttyin='20240213\nj\n../x\n')


class TestScanDirIgnoresStdin(WizLibTestCase):

    def test_scan_dir_stow_does_not_use_stdin(self):
        from filez4eva.command.scan_dir_command import ScanDirCommand
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            (Path(source) / 'b.txt').write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target)
            a.stream = Mock(text='date: 20240213\naccount: j\npart: t\n')
            c = ScanDirCommand(a, dir=source)
            with patch('filez4eva.command.scan_dir_command.StowFileCommand')\
                    as s, \
                    patch.object(a.ui, 'get_option', return_value='stow'), \
                    patch.object(a.ui, 'send'):
                c.execute()
            s.assert_called_once_with(a, file=str(Path(source) / 'b.txt'),
                                      use_stdin=False)

    def test_use_stdin_false_skips_record(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n = Path(source) / 'b.txt'
            n.write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target)
            a.stream = Mock(text='date: 20230101\naccount: k\npart: u\n')
            c = StowFileCommand(a, file=str(n), date='20240213', account='j',
                                part='t', use_stdin=False)
            c.apply_stdin_record = Mock()
            with self.patchout():
                c.execute()
            c.apply_stdin_record.assert_not_called()
            self.assertTrue((Path(target) / '2024/j/20240213-t.txt').is_file())
