from datetime import date
from pathlib import Path
import re

import yaml
from kwark.ai import KwarkAIError, extract

from filez4eva.command import Filez4EvaCommand
from filez4eva.command import ingest_command
from filez4eva.command.transcribe_command import (
    TranscribeCommand, is_raw, recorded_transcript, transcript_body)
from filez4eva.error import Filez4EvaError
from filez4eva.fields import check_value, load_store, suggestions
from filez4eva.progress import ai_progress
from filez4eva.stage import (
    CLASSIFY_DOING, StageCommand, given_values, load_sidecar, record_result,
    saved_cabinet)
from filez4eva.stow import Cabinet, valid_date


# Model used when `filez4eva: classify: model:` is not configured
DEFAULT_MODEL = 'claude-haiku-4-5'

# The catch-all doctype, always offered to the model
OTHER_DOCTYPE = 'other'
OTHER_DESCRIPTION = "Anything that doesn't fit the other types"

# Doctype names are single words (hyphens and underscores allowed)
DOCTYPE_PATTERN = re.compile(r'[A-Za-z0-9_-]+')

TASK = """\
Classify the document below so it can be filed. Return:
- data: a value for each of the fields listed below
- doctype: one of the document types listed below, or "other" if none fits
- summary: a one-line summary of the document"""

# Told to the model when the document's original name, source and file
# date come before its transcript (or, for a text document, its own text)
CONTEXT_NOTE = ("Before the document's transcript (or, for a text file, "
                "its text) you are given its original file name, where "
                "it came from (its source) and, when known, the file's "
                "creation or modified date. Use them as hints, but go by "
                "the transcript or text when they disagree.")

# The most characters of a transcript, or of a text document, given to the
# model; the rest is cut, with a note, to protect its context
MAX_CLASSIFY_CHARS = 100_000

# Fixed rules for the date, whatever its guidance says
DATE_RULES = ("Give it as YYYYMMDD. Prefer the document's own date. If "
              "the document has none, you may use the file date given "
              "with it when that is a reasonable stand-in (for example, "
              "for a photo). Otherwise return an empty string. Never use "
              "today's date.")

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


def asked_fields(cabinet: Cabinet, given=()) -> list:
    """The cabinet's fields the model is asked for: those not given"""
    return [field for field in cabinet.fields if field.name not in given]


def build_schema(cabinet: Cabinet, doctypes: list, given=()) -> dict:
    """Return the JSON schema passed to extract. The cabinet's fields that
    aren't given are nested under `data`, so their names can't clash with
    doctype and summary."""
    fields = {}
    for field in asked_fields(cabinet, given):
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
                       doctypes: dict, context: bool = False,
                       given: dict = None) -> str:
    """Return the instructions passed to extract. vocabulary maps a field
    name to the existing values to offer for it. With context, the model is
    told that the document's original name, source and file date come
    before its transcript. given maps the fields already given for the
    document to their values: the model is told them, and isn't asked for
    them."""
    given = given or {}
    sections = [TASK]
    if context:
        sections.append(CONTEXT_NOTE)
    cabinet_text = f'The document is being filed in the cabinet ' \
        f'"{cabinet.name}"'
    if cabinet.description:
        cabinet_text += f': {cabinet.description.strip()}'
    sections.append(cabinet_text)
    if given:
        sections.append('\n'.join(
            ['Already given for this document (not asked for):']
            + [f'- {field.name}: {given[field.name]}'
               for field in cabinet.fields if field.name in given]))
    lines = ['Fields:']
    for field in asked_fields(cabinet, given):
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


def check_result(result, cabinet: Cabinet, doctypes, given=()) -> dict:
    """Return the model's classification as a dict with data (the
    cabinet's fields not given, in pattern order), doctype and summary,
    validated and
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
    for field in asked_fields(cabinet, given):
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


def read_raw(path: Path) -> str:
    """Return a text document's own text, whole (it is its own transcript,
    see is_raw). Raises Filez4EvaError if it can't be read as UTF-8 or is
    empty."""
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as err:
        raise Filez4EvaError(
            f"Could not read document {path}: {err}") from err
    if not text.strip():
        raise Filez4EvaError(f"Document {path} is empty")
    return text


def document_source(path: Path, results: dict) -> tuple:
    """Return (text, raw) for a document: its own text if it is a text
    document (results.transcribe has `raw: true`; any X.md is ignored),
    otherwise its transcript X.md without front matter"""
    if is_raw(results):
        return read_raw(path), True
    return read_transcript(recorded_transcript(path, results)), False


def ask_model(text: str, schema: dict, instructions: str, model: str,
              api_key):
    """Call extract, turning a Kwark error into Filez4EvaError"""
    try:
        with ai_progress('Classifying', 'Classified'):
            return extract(text, schema, instructions=instructions,
                           model=model, api_key=api_key)
    except KwarkAIError as err:
        raise Filez4EvaError(f"Classification failed: {err}") from err


def classify_text(text: str, cabinet: Cabinet, doctypes: dict, model: str,
                  api_key, context: bool = False, given: dict = None) -> dict:
    """Ask the model for the values of a cabinet's fields that aren't
    given, the doctype and a summary of a document, offering the cabinet's
    existing values. Return the checked result (see check_result), with
    data holding every field of the cabinet in pattern order: the given
    values and the model's. Raises Filez4EvaError if the call fails or the
    answer can't be used."""
    given = given or {}
    schema = build_schema(cabinet, doctypes, given)
    instructions = build_instructions(cabinet, cabinet_vocabulary(cabinet),
                                      doctypes, context, given)
    result = ask_model(text, schema, instructions, model, api_key)
    checked = check_result(result, cabinet, doctypes, given)
    checked['data'] = {
        field.name: given[field.name] if field.name in given
        else checked['data'][field.name] for field in cabinet.fields}
    return checked


def file_date_line(ingest: dict):
    """The file date line given to the model: 'File created: YYYY-MM-DD'
    from results.ingest created, otherwise 'File modified: YYYY-MM-DD' from
    modified, otherwise None. Values that aren't ISO dates are skipped."""
    for key in ('created', 'modified'):
        value = ingest.get(key)
        if isinstance(value, date):
            value = value.isoformat()
        if not isinstance(value, str):
            continue
        try:
            day = date.fromisoformat(value.strip()[:10])
        except ValueError:
            continue
        return f'File {key}: {day.isoformat()}'
    return None


def document_text(transcript: str, ingest: dict, raw: bool = False) -> str:
    """Return the text given to the model for a document in the intake: its
    original file name, source and file date (from results.ingest), then
    its transcript, or with raw, the document's own text (a text document).
    Only the first MAX_CLASSIFY_CHARS characters of it are given; when
    more are cut, its heading says so."""
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
    file_date = file_date_line(ingest)
    if file_date:
        lines.append(file_date)
    heading = 'Document text' if raw else 'Transcript'
    if len(transcript) > MAX_CLASSIFY_CHARS:
        heading += (f" (cut: only the first {MAX_CLASSIFY_CHARS:,} of "
                    f"{len(transcript):,} characters are shown)")
        transcript = transcript[:MAX_CLASSIFY_CHARS]
    return '\n'.join(lines) + f'\n\n{heading}:\n\n' + transcript


class ClassifyCommand(StageCommand):
    """Classify new files (ingesting them first), the documents already in
    the intake, or the ones named with --ingested, with Claude,
    transcribing them first if needed. Each document's cabinet, and any
    given field values, are saved first as results.given (see
    StageCommand.give); the model never picks the cabinet and is asked only
    for the fields not given. Records results.classify (doctype, summary and
    field values for that cabinet) in each document's X.yml. With the
    cabinet and every field given, the record is saved as results.review
    instead, with no model call."""

    name = 'classify'
    summary = 'have an AI model propose field values for each cabinet'
    description = f"""
        Have an AI model propose a doctype, a summary and a value for each
        of the cabinet's fields for each document, and record them as
        results.classify in its X.yml sidecar. Prints each document's
        path.

        The model is given the document's transcript X.md, or a text
        document's own text (it has no transcript), with its original
        name and source. Only the first {MAX_CLASSIFY_CHARS:,}
        characters of the transcript or text are given; the model is told
        when the rest is cut.

        The model never picks the cabinet (see Cabinet below). With
        several cabinets and no --cabinet, classify prompts for each
        document's cabinet before classifying it; give --cabinet to run
        unattended. Given data (--date, --field or stdin) applies to every
        document, and the model fills in only the other fields; with every
        field given, the record is saved as reviewed with no model call
        (see Given data below).

        Main use: `filez4eva classify -c NAME ~/Scans`, then
        `filez4eva stow`."""
    stage = 'classify'
    done = 'Classified'
    doing = CLASSIFY_DOING
    requires = (TranscribeCommand,)

    def handle_vals(self):
        super().handle_vals()
        # Check the doctypes too before any file is touched (the cabinets
        # and --cabinet are checked by StageCommand)
        self.doctypes = load_doctypes(self.app.config)

    @property
    def model(self) -> str:
        """Model from `filez4eva: classify: model:`, or the default"""
        return classify_model(self.app.config)

    @property
    def api_key(self):
        """Key from `filez4eva: anthropic: key:`, or None for the SDK
        default"""
        return anthropic_key(self.app.config)

    def document_cabinet(self, path: Path, results: dict) -> Cabinet:
        """The cabinet saved for the document (results.given). Raises
        Filez4EvaError if there is none or it isn't configured."""
        name = saved_cabinet(results)
        if name is None:
            raise Filez4EvaError(f"No cabinet given for {path.name}")
        if name not in self.cabinets:
            raise Filez4EvaError(
                f"Unknown cabinet {name} for {path.name}; known: "
                + ', '.join(sorted(self.cabinets)))
        return self.cabinets[name]

    def act(self, path: Path) -> str:
        """Classify an ingested, transcribed document for its saved cabinet
        from its transcript (or, for a text document, its own text; see
        document_source), original name, source and file date, asking the
        model only for the fields not given for it (results.given.data),
        record results.classify (data: the given values and the model's), and
        return the document's path"""
        results = load_sidecar(path)['results']
        cabinet = self.document_cabinet(path, results)
        source, raw = document_source(path, results)
        text = document_text(source, results.get('ingest'), raw)
        given = {name: value for name, value in given_values(results).items()
                 if cabinet.field(name) is not None}
        values = classify_text(text, cabinet, self.doctypes, self.model,
                               self.api_key, context=True, given=given)
        record_result(path, self.stage, {
            'at': ingest_command.now().isoformat(timespec='seconds'),
            'model': self.model,
            'doctype': values['doctype'],
            'summary': values['summary'],
            'data': values['data'],
        })
        return str(path)

    @Filez4EvaCommand.wrap
    def execute(self):
        return self.run()
