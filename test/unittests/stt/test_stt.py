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
import sys
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

import mycroft.configuration
from mycroft.configuration import Configuration
import mycroft.listener.stt
from mycroft.listener import RecognizerLoop
from mycroft.util.log import LOG
from ovos_stt_plugin_vosk import VoskKaldiSTT
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
        config = {'module': 'mycroft',
                  'mycroft': {'uri': 'https://test.com'}}
        stt = mycroft.listener.stt.STTFactory.create(config)
        self.assertEqual(type(stt), mycroft.listener.stt.MycroftSTT)

        config = {'stt': config}
        stt = mycroft.listener.stt.STTFactory.create(config)
        self.assertEqual(type(stt), mycroft.listener.stt.MycroftSTT)

    @patch.dict(Configuration._Configuration__patch, STT_CONFIG)
    def test_factory_from_config(self):
        mycroft.listener.stt.STTApi = MagicMock()
        stt = mycroft.listener.stt.STTFactory.create()
        self.assertEqual(type(stt), mycroft.listener.stt.MycroftSTT)

    @patch.dict(Configuration._Configuration__patch, STT_CONFIG)
    def test_mycroft_stt(self,):
        mycroft.listener.stt.STTApi = MagicMock()
        stt = mycroft.listener.stt.MycroftSTT()
        audio = MagicMock()
        stt.execute(audio, 'en-us')
        self.assertTrue(mycroft.listener.stt.STTApi.called)

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
    def test_fallback_stt_not_set(self,  mock_warn, mock_error):
        fallback_stt = RecognizerLoop.get_fallback_stt()
        self.assertIsNone(fallback_stt)
        mock_warn.assert_called_with("No fallback STT configured")
        mock_error.assert_called_with("Failed to create fallback STT")

