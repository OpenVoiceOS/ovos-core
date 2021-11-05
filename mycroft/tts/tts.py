from ovos_plugin_manager.tts import OVOSTTSFactory, load_tts_plugin
from ovos_plugin_manager.templates.tts import PlaybackThread, \
    TTS, TTSValidator, EMPTY_PLAYBACK_QUEUE_TUPLE
from mycroft.configuration import Configuration
from mycroft.tts.dummy_tts import DummyTTS


class TTSFactory(OVOSTTSFactory):
    @staticmethod
    def create():
        config = Configuration.get()
        if config.get("tts", {}).get("module", "") == "dummy":
            return DummyTTS()
        return OVOSTTSFactory.create(config)
