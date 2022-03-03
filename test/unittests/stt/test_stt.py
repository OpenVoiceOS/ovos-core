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
from unittest.mock import MagicMock, patch

import mycroft.stt
from mycroft.configuration import Configuration
from test.util import base_config
from mycroft.client.speech.listener import RecognizerLoop
from ovos_stt_plugin_vosk import VoskKaldiSTT


class TestSTT(unittest.TestCase):
    def test_factory(self):
        config = {'module': 'mycroft',
                  'mycroft': {'uri': 'https://test.com'}}
        stt = mycroft.stt.STTFactory.create(config)
        self.assertEqual(type(stt), mycroft.stt.MycroftSTT)

        config = {'stt': config}
        stt = mycroft.stt.STTFactory.create(config)
        self.assertEqual(type(stt), mycroft.stt.MycroftSTT)

    @patch.object(Configuration, 'get')
    def test_factory_from_config(self, mock_get):
        mycroft.stt.STTApi = MagicMock()
        config = base_config()
        config.merge(
            {
                'stt': {
                    'module': 'mycroft',
                    "fallback_module": "ovos-stt-plugin-vosk",
                    'mycroft': {'uri': 'https://test.com'}
                },
                'lang': 'en-US'
            })
        mock_get.return_value = config

        stt = mycroft.stt.STTFactory.create()
        self.assertEqual(type(stt), mycroft.stt.MycroftSTT)

    @patch.object(Configuration, 'get')
    def test_mycroft_stt(self, mock_get):
        mycroft.stt.STTApi = MagicMock()
        config = base_config()
        config.merge(
            {
                'stt': {
                    'module': 'mycroft',
                    'mycroft': {'uri': 'https://test.com'}
                },
                'lang': 'en-US'
            })
        mock_get.return_value = config

        stt = mycroft.stt.MycroftSTT()
        audio = MagicMock()
        stt.execute(audio, 'en-us')
        self.assertTrue(mycroft.stt.STTApi.called)

    @patch.object(Configuration, 'get')
    def test_falback_stt(self, mock_get):
        config = base_config()
        config.merge(
            {
                'stt': {
                    'module': 'mycroft',
                    "fallback_module": "ovos-stt-plugin-vosk",
                    'mycroft': {'uri': 'https://test.com'}
                },
                'lang': 'en-US'
            })
        mock_get.return_value = config

        # check class matches
        fallback_stt = RecognizerLoop.get_fallback_stt()
        self.assertEqual(fallback_stt, VoskKaldiSTT)

