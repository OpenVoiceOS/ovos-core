import sys
import unittest


class TestDeprecatedImports(unittest.TestCase):
    def test_msm(self):
        from mycroft.skills.msm_wrapper import create_msm, build_msm_config

    def test_tts(self):
        from mycroft.tts import TTS, TTSValidator, TTSFactory, PlaybackThread, EMPTY_PLAYBACK_QUEUE_TUPLE
        from mycroft.tts.tts import TTS, TTSValidator, TTSFactory, PlaybackThread, EMPTY_PLAYBACK_QUEUE_TUPLE
        from mycroft.tts.cache import TextToSpeechCache, hash_from_path, hash_sentence
        from mycroft.tts.remote_tts import RemoteTTS, RemoteTTSException, RemoteTTSTimeoutException

    def test_stt(self):
        from mycroft.stt import STT, STTFactory, StreamingSTT, StreamThread, \
            KeySTT, TokenSTT, MycroftSTT, BasicSTT, GoogleJsonSTT

    def test_audio(self):
        from mycroft.audio.services import AudioBackend, RemoteAudioBackend
        from mycroft.audio.services.simple import SimpleAudioService
        from mycroft.audio.services.vlc import VlcService


    def test_enclosure(self):
        from mycroft.client.enclosure.mark1 import EnclosureMark1, EnclosureMouth, EnclosureEyes, \
            EnclosureArduino, EnclosureReader, EnclosureWriter
        from mycroft.client.enclosure.mark2 import EnclosureMark2
        from mycroft.client.enclosure.generic import EnclosureGeneric
        from mycroft.client.enclosure.base import Enclosure


    def test_speech(self):
        from mycroft.client.speech.data_structures import RollingMean, CyclicAudioBuffer
        from mycroft.client.speech.word_extractor import WordExtractor
        from mycroft.client.speech.mic import MutableMicrophone, MutableStream, ResponsiveRecognizer, get_silence
        from mycroft.client.speech.listener import AudioConsumer, AudioProducer, AudioStreamHandler, \
            RecognizerLoop, RecognizerLoopState, recognizer_conf_hash
