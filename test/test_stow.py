from io import StringIO
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from unittest.mock import Mock, patch

import yaml

"""Tests for Stower and the cabinets in filez4eva/stow.py: reading a
record from --field flags, stdin and prompts, patterns, fields, learned
values, cabinets and transcripts. The stow command itself is tested in
test_command_stow_stage.py."""

from filez4eva import Filez4EvaApp
from filez4eva.command.stow_command import StowCommand
from filez4eva.error import Filez4EvaError
from filez4eva.fields import (
    MAX_SUGGESTIONS, Field, load_store, normalize_value, record_values,
    suggestions, values_path)
from filez4eva.stow import Cabinet, Stower, remember_values

from wizlib.command import CommandCancellation
from wizlib.config_handler import ConfigHandler
from wizlib.parser import WizParser
from wizlib.test_case import WizLibTestCase


def record(**data):
    """Return a stdin record with the given fields under `data:`"""
    return 'data:\n' + ''.join(f'  {k}: {v}\n' for k, v in data.items())


def write_store(target, store):
    """Write a learned values store into a cabinet target"""
    path = values_path(Path(target))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(store))


def execute(stower: Stower):
    """Read the values (flags, stdin, then prompts) and stow, as the stow
    command does with input data; return the destination as text, or None
    if a prompt was cancelled"""
    try:
        stower.read_values()
        return str(stower.stow())
    except CommandCancellation:
        return None


def start_stower(config: str, file: str, *args):
    """Run execute for file with an app set up from a configuration file
    (so nested blocks are flattened as in real use) and the stow command's
    --cabinet, --date and --field options in args; print the
    destination"""
    parser = WizParser()
    StowCommand.add_args(parser)
    vals = parser.parse_args([file, *args])
    app = Filez4EvaApp(config=config)
    result = execute(Stower(app, file=vals.path, cabinet=vals.cabinet,
                            date=vals.date, field=vals.field))
    if result:
        print(result)


def files(dir):
    """Files under dir (relative), ignoring the learned values store"""
    return sorted(str(p.relative_to(dir)) for p in Path(dir).rglob('*')
                  if p.is_file() and '.filez4eva' not in p.parts)


class TestStower(WizLibTestCase):
    """With the default pattern, '{date}-{title}'"""

    def test_file(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n = Path(source) / 'b.txt'
            n.write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target)
            c = Stower(a, file=str(n), date='20240213',
                       data={'title': 't'})
            with self.patchout():
                execute(c)
            self.assertEqual((Path(target) / '20240213-t.txt').read_text(),
                             'a')

    def test_returns_destination_path(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n = Path(source) / 'b.txt'
            n.write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target)
            c = Stower(a, file=str(n), date='20240213',
                       data={'title': 't'})
            with self.patchout():
                r = execute(c)
            expected = Path(target) / '20240213-t.txt'
            self.assertTrue(Path(r).is_absolute())
            self.assertEqual(Path(r), expected)
            self.assertTrue(Path(r).is_file())

    def test_relative_target_rejected(self):
        with TemporaryDirectory() as source:
            n = Path(source) / 'b.txt'
            n.write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target='.')
            c = Stower(a, file=str(n), date='20240213',
                       data={'title': 't'})
            with self.patchout(), \
                    self.assertRaisesRegex(Filez4EvaError,
                                           'target must be an absolute'):
                execute(c)
            self.assertTrue(n.is_file())

    def test_returns_absolute_path_for_home_target(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as home, \
                patch.dict('os.environ', {'HOME': home}):
            n = Path(source) / 'b.txt'
            n.write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target='~/files')
            c = Stower(a, file=str(n), date='20240213',
                       data={'title': 't'})
            with self.patchout():
                r = execute(c)
            self.assertEqual(Path(r), Path(home) / 'files/20240213-t.txt')
            self.assertTrue(Path(r).is_file())

    def test_error_if_no_source(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n = Path(source) / 'b.txt'
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target)
            c = Stower(a, file=str(n), date='20240213',
                       data={'title': 't'})
            with self.patchout(), self.assertRaises(Filez4EvaError):
                execute(c)

    def test_error_if_file_already_exists(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n = Path(source) / 'b.txt'
            n.write_text('a')
            (Path(target) / '20240213-t.txt').write_text('-')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target)
            c = Stower(a, file=str(n), date='20240213',
                       data={'title': 't'})
            with patch('sys.stdout', StringIO()), \
                    self.assertRaises(Filez4EvaError):
                execute(c)
            self.assertEqual(n.read_text(), 'a')

    def run_app(self, *args, ttyin='', config=''):
        """Run start_stower on a new b.txt; return (files under
        target, stdout, stderr)"""
        with TemporaryDirectory() as target, \
                TemporaryDirectory() as sd, \
                self.patchout() as o, \
                self.patcherr() as e, \
                self.patch_ttyin(ttyin):
            sp = Path(sd) / 'b.txt'
            sp.write_text('a')
            with NamedTemporaryFile('w+') as cf:
                cf.write(f"filez4eva:\n  target: {target}\n" + config)
                cf.seek(0)
                start_stower(cf.name, str(sp),
                             *args)
            o.seek(0)
            e.seek(0)
            return files(target), o.read(), e.read()

    def test_from_app(self):
        result, _, _ = self.run_app('--date', '20240213', '--field',
                                    'title=t')
        self.assertEqual(result, ['20240213-t.txt'])

    def test_short_flags(self):
        result, _, _ = self.run_app('-d', '20240213', '-f', 'title=t')
        self.assertEqual(result, ['20240213-t.txt'])

    def test_input_date(self):
        result, _, _ = self.run_app('--field', 'title=t', ttyin='20240213\n')
        self.assertEqual(result, ['20240213-t.txt'])

    def test_input_all(self):
        result, _, err = self.run_app(ttyin='20240213\nt\n')
        self.assertEqual(result, ['20240213-t.txt'])
        self.assertLess(err.index('Date: '), err.index('Title: '))

    def test_date_format(self):
        result, _, err = self.run_app('-f', 'title=t',
                                      ttyin='20240299\n20240317\n')
        self.assertEqual(result, ['20240317-t.txt'])
        self.assertIn('format', err)

    # Field values are normalized to hyphen-separated-lower

    def test_flag_value_normalized(self):
        result, _, _ = self.run_app('-d', '20240213', '-f',
                                    'title=Café Statement, March!')
        self.assertEqual(result, ['20240213-cafe-statement-march.txt'])

    def test_flag_value_may_contain_equals(self):
        result, _, _ = self.run_app('-d', '20240213', '-f', 'title=a=b')
        self.assertEqual(result, ['20240213-a-b.txt'])

    def test_prompted_value_normalized_without_asking_again(self):
        result, _, err = self.run_app('-d', '20240213',
                                      ttyin='Bank Statement\n')
        self.assertEqual(result, ['20240213-bank-statement.txt'])
        self.assertEqual(err.count('Title: '), 1)

    def test_prompted_empty_value_reasked(self):
        result, _, err = self.run_app('-d', '20240213', ttyin='../\nt\n')
        self.assertEqual(result, ['20240213-t.txt'])
        self.assertIn('Title must contain letters or digits', err)

    def test_empty_prompted_value_cancels(self):
        result, _, err = self.run_app('-d', '20240213', ttyin='\n')
        self.assertEqual(result, [])
        self.assertIn('Title required', err)

    def test_flag_value_empty_after_normalizing_raises(self):
        with self.assertRaises(Filez4EvaError) as cm:
            self.run_app('-d', '20240213', '-f', 'title=../')
        self.assertIn('Title must contain letters or digits from --field',
                      str(cm.exception))

    def test_malformed_field_flag_raises(self):
        for flag in ['title', '=t', 'Title=t', '2x=t']:
            with self.subTest(flag=flag), \
                    self.assertRaises(Filez4EvaError) as cm:
                self.run_app('-d', '20240213', '-f', flag)
            self.assertIn('--field must be NAME=VALUE', str(cm.exception))

    def test_date_field_flag_raises(self):
        with self.assertRaises(Filez4EvaError) as cm:
            self.run_app('-f', 'date=20240213', '-f', 'title=t')
        self.assertIn('Use --date', str(cm.exception))

    def test_unknown_field_flag_raises(self):
        with self.assertRaises(Filez4EvaError) as cm:
            self.run_app('-d', '20240213', '-f', 'title=t', '-f',
                         'account=j')
        self.assertIn('Unknown field account for cabinet default; known: '
                      'title', str(cm.exception))

    def test_prompts_follow_pattern_order(self):
        result, _, err = self.run_app(
            ttyin='j\n20240213\nt\n',
            config="  pattern: '{account}/{date}-{title}'\n")
        self.assertEqual(result, ['j/20240213-t.txt'])
        self.assertLess(err.index('Account: '), err.index('Date: '))
        self.assertLess(err.index('Date: '), err.index('Title: '))

    def test_prompts_date_year_first(self):
        result, _, err = self.run_app(
            ttyin='20240213\nj\nt\n',
            config="  pattern: '{date.year}/{account}/{date}_{title}'\n")
        self.assertEqual(result, ['2024/j/20240213_t.txt'])
        self.assertLess(err.index('Date: '), err.index('Account: '))
        self.assertLess(err.index('Account: '), err.index('Title: '))

    def test_field_label(self):
        self.assertEqual(Field('due_date').label, 'Due date')

    # plan() checks the values it is given

    def plan(self, **vals):
        with TemporaryDirectory() as source:
            n = Path(source) / 'b.txt'
            n.write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=source)
            return Stower(a, file=str(n), **vals).plan()

    def test_plan_missing_value_raises(self):
        with self.assertRaises(Filez4EvaError) as cm:
            self.plan(date='20240213', data={})
        self.assertIn('No value for field title', str(cm.exception))

    def test_plan_invalid_date_raises(self):
        with self.assertRaises(Filez4EvaError) as cm:
            self.plan(date='2024', data={'title': 't'})
        self.assertIn('Date must match format YYYYMMDD', str(cm.exception))

    def test_plan_normalizes_values(self):
        _, target, _, _ = self.plan(date='20240213', data={'title': 'A B'})
        self.assertEqual(target.name, '20240213-a-b.txt')


class TestNormalize(WizLibTestCase):

    def test_normalize_value(self):
        for value, expected in [
                ('Royal Bank of Canada', 'royal-bank-of-canada'),
                ('Café Crème', 'cafe-creme'),
                ('--A__b--', 'a-b'),
                ('already-fine-2', 'already-fine-2'),
                ('ÅNGSTRÖM  İstanbul', 'angstrom-istanbul'),
                ('../..', ''),
                ('', '')]:
            with self.subTest(value=value):
                self.assertEqual(normalize_value(value), expected)


class TestStowStdin(WizLibTestCase):
    """Stower reads the cabinet, and the fields under `data:`, from a
    YAML mapping on stdin"""

    def stow(self, stdin, *args, ttyin='', config=''):
        """Run start_stower with the given stdin text and typed
        input; return (destination files under target, stderr text, ttyin
        mock)"""
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
                cf.write(f"filez4eva:\n  target: {targetd}\n" + config)
                cf.seek(0)
                start_stower(cf.name,
                             str(sourcep), *args)
            e.seek(0)
            return files(targetd), e.read(), t

    def test_all_values_from_stdin(self):
        result, _, t = self.stow(record(date='20240213', title='t'))
        self.assertEqual(result, ['20240213-t.txt'])
        t.assert_not_called()

    def test_iso_date_from_stdin(self):
        result, _, _ = self.stow(record(date='2024-02-13', title='t'))
        self.assertEqual(result, ['20240213-t.txt'])

    def test_quoted_date_from_stdin(self):
        result, _, _ = self.stow(record(date="'20240213'", title='t'))
        self.assertEqual(result, ['20240213-t.txt'])

    def test_unknown_keys_ignored(self):
        result, _, t = self.stow(
            'summary: x\ntags: [a]\n'
            + record(date='20240213', title='t', other='x', Bad='y'))
        self.assertEqual(result, ['20240213-t.txt'])
        t.assert_not_called()

    def test_unknown_field_not_validated(self):
        # A value that would be rejected is ignored if it isn't a field
        result, _, _ = self.stow(
            record(date='20240213', title='t', bogus='"!!!"'))
        self.assertEqual(result, ['20240213-t.txt'])

    def test_top_level_fields_ignored(self):
        # Fields must be under data:
        result, _, _ = self.stow('date: 20230101\ntitle: u\n',
                                 ttyin='20240213\nt\n')
        self.assertEqual(result, ['20240213-t.txt'])

    def test_flags_override_stdin(self):
        result, _, t = self.stow(record(date='20240213', title='t'),
                                 '--date', '20230101', '--field', 'title=u')
        self.assertEqual(result, ['20230101-u.txt'])
        t.assert_not_called()

    def test_one_flag_overrides_stdin(self):
        result, _, _ = self.stow(record(date='20240213', title='t'),
                                 '-f', 'title=u')
        self.assertEqual(result, ['20240213-u.txt'])

    def test_partial_stdin_prompts_for_rest(self):
        result, _, _ = self.stow(record(date='20240213'), ttyin='t\n')
        self.assertEqual(result, ['20240213-t.txt'])

    def test_blank_stdin_values_prompted(self):
        result, _, _ = self.stow("data:\n  date: ''\n  title:\n",
                                 ttyin='20240213\nt\n')
        self.assertEqual(result, ['20240213-t.txt'])

    def test_empty_stdin_prompts_as_before(self):
        result, _, _ = self.stow('', ttyin='20240213\nt\n')
        self.assertEqual(result, ['20240213-t.txt'])

    def test_non_mapping_stdin_ignored(self):
        result, _, _ = self.stow('- a\n- b\n', ttyin='20240213\nt\n')
        self.assertEqual(result, ['20240213-t.txt'])

    def test_malformed_stdin_ignored(self):
        result, _, _ = self.stow('data: [unclosed\n', ttyin='20240213\nt\n')
        self.assertEqual(result, ['20240213-t.txt'])

    def test_null_data_ignored(self):
        result, _, _ = self.stow('data: ~\n', ttyin='20240213\nt\n')
        self.assertEqual(result, ['20240213-t.txt'])

    def test_non_mapping_data_raises(self):
        with self.assertRaises(Filez4EvaError) as cm:
            self.stow('data: [a, b]\n')
        self.assertIn('Data from stdin must be a mapping', str(cm.exception))

    def test_bad_stdin_date_raises(self):
        with self.assertRaises(Filez4EvaError):
            self.stow(record(date='20240299', title='t'))

    def test_no_stream_handler(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n = Path(source) / 'b.txt'
            n.write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target)
            del a.stream
            c = Stower(a, file=str(n), date='20240213',
                       data={'title': 't'})
            with self.patchout():
                execute(c)
            self.assertTrue((Path(target) / '20240213-t.txt').is_file())

    # YAML 1.1 scalars must stay as typed (no octal, booleans, etc.)

    def test_leading_zero_kept(self):
        result, _, _ = self.stow(record(date='20240213', title='0123'))
        self.assertEqual(result, ['20240213-0123.txt'])

    def test_yes_no_kept(self):
        result, _, _ = self.stow(
            record(date='20240213', account='yes', title='no'),
            config="  pattern: '{account}/{date}-{title}'\n")
        self.assertEqual(result, ['yes/20240213-no.txt'])

    def test_non_scalar_stdin_value_raises(self):
        with self.assertRaises(Filez4EvaError):
            self.stow(record(date='20240213', title='[a, b]'))

    # Stdin is untrusted: values are normalized, so they can't leave the
    # target, and a value with nothing left is rejected

    def test_value_normalized(self):
        result, _, _ = self.stow(record(date='20240213',
                                        title='Bank Statement'))
        self.assertEqual(result, ['20240213-bank-statement.txt'])

    def test_traversal_normalized(self):
        result, _, _ = self.stow(record(date='20240213',
                                        title='../../escaped'))
        self.assertEqual(result, ['20240213-escaped.txt'])

    def test_empty_after_normalizing_rejected(self):
        with self.assertRaises(Filez4EvaError) as cm:
            self.stow(record(date='20240213', title='"../"'))
        self.assertIn('Title must contain letters or digits from stdin',
                      str(cm.exception))

    def test_bad_stdin_rejected_before_prompting(self):
        # With no typed input, a date prompt would cancel instead of raising
        with self.assertRaises(Filez4EvaError):
            self.stow(record(title='"/"'))

    # YAML null spellings are treated as missing

    def test_null_stdin_values_prompted(self):
        result, _, _ = self.stow(record(date='~', title='null'),
                                 ttyin='20240213\nt\n')
        self.assertEqual(result, ['20240213-t.txt'])


class TestUseStdin(WizLibTestCase):
    """Values never come from stdin with use_stdin False (e.g. when
    stowing a reviewed document)"""

    def test_use_stdin_false_skips_record(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n = Path(source) / 'b.txt'
            n.write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target)
            a.stream = Mock(text=record(date='20230101', title='u'))
            c = Stower(a, file=str(n), date='20240213',
                       data={'title': 't'}, use_stdin=False)
            c.apply_stdin_record = Mock()
            with self.patchout():
                execute(c)
            c.apply_stdin_record.assert_not_called()
            self.assertTrue((Path(target) / '20240213-t.txt').is_file())


class TestStowPattern(WizLibTestCase):
    """The destination layout, and the fields, come from the pattern"""

    CUSTOM = '{account}/{date.year}/{part}-{date}'

    def stow(self, target, pattern, source, name='b.txt',
             data={'account': 'j', 'part': 't'}):
        n = Path(source) / name
        n.write_text('a')
        a = Filez4EvaApp()
        a.config = ConfigHandler.fake(filez4eva_target=target,
                                      filez4eva_pattern=pattern)
        c = Stower(a, file=str(n), date='20240213', data=data)
        with self.patchout():
            return n, execute(c)

    def assert_rejected(self, pattern, message=None):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            with self.assertRaises(Filez4EvaError) as cm:
                self.stow(target, pattern, source)
            self.assertTrue((Path(source) / 'b.txt').is_file())
            self.assertEqual(list(Path(target).iterdir()), [])
            if message:
                self.assertIn(message, str(cm.exception))

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
            _, r = self.stow(target, '{date}-{account}-{part}', source)
            self.assertEqual(Path(r), Path(target) / '20240213-j-t.txt')
            self.assertTrue(Path(r).is_file())

    def test_default_pattern(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            _, r = self.stow(target, None, source, data={'title': 't'})
            self.assertEqual(Path(r), Path(target) / '20240213-t.txt')

    def test_empty_pattern_uses_default(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            _, r = self.stow(target, '', source, data={'title': 't'})
            self.assertEqual(Path(r), Path(target) / '20240213-t.txt')

    def test_extension_always_kept(self):
        for name, expected in [('b.PDF', '20240213-t.PDF'),
                               ('b.tar.gz', '20240213-t.gz'),
                               ('noext', '20240213-t')]:
            with self.subTest(name=name), \
                    TemporaryDirectory() as source, \
                    TemporaryDirectory() as target:
                _, r = self.stow(target, None, source, name=name,
                                 data={'title': 't'})
                self.assertEqual(Path(r), Path(target) / expected)

    def test_year_is_a_plain_field(self):
        # Only {date.year} is derived from the date
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            _, r = self.stow(target, '{year}/{date}', source,
                             data={'year': 'misc'})
            self.assertEqual(Path(r), Path(target) / 'misc/20240213.txt')

    def test_repeated_placeholder(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            _, r = self.stow(target, '{title}/{date}-{title}', source,
                             data={'title': 't'})
            self.assertEqual(Path(r), Path(target) / 't/20240213-t.txt')

    def test_escaped_braces(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            _, r = self.stow(target, '{{x}}/{date}-{title}', source,
                             data={'title': 't'})
            self.assertEqual(Path(r), Path(target) / '{x}/20240213-t.txt')

    def test_fields_in_pattern_order(self):
        a = Filez4EvaApp()
        a.config = ConfigHandler.fake(filez4eva_target='/x',
                                      filez4eva_pattern=self.CUSTOM)
        cabinet = Stower(a).resolve_cabinet()
        # {date.year} places date before part
        self.assertEqual([f.name for f in cabinet.fields],
                         ['account', 'date', 'part'])

    def test_date_year_first_sets_date_position(self):
        a = Filez4EvaApp()
        a.config = ConfigHandler.fake(
            filez4eva_target='/x',
            filez4eva_pattern='{date.year}/{account}/{date}_{part}')
        cabinet = Stower(a).resolve_cabinet()
        self.assertEqual([f.name for f in cabinet.fields],
                         ['date', 'account', 'part'])

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
                start_stower(cf.name, str(sp),
                             '--date', '20240213', '-f', 'account=j',
                             '-f', 'part=t')
            actual = Path(target) / 'j/2024/t-20240213.txt'
            self.assertEqual(actual.read_text(), 'a')
            self.assertEqual(Path(o.getvalue().strip()), actual)

    def test_missing_date_rejected(self):
        self.assert_rejected('{account}/{part}', 'must contain {date}')

    def test_date_year_alone_rejected(self):
        self.assert_rejected('{date.year}/{account}-{part}',
                             'must contain {date}')

    def test_unknown_modifier_rejected(self):
        self.assert_rejected('{date.month}/{date}-{account}-{part}',
                             'unknown modifier in {date.month}')

    def test_modifier_on_other_field_rejected(self):
        self.assert_rejected('{account.year}/{date}-{part}',
                             'unknown modifier')

    def test_invalid_placeholder_message(self):
        self.assert_rejected('{Foo}/{date}', 'invalid placeholder {Foo}')

    def test_malformed_pattern_rejected(self):
        self.assert_rejected('{date/{account}', 'unbalanced braces')

    def test_stray_close_brace_rejected(self):
        self.assert_rejected('{date}}/{account}', 'unbalanced braces')

    def test_positional_rejected(self):
        self.assert_rejected('{}/{date}')

    def test_numbered_rejected(self):
        self.assert_rejected('{0}/{date}')

    def test_index_rejected(self):
        self.assert_rejected('{account[0]}/{date}')

    def test_format_spec_rejected(self):
        self.assert_rejected('{account:>10}/{date}')

    def test_conversion_rejected(self):
        self.assert_rejected('{account!r}/{date}')

    def test_blank_pattern_rejected(self):
        self.assert_rejected('   ')

    def test_absolute_pattern_rejected(self):
        self.assert_rejected('/tmp/{account}/{date}')

    def test_home_pattern_rejected(self):
        self.assert_rejected('~/{account}/{date}')

    def test_parent_pattern_rejected(self):
        self.assert_rejected('../{account}/{date}')

    def test_inner_parent_pattern_rejected(self):
        self.assert_rejected('{account}/../../{date}')

    def test_bad_pattern_rejected_before_prompting(self):
        with TemporaryDirectory() as target, \
                TemporaryDirectory() as sd, \
                self.patchout(), \
                self.patcherr(), \
                self.patch_ttyin('20240213\nt\n'):
            sp = Path(sd) / 'b.txt'
            sp.write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=target,
                                          filez4eva_pattern='{foo}')
            c = Stower(a, file=str(sp))
            with patch.object(Stower, 'prompt_value') as pv, \
                    self.assertRaises(Filez4EvaError):
                execute(c)
            pv.assert_not_called()
            self.assertTrue(sp.is_file())

    def test_destination_outside_target_rejected(self):
        # Defence in depth: even if the pattern check were bypassed, the
        # formatted destination must stay inside the target
        with patch('filez4eva.stow.check_pattern',
                   return_value=['date', 'account', 'part']):
            self.assert_rejected('../{date}{account}{part}', 'outside')

    def test_pattern_naming_target_rejected(self):
        with patch('filez4eva.stow.check_pattern',
                   return_value=['date', 'account', 'part']), \
                TemporaryDirectory() as source:
            n = Path(source) / 'b'
            n.write_text('a')
            a = Filez4EvaApp()
            a.config = ConfigHandler.fake(filez4eva_target=source,
                                          filez4eva_pattern='.')
            c = Stower(a, file=str(n), date='20240213',
                       data={'account': 'j', 'part': 't'})
            with self.assertRaises(Filez4EvaError) as cm:
                c.plan()
            self.assertIn('outside', str(cm.exception))


class TestStowFields(WizLibTestCase):
    """Field settings (guidance and values) from `fields:`"""

    def cabinets(self, **config):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(**config)
        return Stower(app).cabinets

    def test_defaults(self):
        cabinet = self.cabinets(filez4eva_target='/x')['default']
        date, title = cabinet.fields
        self.assertEqual(date.name, 'date')
        self.assertIn("document's own date", date.guidance)
        self.assertEqual(date.values, 'none')
        self.assertFalse(date.learned)
        self.assertEqual(title.name, 'title')
        self.assertEqual(title.guidance,
                         'A short title describing the document')
        self.assertEqual(title.values, 'none')
        self.assertEqual(cabinet.field('title'), title)
        self.assertIsNone(cabinet.field('nope'))

    def test_cabinet_dataclass_default_fields(self):
        self.assertEqual([f.name for f in Cabinet('x', '/x').fields],
                         ['date', 'title'])

    def test_other_fields_learned_without_guidance(self):
        cabinet = self.cabinets(
            filez4eva_target='/x',
            filez4eva_pattern='{account}/{date}')['default']
        account = cabinet.field('account')
        self.assertIsNone(account.guidance)
        self.assertEqual(account.values, 'learned')
        self.assertTrue(account.learned)

    def test_top_level_fields_without_cabinets(self):
        cabinet = self.cabinets(
            filez4eva_target='/x',
            filez4eva_pattern='{account}/{date}-{title}',
            filez4eva_fields={
                'date': {'guidance': 'The  statement\ndate'},
                'account': {'guidance': 'Never me', 'values': 'none'},
                'title': {'values': 'learned'}})['default']
        self.assertEqual(cabinet.field('date').guidance,
                         'The statement date')
        self.assertEqual(cabinet.field('account').guidance, 'Never me')
        self.assertEqual(cabinet.field('account').values, 'none')
        self.assertEqual(cabinet.field('title').values, 'learned')
        # Unset guidance falls back to the built-in default
        self.assertEqual(cabinet.field('title').guidance,
                         'A short title describing the document')

    def test_resolution_order(self):
        cabinets = self.cabinets(
            filez4eva_pattern='{account}/{date}-{part}',
            filez4eva_fields={
                'account': {'guidance': 'Top account', 'values': 'none'},
                'date': {'guidance': 'Top date'}},
            filez4eva_cabinets={
                'a': {'target': '/a',
                      'fields': {'account': {'guidance': 'Own account'},
                                 'part': None}},
                'b': {'target': '/b', 'pattern': '{date}-{title}'}})
        a = cabinets['a']
        # Key by key: guidance from the cabinet, values from the top level
        self.assertEqual(a.field('account').guidance, 'Own account')
        self.assertEqual(a.field('account').values, 'none')
        self.assertEqual(a.field('date').guidance, 'Top date')
        self.assertIsNone(a.field('part').guidance)
        self.assertEqual(a.field('part').values, 'learned')
        # A cabinet with its own pattern still inherits top-level guidance
        b = cabinets['b']
        self.assertEqual([f.name for f in b.fields], ['date', 'title'])
        self.assertEqual(b.field('date').guidance, 'Top date')

    def test_blank_settings_unset(self):
        cabinet = self.cabinets(
            filez4eva_target='/x',
            filez4eva_fields={'title': {'guidance': ' ', 'values': ''}},
        )['default']
        self.assertEqual(cabinet.field('title').guidance,
                         'A short title describing the document')
        self.assertEqual(cabinet.field('title').values, 'none')

    def test_empty_fields_block(self):
        cabinet = self.cabinets(filez4eva_target='/x',
                                filez4eva_fields='')['default']
        self.assertEqual(len(cabinet.fields), 2)

    def assert_config_rejected(self, message, **config):
        with TemporaryDirectory() as source:
            n = Path(source) / 'b.txt'
            n.write_text('a')
            app = Filez4EvaApp()
            app.config = ConfigHandler.fake(**config)
            c = Stower(app, file=str(n), use_stdin=False)
            with patch.object(app.ui, 'get_text') as gt, \
                    self.assertRaises(Filez4EvaError) as cm:
                execute(c)
            gt.assert_not_called()
            self.assertTrue(n.is_file())
            self.assertIn(message, str(cm.exception))

    def test_fields_not_mapping(self):
        self.assert_config_rejected(
            'Top-level filez4eva fields must be a mapping',
            filez4eva_target='/x', filez4eva_fields=['title'])

    def test_bad_field_name(self):
        for name in ['Title', 'two words', '1st', 5]:
            with self.subTest(name=name):
                self.assert_config_rejected(
                    'field name must be lowercase', filez4eva_target='/x',
                    filez4eva_fields={name: {}})

    def test_field_not_mapping(self):
        self.assert_config_rejected(
            'Top-level filez4eva field title must be a mapping',
            filez4eva_target='/x', filez4eva_fields={'title': 'x'})

    def test_unknown_field_setting(self):
        self.assert_config_rejected(
            'field title has unknown setting description; use: guidance, '
            'values', filez4eva_target='/x',
            filez4eva_fields={'title': {'description': 'x'}})

    def test_guidance_not_text(self):
        self.assert_config_rejected(
            'field title guidance must be text', filez4eva_target='/x',
            filez4eva_fields={'title': {'guidance': ['x']}})

    def test_invalid_values(self):
        self.assert_config_rejected(
            "field title has invalid values 'some'", filez4eva_target='/x',
            filez4eva_fields={'title': {'values': 'some'}})

    def test_fixed_values_not_yet_supported(self):
        self.assert_config_rejected(
            'a fixed list of values is not yet supported',
            filez4eva_target='/x',
            filez4eva_fields={'title': {'values': ['a', 'b']}})

    def test_date_values_rejected(self):
        self.assert_config_rejected(
            "field date can't have values", filez4eva_target='/x',
            filez4eva_fields={'date': {'values': 'none'}})

    def test_top_field_not_in_pattern(self):
        self.assert_config_rejected(
            "Top-level filez4eva fields has settings for 'account', which "
            "isn't in the pattern '{date}-{title}'",
            filez4eva_target='/x',
            filez4eva_fields={'account': {'guidance': 'x'}})

    def test_top_field_not_in_any_cabinet_pattern(self):
        self.assert_config_rejected(
            "settings for 'acount', which isn't in any cabinet's pattern",
            filez4eva_fields={'acount': {'guidance': 'x'}},
            filez4eva_cabinets={
                'a': {'target': '/a', 'pattern': '{account}/{date}'},
                'b': {'target': '/b'}})

    def test_top_field_used_by_one_cabinet(self):
        cabinets = self.cabinets(
            filez4eva_fields={'account': {'guidance': 'x'}},
            filez4eva_cabinets={
                'a': {'target': '/a', 'pattern': '{account}/{date}'},
                'b': {'target': '/b'}})
        self.assertEqual(cabinets['a'].field('account').guidance, 'x')

    def test_cabinet_field_not_in_pattern(self):
        self.assert_config_rejected(
            "Cabinet b fields has settings for 'account', which isn't in "
            "its pattern '{date}-{title}'",
            filez4eva_cabinets={
                'a': {'target': '/a'},
                'b': {'target': '/b',
                      'fields': {'account': {'guidance': 'x'}}}})

    def test_cabinet_fields_not_mapping(self):
        self.assert_config_rejected(
            'Cabinet a fields must be a mapping',
            filez4eva_cabinets={'a': {'target': '/a', 'fields': 'title'}})


class TestStowValues(WizLibTestCase):
    """Learned values are recorded in <target>/.filez4eva/values.yaml and
    offered for tab completion once common"""

    PATTERN = '{account}/{date}-{title}'

    def setUp(self):
        super().setUp()
        self.tempdir = TemporaryDirectory()
        self.dir = Path(self.tempdir.name)
        self.target = self.dir / 'target'
        self.source = self.dir / 'in'
        self.source.mkdir()

    def tearDown(self):
        self.tempdir.cleanup()
        super().tearDown()

    def app(self, **config):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(**(config or {
            'filez4eva_target': str(self.target),
            'filez4eva_pattern': self.PATTERN}))
        return app

    def stow(self, app=None, name='b.txt', **data):
        n = self.source / name
        n.write_text('a')
        c = Stower(app or self.app(), file=str(n), date='20240213',
                   data=data, use_stdin=False)
        with self.patchout(), self.patcherr() as e:
            r = execute(c)
            e.seek(0)
            return r, e.read()

    def remember(self, app=None, **data):
        """Record a reviewed record's values (as review does); return what
        was sent to stderr"""
        app = app or self.app()
        cabinet = Stower(app).resolve_cabinet()
        with self.patchout(), self.patcherr() as e:
            remember_values(app, cabinet, dict(data, date='20240213'))
            e.seek(0)
            return e.read()

    def store(self):
        return yaml.safe_load(values_path(self.target).read_text())

    def test_recorded(self):
        self.remember(account='amazon', title='receipt')
        self.assertEqual(self.store(), {'account': {'amazon': {
            'count': 1, 'last_used': date.today().isoformat()}}})

    def test_count_increments(self):
        self.remember(account='amazon', title='one')
        self.remember(account='amazon', title='two')
        self.remember(account='bank', title='three')
        store = self.store()
        self.assertEqual(store['account']['amazon']['count'], 2)
        self.assertEqual(store['account']['bank']['count'], 1)
        self.assertNotIn('title', store)

    def test_title_learned_when_configured(self):
        app = self.app(filez4eva_target=str(self.target),
                       filez4eva_fields={'title': {'values': 'learned'}})
        self.remember(app, title='receipt')
        self.assertEqual(list(self.store()), ['title'])

    def test_nothing_recorded_without_learned_fields(self):
        app = self.app(filez4eva_target=str(self.target))
        self.remember(app, title='receipt')
        self.assertFalse(values_path(self.target).exists())

    def test_not_recorded_by_stow(self):
        r, _ = self.stow(account='amazon', title='x')
        self.assertTrue(Path(r).is_file())
        self.assertFalse(values_path(self.target).exists())

    def test_stow_leaves_counts_alone(self):
        write_store(self.target, {'account': {'amazon': {'count': 4}}})
        self.stow(account='amazon', title='x')
        self.assertEqual(self.store(), {'account': {'amazon': {'count': 4}}})

    def test_not_recorded_by_plan(self):
        n = self.source / 'b.txt'
        n.write_text('a')
        Stower(self.app(), file=str(n), date='20240213',
               data={'account': 'amazon', 'title': 'x'}).plan()
        self.assertFalse(values_path(self.target).exists())

    def test_existing_entries_kept(self):
        write_store(self.target, {
            'account': {'amazon': {'count': 4, 'last_used': '2020-01-01',
                                   'note': 'kept'},
                        'odd': {'count': 'x'}},
            'other': 'junk'})
        self.remember(account='amazon', title='x')
        self.remember(account='odd', title='y')
        store = self.store()
        self.assertEqual(store['account']['amazon'],
                         {'count': 5, 'last_used': date.today().isoformat(),
                          'note': 'kept'})
        self.assertEqual(store['account']['odd']['count'], 1)
        self.assertEqual(store['other'], 'junk')

    def test_junk_field_entry_replaced(self):
        write_store(self.target, {'account': 'junk'})
        self.remember(account='amazon', title='x')
        self.assertEqual(self.store()['account']['amazon']['count'], 1)

    def test_hand_edited_non_string_keys(self):
        path = values_path(self.target)
        path.parent.mkdir(parents=True)
        path.write_text('account:\n  0123:\n    count: 5\n  yes:\n'
                        '    count: 3\n')
        self.remember(account='amazon', title='x')
        self.assertIn('amazon', self.store()['account'])

    def test_malformed_store_reported_and_kept(self):
        path = values_path(self.target)
        path.parent.mkdir(parents=True)
        path.write_text('account: [unclosed\n')
        err = self.remember(account='amazon', title='x')
        self.assertIn(f'Could not record values in {path}', err)
        self.assertEqual(path.read_text(), 'account: [unclosed\n')

    def test_non_mapping_store_reported(self):
        write_store(self.target, ['a'])
        err = self.remember(account='amazon', title='x')
        self.assertIn('must be a mapping', err)

    def test_write_failure_cleans_up(self):
        with patch('os.replace', side_effect=OSError('disk full')):
            err = self.remember(account='amazon', title='x')
        self.assertIn('disk full', err)
        self.assertEqual(list(values_path(self.target).parent.iterdir()),
                         [])

    def test_empty_store_file(self):
        path = values_path(self.target)
        path.parent.mkdir(parents=True)
        path.write_text('')
        self.assertEqual(load_store(self.target), {})
        record_values(self.target, {'account': 'a'}, date(2026, 1, 2))
        self.assertEqual(self.store(), {'account': {'a': {
            'count': 1, 'last_used': '2026-01-02'}}})

    def test_record_nothing(self):
        record_values(self.target, {})
        self.assertFalse(values_path(self.target).exists())

    # Suggestions

    def test_suggestions_common_values_most_used_first(self):
        store = {'account': {
            'once': {'count': 1}, 'bank': {'count': 3},
            'amazon': {'count': 3}, 'telus': {'count': 2},
            'Not Normal': {'count': 9}, 'junk': 'x',
            'flag': {'count': True}, 5: {'count': 9}}}
        self.assertEqual(suggestions(store, 'account'),
                         ['amazon', 'bank', 'telus'])
        self.assertEqual(suggestions(store, 'title'), [])
        self.assertEqual(suggestions({'account': ['x']}, 'account'), [])

    def test_suggestions_capped(self):
        store = {'account': {f'a{i:03}': {'count': 2}
                             for i in range(MAX_SUGGESTIONS + 20)}}
        result = suggestions(store, 'account')
        self.assertEqual(len(result), MAX_SUGGESTIONS)
        self.assertEqual(result[0], 'a000')

    def test_unreadable_store_gives_no_suggestions(self):
        path = values_path(self.target)
        path.parent.mkdir(parents=True)
        path.write_text('account: [unclosed\n')
        self.assertEqual(load_store(self.target), {})

    def test_choices(self):
        write_store(self.target, {
            'account': {'amazon': {'count': 2}, 'bank': {'count': 1}},
            'title': {'receipt': {'count': 5}}})
        c = Stower(self.app())
        cabinet = c.resolve_cabinet()
        self.assertEqual(c.choices(cabinet.field('account')), ['amazon'])
        # title isn't learned by default
        self.assertEqual(c.choices(cabinet.field('title')), [])
        self.assertEqual(c.choices(cabinet.field('date')), [])

    def test_choices_empty_for_missing_target(self):
        c = Stower(self.app())
        cabinet = c.resolve_cabinet()
        self.assertEqual(c.choices(cabinet.field('account')), [])

    def test_prompt_completion_uses_chosen_cabinet(self):
        a = self.dir / 'a'
        b = self.dir / 'b'
        write_store(a, {'account': {'bank': {'count': 2}}})
        write_store(b, {'account': {'trip': {'count': 2}}})
        app = self.app(filez4eva_pattern=self.PATTERN, filez4eva_cabinets={
            'accounts': {'target': str(a)}, 'memories': {'target': str(b)}})
        n = self.source / 'b.txt'
        n.write_text('a')
        c = Stower(app, file=str(n), date='20240213',
                   use_stdin=False)
        answers = iter(['memories', 'trip', 'photo'])
        with patch.object(app.ui, 'get_text',
                          side_effect=lambda *x: next(answers)) as gt, \
                self.patchout():
            execute(c)
        self.assertEqual([call.args for call in gt.call_args_list], [
            ('Cabinet: ', ['accounts', 'memories']),
            ('Account: ', ['trip']),
            ('Title: ', [])])
        self.assertTrue((b / 'trip/20240213-photo.txt').is_file())
        # Stowing records nothing (values are recorded at review)
        self.assertEqual(self.store_at(b)['account']['trip']['count'], 2)

    @staticmethod
    def store_at(target):
        return yaml.safe_load(values_path(target).read_text())


class TestStowCabinets(WizLibTestCase):
    """Multiple named destinations from the `filez4eva: cabinets:` key"""

    CUSTOM = '{account}/{date.year}/{part}-{date}'
    STDIN = record(date='20240213', title='t')

    def run_app(self, config, *args, stdin='', ttyin=''):
        """Run start_stower with a YAML config body (indented under
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
                start_stower(cf.name,
                             str(sourcep), *args)
            e.seek(0)
            return e.read(), t

    files = staticmethod(files)

    def two_cabinets(self, a, b):
        return (f"  cabinets:\n"
                f"    accounts:\n"
                f"      target: {a}\n"
                f"      description: Personal account records\n"
                f"    memories:\n"
                f"      target: {b}\n")

    # No cabinets: an implicit 'default' cabinet, no prompt

    def test_top_level_target(self):
        with TemporaryDirectory() as target:
            _, t = self.run_app(f"  target: {target}\n", stdin=self.STDIN)
            self.assertEqual(self.files(target), ['20240213-t.txt'])
            t.assert_not_called()

    def test_top_level_target_and_pattern(self):
        with TemporaryDirectory() as target:
            _, t = self.run_app(
                f"  target: {target}\n  pattern: '{self.CUSTOM}'\n",
                stdin=record(date='20240213', account='j', part='t'))
            self.assertEqual(self.files(target), ['j/2024/t-20240213.txt'])
            t.assert_not_called()

    def test_default_name(self):
        a = Filez4EvaApp()
        a.config = ConfigHandler.fake(filez4eva_target='/x',
                                      filez4eva_pattern=self.CUSTOM)
        c = Stower(a)
        cabinet = c.resolve_cabinet()
        self.assertEqual(list(c.cabinets), ['default'])
        self.assertEqual(cabinet.name, 'default')
        self.assertEqual(cabinet.pattern, self.CUSTOM)
        self.assertEqual(c.cabinet, 'default')

    def test_default_cabinet_flag(self):
        with TemporaryDirectory() as target:
            self.run_app(f"  target: {target}\n", '-c', 'default',
                         stdin=self.STDIN)
            self.assertEqual(self.files(target), ['20240213-t.txt'])

    def test_no_target_raises(self):
        with self.assertRaises(Filez4EvaError):
            self.run_app("  pattern: '{date}-{title}'\n", stdin=self.STDIN)

    def test_empty_cabinets_uses_target(self):
        with TemporaryDirectory() as target:
            self.run_app(f"  target: {target}\n  cabinets: {{}}\n",
                         stdin=self.STDIN)
            self.assertEqual(self.files(target), ['20240213-t.txt'])

    # One cabinet: used without a prompt; top-level target ignored

    def test_single_cabinet(self):
        with TemporaryDirectory() as target, \
                TemporaryDirectory() as ignored:
            _, t = self.run_app(
                f"  target: {ignored}\n"
                f"  cabinets:\n    only:\n      target: {target}\n",
                stdin=self.STDIN)
            self.assertEqual(self.files(target), ['20240213-t.txt'])
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
            c = Stower(a, file=str(n), date='20240213',
                       data={'title': 't'}, use_stdin=False)
            with self.patchout():
                r = execute(c)
            self.assertEqual(Path(r), Path(target) / '20240213-t.txt')

    # Several cabinets: flag, stdin or prompt

    def test_cabinet_from_flag(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            _, t = self.run_app(self.two_cabinets(a, b), '--cabinet',
                                'memories', stdin=self.STDIN)
            self.assertEqual(self.files(a), [])
            self.assertEqual(self.files(b), ['20240213-t.txt'])
            t.assert_not_called()

    def test_cabinet_from_short_flag(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            self.run_app(self.two_cabinets(a, b), '-c', 'accounts',
                         stdin=self.STDIN)
            self.assertEqual(self.files(a), ['20240213-t.txt'])

    def test_cabinet_from_stdin(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            _, t = self.run_app(self.two_cabinets(a, b),
                                stdin='cabinet: memories\n' + self.STDIN)
            self.assertEqual(self.files(b), ['20240213-t.txt'])
            t.assert_not_called()

    def test_flag_overrides_stdin_cabinet(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            self.run_app(self.two_cabinets(a, b), '-c', 'accounts',
                         stdin='cabinet: memories\n' + self.STDIN)
            self.assertEqual(self.files(a), ['20240213-t.txt'])
            self.assertEqual(self.files(b), [])

    def test_cabinet_from_prompt(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            self.run_app(self.two_cabinets(a, b), stdin=self.STDIN,
                         ttyin='memories\n')
            self.assertEqual(self.files(b), ['20240213-t.txt'])

    def test_prompt_completes_cabinet_names(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as a, \
                TemporaryDirectory() as b:
            n = Path(source) / 'b.txt'
            n.write_text('a')
            app = Filez4EvaApp()
            app.config = ConfigHandler.fake(filez4eva_cabinets={
                'zeta': {'target': a}, 'alpha': {'target': b}})
            c = Stower(app, file=str(n), date='20240213',
                       data={'title': 't'}, use_stdin=False)
            with patch.object(app.ui, 'get_text', return_value='zeta') as gt, \
                    self.patchout():
                r = execute(c)
            gt.assert_called_once_with('Cabinet: ', ['alpha', 'zeta'])
            self.assertEqual(Path(r), Path(a) / '20240213-t.txt')

    def test_cabinet_prompted_before_date(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            self.run_app(self.two_cabinets(a, b), '-f', 'title=t',
                         ttyin='accounts\n20240213\n')
            self.assertEqual(self.files(a), ['20240213-t.txt'])

    def test_fields_of_chosen_cabinet_prompted(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            config = (f"  cabinets:\n"
                      f"    accounts:\n"
                      f"      target: {a}\n"
                      f"      pattern: '{{account}}/{{date}}'\n"
                      f"    memories:\n"
                      f"      target: {b}\n"
                      f"      pattern: '{{event}}/{{date}}'\n")
            err, _ = self.run_app(config, ttyin='memories\nbday\n20240213\n')
            self.assertEqual(self.files(b), ['bday/20240213.txt'])
            self.assertIn('Event: ', err)
            self.assertNotIn('Account: ', err)

    def test_field_flag_checked_against_chosen_cabinet(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            config = (f"  cabinets:\n"
                      f"    accounts:\n"
                      f"      target: {a}\n"
                      f"      pattern: '{{account}}/{{date}}'\n"
                      f"    memories:\n"
                      f"      target: {b}\n")
            with self.assertRaises(Filez4EvaError) as cm:
                self.run_app(config, '-c', 'memories', '-f', 'account=j',
                             '-d', '20240213')
            self.assertIn('Unknown field account for cabinet memories',
                          str(cm.exception))

    def test_invalid_prompted_cabinet_reasked(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            err, _ = self.run_app(self.two_cabinets(a, b), stdin=self.STDIN,
                                  ttyin='nope\naccounts\n')
            self.assertEqual(self.files(a), ['20240213-t.txt'])
            self.assertIn('Cabinet must be one of: accounts, memories', err)

    def test_empty_prompted_cabinet_cancels(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            err, _ = self.run_app(self.two_cabinets(a, b), stdin=self.STDIN,
                                  ttyin='\n')
            self.assertEqual(self.files(a) + self.files(b), [])
            self.assertIn('Cabinet required', err)

    def test_unknown_cabinet_flag_raises(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            with self.assertRaises(Filez4EvaError) as cm:
                self.run_app(self.two_cabinets(a, b), '-c', 'nope',
                             stdin=self.STDIN)
            self.assertIn('Unknown cabinet nope', str(cm.exception))
            self.assertIn('accounts, memories', str(cm.exception))
            self.assertEqual(self.files(a) + self.files(b), [])

    def test_unknown_cabinet_stdin_raises(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            with self.assertRaises(Filez4EvaError):
                self.run_app(self.two_cabinets(a, b),
                             stdin='cabinet: nope\n' + self.STDIN)
            self.assertEqual(self.files(a) + self.files(b), [])

    def test_unknown_cabinet_flag_single_cabinet_raises(self):
        with TemporaryDirectory() as target:
            with self.assertRaises(Filez4EvaError):
                self.run_app(f"  target: {target}\n", '-c', 'nope',
                             stdin=self.STDIN)

    def test_non_scalar_stdin_cabinet_raises(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            with self.assertRaises(Filez4EvaError):
                self.run_app(self.two_cabinets(a, b),
                             stdin='cabinet: [accounts]\n' + self.STDIN)

    # Pattern comes from the chosen cabinet

    def test_per_cabinet_pattern(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            config = (f"  pattern: '{{date}}-{{account}}-{{part}}'\n"
                      f"  cabinets:\n"
                      f"    accounts:\n"
                      f"      target: {a}\n"
                      f"    memories:\n"
                      f"      target: {b}\n"
                      f"      pattern: '{self.CUSTOM}'\n")
            stdin = record(date='20240213', account='j', part='t')
            self.run_app(config, '-c', 'memories', stdin=stdin)
            self.run_app(config, '-c', 'accounts', stdin=stdin)
            self.assertEqual(self.files(b), ['j/2024/t-20240213.txt'])
            # The top-level pattern is the default for other cabinets
            self.assertEqual(self.files(a), ['20240213-j-t.txt'])

    def test_cabinet_default_pattern(self):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(
            filez4eva_cabinets={'x': {'target': '/x', 'pattern': ''}})
        c = Stower(app)
        self.assertEqual(c.pattern, '{date}-{title}')

    def test_description_kept(self):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(filez4eva_cabinets={
            'x': {'target': '~/x', 'description': 'Things'},
            'y': {'target': '/y'}})
        c = Stower(app)
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
            c = Stower(app, file=str(n), use_stdin=False)
            with patch.object(Stower, 'prompt_value') as pv, \
                    patch.object(app.ui, 'get_text') as gt, \
                    self.assertRaises(Filez4EvaError) as cm:
                execute(c)
            pv.assert_not_called()
            gt.assert_not_called()
            self.assertTrue(n.is_file())
            if message:
                self.assertIn(message, str(cm.exception))

    def test_cabinet_missing_target_raises(self):
        self.assert_config_rejected(
            {'a': {'target': '/a'}, 'b': {'pattern': '{date}'}},
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
             'b': {'target': '/b', 'pattern': '{Foo}/{date}'}}, '{Foo}')


class TestStowTranscript(WizLibTestCase):
    """A transcript (FILE.md) is moved with the file, named after it"""

    def command(self, source, target):
        n = Path(source) / 'b.txt'
        n.write_text('a')
        a = Filez4EvaApp()
        a.config = ConfigHandler.fake(filez4eva_target=target)
        c = Stower(a, file=str(n), date='20240213',
                   data={'title': 't'}, use_stdin=False)
        return n, c

    def test_transcript_moved_and_renamed(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n, c = self.command(source, target)
            t = Path(source) / 'b.txt.md'
            t.write_text('# transcript')
            with self.patchout():
                r = execute(c)
            dest = Path(target) / '20240213-t.txt'
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
                r = execute(c)
            dest = Path(target) / '20240213-t.txt'
            self.assertEqual(Path(r), dest)
            files = sorted(str(p.relative_to(target))
                           for p in Path(target).rglob('*') if p.is_file())
            self.assertEqual(files, ['20240213-t.txt'])
            self.assertEqual(list(Path(source).iterdir()), [])

    def test_transcript_collision_moves_nothing(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            n, c = self.command(source, target)
            t = Path(source) / 'b.txt.md'
            t.write_text('# new')
            dest = Path(target) / '20240213-t.txt'
            dest_t = Path(str(dest) + '.md')
            dest_t.parent.mkdir(parents=True, exist_ok=True)
            dest_t.write_text('# existing')
            with self.patchout(), \
                    self.assertRaises(Filez4EvaError) as cm:
                execute(c)
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
                execute(c)
            self.assertEqual(n.read_text(), 'a')
            self.assertEqual(t.read_text(), '# transcript')
            self.assertFalse(
                (Path(target) / '20240213-t.txt').exists())


class TestStowTranscriptLocation(WizLibTestCase):
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
        c = Stower(app, file=str(n), date='20261002',
                   data={'title': 'part'}, use_stdin=False,
                   **extra)
        with self.patchout():
            return Path(execute(c))

    def run_app(self, config, *args, transcript=True):
        """Run start_stower with a YAML config body (indented under
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
                start_stower(cf.name,
                             str(sourcep), '-d', '20261002', '-f',
                             'title=part', *args)
            return self.files(sourced)

    def test_adjacent_by_default(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            dest = self.stow(source, filez4eva_target=target)
            self.assertEqual(self.files(target),
                             ['20261002-part.txt',
                              '20261002-part.txt.md'])
            self.assertEqual(dest, Path(target) /
                             '20261002-part.txt')
            self.assertEqual(self.files(source), [])

    def test_explicit_adjacent(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target:
            self.stow(source, filez4eva_target=target,
                      filez4eva_transcripts_location='adjacent')
            self.assertEqual(self.files(target),
                             ['20261002-part.txt',
                              '20261002-part.txt.md'])

    def test_parallel(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                TemporaryDirectory() as root:
            dest = self.stow(source, filez4eva_target=target,
                             filez4eva_transcripts_location='parallel',
                             filez4eva_transcripts_root=root)
            self.assertEqual(dest, Path(target) /
                             '20261002-part.txt')
            self.assertEqual(self.files(target),
                             ['20261002-part.txt'])
            # The implicit cabinet is named 'default'
            self.assertEqual(self.files(root),
                             ['default/20261002-part.txt.md'])
            self.assertEqual(
                (Path(root) / 'default/20261002-part.txt.md')
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
                ['transcripts/default/20261002-part.txt.md'])

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
                             ['20261002-part.pdf'])
            self.assertEqual(self.files(root),
                             ['accounts/20261002-part.pdf.md'])

    def test_parallel_uses_cabinet_pattern(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                TemporaryDirectory() as root:
            self.stow(source, filez4eva_target=target,
                      filez4eva_pattern='{title}/{date}',
                      filez4eva_transcripts_location='parallel',
                      filez4eva_transcripts_root=root)
            self.assertEqual(self.files(root),
                             ['default/part/20261002.txt.md'])

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
                             ['20261002-part.pdf',
                              '20261002-part.pdf.md'])
            self.assertEqual(self.files(root), [])
            self.run_app(config, '-c', 'accounts')
            self.assertEqual(self.files(a), ['20261002-part.pdf'])
            self.assertEqual(self.files(root),
                             ['accounts/20261002-part.pdf.md'])

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
                             ['20261002-part.pdf',
                              '20261002-part.pdf.md'])
            # The cabinet's location falls back to the top-level root
            self.run_app(config, '-c', 'memories')
            self.assertEqual(self.files(b), ['20261002-part.pdf'])
            self.assertEqual(self.files(root),
                             ['memories/20261002-part.pdf.md'])

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
                             ['accounts/20261002-part.pdf.md'])

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
        c = Stower(app)
        self.assertEqual((c.cabinets['a'].transcripts_location,
                          c.cabinets['a'].transcripts_root),
                         ('parallel', '/t'))
        self.assertEqual(c.cabinets['b'].transcripts_rootdir,
                         Path('~/x').expanduser())
        self.assertEqual(c.cabinets['c'].transcripts_location, 'adjacent')

    def test_default_values(self):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(filez4eva_target='/x')
        cabinet = Stower(app).cabinets['default']
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
                             ['20261002-part.txt'])
            self.assertEqual(list(Path(root).iterdir()), [])

    def test_parallel_collision_moves_nothing(self):
        with TemporaryDirectory() as source, \
                TemporaryDirectory() as target, \
                TemporaryDirectory() as root:
            existing = Path(root) / 'default/20261002-part.txt.md'
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
            c = Stower(app, file=str(n), use_stdin=False)
            with patch.object(Stower, 'prompt_value') as pv, \
                    patch.object(app.ui, 'get_text') as gt, \
                    self.assertRaises(Filez4EvaError) as cm:
                execute(c)
            pv.assert_not_called()
            gt.assert_not_called()
            self.assertTrue(n.is_file())
            self.assertIn(message, str(cm.exception))

    def test_invalid_location_raises(self):
        self.assert_config_rejected(
            "Top-level filez4eva has invalid transcripts location 'beside'",
            filez4eva_target='/x', filez4eva_transcripts_location='beside')

    def test_invalid_top_location_with_cabinets_names_top_level(self):
        self.assert_config_rejected(
            "Top-level filez4eva has invalid transcripts location 'tree'",
            filez4eva_transcripts_location='tree',
            filez4eva_cabinets={'accounts': {'target': '/a'}})

    def test_non_text_top_root_raises(self):
        self.assert_config_rejected(
            "Top-level filez4eva transcripts root must be text",
            filez4eva_target='/x', filez4eva_transcripts_root=['x'])

    def test_non_mapping_top_transcripts_raises(self):
        self.assert_config_rejected(
            "filez4eva transcripts must be a mapping",
            filez4eva_target='/x', filez4eva_transcripts='parallel')

    def test_non_mapping_top_transcripts_from_app_raises(self):
        with TemporaryDirectory() as target:
            with self.assertRaises(Filez4EvaError) as cm:
                self.run_app(f"  target: {target}\n"
                             f"  transcripts: parallel\n")
            self.assertIn("filez4eva transcripts must be a mapping",
                          str(cm.exception))
            self.assertEqual(self.files(target), [])

    def test_empty_top_transcripts_from_app_is_adjacent(self):
        with TemporaryDirectory() as target:
            left = self.run_app(f"  target: {target}\n"
                                f"  transcripts:\n"
                                f"    # location: parallel\n")
            self.assertEqual(left, [])
            self.assertEqual(self.files(target),
                             ['20261002-part.pdf',
                              '20261002-part.pdf.md'])

    def test_empty_top_transcripts_with_env_location(self):
        with TemporaryDirectory() as target, TemporaryDirectory() as root, \
                patch.dict('os.environ',
                           {'FILEZ4EVA_TRANSCRIPTS_LOCATION': 'parallel',
                            'FILEZ4EVA_TRANSCRIPTS_ROOT': root}):
            self.run_app(f"  target: {target}\n"
                         f"  transcripts:\n")
            self.assertEqual(self.files(target),
                             ['20261002-part.pdf'])
            self.assertEqual(self.files(root),
                             ['default/20261002-part.pdf.md'])

    def test_falsy_top_location_raises(self):
        self.assert_config_rejected(
            "Top-level filez4eva has invalid transcripts location False",
            filez4eva_target='/x', filez4eva_transcripts_location=False,
            filez4eva_transcripts_root='/t')

    def test_falsy_top_location_from_app_raises(self):
        with TemporaryDirectory() as target:
            with self.assertRaises(Filez4EvaError) as cm:
                self.run_app(f"  target: {target}\n"
                             f"  transcripts:\n"
                             f"    location: no\n"
                             f"    root: tr\n")
            self.assertIn("invalid transcripts location False",
                          str(cm.exception))
            self.assertEqual(self.files(target), [])

    def test_falsy_cabinet_location_raises(self):
        self.assert_config_rejected(
            "Cabinet a has invalid transcripts location 0",
            filez4eva_cabinets={
                'a': {'target': '/a', 'transcripts': {'location': 0}}})

    def test_empty_string_location_is_unset(self):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(
            filez4eva_transcripts_location='',
            filez4eva_cabinets={
                'a': {'target': '/a', 'transcripts': {'location': ''}}})
        cabinet = Stower(app).cabinets['a']
        self.assertEqual(cabinet.transcripts_location, 'adjacent')

    def test_invalid_cabinet_location_raises(self):
        self.assert_config_rejected(
            "Cabinet b has invalid transcripts location 'nowhere'",
            filez4eva_cabinets={
                'a': {'target': '/a'},
                'b': {'target': '/b',
                      'transcripts': {'location': 'nowhere'}}})

    def test_parallel_without_root_raises(self):
        self.assert_config_rejected(
            "Top-level filez4eva transcripts location 'parallel' needs a "
            "root (cabinet default sets none)",
            filez4eva_target='/x',
            filez4eva_transcripts_location='parallel')

    def test_top_parallel_root_per_cabinet(self):
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(
            filez4eva_transcripts_location='parallel',
            filez4eva_cabinets={
                'a': {'target': '/a', 'transcripts': {'root': '/ra'}}})
        cabinet = Stower(app).cabinets['a']
        self.assertEqual((cabinet.transcripts_location,
                          cabinet.transcripts_root), ('parallel', '/ra'))

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
