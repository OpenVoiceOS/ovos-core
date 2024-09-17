# backwards compat imports
from speech_recognition import (
    Microphone,
    AudioSource,
    AudioData
)
from mycroft.deprecated.speech_client import NoiseTracker, RollingMean
from ovos_listener.data_structures import CyclicAudioBuffer
from ovos_listener.silence import SilenceDetector, SilenceResultType, SilenceMethod
from ovos_listener.mic import WakeWordData, ListenerState, ListeningMode, MutableStream, \
    MutableMicrophone, ResponsiveRecognizer, get_silence
