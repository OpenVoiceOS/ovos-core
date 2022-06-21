from pathlib import Path
from queue import Queue
import time

import unittest
from unittest import mock
import mycroft.tts

mock_phoneme = mock.Mock(name='phoneme')
mock_audio = "/tmp/mock_path.wav"
mock_viseme = mock.Mock(name='viseme')


class MockTTS(mycroft.tts.TTS):
    def __init__(self, lang, config, validator, audio_ext='wav',
                 phonetic_spelling=True, ssml_tags=None):
        super().__init__(lang, config, validator, audio_ext)
        self.get_tts = mock.Mock()
        self.get_tts.return_value = (mock_audio, "this is a phoneme")
        self.viseme = mock.Mock()
        self.viseme.return_value = mock_viseme


class MockTTSValidator(mycroft.tts.TTSValidator):
    def validate(self):
        pass

    def validate_lang(self):
        pass

    def validate_connection(self):
        pass

    def get_tts_class(self):
        return TestTTS


class TestPlaybackThread(unittest.TestCase):
    def test_lifecycle(self):
        playback = mycroft.tts.PlaybackThread(Queue())
        playback.init(mock.Mock())
        playback.start()
        playback.stop()
        playback.join()

    @mock.patch('ovos_plugin_manager.templates.tts.play_audio')
    def test_process_queue(self, mock_play_audio):
        queue = Queue()
        playback = mycroft.tts.PlaybackThread(queue)
        mock_tts = mock.Mock()
        playback.init(mock_tts)
        playback.enclosure = mock.Mock()
        playback.start()
        try:
            # Test wav data
            wav_mock = mock.Mock(name='wav_data')
            queue.put(('wav', wav_mock, None, 0, False))
            time.sleep(0.2)
            mock_tts.begin_audio.called_with()
            mock_play_audio.assert_called_with(wav_mock)
            # TODO fix me
            #mock_tts.end_audio.assert_called_with(False)

            # Test mp3 data and trigger listening True
            mp3_mock = mock.Mock(name='mp3_data')
            queue.put(('mp3', mp3_mock, None, 0, True))
            time.sleep(0.2)
            mock_play_audio.assert_called_with(mp3_mock)

            # TODO fix me
            # mock_tts.end_audio.assert_called_with(True)
            self.assertFalse(playback.enclosure.get.called)

        finally:
            # Terminate the thread
            playback.stop()
            playback.join()


@mock.patch('mycroft.tts.tts.PlaybackThread')
class TestTTS(unittest.TestCase):
    def test_execute(self, mock_playback_thread):
        tts = MockTTS("en-US", {}, MockTTSValidator(None))

        with mock.patch('mycroft.tts.tts.open') as mock_open:
            tts.cache.temporary_cache_dir = Path('/tmp/dummy')
            tts.execute('Oh no, not again', 42)
        tts.get_tts.assert_called_with(
            'Oh no, not again',
            '/tmp/dummy/8da7f22aeb16bc3846ad07b644d59359.wav'
        )

        # TODO
        #tts.queue.put.assert_called_with(
        #    (
        #        'wav',
        #        mock_audio,
        #        mock_viseme,
        #        42,
        #        False
        #    )
        #)

    def test_ssml_support(self, _):
        sentence = "<speak>Prosody can be used to change the way words " \
                   "sound. The following words are " \
                   "<prosody volume='x-loud'> " \
                   "quite a bit louder than the rest of this passage. " \
                   "</prosody> Each morning when I wake up, " \
                   "<prosody rate='x-slow'>I speak quite slowly and " \
                   "deliberately until I have my coffee.</prosody> I can " \
                   "also change the pitch of my voice using prosody. " \
                   "Do you like <prosody pitch='+5%'> speech with a pitch " \
                   "that is higher, </prosody> or <prosody pitch='-10%'> " \
                   "is a lower pitch preferable?</prosody></speak>"
        sentence_no_ssml = "Prosody can be used to change the way " \
                           "words sound. The following words are quite " \
                           "a bit louder than the rest of this passage. " \
                           "Each morning when I wake up, I speak quite " \
                           "slowly and deliberately until I have my " \
                           "coffee. I can also change the pitch of my " \
                           "voice using prosody. Do you like speech " \
                           "with a pitch that is higher, or is " \
                           "a lower pitch preferable?"
        sentence_bad_ssml = "<foo_invalid>" + sentence + \
                            "</foo_invalid end=whatever>"
        sentence_extra_ssml = "<whispered>whisper tts<\\whispered>"

        tts = MockTTS("en-US", {}, MockTTSValidator(None))

        # test valid ssml
        tts.ssml_tags = ['speak', 'prosody']
        self.assertEqual(tts.validate_ssml(sentence), sentence)

        # test extra ssml
        tts.ssml_tags = ['whispered']
        self.assertEqual(tts.validate_ssml(sentence_extra_ssml),
                         sentence_extra_ssml)

        # test unsupported extra ssml
        tts.ssml_tags = ['speak', 'prosody']
        self.assertEqual(tts.validate_ssml(sentence_extra_ssml),
                         "whisper tts")

        # test mixed valid / invalid ssml
        tts.ssml_tags = ['speak', 'prosody']
        self.assertEqual(tts.validate_ssml(sentence_bad_ssml), sentence)

        # test unsupported ssml
        tts.ssml_tags = []
        self.assertEqual(tts.validate_ssml(sentence), sentence_no_ssml)

        self.assertEqual(tts.validate_ssml(sentence_bad_ssml),
                         sentence_no_ssml)

        self.assertEqual(mycroft.tts.TTS.remove_ssml(sentence),
                         sentence_no_ssml)
