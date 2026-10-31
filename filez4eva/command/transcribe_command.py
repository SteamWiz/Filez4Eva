from datetime import datetime, timezone
import hashlib
from pathlib import Path

import yaml
from kwark.ai import KwarkAIError, TRANSCRIBE_DISCLAIMER, transcribe

from filez4eva.atomic import write_atomically
from filez4eva.command import Filez4EvaCommand
from filez4eva.command import ingest_command
from filez4eva.error import Filez4EvaError
from filez4eva.progress import ai_progress
from filez4eva.stage import StageCommand, record_result


# Model used when `filez4eva: transcribe: model:` is not configured
DEFAULT_MODEL = 'claude-opus-4-6'

FRONT_MATTER_DELIMITER = '---'

CHUNK_SIZE = 1024 * 1024

# The binary file types the model transcribes (lower-case suffixes): PDF
# and images. Any other file that decodes as UTF-8 text is a text document,
# its own transcript (see read_text).
TRANSCRIBABLE = ('.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp')

# Key in results.transcribe of a text document: the document is its own
# transcript, so no X.md is written and later stages read the file itself
RAW = 'raw'

# Status label for text documents (`Not transcribed 1 file (text)`)
TEXT_DONE = ('Not transcribed', 'text')


def file_sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of a file, read in chunks"""
    digest = hashlib.sha256()
    with open(path, 'rb') as file:
        while chunk := file.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def transcript_path(path: Path) -> Path:
    """Return the transcript path for a file: the full name plus '.md', so
    scan.pdf becomes scan.pdf.md"""
    return Path(str(path) + '.md')


def transcribable(path: Path) -> bool:
    """True if the file's extension is one of the binary types the model
    transcribes (TRANSCRIBABLE, any case)"""
    return path.suffix.lower() in TRANSCRIBABLE


def read_text(path: Path):
    """Return the content of a text document, or None if the file isn't
    one: its extension is a type the model transcribes, or its content
    doesn't decode as UTF-8 or has a NUL byte. Raises OSError if the file
    can't be read."""
    if transcribable(path):
        return None
    data = path.read_bytes()
    if b'\x00' in data:
        return None
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return None


def unsupported(path: Path) -> Filez4EvaError:
    """The error for a file that is neither a type the model transcribes
    nor UTF-8 text"""
    return Filez4EvaError(
        f"Unsupported file type {path.suffix or '(none)'}: transcribe "
        f"supports {', '.join(TRANSCRIBABLE)} and UTF-8 text")


def is_raw(results: dict) -> bool:
    """True if a document's results.transcribe says it is its own
    transcript (a text document: `raw: true`)"""
    transcribed = results.get('transcribe')
    return isinstance(transcribed, dict) and transcribed.get(RAW) is True


def recorded_transcript(path: Path, results: dict) -> Path:
    """Return a document's transcript X.md, checked against the name in its
    results.transcribe. Raises Filez4EvaError if that names another file,
    so a sidecar can never point a stage at a different file."""
    target = transcript_path(path)
    transcribed = results.get('transcribe')
    name = transcribed.get('transcript') \
        if isinstance(transcribed, dict) else None
    if name is not None and name != target.name:
        raise Filez4EvaError(
            f"results.transcribe names transcript {name!r}, not "
            f"{target.name!r}")
    return target


def read_front_matter(path: Path) -> dict:
    """Return the YAML front matter of a Markdown file as a dict, or an empty
    dict if the file is missing, unreadable, has no front matter, or the front
    matter isn't a valid YAML mapping"""
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return {}
    lines = text.splitlines()
    if not lines or lines[0].rstrip() != FRONT_MATTER_DELIMITER:
        return {}
    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip() == FRONT_MATTER_DELIMITER:
            try:
                data = yaml.safe_load('\n'.join(lines[1:index]))
            except yaml.YAMLError:
                return {}
            return data if isinstance(data, dict) else {}
    return {}


def format_transcript(source: str, sha256: str, model: str,
                      transcribed: str, markdown: str) -> str:
    """Return the transcript file content: front matter, disclaimer comment,
    a blank line, then the Markdown with a trailing newline"""
    front_matter = yaml.safe_dump(
        {'source': source, 'sha256': sha256, 'model': model,
         'transcribed': transcribed},
        sort_keys=False, allow_unicode=True, default_flow_style=False)
    body = markdown.strip('\n')
    return (f"{FRONT_MATTER_DELIMITER}\n{front_matter}"
            f"{FRONT_MATTER_DELIMITER}\n"
            f"<!-- {TRANSCRIBE_DISCLAIMER} -->\n\n"
            f"{body}\n")


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


def transcribe_model(config) -> str:
    """Model from `filez4eva: transcribe: model:`, or the default"""
    return config.get('filez4eva-transcribe-model') or DEFAULT_MODEL


def transcribe_file(path: Path, model: str, api_key=None) -> tuple:
    """Transcribe a file in place, writing FILE.md next to it, unless that
    transcript's sha256 already matches the file. Return (transcript path,
    'Transcribed' or 'Unchanged'). Nothing is ingested or moved. Raises
    Filez4EvaError if the file is missing, isn't a type the model
    transcribes (TRANSCRIBABLE; checked before any model call), or
    transcription fails, leaving any existing transcript as it was."""
    if not path.is_file():
        raise Filez4EvaError(f"File {path} must exist")
    if not transcribable(path):
        raise unsupported(path)
    sha256 = file_sha256(path)
    target = transcript_path(path)
    if target.is_file():
        cached = read_front_matter(target).get('sha256')
        if cached is not None and str(cached) == sha256:
            return target, 'Unchanged'
    try:
        with ai_progress('Transcribing', 'Transcribed'):
            markdown = transcribe(path, model=model, api_key=api_key)
    except KwarkAIError as err:
        raise Filez4EvaError(f"Transcription failed: {err}") from err
    transcribed = datetime.now(timezone.utc).isoformat(timespec='seconds')
    write_atomically(target, format_transcript(
        path.name, sha256, model, transcribed, markdown))
    return target, 'Transcribed'


class TranscribeCommand(StageCommand):
    """Transcribe new files (ingesting them first), the documents already in
    the intake, or the ones named with --ingested, to Markdown with Claude.
    Writes X.md next to each document X in the intake and records
    results.transcribe in X.yml. A text document is its own transcript: no
    model call and no X.md, just results.transcribe with `raw: true`."""

    name = 'transcribe'
    summary = 'transcribe documents to Markdown (X.md) with an AI model'
    description = """
        Transcribe documents to Markdown with an AI model, writing X.md next
        to each document X in the intake and recording results.transcribe
        in its X.yml sidecar. Prints each transcript's path.

        The model transcribes PDF and image files (.pdf, .png, .jpg,
        .jpeg, .gif, .webp). Any other file whose content is UTF-8 text
        (e.g. .txt, .md, .csv, .json, or no extension) is a text document:
        it is its own transcript, so there is no model call and no X.md;
        results.transcribe records `raw: true`, later stages read the file
        itself, and its path is printed. Any other file fails as an
        unsupported file type."""
    stage = 'transcribe'
    done = 'Transcribed'
    doing = 'Transcribing'
    outcomes = (TEXT_DONE,)

    @property
    def model(self) -> str:
        """Model from `filez4eva: transcribe: model:`, or the default"""
        return transcribe_model(self.app.config)

    @property
    def api_key(self):
        """Key from `filez4eva: anthropic: key:` (or the
        FILEZ4EVA_ANTHROPIC_KEY environment variable). None if unset, so the
        Anthropic SDK falls back to ANTHROPIC_API_KEY."""
        return self.app.config.get('filez4eva-anthropic-key') or None

    def act(self, path: Path) -> str:
        """Transcribe an ingested document (reusing a transcript whose
        sha256 matches), record results.transcribe, and return the
        transcript path. A text document (see read_text) is its own
        transcript: record results.transcribe with `raw: true` and its
        length, with no model call and no X.md (one already there is left
        alone and never used), count it as TEXT_DONE, and return its
        path."""
        if not path.is_file():
            raise Filez4EvaError(f"File {path} must exist")
        text = read_text(path)
        if text is not None:
            record_result(path, self.stage, {
                'at': ingest_command.now().isoformat(timespec='seconds'),
                RAW: True,
                'length': len(text),
            })
            self.outcome = TEXT_DONE
            return str(path)
        target, _ = transcribe_file(path, self.model, self.api_key)
        at = ingest_command.now()
        try:
            text = target.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as err:
            raise Filez4EvaError(
                f"Could not read transcript {target}: {err}") from err
        model = read_front_matter(target).get('model') or self.model
        record_result(path, self.stage, {
            'at': at.isoformat(timespec='seconds'),
            'model': str(model),
            'transcript': target.name,
            'length': len(transcript_body(text)),
        })
        return str(target)

    @Filez4EvaCommand.wrap
    def execute(self):
        return self.run()
