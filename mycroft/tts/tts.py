"""
This module contains back compat imports only
logic moved into mycroft.audio module  and ovos plugin manager
"""
from ovos_audio.tts import TTSFactory, OVOSTTSFactory
from ovos_plugin_manager.templates.tts import PlaybackThread, \
    TTS, TTSValidator, EMPTY_PLAYBACK_QUEUE_TUPLE
