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
import time
from copy import deepcopy
from unittest import TestCase, mock

from ovos_bus_client.message import Message
from ovos_bus_client.session import IntentContextManager as ContextManager
from ovos_bus_client.util import get_message_lang
from ovos_config import Configuration
from ovos_config import LocalConf, DEFAULT_CONFIG
from ovos_config.locale import setup_locale
from ovos_core.intent_services import IntentService
from ovos_utils.fakebus import FakeBus
from ovos_workshop.intents import IntentBuilder

# Setup configurations to use with default language tests
BASE_CONF = deepcopy(LocalConf(DEFAULT_CONFIG))
BASE_CONF['lang'] = 'it-it'


class ContextManagerTest(TestCase):

    def setUp(self):
        self.context_manager = ContextManager(3)

    def test_add_context(self):
        entity = {'confidence': 1.0}
        context = 'TestContext'
        word = 'TestWord'
        entity['data'] = [(word, context)]
        entity['match'] = word
        entity['key'] = word

        self.assertEqual(len(self.context_manager.frame_stack), 0)
        self.context_manager.inject_context(entity)
        self.assertEqual(len(self.context_manager.frame_stack), 1)

    def test_remove_context(self):
        entity = {'confidence': 1.0}
        context = 'TestContext'
        word = 'TestWord'
        entity['data'] = [(word, context)]
        entity['match'] = word
        entity['key'] = word

        self.context_manager.inject_context(entity)
        self.assertEqual(len(self.context_manager.frame_stack), 1)
        self.context_manager.remove_context('TestContext')
        self.assertEqual(len(self.context_manager.frame_stack), 0)


class TestLanguageExtraction(TestCase):
    @mock.patch.dict(Configuration._Configuration__patch, BASE_CONF)
    def test_no_lang_in_message(self):
        """No lang in message should result in lang from active locale."""
        setup_locale("it-it")
        msg = Message('test msg', data={})
        self.assertEqual(get_message_lang(msg), 'it-IT')
        setup_locale("en-US")
        self.assertEqual(get_message_lang(msg), 'en-US')

    @mock.patch.dict(Configuration._Configuration__patch, BASE_CONF)
    def test_lang_exists(self):
        """Message has a lang code in data, it should be used."""
        msg = Message('test msg', data={'lang': 'de-de'})
        self.assertEqual(get_message_lang(msg), 'de-DE')
        msg = Message('test msg', data={'lang': 'sv-se'})
        self.assertEqual(get_message_lang(msg), 'sv-SE')


class TestIntentServiceApi(TestCase):
    def setUp(self):
        self.bus = FakeBus()
        self.emitted = []

        def on_msg(m):
            self.emitted.append(Message.deserialize(m))

        self.bus.on("message", on_msg)

        self.intent_service = IntentService(self.bus)

        msg = Message('register_vocab',
                      {'entity_value': 'test', 'entity_type': 'testKeyword'})
        self.intent_service._adapt_service.handle_register_vocab(msg)

        intent = IntentBuilder('skill:testIntent').require('testKeyword')
        msg = Message('register_intent', intent.__dict__)
        self.intent_service._adapt_service.handle_register_intent(msg)

    def test_get_intent_no_match(self):
        """Check that if the intent doesn't match at all None is returned."""
        # Check that no intent is matched
        msg = Message('intent.service.intent.get',
                      data={'utterance': 'five'})
        self.intent_service.handle_get_intent(msg)
        reply = self.emitted[-1]
        self.assertEqual(reply.data['intent'], None)

    def test_get_intent_match(self):
        # Check that intent is matched
        msg = Message('intent.service.intent.get',
                      data={'utterance': 'test'})
        self.intent_service.handle_get_intent(msg)
        reply = self.emitted[-1]
        time.sleep(3)
        self.assertEqual(reply.data['intent']['intent_name'], 'skill:testIntent')
