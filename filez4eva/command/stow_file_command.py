from dataclasses import dataclass, field as dataclass_field
from datetime import datetime
from functools import cached_property
import os
from pathlib import Path
import re
import shutil

import yaml
from wizlib.parser import WizParser
from wizlib.command import CommandCancellation
from wizlib.ui.shell_ui import Emphasis

from filez4eva.command import Filez4EvaCommand
from filez4eva.command.transcribe_command import transcript_path
from filez4eva.error import Filez4EvaError
from filez4eva.fields import (
    DATE_FIELD, DEFAULT_PATTERN, FIELD_NAME, Field, check_field_names,
    check_field_settings, check_pattern, check_value, load_store,
    normalize_value, record_values, render_pattern, resolve_fields,
    suggestions, value_rule, values_path)


DATE_PATTERN = re.compile(r'\d{8}')

# Date formats accepted from stdin; the first is the canonical one.
STDIN_DATE_FORMATS = ['%Y%m%d', '%Y-%m-%d']


# YAML null spellings. BaseLoader returns them as strings, so treat them as
# missing rather than as a value called "null".
YAML_NULLS = {'~', 'null', 'Null', 'NULL'}

DATE_RULE = 'Date must match format YYYYMMDD'


def valid_date(date: str) -> bool:
    """True if date is a real date written as YYYYMMDD"""
    if not DATE_PATTERN.fullmatch(date or ''):
        return False
    try:
        datetime.strptime(date, '%Y%m%d')
    except ValueError:
        return False
    return True


def stdin_null(value) -> bool:
    """True if a value read from stdin means 'not given'"""
    return value is None or (isinstance(value, str)
                             and value.strip() in YAML_NULLS | {''})


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


def blank_to_none(value):
    """Treat an empty string as unset. Other falsy values (False, 0) are
    kept so that validation rejects them."""
    return None if value == '' else value


def get_top_transcripts_value(config, key: str):
    """Return filez4eva-transcripts-<key>, or None if unset. An empty (null)
    `transcripts:` block makes wizlib's nested lookup walk into None and
    raise TypeError; that means the key is unset (environment variables are
    checked before the walk, so they still apply)."""
    try:
        return config.get(f'filez4eva-transcripts-{key}')
    except TypeError:
        return None


def load_top_transcripts(config) -> tuple:
    """Return the top-level (location, root), either of which may be None.
    An empty `transcripts:` block counts as unset. Raises Filez4EvaError if
    `transcripts` isn't a mapping or holds an invalid value."""
    block = config.get('filez4eva-transcripts')
    if block is not None and not isinstance(block, dict):
        raise Filez4EvaError("filez4eva transcripts must be a mapping")
    location = blank_to_none(get_top_transcripts_value(config, 'location'))
    root = get_top_transcripts_value(config, 'root')
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
        own_location = blank_to_none(block.get('location'))
        own_root = block.get('root')
        check_transcripts(f"Cabinet {name}", own_location, own_root)
    if own_location is not None:
        location = own_location
    location = location or DEFAULT_TRANSCRIPT_LOCATION
    root = own_root or root
    if location == 'parallel' and not (root and root.strip()):
        if own_location is None and own_root is None:
            raise Filez4EvaError(
                "Top-level filez4eva transcripts location 'parallel' needs "
                f"a root (cabinet {name} sets none)")
        raise Filez4EvaError(
            f"Cabinet {name} transcripts location 'parallel' needs a root")
    return location, root


def default_fields() -> tuple:
    """The fields of the default pattern, with built-in settings"""
    return resolve_fields(check_pattern(DEFAULT_PATTERN), {}, {})


@dataclass(frozen=True)
class Cabinet:
    """A named destination: a target directory with its own pattern, whose
    placeholders are the cabinet's fields"""

    name: str
    target: str
    pattern: str = DEFAULT_PATTERN
    description: str = None
    transcripts_location: str = DEFAULT_TRANSCRIPT_LOCATION
    transcripts_root: str = None
    # Field for each name in the pattern, in pattern order (date included)
    fields: tuple = dataclass_field(default_factory=default_fields)

    @property
    def targetdir(self) -> Path:
        return Path(self.target).expanduser()

    def field(self, name: str) -> Field:
        """The field with this name, or None"""
        return next((f for f in self.fields if f.name == name), None)

    @property
    def transcripts_rootdir(self) -> Path:
        """The transcript tree root, expanded, or None if not set"""
        if not self.transcripts_root:
            return None
        return Path(self.transcripts_root).expanduser()


def load_cabinets(config) -> dict:
    """Return the configured cabinets as a dict of name -> Cabinet. Without a
    `cabinets` section, the top-level `target`, `pattern` and `fields` form
    a single cabinet named 'default'. With one, the top-level `target` is
    ignored and the top-level `pattern` is the default for cabinets that set
    none. A cabinet's fields are the names in its pattern; each field's
    settings come from the cabinet's `fields`, then the top-level `fields`,
    then the built-in defaults. A cabinet's `transcripts` block likewise
    overrides the top-level `transcripts` location and root key by key.
    Raises Filez4EvaError on bad configuration, including any invalid
    pattern, fields or transcripts setting."""
    pattern = config.get('filez4eva-pattern') or DEFAULT_PATTERN
    location, root = load_top_transcripts(config)
    top_owner = 'Top-level filez4eva'
    top_fields = check_field_settings(top_owner,
                                      config.get('filez4eva-fields'))
    entries = config.get('filez4eva-cabinets')
    if not entries:
        target = config.get('filez4eva-target')
        if not target:
            raise Filez4EvaError(
                "No target configured: set filez4eva target or cabinets")
        names = check_pattern(pattern)
        check_field_names(top_owner, top_fields, names,
                          f"the pattern {pattern!r}")
        transcripts = resolve_transcripts(DEFAULT_CABINET, None, location,
                                          root)
        return {DEFAULT_CABINET: Cabinet(
            DEFAULT_CABINET, str(target), pattern, None, *transcripts,
            resolve_fields(names, {}, top_fields))}
    if not isinstance(entries, dict):
        raise Filez4EvaError(
            "filez4eva cabinets must be a mapping of name to settings")
    cabinets = {}
    used = set()
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
        names = check_pattern(cabinet_pattern)
        own = check_field_settings(f"Cabinet {name}", entry.get('fields'))
        check_field_names(f"Cabinet {name}", own, names,
                          f"its pattern {cabinet_pattern!r}")
        used.update(names)
        transcripts = resolve_transcripts(name, entry.get('transcripts'),
                                          location, root)
        cabinets[name] = Cabinet(name, target, cabinet_pattern, description,
                                 *transcripts,
                                 resolve_fields(names, own, top_fields))
    check_field_names(top_owner, top_fields, used, "any cabinet's pattern")
    return cabinets


class StowFileCommand(Filez4EvaCommand):
    """Move filez to the right place with the right name"""

    name = 'stow-file'

    date: str = None
    # Values of the cabinet's fields other than date, by field name
    data: dict = None
    # NAME=VALUE strings from repeated --field flags
    field: list = None
    cabinet: str = None

    # Set False when stow-file runs inside another command (e.g. scan-dir),
    # so a record piped to that command isn't applied to every file.
    use_stdin: bool = True

    @classmethod
    def add_args(cls, parser: WizParser):
        super().add_args(parser)
        parser.add_argument('--date', '-d')
        parser.add_argument('--field', '-f', action='append',
                            metavar='NAME=VALUE')
        parser.add_argument('--cabinet', '-c')
        parser.add_argument('file')

    def handle_vals(self):
        super().handle_vals()
        # Fail on bad configuration (including any cabinet's pattern) before
        # prompting for anything
        self.cabinets
        self.data = dict(self.data or {})
        flagged = self.apply_field_flags()
        if self.use_stdin:
            self.apply_stdin_record()
        cabinet = self.resolve_cabinet()
        for name in flagged:
            if cabinet.field(name) is None:
                raise Filez4EvaError(
                    f"Unknown field {name} for cabinet {cabinet.name}; "
                    "known: " + ', '.join(f.name for f in cabinet.fields
                                          if not f.is_date))
        for field in cabinet.fields:
            if field.is_date:
                if not self.provided('date'):
                    self.date = self.prompt_value(
                        'Date', [], self.clean_date, DATE_RULE)
            elif not self.data.get(field.name):
                self.data[field.name] = self.prompt_value(
                    field.label, self.choices(field), normalize_value,
                    value_rule(field))

    @staticmethod
    def clean_date(value: str) -> str:
        """The date if valid, otherwise None"""
        return value if valid_date(value) else None

    def prompt_value(self, label: str, choices: list, clean, rule: str,
                     default: str = ''):
        """Prompt until a valid value is entered; cancel on an empty one.
        clean returns the value to use (e.g. normalized), or something falsy
        if the value is invalid. Re-asking (rather than raising) keeps a
        typo from ending a scan-dir session. A default is shown pre-filled,
        so Enter accepts it."""
        # Only pass a default when there is one
        extra = (default,) if default else ()
        while True:
            value = (self.app.ui.get_text(f'{label}: ', choices, *extra)
                     or '').strip()
            if not value:
                self.app.ui.send(f'{label} required', Emphasis.PRINCIPAL)
                raise CommandCancellation()
            cleaned = clean(value)
            if cleaned:
                return cleaned
            self.app.ui.send(rule, Emphasis.PRINCIPAL)

    def apply_field_flags(self) -> list:
        """Put the values of --field NAME=VALUE flags into data, normalized,
        and return the names. The names are checked against the cabinet
        once it is known. Raises Filez4EvaError on a malformed flag or a
        value that is empty once normalized."""
        names = []
        for flag in self.field or []:
            name, equals, value = flag.partition('=')
            name = name.strip()
            if not equals or not FIELD_NAME.fullmatch(name):
                raise Filez4EvaError(
                    f"--field must be NAME=VALUE: {flag!r}")
            if name == DATE_FIELD:
                raise Filez4EvaError("Use --date for the date")
            self.data[name] = check_value(Field(name), value,
                                          'from --field')
            names.append(name)
        return names

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
        """Fill the cabinet, and the date and other fields (under `data`),
        from stdin where not provided as command-line flags. Field names
        are checked once the cabinet is known; values for names the cabinet
        doesn't have are ignored. Stdin is untrusted, so values are
        validated (fields other than date are normalized) and a bad value
        raises Filez4EvaError."""
        record = self.stdin_record()
        cabinet = record.get('cabinet')
        if not self.provided('cabinet') and not stdin_null(cabinet):
            if not isinstance(cabinet, str):
                raise Filez4EvaError(
                    "Cabinet from stdin must be a single value")
            self.check_cabinet(cabinet.strip())
            self.cabinet = cabinet.strip()
        data = record.get('data')
        if stdin_null(data):
            return
        if not isinstance(data, dict):
            raise Filez4EvaError("Data from stdin must be a mapping")
        for name, value in data.items():
            if stdin_null(value) or not isinstance(name, str) \
                    or not FIELD_NAME.fullmatch(name):
                continue
            if not isinstance(value, str):
                raise Filez4EvaError(
                    f"Field {name} from stdin must be a single value")
            if name == DATE_FIELD:
                if not self.provided('date'):
                    self.date = self.normalize_stdin_date(value.strip())
            elif not self.data.get(name):
                self.data[name] = check_value(Field(name), value,
                                              'from stdin')

    @staticmethod
    def normalize_stdin_date(value: str) -> str:
        for format in STDIN_DATE_FORMATS:
            try:
                return datetime.strptime(value, format).strftime('%Y%m%d')
            except ValueError:
                pass
        raise Filez4EvaError(
            f"Date from stdin must match format YYYYMMDD: {value}")

    def choices(self, field: Field) -> list:
        """Return the values offered for a field (for tab completion and to
        the AI): its common learned values in the chosen cabinet, or none"""
        if not field.learned:
            return []
        return suggestions(load_store(self.targetdir), field.name)

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
                'Cabinet', names,
                lambda v: v if v in self.cabinets else None,
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

    def field_values(self) -> dict:
        """Return the value of every field of the chosen cabinet (date
        included), by name. Raises Filez4EvaError if a value is missing or
        invalid."""
        cabinet = self.resolve_cabinet()
        if not valid_date(self.date):
            raise Filez4EvaError(f"{DATE_RULE}: {self.date!r}")
        values = {}
        for field in cabinet.fields:
            if field.is_date:
                values[field.name] = self.date
                continue
            value = (self.data or {}).get(field.name)
            if not value:
                raise Filez4EvaError(f"No value for field {field.name}")
            values[field.name] = check_value(field, value)
        return values

    def plan(self) -> tuple:
        """Work out where the file (and its transcript, if any) would go,
        without moving anything. Return (source, targetpath,
        source_transcript, target_transcript); the transcript paths are None
        if the file has no transcript. Raises Filez4EvaError if the file is
        missing, a value is invalid, a destination is outside its tree, or
        something already exists at a destination."""
        pattern = self.pattern
        check_pattern(pattern)
        path = Path(self.file).expanduser().absolute()
        if not path.is_file():
            raise Filez4EvaError(f"File {path} must exist")
        self.values = self.field_values()
        targetdir = self.targetdir.absolute()
        # The source file's extension is always kept
        relative = render_pattern(pattern, self.values) + path.suffix
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
        else:
            source_transcript = None
        return path, targetpath, source_transcript, target_transcript

    def remember(self):
        """Record the values of the cabinet's learned fields, after a
        successful move. A failure is reported but doesn't undo the move."""
        cabinet = self.resolve_cabinet()
        learned = {f.name: self.values[f.name] for f in cabinet.fields
                   if f.learned}
        try:
            record_values(cabinet.targetdir.absolute(), learned)
        except (OSError, UnicodeDecodeError, yaml.YAMLError,
                ValueError) as error:
            self.app.ui.send(
                f"Could not record values in "
                f"{values_path(cabinet.targetdir)}: {error}", Emphasis.ERROR)

    @Filez4EvaCommand.wrap
    def execute(self):
        path, targetpath, source_transcript, target_transcript = self.plan()
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
        self.remember()
        self.status = 'Done'
        return str(targetpath)
