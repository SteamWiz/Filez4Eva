from contextlib import contextmanager
from datetime import datetime, timedelta
import errno
import os
from pathlib import Path
import re
import shutil

import yaml
try:
    import fcntl
except ImportError:  # pragma: no cover - no fcntl on Windows
    fcntl = None
from wizlib.parser import WizParser
from wizlib.ui.shell_ui import Emphasis

from filez4eva.atomic import write_atomically
from filez4eva.command import Filez4EvaCommand
from filez4eva.error import Filez4EvaError


# Intake directory used when `filez4eva: intake:` is not configured
DEFAULT_INTAKE = '~/.filez4eva/intake'

# A file extension: 1-5 ASCII letters or digits, at least one a letter
EXTENSION = re.compile(r'[A-Za-z0-9]{1,5}')

SIDECAR_SUFFIX = '.yml'

# Subdirectory of the intake where stow moves a stowed document's sidecar
ARCHIVE = 'archive'


def now() -> datetime:
    """The current local time, with its UTC offset. Tests patch this."""
    return datetime.now().astimezone()


def intake_dir(config) -> Path:
    """Return the intake directory from `filez4eva: intake:` (default
    ~/.filez4eva/intake), expanded and absolute, creating it if needed.
    Raises Filez4EvaError if it can't be created."""
    setting = config.get('filez4eva-intake') or DEFAULT_INTAKE
    if not isinstance(setting, str):
        raise Filez4EvaError(
            f"intake must be a directory path, not {setting!r}")
    path = Path(setting).expanduser().absolute()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise Filez4EvaError(
            f"Could not create intake {path}: {error}") from error
    return path


def extensions(name: str) -> str:
    """Return the trailing extensions of a file name, lower case, each with
    its leading dot (e.g. '.docx.pdf'), or '' if there are none. Suffixes are
    taken from the end while each is 1-5 letters or digits with at least one
    letter. The part before the first dot (ignoring leading dots) is never
    an extension."""
    parts = name.lstrip('.').split('.')[1:]
    result = []
    for part in reversed(parts):
        if not EXTENSION.fullmatch(part) or part.isdigit():
            break
        result.insert(0, '.' + part.lower())
    return ''.join(result)


def stamp_name(dt: datetime, exts: str = '') -> str:
    """Return the intake name for a time: YYYYMMDD-HHMMSS-mmm followed by the
    extensions"""
    return f"{dt:%Y%m%d-%H%M%S}-{dt.microsecond // 1000:03d}{exts}"


def sidecar_path(path: Path) -> Path:
    """Return the sidecar path for a document: the full name plus '.yml'"""
    return Path(str(path) + SIDECAR_SUFFIX)


def archived_sidecar(path: Path) -> Path:
    """Return where stow archives the sidecar of a document in the intake:
    <intake>/archive/X.yml"""
    return path.parent / ARCHIVE / sidecar_path(path).name


def in_intake(path: Path, intake: Path) -> bool:
    """True if path is directly in the intake directory. X/X.yml pairing
    only counts there; elsewhere every file is a new document."""
    try:
        return path.parent.samefile(intake)
    except OSError:
        return False


def is_ingested(path: Path) -> bool:
    """True if path is a file X with X.yml next to it: a document already
    ingested, when path is in the intake (see in_intake)"""
    return path.is_file() and sidecar_path(path).is_file()


def is_companion(path: Path) -> bool:
    """True if path belongs to an ingested document rather than being one:
    its sidecar (X.yml next to X) or its transcript (X.md next to X, where
    X.yml exists)"""
    name = path.name
    if name.endswith(SIDECAR_SUFFIX) and len(name) > len(SIDECAR_SUFFIX):
        return path.with_name(name[:-len(SIDECAR_SUFFIX)]).is_file()
    if name.endswith('.md') and len(name) > len('.md'):
        return is_ingested(path.with_name(name[:-len('.md')]))
    return False


def read_sidecar(path: Path) -> dict:
    """Return the sidecar of a document as a dict, or an empty dict if it is
    missing, unreadable, or not a YAML mapping"""
    try:
        data = yaml.safe_load(
            sidecar_path(path).read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def format_sidecar(data: dict) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True,
                          default_flow_style=False)


def write_sidecar(path: Path, data: dict, exclusive: bool = False):
    """Write the sidecar of a document. With exclusive, fail with
    FileExistsError rather than replace an existing sidecar (and remove a
    partly written one on error); otherwise replace it atomically."""
    content = format_sidecar(data)
    target = sidecar_path(path)
    if not exclusive:
        write_atomically(target, content)
        return
    with open(target, 'x', encoding='utf-8') as file:
        try:
            file.write(content)
        except BaseException:
            file.close()
            target.unlink()
            raise


def ingest_record(at: datetime, original_name: str, source: dict) -> dict:
    """Return the sidecar content written by ingest"""
    return {'results': {'ingest': {
        'at': at.isoformat(timespec='seconds'),
        'original-name': original_name,
        'source': dict(source),
    }}}


def parse_meta(flags: list) -> dict:
    """Return the KEY=VALUE strings from --meta flags as a dict. Raises
    Filez4EvaError on a flag without '=' or with an empty key."""
    meta = {}
    for flag in flags or []:
        key, equals, value = flag.partition('=')
        key = key.strip()
        if not equals or not key:
            raise Filez4EvaError(f"--meta must be KEY=VALUE: {flag!r}")
        meta[key] = value
    return meta


def stamp_taken(intake: Path, stamp: str) -> bool:
    """True if any file in the intake uses the stamp: is named `<stamp>` or
    starts with `<stamp>.` (another document, its X.yml sidecar or its X.md
    transcript)"""
    prefix = stamp + '.'
    return any(name == stamp or name.startswith(prefix)
               for name in os.listdir(intake))


@contextmanager
def intake_lock(intake: Path):
    """Hold an exclusive lock on the intake directory, waiting while another
    process holds it. Taken around stamp check-and-claim, so ingest runs into
    the same intake on one machine never pick the same stamp. The lock is an
    flock on the directory itself, so no lock file is left in the intake,
    and the system releases it when the descriptor is closed, even if the
    process dies."""
    if fcntl is None:  # pragma: no cover - no fcntl on Windows
        raise Filez4EvaError("ingest needs file locking (fcntl), which "
                             "this platform doesn't have")
    fd = os.open(intake, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def reserve(intake: Path, dt: datetime, exts: str, record: dict) -> Path:
    """Claim a stamp no other file in the intake uses for time dt, moving on
    a millisecond at a time while the stamp is taken, so each document has
    its own stamp and a later stage's X.yml or X.md can never land on
    another document. Creates an empty placeholder for the file and writes
    its sidecar, both exclusively, so nothing is ever overwritten. A name
    whose sidecar is already in the archive (a document stowed earlier) is
    passed over too, so stow can always archive the new one. The check
    and the claim happen under the intake lock, so concurrent ingest runs on
    one machine never share a stamp. Return the placeholder path."""
    with intake_lock(intake):
        while True:
            stamp = stamp_name(dt)
            target = intake / (stamp + exts)
            if not stamp_taken(intake, stamp) \
                    and not archived_sidecar(target).exists():
                try:
                    os.close(os.open(target,
                                     os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                                     0o600))
                except FileExistsError:
                    pass
                else:
                    try:
                        write_sidecar(target, record, exclusive=True)
                        return target
                    except FileExistsError:
                        target.unlink()
                    except BaseException:
                        target.unlink()
                        raise
            dt += timedelta(milliseconds=1)


def move_onto(source: Path, target: Path):
    """Move source onto the placeholder at target: a rename on the same
    filesystem, otherwise a copy and then removal of the source"""
    try:
        os.rename(source, target)
    except OSError as error:
        if error.errno != errno.EXDEV:
            raise
        shutil.copy2(source, target)
        source.unlink()


def ingest_file(path: Path, intake: Path, source: dict) -> Path:
    """Move a file into the intake under a time-stamped name and write its
    sidecar. Return the new path. If anything fails, the file stays where it
    was and nothing is left behind in the intake."""
    if path.is_symlink() or not path.is_file():
        raise Filez4EvaError(f"{path} must be a regular file")
    dt = now()
    record = ingest_record(dt, path.name, source)
    target = reserve(intake, dt, extensions(path.name), record)
    try:
        move_onto(path, target)
    except BaseException:
        if path.exists():
            target.unlink(missing_ok=True)
            sidecar_path(target).unlink(missing_ok=True)
        raise
    return target


def top_level_documents(path: Path, intake: Path) -> tuple:
    """Return (ingested, new) for a directory, each in name order: the
    documents among the non-hidden regular files at its top level.
    Subdirectories, hidden files and symbolic links are left alone. In the
    intake, a file X with X.yml next to it is ingested, its sidecar and
    transcript belong to it and are left out, and any other file is new;
    elsewhere every such file is new. The lists are taken before anything
    moves."""
    ingested = []
    new = []
    pairing = path.samefile(intake)
    for entry in sorted(path.iterdir()):
        if entry.name.startswith('.') or entry.is_symlink() \
                or not entry.is_file():
            continue
        if not pairing:
            new.append(entry)
        elif is_ingested(entry):
            ingested.append(entry)
        elif not is_companion(entry):
            new.append(entry)
    return ingested, new


def files(count: int) -> str:
    return "1 file" if count == 1 else f"{count} files"


class IngestCommand(Filez4EvaCommand):
    """Move a file, or the files in a directory, into the intake under a
    time-stamped name, with an X.yml sidecar"""

    name = 'ingest'

    # KEY=VALUE strings from repeated --meta flags
    meta: list = None

    @classmethod
    def add_args(cls, parser: WizParser):
        super().add_args(parser)
        parser.add_argument('--meta', '-m', action='append',
                            metavar='KEY=VALUE')
        parser.add_argument('path')

    def handle_vals(self):
        super().handle_vals()
        # Flags win over stdin. Stdin is read once, for every file.
        self.source = self.stdin_mapping()
        self.source.update(parse_meta(self.meta))

    @staticmethod
    def candidates(path: Path, intake: Path) -> tuple:
        """Return (files, skipped) for a directory: the files to ingest are
        the non-hidden regular files at the top level, in order. In the
        intake, documents already ingested (counted in skipped) and their
        sidecars and transcripts are left out; elsewhere every such file is
        a new document. The list is taken before anything moves."""
        ingested, new = top_level_documents(path, intake)
        return new, len(ingested)

    @Filez4EvaCommand.wrap
    def execute(self):
        path = Path(self.path).expanduser().absolute()
        if not path.exists():
            raise Filez4EvaError(f"{path} must exist")
        intake = intake_dir(self.app.config)
        if not path.is_dir():
            if in_intake(path, intake) and \
                    (is_ingested(path) or is_companion(path)):
                self.status = 'Already ingested'
                return None
            target = ingest_file(path, intake, self.source)
            self.status = 'Ingested'
            return str(target)
        todo, skipped = self.candidates(path, intake)
        done = []
        failed = 0
        for file in todo:
            try:
                done.append(str(ingest_file(file, intake, self.source)))
            except (Filez4EvaError, OSError) as error:
                failed += 1
                self.app.ui.send(f"Failed to ingest {file}: {error}",
                                 Emphasis.ERROR)
        if failed:
            if done:
                print('\n'.join(done))
            raise Filez4EvaError(
                f"{failed} of {files(len(todo))} failed to ingest")
        counts = [('Ingested', len(done)), ('Already ingested', skipped)]
        self.status = ' | '.join(f"{label} {files(count)}"
                                 for label, count in counts if count) \
            or 'No files to ingest'
        return '\n'.join(done)
