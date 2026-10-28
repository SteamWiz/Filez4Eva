from pathlib import Path
import re

import yaml
from kwark.ai import KwarkAIError, extract
from wizlib.parser import WizParser

from filez4eva.command import Filez4EvaCommand
from filez4eva.command import ingest_command
from filez4eva.command.stow_file_command import (
    Cabinet, StowFileCommand, load_cabinets, valid_date)
from filez4eva.command.transcribe_command import (
    TranscribeCommand, recorded_transcript, transcribe_file, transcribe_model,
    transcript_body)
from filez4eva.error import Filez4EvaError
from filez4eva.fields import check_value, load_store, suggestions
from filez4eva.stage import StageCommand, load_sidecar, record_result


# Model used when `filez4eva: classify: model:` is not configured
DEFAULT_MODEL = 'claude-haiku-4-5'

# The catch-all doctype, always offered to the model
OTHER_DOCTYPE = 'other'
OTHER_DESCRIPTION = "Anything that doesn't fit the other types"

# Doctype names are single words (hyphens and underscores allowed)
DOCTYPE_PATTERN = re.compile(r'[A-Za-z0-9_-]+')

# Order of the keys in the record that Classifier returns to process and
# scan-dir. The fields (date included) are under `data`, in pattern order.
RECORD_KEYS = ['file', 'transcript', 'cabinet', 'doctype', 'summary', 'data']

TASK = """\
Classify the document below so it can be filed. Return:
- data: a value for each of the fields listed below
- doctype: one of the document types listed below, or "other" if none fits
- summary: a one-line summary of the document"""

# Told to the model when the document's original name and source come
# before its transcript
CONTEXT_NOTE = ("Before the transcript you are given the document's "
                "original file name and where it came from (its source). "
                "Use them as hints, but go by the transcript when they "
                "disagree.")

CABINET_TASK = """\
Choose the cabinet the document below should be filed in. Return:
- cabinet: the name of one of the cabinets listed below"""

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
                       doctypes: dict, context: bool = False) -> str:
    """Return the instructions passed to extract. vocabulary maps a field
    name to the existing values to offer for it. With context, the model is
    told that the document's original name and source come before its
    transcript."""
    sections = [TASK]
    if context:
        sections.append(CONTEXT_NOTE)
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


def cabinet_vocabulary(cabinet: Cabinet) -> dict:
    """Existing values to offer the model, by field name, for a cabinet's
    learned fields that have any (the values tab completion offers)"""
    learned = [field for field in cabinet.fields if field.learned]
    if not learned:
        return {}
    store = load_store(cabinet.targetdir)
    return {field.name: values for field in learned
            if (values := suggestions(store, field.name))}


def classify_model(config) -> str:
    """Model from `filez4eva: classify: model:`, or the default. An empty
    `classify:` block makes wizlib's nested lookup raise TypeError; that
    means unset."""
    try:
        model = config.get('filez4eva-classify-model')
    except TypeError:
        model = None
    return model or DEFAULT_MODEL


def anthropic_key(config):
    """Key from `filez4eva: anthropic: key:`, or None for the SDK default"""
    return config.get('filez4eva-anthropic-key') or None


def read_transcript(transcript: Path) -> str:
    """Return a transcript's Markdown without its front matter. Raises
    Filez4EvaError if it can't be read or is empty."""
    try:
        text = transcript_body(transcript.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError) as err:
        raise Filez4EvaError(
            f"Could not read transcript {transcript}: {err}") from err
    if not text.strip():
        raise Filez4EvaError(f"Transcript {transcript} is empty")
    return text


def ask_model(text: str, schema: dict, instructions: str, model: str,
              api_key):
    """Call extract, turning a Kwark error into Filez4EvaError"""
    try:
        return extract(text, schema, instructions=instructions, model=model,
                       api_key=api_key)
    except KwarkAIError as err:
        raise Filez4EvaError(f"Classification failed: {err}") from err


def classify_text(text: str, cabinet: Cabinet, doctypes: dict, model: str,
                  api_key, context: bool = False) -> dict:
    """Ask the model for a cabinet's field values, the doctype and a
    summary of a document, offering the cabinet's existing values. Return
    the checked result (see check_result). Raises Filez4EvaError if the
    call fails or the answer can't be used."""
    schema = build_schema(cabinet, doctypes)
    instructions = build_instructions(cabinet, cabinet_vocabulary(cabinet),
                                      doctypes, context)
    result = ask_model(text, schema, instructions, model, api_key)
    return check_result(result, cabinet, doctypes)


def build_cabinet_schema(cabinets: dict) -> dict:
    """Return the JSON schema for choosing one of the cabinets"""
    return {
        'type': 'object',
        'properties': {
            'cabinet': {
                'type': 'string', 'enum': list(cabinets),
                'description': 'The cabinet to file the document in'}},
        'required': ['cabinet'],
        'additionalProperties': False,
    }


def build_cabinet_instructions(cabinets: dict) -> str:
    """Return the instructions for choosing a cabinet: the names with their
    descriptions"""
    lines = ['Cabinets:']
    for name, cabinet in cabinets.items():
        description = (cabinet.description or '').strip()
        lines.append(f'- {name}: {description}' if description
                     else f'- {name}')
    return '\n\n'.join([CABINET_TASK, CONTEXT_NOTE, '\n'.join(lines)])


def pick_cabinet(text: str, cabinets: dict, model: str, api_key) -> Cabinet:
    """Ask the model which of the configured cabinets a document belongs
    in, from their names and descriptions. Raises Filez4EvaError if the call
    fails or the answer isn't a configured cabinet."""
    result = ask_model(text, build_cabinet_schema(cabinets),
                       build_cabinet_instructions(cabinets), model, api_key)
    name = result.get('cabinet') if isinstance(result, dict) else None
    if not isinstance(name, str) or name.strip() not in cabinets:
        raise Filez4EvaError(
            f"Classification failed: unknown cabinet {name!r}; known: "
            + ', '.join(sorted(cabinets)))
    return cabinets[name.strip()]


def document_text(transcript: str, ingest: dict) -> str:
    """Return the text given to the model for a document in the intake: its
    original file name and source (from results.ingest), then its
    transcript"""
    ingest = ingest if isinstance(ingest, dict) else {}
    lines = [f"Original file name: {ingest.get('original-name') or '(none)'}"]
    source = ingest.get('source')
    if source:
        dumped = yaml.safe_dump(source, sort_keys=False, allow_unicode=True,
                                default_flow_style=False).rstrip('\n')
        lines.append('Source:')
        lines.extend(f'  {line}' for line in dumped.splitlines())
    else:
        lines.append('Source: (none recorded)')
    return '\n'.join(lines) + '\n\nTranscript:\n\n' + transcript


class Classifier:
    """Transcribe a file in place and classify it for one cabinet, chosen
    with --cabinet, as the only cabinet, or at a prompt. Used by process and
    scan-dir, which confirm the result in the shell; nothing is ingested or
    moved."""

    def __init__(self, app, file: str, cabinet: str = None):
        self.app = app
        self.file = file
        self.cabinet = cabinet
        self.status = None

    def handle_vals(self):
        """Check all the configuration, and choose the cabinet (at a prompt
        if needed), before any call to Claude"""
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
        return classify_model(self.app.config)

    @property
    def api_key(self):
        return anthropic_key(self.app.config)

    def classify(self) -> dict:
        """Transcribe the file if needed, then classify it. Return the
        record (keys in RECORD_KEYS order) and set the status. Call
        handle_vals first."""
        path = Path(self.file).expanduser().absolute()
        if not path.is_file():
            raise Filez4EvaError(f"File {path} must exist")
        transcript, transcribed = transcribe_file(
            path, transcribe_model(self.app.config), self.api_key)
        text = read_transcript(transcript)
        values = classify_text(text, self.chosen, self.doctypes, self.model,
                               self.api_key)
        record = {'file': str(path), 'transcript': str(transcript),
                  'cabinet': self.chosen.name, **values}
        record = {key: record[key] for key in RECORD_KEYS}
        statuses = [transcribed] if transcribed == 'Transcribed' else []
        self.status = ' | '.join(statuses + ['Classified'])
        return record


class ClassifyCommand(StageCommand):
    """Classify a file, the files in a directory, or the documents in the
    intake with Claude, ingesting and transcribing them first if needed.
    Records results.classify (cabinet, doctype, summary and field values)
    in each document's X.yml. Never prompts."""

    name = 'classify'
    stage = 'classify'
    done = 'Classified'
    requires = (TranscribeCommand,)

    # Cabinet for every document in the run; None to use the only cabinet,
    # or let the model pick one when there are several
    cabinet: str = None

    @classmethod
    def add_args(cls, parser: WizParser):
        super().add_args(parser)
        parser.add_argument('--cabinet', '-c')

    def handle_vals(self):
        super().handle_vals()
        # Check all the configuration, including the --cabinet name, before
        # any file is touched
        self.doctypes = load_doctypes(self.app.config)
        self.cabinets = load_cabinets(self.app.config)
        if self.provided('cabinet') and self.cabinet not in self.cabinets:
            raise Filez4EvaError(
                f"Unknown cabinet {self.cabinet}; known: "
                + ', '.join(sorted(self.cabinets)))

    @property
    def model(self) -> str:
        """Model from `filez4eva: classify: model:`, or the default"""
        return classify_model(self.app.config)

    @property
    def api_key(self):
        """Key from `filez4eva: anthropic: key:`, or None for the SDK
        default"""
        return anthropic_key(self.app.config)

    def choose_cabinet(self, text: str) -> Cabinet:
        """The --cabinet cabinet, the only one, or the model's pick"""
        if self.provided('cabinet'):
            return self.cabinets[self.cabinet]
        if len(self.cabinets) == 1:
            return next(iter(self.cabinets.values()))
        return pick_cabinet(text, self.cabinets, self.model, self.api_key)

    def act(self, path: Path) -> str:
        """Classify an ingested, transcribed document from its transcript,
        original name and source, record results.classify, and return the
        document's path"""
        results = load_sidecar(path)['results']
        transcript = recorded_transcript(path, results)
        text = document_text(read_transcript(transcript),
                             results.get('ingest'))
        cabinet = self.choose_cabinet(text)
        values = classify_text(text, cabinet, self.doctypes, self.model,
                               self.api_key, context=True)
        record_result(path, self.stage, {
            'at': ingest_command.now().isoformat(timespec='seconds'),
            'model': self.model,
            'cabinet': cabinet.name,
            'doctype': values['doctype'],
            'summary': values['summary'],
            'data': values['data'],
        })
        return str(path)

    @Filez4EvaCommand.wrap
    def execute(self):
        return self.run()
