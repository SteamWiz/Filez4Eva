from argparse import RawDescriptionHelpFormatter

from wizlib.app import WizApp
from wizlib.stream_handler import StreamHandler
from wizlib.config_handler import ConfigHandler
from wizlib.ui_handler import UIHandler

from filez4eva.command import Filez4EvaCommand


class Filez4EvaApp(WizApp):

    base = Filez4EvaCommand
    name = 'filez4eva'
    handlers = [StreamHandler, ConfigHandler, UIHandler]

    # The commands, in stage order, for `filez4eva --help`
    commands = ('ingest', 'transcribe', 'classify', 'review', 'stow')

    @classmethod
    def initialize(cls):
        super().initialize()
        lines = []
        for name in cls.commands:
            command = cls.base.family_member('name', name)
            lines.append(f"  {name:<12}{command.summary}")
        cls.parser.formatter_class = RawDescriptionHelpFormatter
        cls.parser.description = '\n'.join([
            'Shift scans, photos and other files into structured folders,',
            'in stages:', '', *lines, '',
            'Each command but ingest takes a file, a directory or nothing',
            '(every document in the intake), and runs the earlier stages a',
            'document lacks first, unless --only is given.', '',
            'Main use: `filez4eva classify ~/Scans`, then `filez4eva stow`.',
            '',
            '`filez4eva COMMAND --help` describes a command.'])
