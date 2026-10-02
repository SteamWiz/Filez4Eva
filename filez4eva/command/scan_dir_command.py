import os
from pathlib import Path
from subprocess import run

from wizlib.parser import WizParser
from wizlib.ui import Chooser
from wizlib.ui.shell_ui import Emphasis
from wizlib.app import AppCancellation

from filez4eva.command import Filez4EvaCommand
from filez4eva.command.stow_file_command import StowFileCommand


class StowDirCommand(Filez4EvaCommand):
    """Handle files from a directory"""

    name = 'stow-dir'

    @classmethod
    def add_args(cls, parser: WizParser):
        super().add_args(parser)
        parser.add_argument('dir', nargs='?')

    def handle_vals(self):
        super().handle_vals()
        if not self.provided('dir'):
            self.dir = self.app.config.get('filez4eva-source')

    @Filez4EvaCommand.wrap
    def execute(self):
        path = Path(self.dir).expanduser().absolute()
        self.results = {}
        self.handle_path(path)

    @property
    def status(self):
        keys = sorted(self.results.keys())

        def files(num):
            return "1 file" if (num == 1) else f"{num} files"
        return ' | '.join([f"{k} {files(self.results[k])}" for k in keys])

    def handle_path(self, path: Path):
        if not path.name.startswith('.'):
            if path.is_dir():
                for subpath in sorted(path.iterdir()):
                    self.handle_path(subpath)
            elif path.is_file():
                self.handle_file(path)

    ACTION_CHOOSER = Chooser('', '', {'x': 'skip', 'p': 'preview',
                                      's': 'stow', 'd': 'delete', 'q': 'quit'})

    DELETE_CHOOSER = Chooser('Delete?', 'No', {'Y': 'Yes'})

    def handle_file(self, file):
        self.app.ui.send(file.name)
        while True:
            action = self.app.ui.get_option(self.ACTION_CHOOSER)
            if action == 'preview':
                self.app.ui.send('Previewing...', Emphasis.INFO)
                run(['preview', file])
                continue
            elif action == 'delete':
                confirm = self.app.ui.get_option(self.DELETE_CHOOSER)
                if confirm != 'Yes':
                    continue
                os.remove(file)
                self.increment_result('Deleted')
            elif action == 'stow':
                command = StowFileCommand(self.app, file=str(file))
                command.execute()
                if command.status:
                    self.increment_result('Stowed')
                else:
                    self.app.ui.send(file.name)
                    continue
            elif action == 'quit':
                message = (
                    f"{self.status} | " if self.results else "") + "Quit"
                raise AppCancellation(message)
            elif action == 'skip':
                self.increment_result('Skipped')
            break

    def increment_result(self, result):
        self.results[result] = (self.results.get(result) or 0) + 1
        self.app.ui.send(result, Emphasis.INFO)
