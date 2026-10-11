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

    # Prompts re-ask on an invalid value instead of raising

    def test_invalid_prompted_part_reasked(self):
        files, err, _ = self.stow(
            '', ttyin='20240213\nj\n../x\nbank statement\nt\n')
        self.assertEqual(files, ['2024/j/20240213-t.txt'])
        self.assertEqual(err.count('Part must contain only'), 2)

    def test_invalid_prompted_account_reasked(self):
        files, err, _ = self.stow('', ttyin='20240213\n../x\nj\nt\n')
        self.assertEqual(files, ['2024/j/20240213-t.txt'])
        self.assertIn('Account must be a single directory name', err)

    # YAML null spellings are treated as missing

    def test_null_stdin_values_prompted(self):
        files, _, _ = self.stow('date: 20240213\naccount: ~\npart: null\n',
                                ttyin='j\nt\n')
        self.assertEqual(files, ['2024/j/20240213-t.txt'])


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


class TestStowFilePattern(WizLibTestCase):
    """The destination layout comes from the `filez4eva: pattern:` key"""

    CUSTOM = '{account}/{year}/{part}-{date}{ext}'

    def stow(self, target, pattern, source):
        n = Path(source) / 'b.txt'
        n.write_text('a')
        a = Filez4EvaApp()
        a.config = ConfigHandler.fake(filez4eva_target=target,
                                      filez4eva_pattern=pattern)
        c = StowFileCommand(a, file=str(n), date='20240213', account='j',
                            part='t')
        with self.patchout():
            return n, c.execute()

    def assert_rejected(self, pattern):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            with self.assertRaises(Filez4EvaError):
                n, _ = self.stow(target, pattern, source)
            self.assertTrue((Path(source) / 'b.txt').is_file())
            self.assertEqual(list(Path(target).iterdir()), [])

    def test_custom_pattern(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n, r = self.stow(target, self.CUSTOM, source)
            expected = Path(target) / 'j/2024/t-20240213.txt'
            self.assertEqual(Path(r), expected)
            self.assertEqual(expected.read_text(), 'a')
            self.assertFalse(n.exists())

    def test_flat_pattern(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            _, r = self.stow(target, '{date}-{account}-{part}{ext}', source)
            self.assertEqual(Path(r), Path(target) / '20240213-j-t.txt')
            self.assertTrue(Path(r).is_file())

    def test_explicit_default_pattern(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            _, r = self.stow(target, '{year}/{account}/{date}-{part}{ext}',
                             source)
            self.assertEqual(Path(r), Path(target) / '2024/j/20240213-t.txt')

    def test_custom_pattern_from_app(self):
        with TemporaryDirectory() as target, \
                TemporaryDirectory() as sd, \
                patch('sys.stderr', StringIO()), \
                patch('sys.stdout', o := StringIO()):
            sp = Path(sd) / 'b.txt'
            sp.write_text('a')
            with NamedTemporaryFile('w+') as cf:
                cf.write(f"filez4eva:\n  target: {target}\n"
                         f"  pattern: '{self.CUSTOM}'\n")
                cf.seek(0)
                Filez4EvaApp.start('--config', cf.name, 'stow-file', str(sp),
                                   '--date', '20240213', '--account', 'j',
                                   '--part', 't', debug=True)
            actual = Path(target) / 'j/2024/t-20240213.txt'
            self.assertEqual(actual.read_text(), 'a')
            self.assertEqual(Path(o.getvalue().strip()), actual)

    def test_unknown_placeholder_rejected(self):
        self.assert_rejected('{year}/{foo}/{date}-{part}{ext}')

    def test_unknown_placeholder_message(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            with self.assertRaises(Filez4EvaError) as cm:
                self.stow(target, '{foo}{ext}', source)
        self.assertIn('{foo}', str(cm.exception))

    def test_malformed_pattern_rejected(self):
        self.assert_rejected('{year/{account}{ext}')

    def test_stray_close_brace_rejected(self):
        self.assert_rejected('{year}}/{account}{ext}')

    def test_positional_rejected(self):
        self.assert_rejected('{}/{account}{ext}')

    def test_numbered_rejected(self):
        self.assert_rejected('{0}/{account}{ext}')

    def test_attribute_rejected(self):
        self.assert_rejected('{year.real}/{account}{ext}')

    def test_index_rejected(self):
        self.assert_rejected('{account[0]}/{part}{ext}')

    def test_format_spec_rejected(self):
        self.assert_rejected('{account:>10}/{part}{ext}')

    def test_conversion_rejected(self):
        self.assert_rejected('{account!r}/{part}{ext}')

    def test_empty_pattern_uses_default(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            _, r = self.stow(target, '', source)
            self.assertEqual(Path(r), Path(target) / '2024/j/20240213-t.txt')

    def test_blank_pattern_rejected(self):
        self.assert_rejected('   ')

    def test_absolute_pattern_rejected(self):
        self.assert_rejected('/tmp/{account}/{part}{ext}')

    def test_home_pattern_rejected(self):
        self.assert_rejected('~/{account}/{part}{ext}')

    def test_parent_pattern_rejected(self):
        self.assert_rejected('../{account}/{part}{ext}')

    def test_inner_parent_pattern_rejected(self):
        self.assert_rejected('{account}/../../{part}{ext}')

    def test_pattern_naming_target_rejected(self):
        self.assert_rejected('.')

    def test_bad_pattern_rejected_before_prompting(self):
        with TemporaryDirectory() as target, \
                TemporaryDirectory() as sd, \
                self.patchout(), \
                self.patcherr(), \
                self.patch_ttyin('20240213\nj\nt\n'):
            sp = Path(sd) / 'b.txt'
            sp.write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target,
                                          filez4eva_pattern='{foo}{ext}')
            c = StowFileCommand(a, file=str(sp))
            with patch.object(StowFileCommand, 'prompt_value') as pv, \
                    self.assertRaises(Filez4EvaError):
                c.execute()
            pv.assert_not_called()
            self.assertTrue(sp.is_file())

    def test_custom_pattern_prompts_without_completion(self):
        with TemporaryDirectory() as target, \
                TemporaryDirectory() as sd, \
                self.patchout(), \
                self.patcherr(), \
                self.patch_ttyin('20240213\nj\nt\n'):
            (Path(target) / '2023/k').mkdir(parents=True)
            sp = Path(sd) / 'b.txt'
            sp.write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target,
                                          filez4eva_pattern=self.CUSTOM)
            c = StowFileCommand(a, file=str(sp), use_stdin=False)
            r = c.execute()
            self.assertEqual(Path(r), Path(target) / 'j/2024/t-20240213.txt')
            self.assertTrue(Path(r).is_file())

    def test_completion_empty_for_custom_pattern(self):
        with TemporaryDirectory() as target:
            p = Path(target) / '2024/j/20240213-t.txt'
            p.parent.mkdir(parents=True)
            p.write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target,
                                          filez4eva_pattern=self.CUSTOM)
            c = StowFileCommand(a)
            self.assertEqual(c.get_accounts(), [])
            self.assertEqual(c.get_parts('j'), [])

    def test_completion_for_default_pattern(self):
        with TemporaryDirectory() as target:
            p = Path(target) / '2024/j/20240213-t.txt'
            p.parent.mkdir(parents=True)
            p.write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target)
            c = StowFileCommand(a)
            self.assertEqual(c.get_accounts(), ['j'])
            self.assertEqual(c.get_parts('j'), ['t'])

    def test_destination_outside_target_rejected(self):
        # Defence in depth: even if the pattern check were bypassed, the
        # formatted destination must stay inside the target
        with patch('filez4eva.command.stow_file_command.check_pattern'):
            self.assert_rejected('../{account}{ext}')


class TestStowFileCabinets(WizLibTestCase):
    """Multiple named destinations from the `filez4eva: cabinets:` key"""

    CUSTOM = '{account}/{year}/{part}-{date}{ext}'

    def run_app(self, config, *args, stdin='', ttyin=''):
        """Run stow-file via the app with a YAML config body (indented under
        `filez4eva:`); return (stderr text, ttyin mock)"""
        with \
                TemporaryDirectory() as sourced, \
                self.patchout(), \
                self.patcherr() as e, \
                self.patch_stream(stdin), \
                self.patch_ttyin(ttyin) as t:
            sourcep = Path(sourced) / 'b.txt'
            sourcep.write_text('a')
            with NamedTemporaryFile('w+') as cf:
                cf.write('filez4eva:\n' + config)
                cf.seek(0)
                Filez4EvaApp.start('--config', cf.name, 'stow-file',
                                   str(sourcep), *args, debug=True)
            e.seek(0)
            return e.read(), t

    @staticmethod
    def files(dir):
        return sorted(str(p.relative_to(dir))
                      for p in Path(dir).rglob('*') if p.is_file())

    def two_cabinets(self, a, b):
        return (f"  cabinets:\n"
                f"    accounts:\n"
                f"      target: {a}\n"
                f"      description: Personal account records\n"
                f"    memories:\n"
                f"      target: {b}\n")

    # Legacy config: an implicit 'default' cabinet, no prompt

    def test_legacy_target(self):
        with TemporaryDirectory() as target:
            _, t = self.run_app(f"  target: {target}\n",
                                stdin='date: 20240213\naccount: j\npart: t\n')
            self.assertEqual(self.files(target), ['2024/j/20240213-t.txt'])
            t.assert_not_called()

    def test_legacy_target_and_pattern(self):
        with TemporaryDirectory() as target:
            _, t = self.run_app(
                f"  target: {target}\n  pattern: '{self.CUSTOM}'\n",
                stdin='date: 20240213\naccount: j\npart: t\n')
            self.assertEqual(self.files(target), ['j/2024/t-20240213.txt'])
            t.assert_not_called()

    def test_legacy_default_name(self):
        a = Filez4EvaApp()
        a.config = ConfigHandler.fake(filez4eva_target='/x',
                                      filez4eva_pattern=self.CUSTOM)
        c = StowFileCommand(a)
        cabinet = c.resolve_cabinet()
        self.assertEqual(list(c.cabinets), ['default'])
        self.assertEqual(cabinet.name, 'default')
        self.assertEqual(cabinet.pattern, self.CUSTOM)
        self.assertEqual(c.cabinet, 'default')

    def test_legacy_cabinet_flag(self):
        with TemporaryDirectory() as target:
            self.run_app(f"  target: {target}\n", '-c', 'default',
                         stdin='date: 20240213\naccount: j\npart: t\n')
            self.assertEqual(self.files(target), ['2024/j/20240213-t.txt'])

    def test_no_target_raises(self):
        with self.assertRaises(Filez4EvaError):
            self.run_app("  source: /tmp\n",
                         stdin='date: 20240213\naccount: j\npart: t\n')

    def test_empty_cabinets_uses_target(self):
        with TemporaryDirectory() as target:
            self.run_app(f"  target: {target}\n  cabinets: {{}}\n",
                         stdin='date: 20240213\naccount: j\npart: t\n')
            self.assertEqual(self.files(target), ['2024/j/20240213-t.txt'])

    # One cabinet: used without a prompt; top-level target ignored

    def test_single_cabinet(self):
        with TemporaryDirectory() as target, \
                TemporaryDirectory() as ignored:
            _, t = self.run_app(
                f"  target: {ignored}\n"
                f"  cabinets:\n    only:\n      target: {target}\n",
                stdin='date: 20240213\naccount: j\npart: t\n')
            self.assertEqual(self.files(target), ['2024/j/20240213-t.txt'])
            self.assertEqual(self.files(ignored), [])
            t.assert_not_called()

    def test_single_cabinet_direct(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n = Path(source) / 'b.txt'
            n.write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(
                filez4eva_cabinets={'only': {'target': target}})
            c = StowFileCommand(a, file=str(n), date='20240213', account='j',
                                part='t', use_stdin=False)
            with self.patchout():
                r = c.execute()
            self.assertEqual(Path(r), Path(target) / '2024/j/20240213-t.txt')

    # Several cabinets: flag, stdin or prompt

    def test_cabinet_from_flag(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            _, t = self.run_app(self.two_cabinets(a, b), '--cabinet',
                                'memories',
                                stdin='date: 20240213\naccount: j\npart: t\n')
            self.assertEqual(self.files(a), [])
            self.assertEqual(self.files(b), ['2024/j/20240213-t.txt'])
            t.assert_not_called()

    def test_cabinet_from_short_flag(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            self.run_app(self.two_cabinets(a, b), '-c', 'accounts',
                         stdin='date: 20240213\naccount: j\npart: t\n')
            self.assertEqual(self.files(a), ['2024/j/20240213-t.txt'])

    def test_cabinet_from_stdin(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            _, t = self.run_app(
                self.two_cabinets(a, b),
                stdin='cabinet: memories\ndate: 20240213\naccount: j\n'
                      'part: t\n')
            self.assertEqual(self.files(b), ['2024/j/20240213-t.txt'])
            t.assert_not_called()

    def test_flag_overrides_stdin_cabinet(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            self.run_app(self.two_cabinets(a, b), '-c', 'accounts',
                         stdin='cabinet: memories\ndate: 20240213\n'
                               'account: j\npart: t\n')
            self.assertEqual(self.files(a), ['2024/j/20240213-t.txt'])
            self.assertEqual(self.files(b), [])

    def test_cabinet_from_prompt(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            self.run_app(self.two_cabinets(a, b),
                         stdin='date: 20240213\naccount: j\npart: t\n',
                         ttyin='memories\n')
            self.assertEqual(self.files(b), ['2024/j/20240213-t.txt'])

    def test_prompt_completes_cabinet_names(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as a, \
                TemporaryDirectory() as b:
            n = Path(source) / 'b.txt'
            n.write_text('a')
            app = Filez4EvaApp()
            app.config = ConfigHandler.fake(filez4eva_cabinets={
                'zeta': {'target': a}, 'alpha': {'target': b}})
            c = StowFileCommand(app, file=str(n), date='20240213',
                                account='j', part='t', use_stdin=False)
            with patch.object(app.ui, 'get_text', return_value='zeta') as gt, \
                    self.patchout():
                r = c.execute()
            gt.assert_called_once_with('Cabinet: ', ['alpha', 'zeta'])
            self.assertEqual(Path(r), Path(a) / '2024/j/20240213-t.txt')

    def test_cabinet_prompted_before_date(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            self.run_app(self.two_cabinets(a, b), '-a', 'j', '-p', 't',
                         ttyin='accounts\n20240213\n')
            self.assertEqual(self.files(a), ['2024/j/20240213-t.txt'])

    def test_invalid_prompted_cabinet_reasked(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            err, _ = self.run_app(
                self.two_cabinets(a, b),
                stdin='date: 20240213\naccount: j\npart: t\n',
                ttyin='nope\naccounts\n')
            self.assertEqual(self.files(a), ['2024/j/20240213-t.txt'])
            self.assertIn('Cabinet must be one of: accounts, memories', err)

    def test_empty_prompted_cabinet_cancels(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            err, _ = self.run_app(
                self.two_cabinets(a, b),
                stdin='date: 20240213\naccount: j\npart: t\n', ttyin='\n')
            self.assertEqual(self.files(a) + self.files(b), [])
            self.assertIn('Cabinet required', err)

    def test_unknown_cabinet_flag_raises(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            with self.assertRaises(Filez4EvaError) as cm:
                self.run_app(self.two_cabinets(a, b), '-c', 'nope',
                             stdin='date: 20240213\naccount: j\npart: t\n')
            self.assertIn('Unknown cabinet nope', str(cm.exception))
            self.assertIn('accounts, memories', str(cm.exception))
            self.assertEqual(self.files(a) + self.files(b), [])

    def test_unknown_cabinet_stdin_raises(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            with self.assertRaises(Filez4EvaError):
                self.run_app(self.two_cabinets(a, b),
                             stdin='cabinet: nope\ndate: 20240213\n'
                                   'account: j\npart: t\n')
            self.assertEqual(self.files(a) + self.files(b), [])

    def test_unknown_cabinet_flag_single_cabinet_raises(self):
        with TemporaryDirectory() as target:
            with self.assertRaises(Filez4EvaError):
                self.run_app(f"  target: {target}\n", '-c', 'nope',
                             stdin='date: 20240213\naccount: j\npart: t\n')

    def test_non_scalar_stdin_cabinet_raises(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            with self.assertRaises(Filez4EvaError):
                self.run_app(self.two_cabinets(a, b),
                             stdin='cabinet: [accounts]\ndate: 20240213\n'
                                   'account: j\npart: t\n')

    # Completion and pattern come from the chosen cabinet

    def test_completion_uses_chosen_cabinet(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            (Path(a) / '2024/bank').mkdir(parents=True)
            (Path(a) / '2024/bank/20240101-statement.pdf').write_text('x')
            (Path(b) / '2023/trip').mkdir(parents=True)
            (Path(b) / '2023/trip/20230101-photo.jpg').write_text('x')
            app = Filez4EvaApp()
            app.config = ConfigHandler.fake(filez4eva_cabinets={
                'accounts': {'target': a}, 'memories': {'target': b}})
            c = StowFileCommand(app, cabinet='memories')
            self.assertEqual(c.get_accounts(), ['trip'])
            self.assertEqual(c.get_parts('trip'), ['photo'])
            c = StowFileCommand(app, cabinet='accounts')
            self.assertEqual(c.get_accounts(), ['bank'])
            self.assertEqual(c.get_parts('bank'), ['statement'])

    def test_prompt_completion_uses_chosen_cabinet(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as a, \
                TemporaryDirectory() as b:
            (Path(b) / '2023/trip').mkdir(parents=True)
            (Path(b) / '2023/trip/20230101-photo.jpg').write_text('x')
            n = Path(source) / 'b.txt'
            n.write_text('a')
            app = Filez4EvaApp()
            app.config = ConfigHandler.fake(filez4eva_cabinets={
                'accounts': {'target': a}, 'memories': {'target': b}})
            c = StowFileCommand(app, file=str(n), date='20240213',
                                use_stdin=False)
            answers = iter(['memories', 'trip', 'photo'])
            with patch.object(app.ui, 'get_text',
                              side_effect=lambda *x: next(answers)) as gt, \
                    self.patchout():
                c.execute()
            self.assertEqual(gt.call_args_list[1].args,
                             ('Account: ', ['trip']))
            self.assertEqual(gt.call_args_list[2].args,
                             ('Part: ', ['photo']))
            self.assertTrue(
                (Path(b) / '2024/trip/20240213-photo.txt').is_file())

    def test_per_cabinet_pattern(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            config = (f"  pattern: '{{date}}-{{account}}-{{part}}{{ext}}'\n"
                      f"  cabinets:\n"
                      f"    accounts:\n"
                      f"      target: {a}\n"
                      f"    memories:\n"
                      f"      target: {b}\n"
                      f"      pattern: '{self.CUSTOM}'\n")
            stdin = 'date: 20240213\naccount: j\npart: t\n'
            self.run_app(config, '-c', 'memories', stdin=stdin)
            self.run_app(config, '-c', 'accounts', stdin=stdin)
            self.assertEqual(self.files(b), ['j/2024/t-20240213.txt'])
            # The top-level pattern is the default for other cabinets
            self.assertEqual(self.files(a), ['20240213-j-t.txt'])

    def test_cabinet_default_pattern(self):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(
            filez4eva_cabinets={'x': {'target': '/x', 'pattern': ''}})
        c = StowFileCommand(app)
        self.assertEqual(c.pattern, '{year}/{account}/{date}-{part}{ext}')

    def test_description_kept(self):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(filez4eva_cabinets={
            'x': {'target': '~/x', 'description': 'Things'},
            'y': {'target': '/y'}})
        c = StowFileCommand(app)
        self.assertEqual(c.cabinets['x'].description, 'Things')
        self.assertIsNone(c.cabinets['y'].description)
        self.assertEqual(c.cabinets['x'].targetdir,
                         Path('~/x').expanduser())

    # Configuration errors raise before prompting or moving anything

    def assert_config_rejected(self, cabinets, message=None):
        with TemporaryDirectory() as source:
            n = Path(source) / 'b.txt'
            n.write_text('a')
            app = Filez4EvaApp()
            app.config = ConfigHandler.fake(filez4eva_cabinets=cabinets)
            c = StowFileCommand(app, file=str(n), use_stdin=False)
            with patch.object(StowFileCommand, 'prompt_value') as pv, \
                    patch.object(app.ui, 'get_text') as gt, \
                    self.assertRaises(Filez4EvaError) as cm:
                c.execute()
            pv.assert_not_called()
            gt.assert_not_called()
            self.assertTrue(n.is_file())
            if message:
                self.assertIn(message, str(cm.exception))

    def test_cabinet_missing_target_raises(self):
        self.assert_config_rejected(
            {'a': {'target': '/a'}, 'b': {'pattern': '{part}{ext}'}},
            'Cabinet b must have a target')

    def test_cabinet_empty_entry_raises(self):
        self.assert_config_rejected({'a': None}, 'Cabinet a must have')

    def test_cabinet_non_mapping_entry_raises(self):
        self.assert_config_rejected({'a': '/a'}, 'Cabinet a must be a')

    def test_cabinets_not_mapping_raises(self):
        self.assert_config_rejected(['a', 'b'], 'must be a mapping')

    def test_cabinet_bad_name_raises(self):
        self.assert_config_rejected({2024: {'target': '/a'}}, 'name')

    def test_cabinet_bad_description_raises(self):
        self.assert_config_rejected(
            {'a': {'target': '/a', 'description': ['x']}}, 'description')

    def test_cabinet_bad_pattern_raises(self):
        self.assert_config_rejected(
            {'a': {'target': '/a'},
             'b': {'target': '/b', 'pattern': '{foo}{ext}'}}, '{foo}')


class TestStowFileTranscript(WizLibTestCase):
    """A transcript (FILE.md) is moved with the file, named after it"""

    def command(self, source, target):
        n = Path(source) / 'b.txt'
        n.write_text('a')
        a = Filez4EvaApp()
        a.config = ConfigHandler.fake(filez4eva_target=target)
        c = StowFileCommand(a, file=str(n), date='20240213', account='j',
                            part='t', use_stdin=False)
        return n, c

    def test_transcript_moved_and_renamed(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n, c = self.command(source, target)
            t = Path(source) / 'b.txt.md'
            t.write_text('# transcript')
            with self.patchout():
                r = c.execute()
            dest = Path(target) / '2024/j/20240213-t.txt'
            self.assertEqual(Path(r), dest)
            self.assertEqual(dest.read_text(), 'a')
            self.assertEqual(Path(str(dest) + '.md').read_text(),
                             '# transcript')
            self.assertFalse(n.exists())
            self.assertFalse(t.exists())

    def test_no_transcript_unchanged(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n, c = self.command(source, target)
            with self.patchout():
                r = c.execute()
            dest = Path(target) / '2024/j/20240213-t.txt'
            self.assertEqual(Path(r), dest)
            files = sorted(str(p.relative_to(target))
                           for p in Path(target).rglob('*') if p.is_file())
            self.assertEqual(files, ['2024/j/20240213-t.txt'])
            self.assertEqual(list(Path(source).iterdir()), [])

    def test_transcript_collision_moves_nothing(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n, c = self.command(source, target)
            t = Path(source) / 'b.txt.md'
            t.write_text('# new')
            dest = Path(target) / '2024/j/20240213-t.txt'
            dest_t = Path(str(dest) + '.md')
            dest_t.parent.mkdir(parents=True)
            dest_t.write_text('# existing')
            with self.patchout(), \
                    self.assertRaises(Filez4EvaError) as cm:
                c.execute()
            self.assertIn(str(dest_t), str(cm.exception))
            self.assertEqual(n.read_text(), 'a')
            self.assertEqual(t.read_text(), '# new')
            self.assertFalse(dest.exists())
            self.assertEqual(dest_t.read_text(), '# existing')

    def test_transcript_move_failure_rolls_back(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n, c = self.command(source, target)
            t = Path(source) / 'b.txt.md'
            t.write_text('# transcript')
            with self.patchout(), \
                    patch('shutil.move', side_effect=OSError('boom')), \
                    self.assertRaises(Filez4EvaError):
                c.execute()
            self.assertEqual(n.read_text(), 'a')
            self.assertEqual(t.read_text(), '# transcript')
            self.assertFalse(
                (Path(target) / '2024/j/20240213-t.txt').exists())


class TestStowFileTranscriptLocation(WizLibTestCase):
    """The transcript goes adjacent to the file (default) or into a parallel
    tree under a configured root"""

    @staticmethod
    def files(dir):
        return sorted(str(p.relative_to(dir))
                      for p in Path(dir).rglob('*') if p.is_file())

    def stow(self, source, transcript=True, cabinet=None, **config):
        """Stow source/b.txt (with a transcript if asked) using a fake
        config; return the destination path"""
        n = Path(source) / 'b.txt'
        n.write_text('a')
        if transcript:
            (Path(source) / 'b.txt.md').write_text('# transcript')
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(**config)
        extra = {'cabinet': cabinet} if cabinet else {}
        c = StowFileCommand(app, file=str(n), date='20261002',
                            account='acct', part='part', use_stdin=False,
                            **extra)
        with self.patchout():
            return Path(c.execute())

    def run_app(self, config, *args, transcript=True):
        """Run stow-file via the app with a YAML config body (indented under
        `filez4eva:`), so nested blocks are flattened as in real use"""
        with TemporaryDirectory() as sourced, \
                self.patchout(), self.patcherr():
            sourcep = Path(sourced) / 'b.pdf'
            sourcep.write_text('a')
            if transcript:
                (Path(sourced) / 'b.pdf.md').write_text('# transcript')
            with NamedTemporaryFile('w+') as cf:
                cf.write('filez4eva:\n' + config)
                cf.seek(0)
                Filez4EvaApp.start('--config', cf.name, 'stow-file',
                                   str(sourcep), '-d', '20261002', '-a',
                                   'acct', '-p', 'part', *args, debug=True)
            return self.files(sourced)

    def test_adjacent_by_default(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            dest = self.stow(source, filez4eva_target=target)
            self.assertEqual(self.files(target),
                             ['2026/acct/20261002-part.txt',
                              '2026/acct/20261002-part.txt.md'])
            self.assertEqual(dest, Path(target) /
                             '2026/acct/20261002-part.txt')
            self.assertEqual(self.files(source), [])

    def test_explicit_adjacent(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            self.stow(source, filez4eva_target=target,
                      filez4eva_transcripts_location='adjacent')
            self.assertEqual(self.files(target),
                             ['2026/acct/20261002-part.txt',
                              '2026/acct/20261002-part.txt.md'])

    def test_parallel(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                TemporaryDirectory() as root:
            dest = self.stow(source, filez4eva_target=target,
                             filez4eva_transcripts_location='parallel',
                             filez4eva_transcripts_root=root)
            self.assertEqual(dest, Path(target) /
                             '2026/acct/20261002-part.txt')
            self.assertEqual(self.files(target),
                             ['2026/acct/20261002-part.txt'])
            # The implicit cabinet is named 'default'
            self.assertEqual(self.files(root),
                             ['default/2026/acct/20261002-part.txt.md'])
            self.assertEqual(
                (Path(root) / 'default/2026/acct/20261002-part.txt.md')
                .read_text(), '# transcript')
            self.assertEqual(self.files(source), [])

    def test_parallel_root_expands_home(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                TemporaryDirectory() as home, \
                patch.dict('os.environ', {'HOME': home}):
            self.stow(source, filez4eva_target=target,
                      filez4eva_transcripts_location='parallel',
                      filez4eva_transcripts_root='~/transcripts')
            self.assertEqual(
                self.files(home),
                ['transcripts/default/2026/acct/20261002-part.txt.md'])

    def test_parallel_named_cabinet_from_app(self):
        with TemporaryDirectory() as target, TemporaryDirectory() as root:
            left = self.run_app(f"  transcripts:\n"
                                f"    location: parallel\n"
                                f"    root: {root}\n"
                                f"  cabinets:\n"
                                f"    accounts:\n"
                                f"      target: {target}\n")
            self.assertEqual(left, [])
            self.assertEqual(self.files(target),
                             ['2026/acct/20261002-part.pdf'])
            self.assertEqual(self.files(root),
                             ['accounts/2026/acct/20261002-part.pdf.md'])

    def test_parallel_uses_cabinet_pattern(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                TemporaryDirectory() as root:
            self.stow(source, filez4eva_target=target,
                      filez4eva_pattern='{account}/{part}-{date}{ext}',
                      filez4eva_transcripts_location='parallel',
                      filez4eva_transcripts_root=root)
            self.assertEqual(self.files(root),
                             ['default/acct/part-20261002.txt.md'])

    def test_cabinet_overrides_to_adjacent(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b, \
                TemporaryDirectory() as root:
            config = (f"  transcripts:\n"
                      f"    location: parallel\n"
                      f"    root: {root}\n"
                      f"  cabinets:\n"
                      f"    accounts:\n"
                      f"      target: {a}\n"
                      f"    memories:\n"
                      f"      target: {b}\n"
                      f"      transcripts:\n"
                      f"        location: adjacent\n")
            self.run_app(config, '-c', 'memories')
            self.assertEqual(self.files(b),
                             ['2026/acct/20261002-part.pdf',
                              '2026/acct/20261002-part.pdf.md'])
            self.assertEqual(self.files(root), [])
            self.run_app(config, '-c', 'accounts')
            self.assertEqual(self.files(a), ['2026/acct/20261002-part.pdf'])
            self.assertEqual(self.files(root),
                             ['accounts/2026/acct/20261002-part.pdf.md'])

    def test_cabinet_overrides_to_parallel(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b, \
                TemporaryDirectory() as root:
            config = (f"  transcripts:\n"
                      f"    root: {root}\n"
                      f"  cabinets:\n"
                      f"    accounts:\n"
                      f"      target: {a}\n"
                      f"    memories:\n"
                      f"      target: {b}\n"
                      f"      transcripts:\n"
                      f"        location: parallel\n")
            self.run_app(config, '-c', 'accounts')
            self.assertEqual(self.files(a),
                             ['2026/acct/20261002-part.pdf',
                              '2026/acct/20261002-part.pdf.md'])
            # The cabinet's location falls back to the top-level root
            self.run_app(config, '-c', 'memories')
            self.assertEqual(self.files(b), ['2026/acct/20261002-part.pdf'])
            self.assertEqual(self.files(root),
                             ['memories/2026/acct/20261002-part.pdf.md'])

    def test_cabinet_specific_root(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as root, \
                TemporaryDirectory() as own:
            config = (f"  transcripts:\n"
                      f"    location: parallel\n"
                      f"    root: {root}\n"
                      f"  cabinets:\n"
                      f"    accounts:\n"
                      f"      target: {a}\n"
                      f"      transcripts:\n"
                      f"        root: {own}\n")
            self.run_app(config)
            self.assertEqual(self.files(root), [])
            self.assertEqual(self.files(own),
                             ['accounts/2026/acct/20261002-part.pdf.md'])

    def test_cabinet_values_resolved(self):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(
            filez4eva_transcripts_location='parallel',
            filez4eva_transcripts_root='/t',
            filez4eva_cabinets={
                'a': {'target': '/a'},
                'b': {'target': '/b', 'transcripts': {'root': '~/x'}},
                'c': {'target': '/c',
                      'transcripts': {'location': 'adjacent'}}})
        c = StowFileCommand(app)
        self.assertEqual((c.cabinets['a'].transcripts_location,
                          c.cabinets['a'].transcripts_root),
                         ('parallel', '/t'))
        self.assertEqual(c.cabinets['b'].transcripts_rootdir,
                         Path('~/x').expanduser())
        self.assertEqual(c.cabinets['c'].transcripts_location, 'adjacent')

    def test_default_values(self):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(filez4eva_target='/x')
        cabinet = StowFileCommand(app).cabinets['default']
        self.assertEqual(cabinet.transcripts_location, 'adjacent')
        self.assertIsNone(cabinet.transcripts_root)
        self.assertIsNone(cabinet.transcripts_rootdir)

    def test_parallel_no_transcript_creates_nothing(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                TemporaryDirectory() as root:
            self.stow(source, transcript=False, filez4eva_target=target,
                      filez4eva_transcripts_location='parallel',
                      filez4eva_transcripts_root=root)
            self.assertEqual(self.files(target),
                             ['2026/acct/20261002-part.txt'])
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_parallel_collision_moves_nothing(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                TemporaryDirectory() as root:
            existing = Path(root) / 'default/2026/acct/20261002-part.txt.md'
            existing.parent.mkdir(parents=True)
            existing.write_text('# existing')
            with self.assertRaises(Filez4EvaError) as cm:
                self.stow(source, filez4eva_target=target,
                          filez4eva_transcripts_location='parallel',
                          filez4eva_transcripts_root=root)
            self.assertIn(str(existing), str(cm.exception))
            self.assertEqual(self.files(source), ['b.txt', 'b.txt.md'])
            self.assertEqual(self.files(target), [])
            self.assertEqual(existing.read_text(), '# existing')

    def test_parallel_move_failure_rolls_back(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                TemporaryDirectory() as root:
            def move(src, dst):
                # Simulate a cross-filesystem copy that fails part way
                Path(dst).write_text('# part')
                raise OSError('boom')
            with patch('shutil.move', move), \
                    self.assertRaises(Filez4EvaError):
                self.stow(source, filez4eva_target=target,
                          filez4eva_transcripts_location='parallel',
                          filez4eva_transcripts_root=root)
            self.assertEqual(self.files(source), ['b.txt', 'b.txt.md'])
            self.assertEqual((Path(source) / 'b.txt.md').read_text(),
                             '# transcript')
            self.assertEqual(self.files(target), [])
            self.assertEqual(self.files(root), [])

    def test_odd_cabinet_name_rejected(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                TemporaryDirectory() as root:
            with self.assertRaises(Filez4EvaError) as cm:
                self.stow(source, cabinet='..',
                          filez4eva_transcripts_location='parallel',
                          filez4eva_transcripts_root=root,
                          filez4eva_cabinets={'..': {'target': target}})
            self.assertIn('outside', str(cm.exception))
            self.assertEqual(self.files(source), ['b.txt', 'b.txt.md'])
            self.assertEqual(self.files(target), [])

    # Configuration errors raise before prompting or moving anything

    def assert_config_rejected(self, message, **config):
        with TemporaryDirectory() as source:
            n = Path(source) / 'b.txt'
            n.write_text('a')
            app = Filez4EvaApp()
            app.config = ConfigHandler.fake(**config)
            c = StowFileCommand(app, file=str(n), use_stdin=False)
            with patch.object(StowFileCommand, 'prompt_value') as pv, \
                    patch.object(app.ui, 'get_text') as gt, \
                    self.assertRaises(Filez4EvaError) as cm:
                c.execute()
            pv.assert_not_called()
            gt.assert_not_called()
            self.assertTrue(n.is_file())
            self.assertIn(message, str(cm.exception))

    def test_invalid_location_raises(self):
        self.assert_config_rejected(
            "Cabinet default has invalid transcripts location 'beside'",
            filez4eva_target='/x', filez4eva_transcripts_location='beside')

    def test_invalid_cabinet_location_raises(self):
        self.assert_config_rejected(
            "Cabinet b has invalid transcripts location 'nowhere'",
            filez4eva_cabinets={
                'a': {'target': '/a'},
                'b': {'target': '/b',
                      'transcripts': {'location': 'nowhere'}}})

    def test_parallel_without_root_raises(self):
        self.assert_config_rejected(
            "Cabinet default transcripts location 'parallel' needs a root",
            filez4eva_target='/x',
            filez4eva_transcripts_location='parallel')

    def test_parallel_blank_root_raises(self):
        self.assert_config_rejected(
            "needs a root",
            filez4eva_target='/x',
            filez4eva_transcripts_location='parallel',
            filez4eva_transcripts_root='  ')

    def test_cabinet_parallel_without_root_raises(self):
        self.assert_config_rejected(
            "Cabinet a transcripts location 'parallel' needs a root",
            filez4eva_cabinets={
                'a': {'target': '/a',
                      'transcripts': {'location': 'parallel'}}})

    def test_non_text_root_raises(self):
        self.assert_config_rejected(
            "Cabinet a transcripts root must be text",
            filez4eva_cabinets={
                'a': {'target': '/a', 'transcripts': {'root': ['x']}}})

    def test_non_mapping_transcripts_raises(self):
        self.assert_config_rejected(
            "Cabinet a transcripts must be a mapping",
            filez4eva_cabinets={'a': {'target': '/a',
                                      'transcripts': 'parallel'}})

    def test_invalid_location_from_app_raises(self):
        with TemporaryDirectory() as target:
            with self.assertRaises(Filez4EvaError):
                self.run_app(f"  target: {target}\n"
                             f"  transcripts:\n"
                             f"    location: sideways\n")
            self.assertEqual(self.files(target), [])
