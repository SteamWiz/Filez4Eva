import yaml
from wizlib.command import WizCommand


class Filez4EvaCommand(WizCommand):

    default = 'scan-dir'

    def stdin_mapping(self) -> dict:
        """Return the YAML mapping piped on stdin, or an empty dict if stdin
        is absent, empty, malformed, or not a mapping. BaseLoader keeps every
        scalar as a string, so values like 0123 or yes are not converted."""
        stream = getattr(self.app, 'stream', None)
        text = getattr(stream, 'text', None) if stream else None
        if not isinstance(text, str) or not text.strip():
            return {}
        try:
            record = yaml.load(text, Loader=yaml.BaseLoader)
        except yaml.YAMLError:
            return {}
        return record if isinstance(record, dict) else {}
