from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
import os
from pathlib import Path
import re
import shutil
from string import Formatter
from subprocess import run
import sys

import yaml
from wizlib.parser import WizParser
from wizlib.command import CommandCancellation
from wizlib.ui.shell_ui import Emphasis

from filez4eva.command import Filez4EvaCommand
from filez4eva.command.transcribe_command import transcript_path
from filez4eva.error import Filez4EvaError


FILE_PATTERN = re.compile(r'\d{8}\-([a-zA-Z0-9-]+)\.(\w+)')

# Keys that stow-file reads from a YAML mapping on stdin. Other keys are
# ignored.
STDIN_KEYS = ['cabinet', 'date', 'account', 'part']

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


# Name of the implicit cabinet built from the top-level `target` and
# `pattern` keys when no `cabinets` section is configured.
DEFAULT_CABINET = 'default'

# Where stow-file puts a file's transcript: next to the stowed file
# ('adjacent') or under a separate root that mirrors the cabinet layout
# ('parallel').
TRANSCRIPT_LOCATIONS = ('adjacent', 'parallel')
DEFAULT_TRANSCRIPT_LOCATION = 'adjacent'


def check_transcripts(owner: str, location, root):
    """Raise Filez4EvaError if a transcripts location (when set) is unknown
    or a root (when set) isn't text. owner names where the values come from,
    for the error message."""
    if location is not None and location not in TRANSCRIPT_LOCATIONS:
        raise Filez4EvaError(
            f"{owner} has invalid transcripts location {location!r}; "
            "use one of: " + ', '.join(TRANSCRIPT_LOCATIONS))
    if root is not None and not isinstance(root, str):
        raise Filez4EvaError(f"{owner} transcripts root must be text")


def load_top_transcripts(config) -> tuple:
    """Return the top-level (location, root), either of which may be None.
    Raises Filez4EvaError if `transcripts` isn't a mapping or holds an
    invalid value."""
    block = config.get('filez4eva-transcripts')
    if block is not None and not isinstance(block, dict):
        raise Filez4EvaError("filez4eva transcripts must be a mapping")
    location = config.get('filez4eva-transcripts-location') or None
    root = config.get('filez4eva-transcripts-root')
    check_transcripts('Top-level filez4eva', location, root)
    return location, root


def resolve_transcripts(name: str, block, location=None, root=None) -> tuple:
    """Return (location, root) for a cabinet. Values in the cabinet's own
    `transcripts` block win, key by key, over the given top-level values
    (already checked by load_top_transcripts); location defaults to
    'adjacent'. Raises Filez4EvaError on a block that isn't a mapping, an
    unknown location, or 'parallel' without a root."""
    own_location = own_root = None
    if block is not None:
        if not isinstance(block, dict):
            raise Filez4EvaError(
                f"Cabinet {name} transcripts must be a mapping")
        own_location = block.get('location') or None
        own_root = block.get('root')
        check_transcripts(f"Cabinet {name}", own_location, own_root)
    location = own_location or location or DEFAULT_TRANSCRIPT_LOCATION
    root = own_root or root
    if location == 'parallel' and not (root and root.strip()):
        if own_location is None and own_root is None:
            raise Filez4EvaError(
                "Top-level filez4eva transcripts location 'parallel' needs "
                f"a root (cabinet {name} sets none)")
        raise Filez4EvaError(
            f"Cabinet {name} transcripts location 'parallel' needs a root")
    return location, root


@dataclass(frozen=True)
class Cabinet:
    """A named destination: a target directory with its own pattern"""

    name: str
    target: str
    pattern: str = DEFAULT_PATTERN
    description: str = None
    transcripts_location: str = DEFAULT_TRANSCRIPT_LOCATION
    transcripts_root: str = None

    @property
    def targetdir(self) -> Path:
        return Path(self.target).expanduser()

    @property
    def transcripts_rootdir(self) -> Path:
        """The transcript tree root, expanded, or None if not set"""
        if not self.transcripts_root:
            return None
        return Path(self.transcripts_root).expanduser()


def load_cabinets(config) -> dict:
    """Return the configured cabinets as a dict of name -> Cabinet. Without a
    `cabinets` section, the top-level `target` and `pattern` form a single
    cabinet named 'default'. With one, the top-level `target` is ignored and
    the top-level `pattern` is the default for cabinets that set none. A
    cabinet's `transcripts` block likewise overrides the top-level
    `transcripts` location and root key by key. Raises Filez4EvaError on bad
    configuration, including any invalid pattern or transcripts setting."""
    pattern = config.get('filez4eva-pattern') or DEFAULT_PATTERN
    location, root = load_top_transcripts(config)
    entries = config.get('filez4eva-cabinets')
    if not entries:
        target = config.get('filez4eva-target')
        if not target:
            raise Filez4EvaError(
                "No target configured: set filez4eva target or cabinets")
        check_pattern(pattern)
        transcripts = resolve_transcripts(DEFAULT_CABINET, None, location,
                                          root)
        return {DEFAULT_CABINET: Cabinet(DEFAULT_CABINET, str(target),
                                         pattern, None, *transcripts)}
    if not isinstance(entries, dict):
        raise Filez4EvaError(
            "filez4eva cabinets must be a mapping of name to settings")
    cabinets = {}
    for name, entry in entries.items():
        if not isinstance(name, str) or not name.strip():
            raise Filez4EvaError(
                f"Cabinet name must be a non-empty string: {name!r}")
        if entry is None:
            entry = {}
        if not isinstance(entry, dict):
            raise Filez4EvaError(f"Cabinet {name} must be a mapping")
        target = entry.get('target')
        if not isinstance(target, str) or not target.strip():
            raise Filez4EvaError(f"Cabinet {name} must have a target")
        description = entry.get('description')
        if description is not None and not isinstance(description, str):
            raise Filez4EvaError(
                f"Cabinet {name} description must be text")
        cabinet_pattern = entry.get('pattern') or pattern
        check_pattern(cabinet_pattern)
        transcripts = resolve_transcripts(name, entry.get('transcripts'),
                                          location, root)
        cabinets[name] = Cabinet(name, target, cabinet_pattern, description,
                                 *transcripts)
    return cabinets


class StowFileCommand(Filez4EvaCommand):
    """Move filez to the right place with the right name"""

    name = 'stow-file'

    date: str
    account: str
    part: str
    cabinet: str

    # Set False when stow-file runs inside another command (e.g. scan-dir),
    # so a record piped to that command isn't applied to every file.
    use_stdin: bool = True

    @classmethod
    def add_args(cls, parser: WizParser):
        super().add_args(parser)
        parser.add_argument('--date', '-d')
        parser.add_argument('--account', '-a')
        parser.add_argument('--part', '-p')
        parser.add_argument('--cabinet', '-c')
        parser.add_argument('file')

    def handle_vals(self):
        super().handle_vals()
        # Fail on bad configuration (including any cabinet's pattern) before
        # prompting for anything
        self.cabinets
        if self.use_stdin:
            self.apply_stdin_record()
        self.resolve_cabinet()
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
            if key == 'cabinet':
                self.check_cabinet(value)
            elif key == 'date':
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

    @cached_property
    def cabinets(self) -> dict:
        """Configured cabinets by name"""
        return load_cabinets(self.app.config)

    def check_cabinet(self, name: str):
        """Raise Filez4EvaError unless name is a configured cabinet"""
        if name not in self.cabinets:
            known = ', '.join(sorted(self.cabinets))
            raise Filez4EvaError(f"Unknown cabinet {name}; known: {known}")

    def resolve_cabinet(self) -> Cabinet:
        """Return the selected cabinet, choosing it on first use: the
        --cabinet flag or stdin value if given (an unknown name raises),
        otherwise the only cabinet, otherwise a prompt."""
        if self.provided('cabinet'):
            self.check_cabinet(self.cabinet)
        elif len(self.cabinets) == 1:
            self.cabinet = next(iter(self.cabinets))
        else:
            names = sorted(self.cabinets)
            self.cabinet = self.prompt_value(
                'Cabinet', names, lambda v: v in self.cabinets,
                'Cabinet must be one of: ' + ', '.join(names))
        return self.cabinets[self.cabinet]

    @property
    def targetdir(self) -> Path:
        return self.resolve_cabinet().targetdir

    @property
    def pattern(self) -> str:
        return self.resolve_cabinet().pattern

    def target_transcript(self, relative: str, targetpath: Path) -> Path:
        """Return where the stowed file's transcript goes. 'adjacent' puts
        it next to the stowed file; 'parallel' puts it at
        <root>/<cabinet>/<relative>.md, where relative is the stowed file's
        path under the cabinet target."""
        cabinet = self.resolve_cabinet()
        if cabinet.transcripts_location != 'parallel':
            return transcript_path(targetpath)
        base = cabinet.transcripts_rootdir.absolute() / cabinet.name
        result = base / (str(Path(relative)) + '.md')
        # Checked lexically, like the target, in case of odd cabinet names
        root = os.path.normpath(cabinet.transcripts_rootdir.absolute())
        base_norm = os.path.normpath(base)
        dest = os.path.normpath(result)
        if os.path.commonpath([root, base_norm]) != root \
                or base_norm == root \
                or os.path.commonpath([base_norm, dest]) != base_norm \
                or dest == base_norm:
            raise Filez4EvaError(
                f"Transcript destination {result} is outside {base}")
        return result

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
        # A transcript (FILE.md) travels with the file, named after it
        source_transcript = transcript_path(path)
        target_transcript = None
        if source_transcript.is_file():
            target_transcript = self.target_transcript(relative, targetpath)
            if target_transcript.exists():
                raise Filez4EvaError(
                    f"File already exists at {target_transcript}")
        targetpath.parent.mkdir(parents=True, exist_ok=True)
        path.rename(targetpath)
        if target_transcript:
            try:
                target_transcript.parent.mkdir(parents=True, exist_ok=True)
                # shutil.move copes with a transcript root on another
                # filesystem, where a rename would fail
                shutil.move(source_transcript, target_transcript)
            except OSError as error:
                # Roll back so the file and its transcript stay together.
                # A failed cross-filesystem move can leave a partial copy;
                # nothing was at the destination before, so remove it.
                if source_transcript.is_file() and \
                        target_transcript.is_file():
                    target_transcript.unlink()
                targetpath.rename(path)
                raise Filez4EvaError(
                    f"Could not move transcript {source_transcript}: "
                    f"{error}") from error
        self.status = 'Done'
        return str(targetpath)
