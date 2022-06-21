# Copyright 2017 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import unittest
import unittest.mock as mock

from shutil import rmtree
from threading import Thread
from time import sleep

from os.path import exists

from mycroft.audio.service import SpeechService
from mycroft.messagebus import Message
from mycroft.tts.remote_tts import RemoteTTSTimeoutException

"""Tests for speech dispatch service."""


tts_mock = mock.Mock()


def setup_mocks(config_mock, tts_factory_mock):
    """Do the common setup for the mocks."""
    config_mock.get.return_value = {}

    tts_factory_mock.create.return_value = tts_mock
    config_mock.reset_mock()
    tts_factory_mock.reset_mock()
    tts_mock.reset_mock()


@mock.patch('mycroft.audio.service.Configuration')
@mock.patch('mycroft.audio.service.TTSFactory')
class TestSpeech(unittest.TestCase):
    def test_life_cycle(self, tts_factory_mock, config_mock):
        """Ensure the init and shutdown behaves as expected."""
        setup_mocks(config_mock, tts_factory_mock)
        bus = mock.Mock()
        speech = SpeechService(bus=bus)
        speech.daemon = True
        speech.run()

        self.assertTrue(tts_factory_mock.create.called)
        bus.on.assert_any_call('mycroft.stop', speech.handle_stop)
        bus.on.assert_any_call('mycroft.audio.speech.stop',
                               speech.handle_stop)
        bus.on.assert_any_call('speak', speech.handle_speak)

        speech.shutdown()
        self.assertFalse(speech.is_alive())
        # TODO TTS.playback is now a singleton, this test does not reach it anymore when using mock
        #self.assertTrue(tts_mock.playback.stop.called)
        #self.assertTrue(tts_mock.playback.join.called)

    def test_speak(self, tts_factory_mock, config_mock):
        """Ensure the speech handler executes the tts."""
        setup_mocks(config_mock, tts_factory_mock)
        bus = mock.Mock()
        speech = SpeechService(bus=bus)
        speech.daemon = True
        speech.run()

        speak_msg = Message('speak',
                            data={'utterance': 'hello there. world',
                                  'listen': False},
                            context={'ident': 'a'})
        speech.handle_speak(speak_msg)
        tts_mock.execute.assert_has_calls(
            [mock.call('hello there. world', 'a', False)])
        speech.shutdown()

    def test_fallback_tts(self, tts_factory_mock, config_mock):
        """Ensure the fallback tts is triggered if the remote times out."""
        setup_mocks(config_mock, tts_factory_mock)
        bus = mock.Mock()

        mimic_mock = mock.Mock()

        tts = tts_factory_mock.create.return_value
        tts.execute.side_effect = RemoteTTSTimeoutException

        speech = SpeechService(bus=bus)
        speech.daemon = True
        speech._get_tts_fallback = mock.Mock()
        speech._get_tts_fallback.return_value = mimic_mock
        speech.run()

        speak_msg = Message('speak',
                            data={'utterance': 'hello there. world',
                                  'listen': False},
                            context={'ident': 'a'})
        speech.handle_speak(speak_msg)
        mimic_mock.execute.assert_has_calls(
            [mock.call('hello there. world', 'a', False)])
        speech.shutdown()

    @unittest.skip("# TODO refactor test for TTS.playback (now a singleton)")
    @mock.patch('mycroft.audio.service.check_for_signal')
    def test_abort_speak(self, check_for_signal_mock, tts_factory_mock,
                         config_mock):
        """Ensure the speech handler aborting speech on stop signal."""
        setup_mocks(config_mock, tts_factory_mock)
        check_for_signal_mock.return_value = True
        tts = tts_factory_mock.create.return_value

        bus = mock.Mock()
        speech = SpeechService(bus=bus)
        speech.daemon = True

        def execute_trigger_stop():
            speech.handle_stop(None)

        tts.execute.side_effect = execute_trigger_stop

        speech.run()

        speak_msg = Message('speak',
                            data={'utterance': 'hello there. world',
                                  'listen': False},
                            context={'ident': 'a'})
        speech.handle_speak(speak_msg)
        self.assertTrue(tts.playback.clear.called)
        speech.shutdown()

    @mock.patch('mycroft.audio.service.check_for_signal')
    def test_stop(self, check_for_signal_mock, tts_factory_mock, config_mock):
        """Ensure the stop handler signals stop correctly."""
        setup_mocks(config_mock, tts_factory_mock)
        bus = mock.Mock()
        config_mock.get.return_value = {'tts': {'module': 'test'}}
        speech = SpeechService(bus=bus)

        speech._last_stop_signal = 0
        check_for_signal_mock.return_value = False
        speech.handle_stop(Message('mycroft.stop'))
        self.assertEqual(speech._last_stop_signal, 0)

        check_for_signal_mock.return_value = True
        speech.handle_stop(Message('mycroft.stop'))
        self.assertNotEqual(speech._last_stop_signal, 0)
        speech.shutdown()


if __name__ == "__main__":
    unittest.main()
