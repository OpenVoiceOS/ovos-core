"""
This module contains back compat imports only
Speech client moved into mycroft.listener module
"""
from ovos_listener.mic import WakeWordData, MutableStream, MutableMicrophone, get_silence, ResponsiveRecognizer
from mycroft.deprecated.speech_client import NoiseTracker

