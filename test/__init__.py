import re

from filez4eva import Filez4EvaApp


Filez4EvaApp.initialize()


# The colour codes WizLib's shell UI puts around a line it sends
COLOUR = re.compile(r'\x1b\[[0-9;]*m')


def plain(text: str) -> str:
    """stderr text without colour codes"""
    return COLOUR.sub('', text)
