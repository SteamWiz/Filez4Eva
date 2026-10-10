from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml
from kwark.ai import KwarkAIError, TRANSCRIBE_DISCLAIMER, transcribe
from wizlib.parser import WizParser

from filez4eva.command import Filez4EvaCommand
from filez4eva.error import Filez4EvaError


# Model used when `filez4eva: transcribe: model:` is not configured
DEFAULT_MODEL = 'claude-opus-4-6'

FRONT_MATTER_DELIMITER = '---'

CHUNK_SIZE = 1024 * 1024


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


def write_atomically(path: Path, content: str):
    """Write text to path via a temporary file in the same directory, so a
    failure never leaves a partial transcript behind"""
    with NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                            prefix=f'.{path.name}.', suffix='.tmp',
                            delete=False) as temp:
        try:
            temp.write(content)
        except BaseException:
            temp.close()
            os.unlink(temp.name)
            raise
    try:
        os.replace(temp.name, path)
    except BaseException:
        os.unlink(temp.name)
        raise


class TranscribeCommand(Filez4EvaCommand):
    """Transcribe a file to Markdown with Claude, writing FILE.md next to
    FILE"""

    name = 'transcribe'

    force: bool = False

    @classmethod
    def add_args(cls, parser: WizParser):
        super().add_args(parser)
        parser.add_argument('--force', '-f', action='store_true')
        parser.add_argument('file')

    @property
    def model(self) -> str:
        """Model from `filez4eva: transcribe: model:`, or the default"""
        return self.app.config.get('filez4eva-transcribe-model') \
            or DEFAULT_MODEL

    @property
    def api_key(self):
        """Key from `filez4eva: anthropic: key:` (or the
        FILEZ4EVA_ANTHROPIC_KEY environment variable). None if unset, so the
        Anthropic SDK falls back to ANTHROPIC_API_KEY."""
        return self.app.config.get('filez4eva-anthropic-key') or None

    @Filez4EvaCommand.wrap
    def execute(self):
        path = Path(self.file).expanduser().absolute()
        if not path.is_file():
            raise Filez4EvaError(f"File {path} must exist")
        sha256 = file_sha256(path)
        target = transcript_path(path)
        if not self.force and target.is_file():
            cached = read_front_matter(target).get('sha256')
            if cached is not None and str(cached) == sha256:
                self.status = 'Unchanged'
                return str(target)
        model = self.model
        try:
            markdown = transcribe(path, model=model, api_key=self.api_key)
        except KwarkAIError as err:
            raise Filez4EvaError(f"Transcription failed: {err}") from err
        transcribed = datetime.now(timezone.utc).isoformat(timespec='seconds')
        write_atomically(target, format_transcript(
            path.name, sha256, model, transcribed, markdown))
        self.status = 'Transcribed'
        return str(target)
