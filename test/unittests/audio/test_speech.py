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
import json
import unittest
import unittest.mock as mock
from queue import Queue

from mycroft import MYCROFT_ROOT_PATH
from mycroft.audio.service import PlaybackService
from ovos_config import Configuration
from ovos_utils.messagebus import Message, FakeBus
from ovos_utils.process_utils import ProcessState

"""Tests for speech dispatch service."""

tts_mock = mock.Mock()


def setup_mocks(config_mock, tts_factory_mock, fallback="A"):
    """Do the common setup for the mocks."""
    c = Configuration.get()
    c["tts"] = {"module": "A", "fallback_module": fallback}
    config_mock.return_value = c

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
        speech = PlaybackService(bus=bus)
        speech.daemon = True
        self.assertTrue(ProcessState.NOT_STARTED <= speech.status.state < ProcessState.ALIVE)
        speech.run()
        self.assertTrue(speech.status.state >= ProcessState.ALIVE)
        self.assertTrue(tts_factory_mock.create.called)
        self.assertTrue(speech.tts.init.called)

        bus.on.assert_any_call('mycroft.stop', speech.handle_stop)
        bus.on.assert_any_call('mycroft.audio.speech.stop',
                               speech.handle_stop)
        bus.on.assert_any_call('speak', speech.handle_speak)

        self.assertTrue(speech.status.state > ProcessState.STOPPING)
        speech.shutdown()
        self.assertTrue(speech.status.state <= ProcessState.STOPPING)
        self.assertFalse(speech.is_alive())

    def test_error_life_cycle(self, tts_factory_mock, config_mock):
        """Ensure the init and shutdown behaves as expected."""
        setup_mocks(config_mock, tts_factory_mock)
        bus = mock.Mock()
        speech = PlaybackService(bus=bus)
        speech.daemon = True
        speech.tts = None
        self.assertTrue(ProcessState.NOT_STARTED <= speech.status.state < ProcessState.ALIVE)
        speech.run()
        self.assertTrue(speech.status.state == ProcessState.ERROR)

    @mock.patch('mycroft.audio.service.check_for_signal')
    def test_stop(self, check_for_signal_mock, tts_factory_mock, config_mock):
        """Ensure the stop handler signals stop correctly."""
        setup_mocks(config_mock, tts_factory_mock)
        bus = mock.Mock()
        config_mock.get.return_value = {'tts': {'module': 'test'}}
        speech = PlaybackService(bus=bus)

        speech._last_stop_signal = 0
        check_for_signal_mock.return_value = False
        speech.handle_stop(Message('mycroft.stop'))
        self.assertEqual(speech._last_stop_signal, 0)

        check_for_signal_mock.return_value = True
        speech.handle_stop(Message('mycroft.stop'))
        self.assertNotEqual(speech._last_stop_signal, 0)
        speech.shutdown()

    def test_fallback_tts_creation(self, tts_factory_mock, config_mock):
        """Ensure the init and shutdown behaves as expected."""
        setup_mocks(config_mock, tts_factory_mock, fallback="B")
        bus = mock.Mock()
        speech = PlaybackService(bus=bus)
        speech.fallback_tts = None
        speech._get_tts_fallback()
        self.assertIsNotNone(speech.fallback_tts)
        self.assertTrue(speech.fallback_tts.init.called)

    def test_no_fallback_tts(self, tts_factory_mock, config_mock):
        """Ensure the init and shutdown behaves as expected."""
        setup_mocks(config_mock, tts_factory_mock)
        bus = mock.Mock()

        _real = PlaybackService._get_tts_fallback
        _real2 = PlaybackService.execute_fallback_tts
        PlaybackService._get_tts_fallback = mock.Mock()
        PlaybackService.execute_fallback_tts = mock.Mock()
        PlaybackService.tts = mock.Mock()
        speech = PlaybackService(bus=bus)
        self.assertTrue(tts_factory_mock.create.called)
        self.assertFalse(speech._get_tts_fallback.called)

        speech.execute_tts("hello", "123")
        self.assertTrue(speech.tts.execute.called)
        self.assertFalse(speech.execute_fallback_tts.called)

        PlaybackService._get_tts_fallback = _real
        PlaybackService.execute_fallback_tts = _real2

    def test_fallback_tts(self, tts_factory_mock, config_mock):
        """Ensure the init and shutdown behaves as expected."""
        setup_mocks(config_mock, tts_factory_mock, fallback="B")
        bus = mock.Mock()
        _real = PlaybackService._get_tts_fallback
        PlaybackService._get_tts_fallback = mock.Mock()

        speech = PlaybackService(bus=bus)
        self.assertTrue(tts_factory_mock.create.called)
        self.assertTrue(speech._get_tts_fallback.called)

        PlaybackService._get_tts_fallback = _real

    def test_fallback_tts_execute(self, tts_factory_mock, config_mock):
        """Ensure the init and shutdown behaves as expected."""
        setup_mocks(config_mock, tts_factory_mock, fallback="B")
        bus = mock.Mock()

        class FailingTTS:
            def execute(*args, **kwargs):
                raise RuntimeError("oops")

        speech = PlaybackService(bus=bus)
        speech.tts = FailingTTS()

        speech.execute_tts("hello", "123")
        self.assertTrue(speech.fallback_tts.execute.called)

    @mock.patch('mycroft.audio.service.TTS')
    def test_queue(self, mock_TTS, tts_factory_mock, config_mock):
        mock_TTS.queue = Queue()
        setup_mocks(config_mock, tts_factory_mock)
        bus = mock.Mock()
        speech = PlaybackService(bus=bus)

        with self.assertRaises(ValueError):
            msg = Message("", {})
            speech.handle_queue_audio(msg)

        with self.assertRaises(FileNotFoundError):
            msg = Message("", {"filename": "no_exist.mp3"})
            speech.handle_queue_audio(msg)

        f = f"{MYCROFT_ROOT_PATH}/mycroft/res/snd/start_listening.wav"
        msg = Message("", {"filename": f})
        speech.handle_queue_audio(msg)
        data = mock_TTS.queue.get()
        self.assertEqual(data[0], "wav")
        self.assertEqual(data[1], f)
        self.assertEqual(data[-1], False)

    @mock.patch('mycroft.audio.service.report_timing')
    def test_speak(self, mock_timing, tts_factory_mock, config_mock):
        setup_mocks(config_mock, tts_factory_mock)
        bus = mock.Mock()
        speech = PlaybackService(bus=bus)
        speech.execute_tts = mock.Mock()
        speech.native_sources = ["A"]

        msg = Message("speak", {"utterance": "hello world"}, {"ident": "123"})

        # test message.context.destination
        msg.context["destination"] = "B"  # not native source, ignore
        speech.handle_speak(msg)
        self.assertFalse(speech.execute_tts.called)
        self.assertFalse(mock_timing.called)

        msg.context["destination"] = "A"  # native source
        speech.handle_speak(msg)
        self.assertTrue(speech.execute_tts.called)
        self.assertTrue(mock_timing.called)
        self.assertEqual(mock_timing.call_args[0][0], "123")

        msg.context.pop("destination")  # multi cast
        msg.context.pop("ident")  # optional
        speech.handle_speak(msg)
        self.assertTrue(speech.execute_tts.called)
        self.assertTrue(mock_timing.called)
        self.assertEqual(mock_timing.call_args[0][0], "unknown")

    @mock.patch('mycroft.audio.service.get_tts_lang_configs')
    @mock.patch('mycroft.audio.service.get_tts_supported_langs')
    @mock.patch('mycroft.audio.service.get_tts_module_configs')
    def test_opm_tts(self,
                     mock_get_configs, mock_get_lang, mock_get_lang_configs,
                     tts_factory_mock, config_mock):
        setup_mocks(config_mock, tts_factory_mock)
        en = {'display_name': 'Pretty Name',
              'lang': 'en-us',
              'offline': True,
              'priority': 50}

        mock_get_lang.return_value = {"en-us": ['my-plugin']}
        # mocking same return val for all lang inputs (!)
        # used to generate selectable options list
        mock_get_lang_configs.return_value = {
            "my-plugin": [en]}

        # per module configs, mocking same return val for all plugin inputs (!)
        mock_get_configs.return_value = {"en-us": [en]}

        bus = FakeBus()
        speech = PlaybackService(bus=bus)

        def rcvm(msg):
            msg = json.loads(msg)

            self.assertEqual(msg["type"], "opm.tts.query.response")
            en2 = dict(en)
            en2["engine"] = "my-plugin"
            self.assertEqual(msg["data"]["langs"], ['en-us'])
            self.assertEqual(msg["data"]["plugins"], {'en-us': ['my-plugin']})
            self.assertEqual(msg["data"]["configs"]["my-plugin"]["en-us"], [en2])
            en2["plugin_name"] = 'My Plugin'
            self.assertEqual(msg["data"]["options"]["en-us"], [en2])

        bus.on("message", rcvm)

        speech.handle_opm_tts_query(Message("opm.tts.query"))

    @mock.patch('mycroft.audio.service.get_g2p_lang_configs')
    @mock.patch('mycroft.audio.service.get_g2p_supported_langs')
    @mock.patch('mycroft.audio.service.get_g2p_module_configs')
    def test_opm_g2p(self,
                     mock_get_configs, mock_get_lang, mock_get_lang_configs,
                     tts_factory_mock, config_mock):
        setup_mocks(config_mock, tts_factory_mock)
        en = {'display_name': 'Pretty Name',
              'lang': 'en-us',
              'offline': True,
              'priority': 50}

        mock_get_lang.return_value = {"en-us": ['my-plugin']}
        # mocking same return val for all lang inputs (!)
        # used to generate selectable options list
        mock_get_lang_configs.return_value = {
            "my-plugin": [en]}

        # per module configs, mocking same return val for all plugin inputs (!)
        mock_get_configs.return_value = {"en-us": [en]}

        bus = FakeBus()
        speech = PlaybackService(bus=bus)

        def rcvm(msg):
            msg = json.loads(msg)

            self.assertEqual(msg["type"], "opm.g2p.query.response")
            en2 = dict(en)
            en2["engine"] = "my-plugin"
            self.assertEqual(msg["data"]["langs"], ['en-us'])
            self.assertEqual(msg["data"]["plugins"], {'en-us': ['my-plugin']})
            self.assertEqual(msg["data"]["configs"]["my-plugin"]["en-us"], [en2])
            en2["plugin_name"] = 'My Plugin'
            self.assertEqual(msg["data"]["options"]["en-us"], [en2])

        bus.on("message", rcvm)

        speech.handle_opm_g2p_query(Message("opm.g2p.query"))

    @mock.patch('mycroft.audio.service.get_audio_service_configs')
    def test_opm_audio(self, mock_get_configs, tts_factory_mock, config_mock):
        setup_mocks(config_mock, tts_factory_mock)

        ocp = {"type": "ovos_common_play", "active": True}
        p = {"type": "ovos_badass_player", "active": True}

        # per module configs, mocking same return val for all plugin inputs (!)
        mock_get_configs.return_value = {"ocp": ocp, "badass": p}

        bus = FakeBus()
        speech = PlaybackService(bus=bus)

        def rcvm(msg):
            msg = json.loads(msg)
            self.assertEqual(msg["type"], "opm.audio.query.response")
            self.assertEqual(msg["data"]["plugins"], ["ocp", "badass"])
            self.assertEqual(msg["data"]["configs"], {"ocp": ocp, "badass": p})
            ocp["plugin_name"] = 'Ovos Common Play'
            p["plugin_name"] = 'Ovos Badass Player'
            self.assertEqual(msg["data"]["options"], [ocp, p])

        bus.on("message", rcvm)

        speech.handle_opm_audio_query(Message("opm.audio.query"))


if __name__ == "__main__":
    unittest.main()
