from datetime import datetime
import os
from pathlib import Path
import re
from string import Formatter
from subprocess import run
import sys

import yaml
from wizlib.parser import WizParser
from wizlib.command import CommandCancellation
from wizlib.ui.shell_ui import Emphasis

from filez4eva.command import Filez4EvaCommand
from filez4eva.error import Filez4EvaError


FILE_PATTERN = re.compile(r'\d{8}\-([a-zA-Z0-9-]+)\.(\w+)')

# Keys that stow-file reads from a YAML mapping on stdin. Other keys are
# ignored.
STDIN_KEYS = ['date', 'account', 'part']

# A part becomes part of the filename, so it must match FILE_PATTERN.
PART_PATTERN = re.compile(r'[a-zA-Z0-9-]+')

# Date formats accepted from stdin; the first is the canonical one.
STDIN_DATE_FORMATS = ['%Y%m%d', '%Y-%m-%d']


# YAML null spellings. BaseLoader returns them as strings, so treat them as
# missing rather than as a directory or part called "null".
YAML_NULLS = {'~', 'null', 'Null', 'NULL'}

# Destination layout under the target directory, from the `filez4eva:
# pattern:` config key. The default reproduces the original layout.
DEFAULT_PATTERN = '{year}/{account}/{date}-{part}{ext}'

# Placeholders allowed in a pattern. `date` is YYYYMMDD and `ext` includes
# the dot.
PLACEHOLDERS = {'year', 'date', 'account', 'part', 'ext'}

PATTERN_RULE = ('Pattern may only use the placeholders '
                + ', '.join('{' + p + '}' for p in sorted(PLACEHOLDERS))
                + ' (no format specs, conversions, attributes or indexes)'
                + ' and must be a relative path inside the target')

ACCOUNT_RULE = 'Account must be a single directory name'
PART_RULE = 'Part must contain only letters, digits and hyphens'


def valid_account(account: str) -> bool:
    """True if account is one safe path segment"""
    return not (not account or account in ('.', '..') or '/' in account
                or '\\' in account or '\0' in account)


def valid_part(part: str) -> bool:
    """True if part contains only letters, digits and hyphens"""
    return bool(PART_PATTERN.fullmatch(part or ''))


def check_account(account: str):
    """Raise Filez4EvaError unless account is one safe path segment"""
    if not valid_account(account):
        raise Filez4EvaError(f"{ACCOUNT_RULE}: {account!r}")


def check_part(part: str):
    """Raise Filez4EvaError unless part contains only letters, digits and
    hyphens"""
    if not valid_part(part):
        raise Filez4EvaError(f"{PART_RULE}: {part!r}")


def check_pattern(pattern: str):
    """Raise Filez4EvaError unless pattern is a valid destination pattern"""
    def error(detail):
        return Filez4EvaError(
            f"Invalid filez4eva pattern {pattern!r}: {detail}. "
            f"{PATTERN_RULE}")
    if not isinstance(pattern, str) or not pattern.strip():
        raise error("must not be empty")
    try:
        fields = list(Formatter().parse(pattern))
    except ValueError as err:
        raise error(str(err)) from None
    for _, name, spec, conversion in fields:
        if name is None:
            continue
        if name not in PLACEHOLDERS:
            raise error(f"unknown placeholder {{{name}}}")
        if spec or conversion:
            raise error(f"format spec or conversion on {{{name}}}")
    pure = Path(pattern)
    if pure.is_absolute() or pattern.startswith('~') or '..' in pure.parts:
        raise error("must stay inside the target")


class StowFileCommand(Filez4EvaCommand):
    """Move filez to the right place with the right name"""

    name = 'stow-file'

    date: str
    account: str
    part: str

    # Set False when stow-file runs inside another command (e.g. scan-dir),
    # so a record piped to that command isn't applied to every file.
    use_stdin: bool = True

    @classmethod
    def add_args(cls, parser: WizParser):
        super().add_args(parser)
        parser.add_argument('--date', '-d')
        parser.add_argument('--account', '-a')
        parser.add_argument('--part', '-p')
        parser.add_argument('file')

    def handle_vals(self):
        super().handle_vals()
        # Fail on a bad pattern before prompting for anything
        check_pattern(self.pattern)
        if self.use_stdin:
            self.apply_stdin_record()
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
            self.account = self.prompt_value(
                'Account', accounts, valid_account, ACCOUNT_RULE)
        if not self.provided('part'):
            parts = self.get_parts(self.account)
            self.part = self.prompt_value(
                'Part', parts, valid_part, PART_RULE)

    def prompt_value(self, label: str, choices: list, valid, rule: str):
        """Prompt until a valid value is entered; cancel on an empty one.
        Re-asking (rather than raising) keeps a typo from ending a scan-dir
        session."""
        while True:
            value = self.app.ui.get_text(f'{label}: ', choices)
            if not value:
                self.app.ui.send(f'{label} required', Emphasis.PRINCIPAL)
                raise CommandCancellation()
            if valid(value):
                return value
            self.app.ui.send(rule, Emphasis.PRINCIPAL)

    def stdin_record(self) -> dict:
        """Return the YAML mapping piped on stdin, or an empty dict if stdin
        is absent, empty, malformed, or not a mapping. BaseLoader keeps every
        scalar as a string, so values like 0123 or yes are not converted."""
        stream = getattr(self.app, 'stream', None)
        text = getattr(stream, 'text', None) if stream else None
        if not isinstance(text, str) or not text.strip():
            return {}
        try:
            record = yaml.load(text, Loader=yaml.BaseLoader)
        except yaml.YAMLError:
            return {}
        return record if isinstance(record, dict) else {}

    def apply_stdin_record(self):
        """Fill date, account and part from stdin where not provided as
        command-line flags. Stdin is untrusted, so values are validated and
        a bad value raises Filez4EvaError."""
        record = self.stdin_record()
        for key in STDIN_KEYS:
            if self.provided(key):
                continue
            value = record.get(key)
            if value is None or value == '':
                continue
            if not isinstance(value, str):
                raise Filez4EvaError(
                    f"{key.capitalize()} from stdin must be a single value")
            value = value.strip()
            if not value or value in YAML_NULLS:
                continue
            if key == 'date':
                value = self.normalize_stdin_date(value)
            elif key == 'account':
                check_account(value)
            elif key == 'part':
                check_part(value)
            setattr(self, key, value)

    @staticmethod
    def normalize_stdin_date(value: str) -> str:
        for format in STDIN_DATE_FORMATS:
            try:
                return datetime.strptime(value, format).strftime('%Y%m%d')
            except ValueError:
                pass
        raise Filez4EvaError(
            f"Date from stdin must match format YYYYMMDD: {value}")

    def get_accounts(self) -> list:
        """Return past accounts for tab completion. Only supported for the
        default pattern; other patterns return an empty list."""
        if self.pattern != DEFAULT_PATTERN:
            return []
        accounts = set()
        for year in self.targetdir.iterdir():
            if year.name.isdigit() and year.is_dir():
                for dir in year.iterdir():
                    if dir.is_dir():
                        accounts.add(dir.name)
        return sorted(accounts)

    def get_parts(self, sub: str) -> list:
        """Return past filename parts for tab completion. Only supported for
        the default pattern; other patterns return an empty list."""
        if self.pattern != DEFAULT_PATTERN:
            return []
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
        return Path(self.app.config.get('filez4eva-target')).expanduser()

    @property
    def pattern(self) -> str:
        return self.app.config.get('filez4eva-pattern') or DEFAULT_PATTERN

    @Filez4EvaCommand.wrap
    def execute(self):
        pattern = self.pattern
        check_pattern(pattern)
        path = Path(self.file).expanduser().absolute()
        if not path.is_file():
            raise Filez4EvaError(f"File {path} must exist")
        check_account(self.account)
        check_part(self.part)
        date = datetime.strptime(self.date, "%Y%m%d")
        targetdir = self.targetdir.absolute()
        relative = pattern.format(
            year=str(date.year), date=date.strftime('%Y%m%d'),
            account=self.account, part=self.part, ext=path.suffix)
        targetpath = targetdir / relative
        # Belt and braces: the formatted path must name a file inside the
        # target directory (checked lexically, so symlinks are allowed).
        base = os.path.normpath(targetdir)
        dest = os.path.normpath(targetpath)
        if os.path.commonpath([base, dest]) != base or dest == base:
            raise Filez4EvaError(
                f"Destination {targetpath} is outside target {targetdir}")
        if targetpath.exists():
            raise Filez4EvaError(f"File already exists at {targetpath}")
        targetpath.parent.mkdir(parents=True, exist_ok=True)
        path.rename(targetpath)
        self.status = 'Done'
        return str(targetpath)
