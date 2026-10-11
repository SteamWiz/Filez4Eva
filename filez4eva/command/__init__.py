from wizlib.command import WizCommand


class Filez4EvaCommand(WizCommand):

    default = 'scan-dir'

    @property
    def api_key(self):
        """Key from `filez4eva: anthropic: key:` (or the
        FILEZ4EVA_ANTHROPIC_KEY environment variable). None if unset, so the
        Anthropic SDK falls back to ANTHROPIC_API_KEY."""
        return self.app.config.get('filez4eva-anthropic-key') or None
