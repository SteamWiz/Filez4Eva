"""Progress indicator for AI calls: while a blocking call to the model runs,
and stderr is a terminal, a spinner and the elapsed seconds are redrawn in
place on one stderr line. When the call ends, the line is replaced with a
final one (e.g. `Transcribed in 23s`); when it fails or is interrupted, the
line is cleared. When stderr isn't a terminal, nothing is drawn."""

from contextlib import contextmanager
import sys
import threading
import time


# Spinner frames, drawn in turn
FRAMES = '|/-\\'

# Seconds between redraws (the elapsed time is shown in whole seconds, so
# it changes at least once a second)
INTERVAL = 0.2

# Return to the start of the line and clear it
CLEAR = '\r\x1b[K'


def is_terminal(stream) -> bool:
    """True if the stream is a terminal"""
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


class Spinner:
    """A spinner and the elapsed seconds on one line of a terminal stream,
    redrawn by a daemon thread every `interval` seconds until stop()"""

    def __init__(self, doing: str, stream, clock=time.monotonic,
                 interval: float = INTERVAL):
        self.doing = doing
        self.stream = stream
        self.clock = clock
        self.interval = interval
        self.frame = 0
        self.stopping = threading.Event()
        self.thread = None
        self.started = None

    def elapsed(self) -> int:
        """Whole seconds since start()"""
        return int(self.clock() - self.started)

    def write(self, text: str):
        self.stream.write(text)
        self.stream.flush()

    def draw(self):
        """Draw the next frame in place"""
        char = FRAMES[self.frame % len(FRAMES)]
        self.frame += 1
        self.write(f"{CLEAR}{char} {self.doing}... {self.elapsed()}s")

    def spin(self):
        while not self.stopping.wait(self.interval):
            self.draw()

    def start(self):
        """Draw the first frame now, then keep redrawing in the background"""
        self.started = self.clock()
        self.draw()
        self.thread = threading.Thread(target=self.spin, daemon=True)
        self.thread.start()

    def stop(self, final: str = None):
        """Stop redrawing and clear the line, writing final (a line of its
        own) in its place, if given"""
        self.stopping.set()
        self.thread.join()
        self.write(CLEAR + (f"{final}\n" if final else ''))


@contextmanager
def ai_progress(doing: str, done: str, clock=None, interval: float = None):
    """Show a spinner and the elapsed seconds on stderr (if it is a
    terminal) while the block runs, e.g. a blocking AI call. doing names
    the work in progress (e.g. 'Transcribing'); done is the start of the
    final line (e.g. 'Transcribed', for `Transcribed in 23s`). On an error
    or an interrupt, the line is cleared and the exception goes on. clock
    (default time.monotonic) and interval (default INTERVAL) are for
    tests."""
    stream = sys.stderr
    if not is_terminal(stream):
        yield
        return
    spinner = Spinner(doing, stream, clock or time.monotonic,
                      INTERVAL if interval is None else interval)
    spinner.start()
    try:
        yield
    except BaseException:
        spinner.stop()
        raise
    spinner.stop(f"{done} in {spinner.elapsed()}s")
