"""Directory paths from the configuration (targets, the intake, transcript
roots), which must be absolute"""

from pathlib import Path

from filez4eva.error import Filez4EvaError


def absolute_path(owner: str, key: str, value: str) -> Path:
    """Return a configured path, with ~ and ~user expanded. Raises
    Filez4EvaError naming the owner and key if the result isn't absolute
    (a ~ or ~user that can't be expanded fails too)."""
    try:
        path = Path(value).expanduser()
    except RuntimeError:
        # No home directory for ~ or ~user
        path = Path(value)
    if not path.is_absolute():
        raise Filez4EvaError(
            f"{owner} {key} must be an absolute path (or start with ~), "
            f"not {value!r}")
    return path
