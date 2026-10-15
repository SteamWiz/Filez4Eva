from pathlib import Path
import re

import yaml
from kwark.ai import KwarkAIError, TRANSCRIBE_DISCLAIMER, extract
from wizlib.parser import WizParser

from filez4eva.command import Filez4EvaCommand
from filez4eva.command.stow_file_command import (
    Cabinet, StowFileCommand, valid_date)
from filez4eva.command.transcribe_command import (
    FRONT_MATTER_DELIMITER, TranscribeCommand)
from filez4eva.error import Filez4EvaError
from filez4eva.fields import check_value


# Model used when `filez4eva: classify: model:` is not configured
DEFAULT_MODEL = 'claude-haiku-4-5'

# The catch-all doctype, always offered to the model
OTHER_DOCTYPE = 'other'
OTHER_DESCRIPTION = "Anything that doesn't fit the other types"

# Doctype names are single words (hyphens and underscores allowed)
DOCTYPE_PATTERN = re.compile(r'[A-Za-z0-9_-]+')

# Order of the keys in the printed record. The fields (date included) are
# under `data`, in pattern order.
RECORD_KEYS = ['file', 'transcript', 'cabinet', 'doctype', 'summary', 'data']

TASK = """\
Classify the document below so it can be filed. Return:
- data: a value for each of the fields listed below
- doctype: one of the document types listed below, or "other" if none fits
- summary: a one-line summary of the document"""

# Fixed rules for the date, whatever its guidance says
DATE_RULES = ("Give it as YYYYMMDD. If you can't determine the document's "
              "own date, return an empty string. Do not guess and do not "
              "use today's date.")

# Fixed rule for every other field (values are normalized anyway)
VALUE_RULES = ("Use lowercase words and digits separated by hyphens, such "
               "as royal-bank-of-canada.")


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


def sentence(text: str) -> str:
    """text ending with a full stop"""
    text = text.strip()
    return text if text.endswith(('.', '!', '?')) else text + '.'


def field_description(field) -> str:
    """The guidance and fixed rules for a field, as shown to the model"""
    rules = DATE_RULES if field.is_date else VALUE_RULES
    if field.guidance:
        return f'{sentence(field.guidance)} {rules}'
    return rules


def build_schema(cabinet: Cabinet, doctypes: list) -> dict:
    """Return the JSON schema passed to extract. The cabinet's fields are
    nested under `data`, so their names can't clash with doctype and
    summary."""
    fields = {}
    for field in cabinet.fields:
        fields[field.name] = {'type': 'string',
                              'description': field_description(field)}
        if field.is_date:
            fields[field.name]['pattern'] = r'^(\d{8})?$'
    return {
        'type': 'object',
        'properties': {
            'data': {
                'type': 'object',
                'properties': fields,
                'required': list(fields),
                'additionalProperties': False,
                'description': 'A value for each field'},
            'doctype': {
                'type': 'string', 'enum': list(doctypes),
                'description': 'The document type'},
            'summary': {
                'type': 'string',
                'description': 'A one-line summary of the document'},
        },
        'required': ['data', 'doctype', 'summary'],
        'additionalProperties': False,
    }


def build_instructions(cabinet: Cabinet, vocabulary: dict,
                       doctypes: dict) -> str:
    """Return the instructions passed to extract. vocabulary maps a field
    name to the existing values to offer for it."""
    sections = [TASK]
    cabinet_text = f'The document is being filed in the cabinet ' \
        f'"{cabinet.name}"'
    if cabinet.description:
        cabinet_text += f': {cabinet.description.strip()}'
    sections.append(cabinet_text)
    lines = ['Fields:']
    for field in cabinet.fields:
        lines.append(f'- {field.name}: {field_description(field)}')
        values = vocabulary.get(field.name)
        if values:
            lines.append('  Existing values (reuse one when it fits; only '
                         'make up a new one when none fits): '
                         + ', '.join(values))
    sections.append('\n'.join(lines))
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


def check_result(result, cabinet: Cabinet, doctypes) -> dict:
    """Return the model's classification as a dict with data (the
    cabinet's fields, in pattern order), doctype and summary, validated and
    cleaned up. The date is None if the model gave none, or gave anything
    that isn't a valid YYYYMMDD date (a document may have no date of its
    own). Other fields are normalized to hyphen-separated-lower. Raises
    Filez4EvaError if any other value can't be used."""
    if not isinstance(result, dict):
        raise Filez4EvaError("Classification failed: result isn't a mapping")
    data = result.get('data')
    if not isinstance(data, dict):
        raise Filez4EvaError("Classification failed: no data in result")
    values = {}
    for field in cabinet.fields:
        value = data.get(field.name)
        if field.is_date:
            value = value.strip() if isinstance(value, str) else None
            values[field.name] = value if valid_date(value) else None
            continue
        if not isinstance(value, str) or not value.strip():
            raise Filez4EvaError(
                f"Classification failed: no {field.name} in result")
        try:
            values[field.name] = check_value(field, value)
        except Filez4EvaError as error:
            raise Filez4EvaError(
                f"Classification failed: {error}") from None
    checked = {'data': values}
    for key in ['doctype', 'summary']:
        value = result.get(key)
        if not isinstance(value, str) or not value.strip():
            raise Filez4EvaError(
                f"Classification failed: no {key} in result")
        checked[key] = value.strip()
    if checked['doctype'] not in doctypes:
        raise Filez4EvaError(
            f"Classification failed: unknown doctype {checked['doctype']!r}")
    checked['summary'] = ' '.join(checked['summary'].split())
    return checked


class ClassifyCommand(Filez4EvaCommand):
    """Propose a cabinet, a value for each of the cabinet's fields, and a
    doctype for a file from its transcript, printed as YAML"""

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
        # True if the cabinet is about to be chosen at a prompt
        self.cabinet_prompted = not self.stow.provided('cabinet') \
            and len(self.stow.cabinets) > 1
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
        """Existing values to offer the model, by field name, for the
        chosen cabinet's fields that have any"""
        return {field.name: values for field in self.chosen.fields
                if (values := self.stow.choices(field))}

    def classify(self) -> dict:
        """Transcribe the file if needed, then classify it. Return the
        record (keys in RECORD_KEYS order) and set the status. Call
        handle_vals first."""
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
        schema = build_schema(self.chosen, self.doctypes)
        instructions = build_instructions(self.chosen, self.vocabulary(),
                                          self.doctypes)
        try:
            result = extract(text, schema, instructions=instructions,
                             model=self.model, api_key=self.api_key)
        except KwarkAIError as err:
            raise Filez4EvaError(f"Classification failed: {err}") from err
        values = check_result(result, self.chosen, self.doctypes)
        record = {'file': str(path), 'transcript': str(transcript),
                  'cabinet': self.chosen.name, **values}
        record = {key: record[key] for key in RECORD_KEYS}
        statuses = [transcriber.status] \
            if transcriber.status == 'Transcribed' else []
        self.status = ' | '.join(statuses + ['Classified'])
        return record

    @Filez4EvaCommand.wrap
    def execute(self):
        record = self.classify()
        return yaml.safe_dump(record, sort_keys=False, allow_unicode=True,
                              default_flow_style=False,
                              width=float('inf')).rstrip('\n')
