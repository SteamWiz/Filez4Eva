"""Keep the test suite independent of the machine it runs on.

- Temporary files live behind a symbolic link for the whole run, as they
  do on macOS (where the temporary directory is under /var, a link to
  /private/var), so a command that mixes resolved and unresolved paths
  fails on every machine, Linux CI included.
- Each test starts with no FILEZ4EVA_* environment variables, an empty
  home directory (so no ~/.filez4eva.yml and no ~/.filez4eva/intake) and
  FILEZ4EVA_CONFIG pointing at an empty configuration file (so no
  .filez4eva.yml in the working directory either). Tests that need such
  state set it up themselves, in a temporary location.
"""

import os
import tempfile

import pytest


@pytest.fixture(scope='session', autouse=True)
def symlinked_tempdir(tmp_path_factory):
    """Point tempfile (and so every TemporaryDirectory and
    NamedTemporaryFile) at a symbolic link to a real directory"""
    base = tmp_path_factory.mktemp('tempdir')
    real = base / 'real'
    real.mkdir()
    link = base / 'link'
    link.symlink_to(real, target_is_directory=True)
    saved = tempfile.tempdir
    tempfile.tempdir = str(link)
    yield link
    tempfile.tempdir = saved


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Hide the developer's own Filez4Eva configuration from the test"""
    for name in list(os.environ):
        if name.startswith('FILEZ4EVA_'):
            monkeypatch.delenv(name)
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    config = tmp_path / 'filez4eva.yml'
    config.write_text('')
    monkeypatch.setenv('FILEZ4EVA_CONFIG', str(config))
    return home
