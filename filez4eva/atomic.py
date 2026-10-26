import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def write_atomically(path: Path, content: str):
    """Write text to path via a temporary file in the same directory, so a
    failure never leaves a partly written file behind"""
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
