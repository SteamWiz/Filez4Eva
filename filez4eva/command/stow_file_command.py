from datetime import datetime
import os
from pathlib import Path
import re
from subprocess import run
import sys

from wizlib.parser import WizParser
from wizlib.command import CommandCancellation
from wizlib.ui.shell_ui import Emphasis

from filez4eva.command import Filez4EvaCommand
from filez4eva.error import Filez4EvaError


FILE_PATTERN = re.compile(r'\d{8}\-([a-zA-Z0-9-]+)\.(\w+)')


class StowFileCommand(Filez4EvaCommand):
    """Move filez to the right place with the right name"""

    name = 'stow-file'

    date: str
    account: str
    part: str

    @classmethod
    def add_args(cls, parser: WizParser):
        super().add_args(parser)
        parser.add_argument('--date', '-d')
        parser.add_argument('--account', '-a')
        parser.add_argument('--part', '-p')
        parser.add_argument('file')

    def handle_vals(self):
        super().handle_vals()
        if not self.provided('date'):
            while True:
                self.date = self.app.ui.get_text('Date: ').strip()
                if not self.date:
                    self.app.ui.send('Date required', Emphasis.PRINCIPAL)
                    raise CommandCancellation()
                try:
                    datetime.strptime(self.date, "%Y%m%d")
                    break
                except ValueError:
                    self.app.ui.send('Date must match format YYYYMMDD',
                                     Emphasis.PRINCIPAL)
        if not self.provided('account'):
            accounts = self.get_accounts()
            self.account = self.app.ui.get_text('Account: ', accounts)
            if not self.account:
                self.app.ui.send('Account required', Emphasis.PRINCIPAL)
                raise CommandCancellation()
        if not self.provided('part'):
            parts = self.get_parts(self.account)
            self.part = self.app.ui.get_text('Part: ', parts)
            if not self.part:
                self.app.ui.send('Part required', Emphasis.PRINCIPAL)
                raise CommandCancellation()

    def get_accounts(self) -> list:
        accounts = set()
        for year in self.targetdir.iterdir():
            if year.name.isdigit() and year.is_dir():
                for dir in year.iterdir():
                    if dir.is_dir():
                        accounts.add(dir.name)
        return sorted(accounts)

    def get_parts(self, sub: str) -> list:
        """Return a set of past filename parts"""
        parts = set()
        for year in self.targetdir.iterdir():
            if year.name.isdigit():
                subdir = year / sub
                if subdir.is_dir():
                    for file in subdir.iterdir():
                        match = re.match(FILE_PATTERN, file.name)
                        if match:
                            parts.add(match.groups()[0])
        return sorted(parts)

    @property
    def targetdir(self):
        return Path(self.app.config.get('filez4eva-target'))

    @Filez4EvaCommand.wrap
    def execute(self):
        path = Path(self.file).expanduser().absolute()
        if not path.is_file():
            raise Filez4EvaError(f"File {path} must exist")
        extension = path.suffix
        date = datetime.strptime(self.date, "%Y%m%d")
        dirpath = self.targetdir / str(date.year) / self.account
        if not dirpath.exists():
            # confirm = rlinput(f"Create {dirpath}? ", default="yes")
            # if confirm.startswith('y'):
            dirpath.mkdir(parents=True)
        targetpath = dirpath / \
            f"{date.strftime('%Y%m%d')}-{self.part}{extension}"
        if targetpath.exists():
            raise Filez4EvaError(f"File already exists at {targetpath}")
        # confirm = rlinput(f"Move file to {targetpath}? ", default="yes")
        # if confirm.startswith('y'):
        path.rename(targetpath)
        self.status = 'Done'
