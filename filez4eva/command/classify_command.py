from datetime import datetime
from pathlib import Path
import re

import yaml
from kwark.ai import KwarkAIError, TRANSCRIBE_DISCLAIMER, extract
from wizlib.parser import WizParser

from filez4eva.command import Filez4EvaCommand
from filez4eva.command.stow_file_command import (
    Cabinet, StowFileCommand, check_account, check_part, list_accounts,
    list_parts)
from filez4eva.command.transcribe_command import (
    FRONT_MATTER_DELIMITER, TranscribeCommand)
from filez4eva.error import Filez4EvaError


# Model used when `filez4eva: classify: model:` is not configured
DEFAULT_MODEL = 'claude-haiku-4-5'

# The catch-all doctype, always offered to the model
OTHER_DOCTYPE = 'other'
OTHER_DESCRIPTION = "Anything that doesn't fit the other types"

# Doctype names are single words (hyphens and underscores allowed)
DOCTYPE_PATTERN = re.compile(r'[A-Za-z0-9_-]+')

DATE_PATTERN = re.compile(r'\d{8}')

# Order of the keys in the printed record
RECORD_KEYS = ['file', 'transcript', 'cabinet', 'date', 'account', 'part',
               'doctype', 'summary']

TASK = """\
Classify the document below so it can be filed. Return:
- date: the document's own date (such as its issue, statement or \
transaction date) as YYYYMMDD, not today's date
- account: the organisation, person or account the document belongs to, as \
a single directory name (no slashes)
- part: a short label for this kind of document within the account, using \
only letters, digits and hyphens
- doctype: one of the document types listed below, or "other" if none fits
- summary: a one-line summary of the document"""


def load_doctypes(config) -> dict:
    """Return the configured doctypes as a dict of name -> description
    (None if not given), with 'other' always last. Raises Filez4EvaError on
    bad configuration."""
    entries = config.get('filez4eva-doctypes')
    if entries is None or entries == '':
        entries = {}
    if not isinstance(entries, dict):
        raise Filez4EvaError(
            "filez4eva doctypes must be a mapping of name to settings")
    doctypes = {}
    for name, entry in entries.items():
        if not isinstance(name, str) or not DOCTYPE_PATTERN.fullmatch(name):
            raise Filez4EvaError(
                f"Doctype name must be a single word: {name!r}")
        if entry is None:
            entry = {}
        if not isinstance(entry, dict):
            raise Filez4EvaError(f"Doctype {name} must be a mapping")
        description = entry.get('description')
        if description is not None and not isinstance(description, str):
            raise Filez4EvaError(f"Doctype {name} description must be text")
        doctypes[name] = description.strip() if description else None
    other = doctypes.pop(OTHER_DOCTYPE, None)
    doctypes[OTHER_DOCTYPE] = other or OTHER_DESCRIPTION
    return doctypes


def build_schema(doctypes: list) -> dict:
    """Return the JSON schema passed to extract"""
    return {
        'type': 'object',
        'properties': {
            'date': {
                'type': 'string', 'pattern': r'^\d{8}$',
                'description': "The document's own date as YYYYMMDD"},
            'account': {
                'type': 'string',
                'description': 'The account the document belongs to'},
            'part': {
                'type': 'string', 'pattern': r'^[a-zA-Z0-9-]+$',
                'description': 'The kind of document within the account'},
            'doctype': {
                'type': 'string', 'enum': list(doctypes),
                'description': 'The document type'},
            'summary': {
                'type': 'string',
                'description': 'A one-line summary of the document'},
        },
        'required': ['date', 'account', 'part', 'doctype', 'summary'],
        'additionalProperties': False,
    }


def build_instructions(cabinet: Cabinet, vocabulary: dict,
                       doctypes: dict) -> str:
    """Return the instructions passed to extract. vocabulary maps each
    existing account to its existing parts."""
    sections = [TASK]
    cabinet_text = f'The document is being filed in the cabinet ' \
        f'"{cabinet.name}"'
    if cabinet.description:
        cabinet_text += f': {cabinet.description.strip()}'
    sections.append(cabinet_text)
    if vocabulary:
        lines = ['Existing accounts, each with its existing parts. Reuse an '
                 'existing account and part when they fit; only make up a '
                 'new one when none fits:']
        for account, parts in vocabulary.items():
            lines.append(f'- {account}: {", ".join(parts)}' if parts
                         else f'- {account}')
        sections.append('\n'.join(lines))
    else:
        sections.append('There are no existing accounts yet.')
    lines = ['Document types:']
    for name, description in doctypes.items():
        lines.append(f'- {name}: {description}' if description
                     else f'- {name}')
    sections.append('\n'.join(lines))
    return '\n\n'.join(sections)


def transcript_body(text: str) -> str:
    """Return a transcript's Markdown without its front matter and AI
    disclaimer comment"""
    lines = text.splitlines()
    if lines and lines[0].rstrip() == FRONT_MATTER_DELIMITER:
        for index, line in enumerate(lines[1:], start=1):
            if line.rstrip() == FRONT_MATTER_DELIMITER:
                lines = lines[index + 1:]
                break
    if lines and lines[0].strip() == f'<!-- {TRANSCRIBE_DISCLAIMER} -->':
        lines = lines[1:]
    return '\n'.join(lines).strip('\n')


def check_result(result, doctypes) -> dict:
    """Return the model's classification, validated and cleaned up. Raises
    Filez4EvaError if it can't be used."""
    if not isinstance(result, dict):
        raise Filez4EvaError("Classification failed: result isn't a mapping")
    values = {}
    for key in ['date', 'account', 'part', 'doctype', 'summary']:
        value = result.get(key)
        if not isinstance(value, str) or not value.strip():
            raise Filez4EvaError(
                f"Classification failed: no {key} in result")
        values[key] = value.strip()
    date = values['date']
    try:
        if not DATE_PATTERN.fullmatch(date):
            raise ValueError
        datetime.strptime(date, '%Y%m%d')
    except ValueError:
        raise Filez4EvaError(
            f"Classification failed: date must match format YYYYMMDD: "
            f"{date!r}") from None
    check_account(values['account'])
    check_part(values['part'])
    if values['doctype'] not in doctypes:
        raise Filez4EvaError(
            f"Classification failed: unknown doctype {values['doctype']!r}")
    values['summary'] = ' '.join(values['summary'].split())
    return values


class ClassifyCommand(Filez4EvaCommand):
    """Propose a cabinet, date, account, part and doctype for a file from
    its transcript, printed as YAML"""

    name = 'classify'

    cabinet: str = None

    @classmethod
    def add_args(cls, parser: WizParser):
        super().add_args(parser)
        parser.add_argument('--cabinet', '-c')
        parser.add_argument('file')

    def handle_vals(self):
        super().handle_vals()
        # Check all the configuration (and choose the cabinet) before any
        # call to Claude
        self.doctypes = load_doctypes(self.app.config)
        self.stow = StowFileCommand(self.app, cabinet=self.cabinet,
                                    use_stdin=False)
        self.stow.cabinets
        self.chosen = self.stow.resolve_cabinet()

    @property
    def model(self) -> str:
        """Model from `filez4eva: classify: model:`, or the default. An
        empty `classify:` block makes wizlib's nested lookup raise
        TypeError; that means unset."""
        try:
            model = self.app.config.get('filez4eva-classify-model')
        except TypeError:
            model = None
        return model or DEFAULT_MODEL

    @property
    def api_key(self):
        """Key from `filez4eva: anthropic: key:`, or None for the SDK
        default"""
        return self.app.config.get('filez4eva-anthropic-key') or None

    def vocabulary(self) -> dict:
        """Existing accounts in the cabinet, each with its existing parts"""
        targetdir = self.chosen.targetdir
        pattern = self.chosen.pattern
        return {account: list_parts(targetdir, pattern, account)
                for account in list_accounts(targetdir, pattern)}

    @Filez4EvaCommand.wrap
    def execute(self):
        path = Path(self.file).expanduser().absolute()
        if not path.is_file():
            raise Filez4EvaError(f"File {path} must exist")
        transcriber = TranscribeCommand(self.app, file=str(path))
        transcript = Path(transcriber.execute())
        try:
            text = transcript_body(transcript.read_text(encoding='utf-8'))
        except (OSError, UnicodeDecodeError) as err:
            raise Filez4EvaError(
                f"Could not read transcript {transcript}: {err}") from err
        if not text.strip():
            raise Filez4EvaError(f"Transcript {transcript} is empty")
        schema = build_schema(self.doctypes)
        instructions = build_instructions(self.chosen, self.vocabulary(),
                                          self.doctypes)
        try:
            result = extract(text, schema, instructions=instructions,
                             model=self.model, api_key=self.api_key)
        except KwarkAIError as err:
            raise Filez4EvaError(f"Classification failed: {err}") from err
        values = check_result(result, self.doctypes)
        record = {'file': str(path), 'transcript': str(transcript),
                  'cabinet': self.chosen.name, **values}
        record = {key: record[key] for key in RECORD_KEYS}
        statuses = [transcriber.status] \
            if transcriber.status == 'Transcribed' else []
        self.status = ' | '.join(statuses + ['Classified'])
        return yaml.safe_dump(record, sort_keys=False, allow_unicode=True,
                              default_flow_style=False,
                              width=float('inf')).rstrip('\n')
