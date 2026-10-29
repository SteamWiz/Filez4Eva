"""The command set: the five stage commands, no default command, and no
stow-file, scan-dir or process"""

from io import StringIO
from unittest.mock import patch

from wizlib.test_case import WizLibTestCase

from filez4eva import Filez4EvaApp


def start(*args):
    """Run the app as the CLI does; return (stdout, stderr, exit code)"""
    code = 0
    with patch('sys.stdout', out := StringIO()), \
            patch('sys.stderr', err := StringIO()):
        try:
            Filez4EvaApp.start(*args)
        except SystemExit as exit:
            code = exit.code
    return out.getvalue(), err.getvalue(), code


class TestCommands(WizLibTestCase):

    def test_the_five_commands(self):
        names = {c.name for c in Filez4EvaApp.base.family_members('name')}
        self.assertEqual(names, {'ingest', 'transcribe', 'classify',
                                 'review', 'stow'})

    def test_no_default_command(self):
        self.assertIsNone(Filez4EvaApp.base.default)

    def test_removed_commands_are_unknown(self):
        # The same error as for any name that was never a command
        _, expected, code = start('no-such-command', 'x')
        self.assertEqual(code, 1)
        self.assertIn('unrecognized arguments: no-such-command x', expected)
        for name in ['stow-file', 'scan-dir', 'process']:
            with self.subTest(name=name):
                out, err, code = start(name, 'x')
                self.assertEqual(out, '')
                self.assertEqual(code, 1)
                self.assertEqual(
                    err, expected.replace('no-such-command', name))

    def test_no_command_is_an_error(self):
        # WizLib's handling of a missing command when there is no default
        out, err, code = start()
        self.assertEqual(out, '')
        self.assertEqual(code, 1)
        self.assertIn('Unknown command None', err)

    def test_help_lists_the_five_commands(self):
        out, _, code = start('--help')
        self.assertEqual(code, 0)
        self.assertEqual(set(Filez4EvaApp.commands), {
            c.name for c in Filez4EvaApp.base.family_members('name')})
        for name in Filez4EvaApp.commands:
            command = Filez4EvaApp.base.family_member('name', name)
            self.assertIn(f'  {name:<12}{command.summary}\n', out)
        self.assertLess(out.index('  ingest '), out.index('  stow '))
        self.assertIn('Main use: `filez4eva classify ~/Scans`, then '
                      '`filez4eva stow`', out)
        for name in ['stow-file', 'scan-dir', 'process']:
            self.assertNotIn(name, out)

    def test_command_help(self):
        for name, text in [
                ('ingest', 'into the intake under a time-stamped name'),
                ('transcribe', 'Transcribe documents to Markdown'),
                ('classify', 'Never prompts'),
                ('review', 'Nothing is stowed'),
                ('stow', 'Input data (--cabinet, --date, --field')]:
            with self.subTest(name=name):
                out, _, code = start(name, '--help')
                self.assertEqual(code, 0)
                self.assertTrue(out.startswith(f'usage: filez4eva {name} '))
                # Ignore where argparse wraps the lines
                out = ' '.join(out.split())
                self.assertIn(text, out)
                if name != 'ingest':
                    self.assertIn('every document in the intake', out)
                    self.assertIn('act only on documents that have had '
                                  'every earlier stage', out)

    def test_only_help_names_the_earlier_stages(self):
        out, _, _ = start('stow', '--help')
        self.assertIn('(ingest, transcribe, classify, review)',
                      ' '.join(out.split()))

    def test_ingest_needs_a_path(self):
        out, err, code = start('ingest')
        self.assertEqual(out, '')
        self.assertEqual(code, 1)
        self.assertIn('ingest needs a path', err)
