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
from time import sleep
from unittest.mock import MagicMock, patch, Mock

from ovos_stt_plugin_selene import SeleneSTT
from ovos_stt_plugin_vosk import VoskKaldiSTT

import mycroft.configuration
import mycroft.listener.stt
from mycroft.configuration import Configuration
from mycroft.listener import RecognizerLoop
from mycroft.listener.service import SpeechService
from mycroft.util.log import LOG
from ovos_utils.messagebus import Message, FakeBus
from ovos_utils.process_utils import ProcessState
from test.util import base_config

STT_CONFIG = base_config()
STT_CONFIG.merge({
    'stt': {
        'module': 'mycroft',
        "fallback_module": "ovos-stt-plugin-vosk",
        'mycroft': {'uri': 'https://test.com'}
    },
    'lang': 'en-US'
})

STT_NO_FB_CONFIG = base_config()
STT_NO_FB_CONFIG.merge({
    'stt': {
        'module': 'mycroft',
        'fallback_module': None,
        'mycroft': {'uri': 'https://test.com'}
    },
    'lang': 'en-US'
})

STT_INVALID_FB_CONFIG = base_config()
STT_INVALID_FB_CONFIG.merge({
    'stt': {
        'module': 'mycroft',
        'fallback_module': 'invalid',
        'mycroft': {'uri': 'https://test.com'}
    },
    'lang': 'en-US'
})


class TestSTT(unittest.TestCase):
    def test_factory(self):
        config = {'module': 'mycroft'}
        stt = mycroft.listener.stt.STTFactory.create(config)
        self.assertEqual(type(stt), SeleneSTT)

        config = {'module': 'ovos-stt-plugin-selene'}
        stt = mycroft.listener.stt.STTFactory.create(config)
        self.assertEqual(type(stt), SeleneSTT)

        config = {'stt': config}
        stt = mycroft.listener.stt.STTFactory.create(config)
        self.assertEqual(type(stt), SeleneSTT)

    @patch.dict(Configuration._Configuration__patch, STT_CONFIG)
    def test_factory_from_config(self):
        stt = mycroft.listener.stt.STTFactory.create()
        self.assertEqual(type(stt), SeleneSTT)

    @patch.dict(Configuration._Configuration__patch, STT_CONFIG)
    def test_mycroft_stt(self, ):
        stt = SeleneSTT()
        stt.api = MagicMock()
        audio = MagicMock()
        stt.execute(audio, 'en-us')
        self.assertTrue(stt.api.stt.called)

    @patch.dict(Configuration._Configuration__patch, STT_CONFIG)
    def test_fallback_stt(self):
        # check class matches
        fallback_stt = RecognizerLoop.get_fallback_stt()
        self.assertEqual(fallback_stt, VoskKaldiSTT)

    @patch.dict(Configuration._Configuration__patch, STT_INVALID_FB_CONFIG)
    @patch.object(LOG, 'error')
    @patch.object(LOG, 'warning')
    def test_invalid_fallback_stt(self, mock_warn, mock_error):
        fallback_stt = RecognizerLoop.get_fallback_stt()
        self.assertIsNone(fallback_stt)
        mock_warn.assert_called_with("Could not find plugin: invalid")
        mock_error.assert_called_with("Failed to create fallback STT")

    @patch.dict(Configuration._Configuration__patch, STT_NO_FB_CONFIG)
    @patch.object(LOG, 'error')
    @patch.object(LOG, 'warning')
    def test_fallback_stt_not_set(self, mock_warn, mock_error):
        fallback_stt = RecognizerLoop.get_fallback_stt()
        self.assertIsNone(fallback_stt)
        mock_warn.assert_called_with("No fallback STT configured")
        mock_error.assert_called_with("Failed to create fallback STT")


class TestService(unittest.TestCase):
    def test_life_cycle(self):
        """Ensure the init and shutdown behaves as expected."""
        bus = Mock()
        loop = Mock()

        speech = SpeechService(bus=bus, loop=loop)
        speech.daemon = True

        def run():
            while speech.status.state != ProcessState.READY:
                sleep(1)
            while speech.status.state != ProcessState.STOPPING:
                sleep(1)

        loop.run = run

        self.assertTrue(ProcessState.NOT_STARTED <= speech.status.state <= ProcessState.ALIVE)
        speech.start()
        sleep(1)
        self.assertTrue(speech.status.state >= ProcessState.ALIVE)
        self.assertTrue(speech.status.state > ProcessState.STOPPING)
        speech.shutdown()
        sleep(1)
        self.assertTrue(speech.status.state <= ProcessState.STOPPING)
        self.assertFalse(speech.is_alive())

    @patch('mycroft.listener.service.get_stt_lang_configs')
    @patch('mycroft.listener.service.get_stt_supported_langs')
    @patch('mycroft.listener.service.get_stt_module_configs')
    def test_opm_stt(self,
                     mock_get_configs, mock_get_lang, mock_get_lang_configs):
        loop = Mock()

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
        speech = SpeechService(bus=bus, loop=loop)

        def rcvm(msg):
            msg = json.loads(msg)

            self.assertEqual(msg["type"], "opm.stt.query.response")
            en2 = dict(en)
            en2["engine"] = "my-plugin"
            self.assertEqual(msg["data"]["langs"], ['en-us'])
            self.assertEqual(msg["data"]["plugins"], {'en-us': ['my-plugin']})
            self.assertEqual(msg["data"]["configs"]["my-plugin"]["en-us"], [en2])
            en2["plugin_name"] = 'My Plugin'
            self.assertEqual(msg["data"]["options"]["en-us"], [en2])

        bus.on("message", rcvm)

        speech.handle_opm_stt_query(Message("opm.stt.query"))

    @patch('mycroft.listener.service.get_vad_configs')
    def test_opm_vad(self,  mock_get_configs):
        loop = Mock()

        en = {'display_name': 'Pretty Name',
              'offline': True,
              'priority': 50}

        # per module configs, mocking same return val for all plugin inputs (!)
        mock_get_configs.return_value = {"my-vad-plugin": [en]}

        bus = FakeBus()
        speech = SpeechService(bus=bus, loop=loop)

        def rcvm(msg):
            msg = json.loads(msg)

            self.assertEqual(msg["type"], "opm.vad.query.response")
            en2 = dict(en)
            en2["engine"] = "my-vad-plugin"
            en2["plugin_name"] = 'My Vad Plugin'

            self.assertEqual(msg["data"]["plugins"], ["my-vad-plugin"])
            self.assertEqual(msg["data"]["configs"]["my-vad-plugin"], [en2])
            self.assertEqual(msg["data"]["options"][0], en2)

        bus.on("message", rcvm)

        speech.handle_opm_vad_query(Message("opm.vad.query"))

    @patch('mycroft.listener.service.get_ww_lang_configs')
    @patch('mycroft.listener.service.get_ww_supported_langs')
    @patch('mycroft.listener.service.get_ww_module_configs')
    def test_opm_ww(self,
                     mock_get_configs, mock_get_lang, mock_get_lang_configs):
        loop = Mock()

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
        speech = SpeechService(bus=bus, loop=loop)

        def rcvm(msg):
            msg = json.loads(msg)

            self.assertEqual(msg["type"], "opm.ww.query.response")
            en2 = dict(en)
            en2["engine"] = "my-plugin"
            self.assertEqual(msg["data"]["langs"], ['en-us'])
            self.assertEqual(msg["data"]["plugins"], {'en-us': ['my-plugin']})
            self.assertEqual(msg["data"]["configs"]["my-plugin"]["en-us"], [en2])
            en2["plugin_name"] = 'My Plugin'
            self.assertEqual(msg["data"]["options"]["en-us"], [en2])

        bus.on("message", rcvm)

        speech.handle_opm_ww_query(Message("opm.ww.query"))
