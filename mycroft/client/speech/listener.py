"""
This module contains back compat imports only
Speech client moved into mycroft.listener module
"""
from ovos_listener.stt import STTFactory
from ovos_listener.hotword_factory import HotWordFactory
from ovos_listener.listener import AudioConsumer, AudioProducer, AudioStreamHandler, \
    AUDIO_DATA, STREAM_DATA, STREAM_STOP, STREAM_START, MAX_MIC_RESTARTS, \
    RecognizerLoop, RecognizerLoopState, recognizer_conf_hash
from ovos_listener.utils import find_input_device
