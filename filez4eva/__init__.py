from wizlib.app import WizApp
from wizlib.stream_handler import StreamHandler
from wizlib.config_handler import ConfigHandler
from wizlib.ui_handler import UIHandler

from filez4eva.command import Filez4EvaCommand


class Filez4EvaApp(WizApp):

    base = Filez4EvaCommand
    name = 'filez4eva'
    handlers = [StreamHandler, ConfigHandler, UIHandler]
