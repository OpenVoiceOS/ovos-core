# backwards compat imports
from ovos_listener.listener import RecognizerLoop
from ovos_listener.mic import ListenerState, ListeningMode
from ovos_listener.service import SpeechService, on_ready, on_stopping, on_error
from ovos_utils.log import LOG


class SpeechClient(SpeechService):
    def __init__(self, *args, **kwargs):
        LOG.warning("SpeechClient has been renamed to SpeechService, it will be removed in 0.1.0")
        super().__init__(self, *args, **kwargs)

