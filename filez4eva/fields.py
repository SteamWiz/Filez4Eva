"""Cabinet fields: the destination pattern that names them, their settings
(guidance and values) from the configuration, normalization of their values,
and the per-cabinet store of learned values."""

from contextlib import suppress
from dataclasses import dataclass
from datetime import date as Date, datetime
import os
from pathlib import Path
import re
import tempfile
import unicodedata

import yaml

from filez4eva.error import Filez4EvaError


# Every pattern must contain {date}; it has a fixed YYYYMMDD format
DATE_FIELD = 'date'

# Destination layout under the target when no pattern is configured
DEFAULT_PATTERN = '{date}-{title}'

# Field names, as used in a pattern and under `fields:`
FIELD_NAME = re.compile(r'[a-z][a-z0-9_]*')

# Every field other than date ends up hyphen-separated-lower
VALUE_PATTERN = re.compile(r'[a-z0-9]+(-[a-z0-9]+)*')

# Modifiers allowed after a field name in a pattern, e.g. {date.year}
MODIFIERS = {DATE_FIELD: {'year'}}

# How a field's existing values are kept: not at all, or learned by
# filez4eva from the values it files
VALUES_NONE = 'none'
VALUES_LEARNED = 'learned'
VALUES_KINDS = (VALUES_NONE, VALUES_LEARNED)

# Built-in settings, used when neither the cabinet nor the top level sets
# them. Fields not listed have no guidance and learned values.
DEFAULT_GUIDANCE = {
    DATE_FIELD: "The document's own date, such as its issue, statement or "
                "transaction date",
    'title': 'A short title describing the document',
}
DEFAULT_VALUES = {'title': VALUES_NONE}

# Keys allowed in a field's settings
FIELD_KEYS = ('guidance', 'values')

# Learned values live inside each cabinet's target
VALUES_DIR = '.filez4eva'
VALUES_FILE = 'values.yaml'

# A learned value is only offered once it has been used this often, and
# at most this many values are offered per field
MIN_COUNT = 2
MAX_SUGGESTIONS = 100

PATTERN_RULE = ('Pattern placeholders are field names like {title} '
                '(lowercase letters, digits and underscores, starting with '
                'a letter) or {date.year}; it must contain {date} and be a '
                'relative path inside the target')


# Pattern parsing

# A pattern token: an escaped brace, a placeholder, or a stray brace
TOKEN = re.compile(r'\{\{|\}\}|\{([^{}]*)\}|[{}]')

PLACEHOLDER = re.compile(r'([a-z][a-z0-9_]*)(?:\.([a-z][a-z0-9_]*))?')


@dataclass(frozen=True)
class Placeholder:
    """A {name} or {name.modifier} in a pattern"""

    name: str
    modifier: str = None


def parse_pattern(pattern: str) -> list:
    """Return the pattern as a list of literal strings and Placeholders.
    `{{` and `}}` are literal braces. Raises ValueError with a short reason
    if the pattern can't be parsed."""
    parts = []
    position = 0
    for match in TOKEN.finditer(pattern):
        if match.start() > position:
            parts.append(pattern[position:match.start()])
        token = match.group(0)
        if token in ('{{', '}}'):
            parts.append(token[0])
        elif match.group(1) is not None:
            parts.append(parse_placeholder(match.group(1)))
        else:
            raise ValueError('unbalanced braces')
        position = match.end()
    if position < len(pattern):
        parts.append(pattern[position:])
    return parts


def parse_placeholder(text: str) -> Placeholder:
    match = PLACEHOLDER.fullmatch(text)
    if not match:
        raise ValueError(f'invalid placeholder {{{text}}}')
    name, modifier = match.groups()
    if modifier is not None and modifier not in MODIFIERS.get(name, ()):
        raise ValueError(f'unknown modifier in {{{text}}}')
    return Placeholder(name, modifier)


def check_pattern(pattern) -> list:
    """Return the pattern's field names in order of first use, including
    date. Raises Filez4EvaError unless pattern is a valid destination
    pattern."""
    def error(detail):
        return Filez4EvaError(
            f"Invalid filez4eva pattern {pattern!r}: {detail}. "
            f"{PATTERN_RULE}")
    if not isinstance(pattern, str) or not pattern.strip():
        raise error("must not be empty")
    try:
        parts = parse_pattern(pattern)
    except ValueError as err:
        raise error(str(err)) from None
    # A field's first appearance, with or without a modifier (e.g.
    # {date.year}), sets its position
    placeholders = [part for part in parts if isinstance(part, Placeholder)]
    names = list(dict.fromkeys(part.name for part in placeholders))
    if Placeholder(DATE_FIELD) not in placeholders:
        raise error("must contain {date}")
    pure = Path(pattern)
    if pure.is_absolute() or pattern.startswith('~') or '..' in pure.parts:
        raise error("must stay inside the target")
    return names


def render_pattern(pattern: str, values: dict) -> str:
    """Return the pattern with each placeholder replaced by its value.
    values maps every field name (including date, as YYYYMMDD) to its
    value."""
    result = []
    for part in parse_pattern(pattern):
        if not isinstance(part, Placeholder):
            result.append(part)
        elif part.modifier == 'year':
            result.append(str(datetime.strptime(values[part.name],
                                                '%Y%m%d').year))
        else:
            result.append(values[part.name])
    return ''.join(result)


# Field settings

@dataclass(frozen=True)
class Field:
    """A field of a cabinet, with its resolved settings"""

    name: str
    guidance: str = None
    values: str = VALUES_LEARNED

    @property
    def is_date(self) -> bool:
        return self.name == DATE_FIELD

    @property
    def learned(self) -> bool:
        return self.values == VALUES_LEARNED

    @property
    def label(self) -> str:
        """Name shown at a prompt, e.g. 'Account' or 'Due date'"""
        return self.name.replace('_', ' ').capitalize()


def check_field_settings(owner: str, entries) -> dict:
    """Return a `fields:` block as a dict of name -> settings (only the keys
    that are set). owner names where the block comes from, for error
    messages. Raises Filez4EvaError on bad configuration."""
    if entries is None or entries == '':
        return {}
    if not isinstance(entries, dict):
        raise Filez4EvaError(
            f"{owner} fields must be a mapping of field name to settings")
    result = {}
    for name, entry in entries.items():
        if not isinstance(name, str) or not FIELD_NAME.fullmatch(name):
            raise Filez4EvaError(
                f"{owner} field name must be lowercase letters, digits and "
                f"underscores, starting with a letter: {name!r}")
        if entry is None:
            entry = {}
        if not isinstance(entry, dict):
            raise Filez4EvaError(f"{owner} field {name} must be a mapping")
        unknown = [str(k) for k in entry if k not in FIELD_KEYS]
        if unknown:
            raise Filez4EvaError(
                f"{owner} field {name} has unknown setting "
                f"{', '.join(unknown)}; use: {', '.join(FIELD_KEYS)}")
        settings = {}
        guidance = entry.get('guidance')
        if guidance is not None and not isinstance(guidance, str):
            raise Filez4EvaError(
                f"{owner} field {name} guidance must be text")
        if guidance and guidance.strip():
            settings['guidance'] = ' '.join(guidance.split())
        values = entry.get('values')
        if values is not None and values != '':
            if name == DATE_FIELD:
                raise Filez4EvaError(
                    f"{owner} field date can't have values")
            if isinstance(values, list):
                raise Filez4EvaError(
                    f"{owner} field {name}: a fixed list of values is not "
                    f"yet supported; use one of: {', '.join(VALUES_KINDS)}")
            if values not in VALUES_KINDS:
                raise Filez4EvaError(
                    f"{owner} field {name} has invalid values {values!r}; "
                    f"use one of: {', '.join(VALUES_KINDS)}")
            settings['values'] = values
        result[name] = settings
    return result


def check_field_names(owner: str, settings: dict, names, where: str):
    """Raise Filez4EvaError if settings has an entry for a field that isn't
    in names. where describes names, for the error message."""
    for name in settings:
        if name not in names:
            raise Filez4EvaError(
                f"{owner} fields has settings for {name!r}, which isn't in "
                f"{where}")


def resolve_fields(names: list, own: dict, top: dict) -> tuple:
    """Return a Field for each name, in order. Each setting comes from the
    cabinet's own fields, then the top-level fields, then the built-in
    default."""
    fields = []
    for name in names:
        def setting(key, default):
            for source in (own, top):
                if key in source.get(name, {}):
                    return source[name][key]
            return default
        guidance = setting('guidance', DEFAULT_GUIDANCE.get(name))
        if name == DATE_FIELD:
            values = VALUES_NONE
        else:
            values = setting('values',
                             DEFAULT_VALUES.get(name, VALUES_LEARNED))
        fields.append(Field(name, guidance, values))
    return tuple(fields)


# Values

def normalize_value(value: str) -> str:
    """Return value as hyphen-separated-lower: accents stripped, lowercase,
    each run of anything other than a-z and 0-9 turned into one hyphen,
    hyphens trimmed from both ends. May return an empty string."""
    text = unicodedata.normalize('NFKD', str(value))
    text = ''.join(c for c in text if not unicodedata.combining(c)).lower()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-')


def value_rule(field: Field) -> str:
    return f"{field.label} must contain letters or digits"


def check_value(field: Field, value, source: str = '') -> str:
    """Return value normalized. Raises Filez4EvaError if it isn't text or
    nothing is left after normalizing. source (e.g. 'from stdin') is added
    to the message."""
    normalized = normalize_value(value) if isinstance(value, str) else ''
    if not normalized:
        where = f' {source}' if source else ''
        raise Filez4EvaError(f"{value_rule(field)}{where}: {value!r}")
    return normalized


# Learned values store

def values_path(targetdir: Path) -> Path:
    return Path(targetdir) / VALUES_DIR / VALUES_FILE


def read_store(path: Path) -> dict:
    """Return the store at path, or an empty dict if there is none. Raises
    OSError, yaml.YAMLError or ValueError if it can't be read or isn't a
    mapping."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a mapping")
    return data


def load_store(targetdir: Path) -> dict:
    """Return the cabinet's learned values store, or an empty dict if it is
    missing or can't be read"""
    try:
        return read_store(values_path(targetdir))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ValueError):
        return {}


def count_of(entry) -> int:
    count = entry.get('count') if isinstance(entry, dict) else None
    return count if isinstance(count, int) and \
        not isinstance(count, bool) else 0


def suggestions(store: dict, name: str) -> list:
    """Return the learned values of a field that have been used at least
    MIN_COUNT times, most-used first (then alphabetically), at most
    MAX_SUGGESTIONS. Values that aren't hyphen-separated-lower are
    skipped."""
    entries = store.get(name)
    if not isinstance(entries, dict):
        return []
    counted = [(value, count_of(entry)) for value, entry in entries.items()
               if isinstance(value, str) and VALUE_PATTERN.fullmatch(value)]
    counted = [(v, c) for v, c in counted if c >= MIN_COUNT]
    counted.sort(key=lambda item: (-item[1], item[0]))
    return [value for value, _ in counted[:MAX_SUGGESTIONS]]


def record_values(targetdir: Path, values: dict, today: Date = None):
    """Add one use of each value (a dict of field name -> value) to the
    cabinet's store, with today's date as last_used. The store is written
    to a temporary file and then renamed, so a synced target never sees a
    half-written file. Raises OSError, yaml.YAMLError or ValueError if the
    existing store can't be read (it is left as it is) or written."""
    if not values:
        return
    today = today or Date.today()
    path = values_path(targetdir)
    store = read_store(path)
    for name, value in values.items():
        entries = store.get(name)
        if not isinstance(entries, dict):
            entries = store[name] = {}
        entry = entries.get(value)
        entry = entry if isinstance(entry, dict) else {}
        entries[value] = dict(entry, count=count_of(entry) + 1,
                              last_used=today.isoformat())
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix='.values-',
                                    suffix='.tmp')
    try:
        with os.fdopen(handle, 'w', encoding='utf-8') as file:
            # Not sorted: hand-edited keys may mix types
            yaml.safe_dump(store, file, sort_keys=False, allow_unicode=True,
                           default_flow_style=False)
        os.replace(temp, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(temp)
        raise
