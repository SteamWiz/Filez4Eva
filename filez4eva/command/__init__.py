from argparse import RawDescriptionHelpFormatter
from inspect import cleandoc

import yaml
from wizlib.command import WizCommand
from wizlib.parser import WizParser


def stdin_mapping(app) -> dict:
    """Return the YAML mapping piped on stdin, or an empty dict if stdin
    is absent, empty, malformed, or not a mapping. BaseLoader keeps every
    scalar as a string, so values like 0123 or yes are not converted."""
    stream = getattr(app, 'stream', None)
    text = getattr(stream, 'text', None) if stream else None
    if not isinstance(text, str) or not text.strip():
        return {}
    try:
        record = yaml.load(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError:
        return {}
    return record if isinstance(record, dict) else {}


class Filez4EvaCommand(WizCommand):

    # No default command: running filez4eva without one is an error
    default = None

    # One line for the list of commands in `filez4eva --help`
    summary: str = None

    # The text of `filez4eva COMMAND --help`, before the arguments
    description: str = None

    @classmethod
    def add_args(cls, parser: WizParser):
        super().add_args(parser)
        parser.formatter_class = RawDescriptionHelpFormatter
        if cls.description:
            parser.description = cleandoc(cls.description)

    def stdin_mapping(self) -> dict:
        """Return the YAML mapping piped on stdin; see stdin_mapping"""
        return stdin_mapping(self.app)
