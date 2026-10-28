import os
from pathlib import Path
import tempfile
from tempfile import TemporaryDirectory
from unittest import TestCase

from filez4eva import Filez4EvaApp


class TestEnvironment(TestCase):
    """The isolation in conftest.py is in place for every test, so results
    don't depend on the machine running them"""

    def test_temporary_files_are_behind_a_symlink(self):
        # As on macOS, where /var is a link to /private/var
        root = Path(tempfile.gettempdir())
        self.assertTrue(root.is_symlink())
        self.assertNotEqual(root.resolve(), root)
        with TemporaryDirectory() as d:
            self.assertEqual(Path(d).parent, root)
            self.assertNotEqual(Path(d).resolve(), Path(d))

    def test_no_filez4eva_environment_variables(self):
        names = [n for n in os.environ if n.startswith('FILEZ4EVA_')]
        self.assertEqual(names, ['FILEZ4EVA_CONFIG'])

    def test_home_is_empty(self):
        self.assertEqual(list(Path.home().iterdir()), [])
        self.assertFalse(Path('~/.filez4eva').expanduser().exists())

    def test_configuration_is_empty(self):
        config = Path(os.environ['FILEZ4EVA_CONFIG'])
        self.assertEqual(config.read_text(), '')
        app = Filez4EvaApp()
        self.assertIsNone(app.config.get('filez4eva-intake'))
