"""
NOTE: this is dead code! do not use!
This file is only present to ensure backwards compatibility
in case someone is importing from here
This is only meant for 3rd party code expecting ovos-core
to be a drop in replacement for mycroft-core
"""
from ovos_audio.tts import TTSFactory, OVOSTTSFactory
from ovos_plugin_manager.templates.tts import TTS, RemoteTTS
from ovos_plugin_manager.templates.tts import PlaybackThread, \
    TTS, TTSValidator, EMPTY_PLAYBACK_QUEUE_TUPLE
