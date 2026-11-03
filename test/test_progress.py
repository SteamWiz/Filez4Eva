"""The AI progress indicator: a spinner and the elapsed seconds on stderr
while a model call runs, only when stderr is a terminal"""

from io import StringIO
import threading
from unittest.mock import patch

from kwark.ai import APIError
from wizlib.config_handler import ConfigHandler

from filez4eva import Filez4EvaApp
from filez4eva.command.classify_command import ClassifyCommand
from filez4eva.command.transcribe_command import TranscribeCommand
from filez4eva.error import Filez4EvaError
from filez4eva.progress import (
    CLEAR, INTERVAL, Spinner, ai_progress, is_terminal)
from test import plain
from test.test_command_review import (
    EXTRACT, RESULT, STAMP, TRANSCRIBE, ReviewTestCase)


class Terminal(StringIO):
    """A stream that says it is a terminal"""

    def isatty(self):
        return True


class Clock:
    """A clock that only moves when told to"""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# Long enough that the background thread never redraws during a test, so
# the output is predictable
NEVER = 3600


class TestAIProgress(ReviewTestCase):

    def test_redrawn_at_least_once_a_second(self):
        self.assertLessEqual(INTERVAL, 1)

    def test_spinner_around_the_call_on_a_terminal(self):
        clock = Clock()
        stream = Terminal()
        with patch('sys.stderr', stream):
            with ai_progress('Transcribing', 'Transcribed', clock, NEVER):
                clock.advance(23.6)
        self.assertEqual(stream.getvalue(),
                         f'{CLEAR}| Transcribing... 0s'
                         f'{CLEAR}Transcribed in 23s\n')

    def test_nothing_when_not_a_terminal(self):
        stream = StringIO()
        with patch('sys.stderr', stream), \
                patch('filez4eva.progress.threading.Thread') as thread:
            with ai_progress('Transcribing', 'Transcribed'):
                pass
        thread.assert_not_called()
        self.assertEqual(stream.getvalue(), '')

    def test_failure_clears_the_line(self):
        for error in [Filez4EvaError('boom'), KeyboardInterrupt()]:
            with self.subTest(error=type(error).__name__):
                stream = Terminal()
                with patch('sys.stderr', stream), \
                        self.assertRaises(type(error)):
                    with ai_progress('Classifying', 'Classified', Clock(),
                                     NEVER):
                        raise error
                self.assertEqual(stream.getvalue(),
                                 f'{CLEAR}| Classifying... 0s{CLEAR}')

    def test_redraws_while_the_call_runs(self):
        clock = Clock()
        drawn = threading.Event()

        class Counting(Terminal):
            def write(self, text):
                super().write(text)
                if self.getvalue().count('Classifying...') >= 3:
                    drawn.set()
        stream = Counting()
        with patch('sys.stderr', stream):
            with ai_progress('Classifying', 'Classified', clock, 0.001):
                clock.advance(2)
                self.assertTrue(drawn.wait(5))
        frames = stream.getvalue().split(CLEAR)[1:]
        self.assertEqual(frames[:3], ['| Classifying... 0s',
                                      '/ Classifying... 2s',
                                      '- Classifying... 2s'])
        self.assertEqual(frames[-1], 'Classified in 2s\n')

    def test_spinner_frames_cycle(self):
        stream = StringIO()
        spinner = Spinner('Transcribing', stream, Clock())
        spinner.started = 1000.0
        for _ in range(5):
            spinner.draw()
        self.assertEqual([frame[0] for frame in
                          stream.getvalue().split(CLEAR)[1:]],
                         ['|', '/', '-', '\\', '|'])

    def test_is_terminal(self):
        closed = StringIO()
        closed.close()
        self.assertTrue(is_terminal(Terminal()))
        self.assertFalse(is_terminal(StringIO()))
        self.assertFalse(is_terminal(object()))
        self.assertFalse(is_terminal(closed))

    def run_on_terminal(self, command_class, clock):
        """Run a stage command on the intake with stderr a terminal and
        the clock mocked; return its stdout. stderr is kept in self.err,
        also when the command raises."""
        app = Filez4EvaApp()
        app.config = ConfigHandler.fake(**self.config())
        command = command_class(app)
        out, err = StringIO(), Terminal()
        try:
            with patch('filez4eva.progress.time.monotonic', clock), \
                    patch('filez4eva.progress.INTERVAL', NEVER), \
                    patch('sys.stdout', out), patch('sys.stderr', err), \
                    self.patch_stream(''):
                command.execute()
        finally:
            self.err = plain(err.getvalue())
        return out.getvalue()

    def test_transcribe_call_has_the_spinner(self):
        document = self.make_document(classify=None, transcript=None)
        clock = Clock()

        def transcribe(path, **kwargs):
            clock.advance(23)
            return '# Hi'
        with patch(TRANSCRIBE, side_effect=transcribe) as t:
            out = self.run_on_terminal(TranscribeCommand, clock)
        t.assert_called_once()
        self.assertEqual(self.err, (
            f'Transcribing {document.name} (Scan 1.PDF)\n'
            f'{CLEAR}| Transcribing... 0s{CLEAR}Transcribed in 23s\n'))
        self.assertEqual(out, '')

    def test_classify_call_has_the_spinner(self):
        document = self.make_document(classify=None)
        clock = Clock()

        def extract(*args, **kwargs):
            clock.advance(4)
            return RESULT
        with patch(EXTRACT, side_effect=extract) as e:
            out = self.run_on_terminal(ClassifyCommand, clock)
        e.assert_called_once()
        self.assertEqual(self.err, (
            f'Classifying {document.name} (Scan 1.PDF)\n'
            f'{CLEAR}| Classifying... 0s{CLEAR}Classified in 4s\n'))
        self.assertEqual(out, '')

    def test_failed_call_clears_the_spinner(self):
        document = self.make_document(classify=None, transcript=None)
        with patch(TRANSCRIBE, side_effect=APIError('nope')), \
                self.assertRaises(Filez4EvaError):
            self.run_on_terminal(TranscribeCommand, Clock())
        self.assertEqual(self.err.split('\n'), [
            f'Transcribing {document.name} (Scan 1.PDF)',
            f'{CLEAR}| Transcribing... 0s{CLEAR}Failed to transcribe '
            f'{document}: Transcription failed: nope', ''])

    def test_no_spinner_when_stderr_is_not_a_terminal(self):
        self.make_document(classify=None, transcript=None)
        self.make_document(f'{STAMP[:-1]}3.pdf', classify=None)
        with patch('filez4eva.progress.Spinner') as spinner:
            self.run_command(keys='cc', answers=['a', 'b', 'c'] * 2)
        spinner.assert_not_called()
        self.assertNotIn(CLEAR, self.err)
        self.assertNotIn(' in 0s', self.err)
