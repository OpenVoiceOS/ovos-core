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
from unittest import TestCase, mock

from ovos_bus_client.message import Message
from ovos_bus_client.util import get_message_lang
from ovos_config import Configuration
from ovos_config.locale import setup_locale
from ovos_core.intent_services import IntentService
from ovos_core.intent_services.adapt_service import ContextManager
from ovos_workshop.intents import IntentBuilder, Intent as AdaptIntent
from test.util import base_config

# Setup configurations to use with default language tests
BASE_CONF = base_config()
BASE_CONF['lang'] = 'it-it'

NO_LANG_CONF = base_config()
NO_LANG_CONF.pop('lang')

setup_locale("en-us")


class MockEmitter(object):
    def __init__(self):
        self.reset()

    def emit(self, message):
        self.types.append(message.msg_type)
        self.results.append(message.data)

    def get_types(self):
        return self.types

    def get_results(self):
        return self.results

    def remove(self, msg_type, handler):
        self.removed.append(msg_type)

    def on(self, msg_type, handler):
        pass

    def reset(self):
        self.removed = []
        self.types = []
        self.results = []


class ContextManagerTest(TestCase):
    emitter = MockEmitter()

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


def check_converse_request(message, skill_id):
    return (message.msg_type == 'skill.converse.request' and
            message.data['skill_id'] == skill_id)


class TestLanguageExtraction(TestCase):
    @mock.patch.dict(Configuration._Configuration__patch, BASE_CONF)
    def test_no_lang_in_message(self):
        """No lang in message should result in lang from active locale."""
        setup_locale("it-it")
        msg = Message('test msg', data={})
        self.assertEqual(get_message_lang(msg), 'it-it')
        setup_locale("en-us")
        self.assertEqual(get_message_lang(msg), 'en-us')

    @mock.patch.dict(Configuration._Configuration__patch, BASE_CONF)
    def test_lang_exists(self):
        """Message has a lang code in data, it should be used."""
        msg = Message('test msg', data={'lang': 'de-de'})
        self.assertEqual(get_message_lang(msg), 'de-de')
        msg = Message('test msg', data={'lang': 'sv-se'})
        self.assertEqual(get_message_lang(msg), 'sv-se')


def create_old_style_vocab_msg(keyword, value):
    """Create a message for registering an adapt keyword."""
    return Message('register_vocab',
                   {'start': value, 'end': keyword})


def create_vocab_msg(keyword, value):
    """Create a message for registering an adapt keyword."""
    return Message('register_vocab',
                   {'entity_value': value, 'entity_type': keyword})


def get_last_message(bus):
    """Get last sent message on mock bus."""
    last = bus.emit.call_args
    return last[0][0]


class TestIntentServiceApi(TestCase):
    def setUp(self):
        self.intent_service = IntentService(mock.Mock())

    def setup_simple_adapt_intent(self,
                                  msg=create_vocab_msg('testKeyword', 'test')):
        self.intent_service.handle_register_vocab(msg)

        intent = IntentBuilder('skill:testIntent').require('testKeyword')
        msg = Message('register_intent', intent.__dict__)
        self.intent_service.handle_register_intent(msg)

    def test_keyword_backwards_compatibility(self):
        self.setup_simple_adapt_intent(
            create_old_style_vocab_msg('testKeyword', 'test')
        )

        # Check that the intent is returned
        msg = Message('intent.service.adapt.get',
                      data={'utterance': 'test'})
        self.intent_service.handle_get_adapt(msg)

        reply = get_last_message(self.intent_service.bus)
        self.assertEqual(reply.data['intent']['intent_type'],
                         'skill:testIntent')

    def test_get_adapt_intent(self):
        self.setup_simple_adapt_intent()
        # Check that the intent is returned
        msg = Message('intent.service.adapt.get',
                      data={'utterance': 'test'})
        self.intent_service.handle_get_adapt(msg)

        reply = get_last_message(self.intent_service.bus)
        self.assertEqual(reply.data['intent']['intent_type'],
                         'skill:testIntent')

    def test_get_adapt_intent_no_match(self):
        """Check that if the intent doesn't match at all None is returned."""
        self.setup_simple_adapt_intent()
        # Check that no intent is matched
        msg = Message('intent.service.adapt.get',
                      data={'utterance': 'five'})
        self.intent_service.handle_get_adapt(msg)
        reply = get_last_message(self.intent_service.bus)
        self.assertEqual(reply.data['intent'], None)

    def test_get_intent(self):
        """Check that the registered adapt intent is triggered."""
        self.setup_simple_adapt_intent()
        # Check that the intent is returned
        msg = Message('intent.service.adapt.get',
                      data={'utterance': 'test'})
        self.intent_service.handle_get_intent(msg)

        reply = get_last_message(self.intent_service.bus)
        self.assertEqual(reply.data['intent']['intent_type'],
                         'skill:testIntent')

    def test_get_intent_no_match(self):
        """Check that if the intent doesn't match at all None is returned."""
        self.setup_simple_adapt_intent()
        # Check that no intent is matched
        msg = Message('intent.service.intent.get',
                      data={'utterance': 'five'})
        self.intent_service.handle_get_intent(msg)
        reply = get_last_message(self.intent_service.bus)
        self.assertEqual(reply.data['intent'], None)

    def test_get_intent_manifest(self):
        """Check that if the intent doesn't match at all None is returned."""
        self.setup_simple_adapt_intent()
        # Check that no intent is matched
        msg = Message('intent.service.intent.get',
                      data={'utterance': 'five'})
        self.intent_service.handle_get_intent(msg)
        reply = get_last_message(self.intent_service.bus)
        self.assertEqual(reply.data['intent'], None)

    def test_get_adapt_intent_manifest(self):
        """Make sure the manifest returns a list of Intent Parser objects."""
        self.setup_simple_adapt_intent()
        msg = Message('intent.service.adapt.manifest.get')
        self.intent_service.handle_adapt_manifest(msg)
        reply = get_last_message(self.intent_service.bus)
        self.assertEqual(reply.data['intents'][0]['name'],
                         'skill:testIntent')

    def test_get_adapt_vocab_manifest(self):
        self.setup_simple_adapt_intent()
        msg = Message('intent.service.adapt.vocab.manifest.get')
        self.intent_service.handle_vocab_manifest(msg)
        reply = get_last_message(self.intent_service.bus)
        value = reply.data['vocab'][0]['entity_value']
        keyword = reply.data['vocab'][0]['entity_type']
        self.assertEqual(keyword, 'testKeyword')
        self.assertEqual(value, 'test')

    def test_get_no_match_after_detach(self):
        """Check that a removed intent doesn't match."""
        self.setup_simple_adapt_intent()
        # Check that no intent is matched
        msg = Message('detach_intent',
                      data={'intent_name': 'skill:testIntent'})
        self.intent_service.handle_detach_intent(msg)
        msg = Message('intent.service.adapt.get', data={'utterance': 'test'})
        self.intent_service.handle_get_adapt(msg)
        reply = get_last_message(self.intent_service.bus)
        self.assertEqual(reply.data['intent'], None)

    def test_get_no_match_after_detach_skill(self):
        """Check that a removed skill's intent doesn't match."""
        self.setup_simple_adapt_intent()
        # Check that no intent is matched
        msg = Message('detach_intent',
                      data={'skill_id': 'skill'})
        self.intent_service.handle_detach_skill(msg)
        msg = Message('intent.service.adapt.get', data={'utterance': 'test'})
        self.intent_service.handle_get_adapt(msg)
        reply = get_last_message(self.intent_service.bus)
        self.assertEqual(reply.data['intent'], None)

    def test_shutdown(self):

        intent_service = IntentService(MockEmitter(), config={"experimental_ocp_pipeline": False})
        intent_service.shutdown()
        self.assertListEqual(intent_service.bus.removed,
                             ['padatious:register_intent',
                              'padatious:register_entity',
                              'detach_intent',
                              'detach_skill',
                              'question:query.response',
                              'common_query.question',
                              'ovos.common_query.pong',
                              'mycroft.speech.recognition.unknown',
                              'intent.service.skills.deactivate',
                              'intent.service.skills.activate',
                              'active_skill_request',
                              'intent.service.active_skills.get',
                              'skill.converse.get_response.enable',
                              'skill.converse.get_response.disable',
                              'ovos.skills.fallback.register',
                              'ovos.skills.fallback.deregister',
                              'register_vocab',
                              'register_intent',
                              'recognizer_loop:utterance',
                              'detach_intent',
                              'detach_skill',
                              'add_context',
                              'remove_context',
                              'clear_context',
                              'mycroft.skills.loaded',
                              'intent.service.intent.get',
                              'intent.service.skills.get',
                              'intent.service.adapt.get',
                              'intent.service.adapt.manifest.get',
                              'intent.service.adapt.vocab.manifest.get',
                              'intent.service.padatious.get',
                              'intent.service.padatious.manifest.get',
                              'intent.service.padatious.entities.manifest.get']
                             )

        intent_service = IntentService(MockEmitter(), config={"experimental_ocp_pipeline": True})
        intent_service.shutdown()
        self.assertListEqual(intent_service.bus.removed,
                             ['padatious:register_intent',
                              'padatious:register_entity',
                              'detach_intent',
                              'detach_skill',
                              'question:query.response',
                              'common_query.question',
                              'ovos.common_query.pong',
                              'mycroft.speech.recognition.unknown',
                              'intent.service.skills.deactivate',
                              'intent.service.skills.activate',
                              'active_skill_request',
                              'intent.service.active_skills.get',
                              'skill.converse.get_response.enable',
                              'skill.converse.get_response.disable',
                              'ovos.skills.fallback.register',
                              'ovos.skills.fallback.deregister',
                              'play:query.response',
                              'ovos.common_play.search',
                              'ovos.common_play.play_search',
                              'ovos.common_play.status.response',
                              'ovos.common_play.track.state',
                              'ovos.common_play.SEI.get.response',
                              'ovos.common_play.register_keyword',
                              'ovos.common_play.deregister_keyword',
                              'ovos.common_play.announce',
                              'mycroft.audio.playing_track',
                              'mycroft.audio.queue_end',
                              'mycroft.audio.service.pause',
                              'mycroft.audio.service.resume',
                              'mycroft.audio.service.stop',
                              'ocp:play',
                              'ocp:play_favorites',
                              'ocp:open',
                              'ocp:next',
                              'ocp:prev',
                              'ocp:pause',
                              'ocp:resume',
                              'ocp:media_stop',
                              'ocp:search_error',
                              'ocp:like_song',
                              'ocp:legacy_cps',
                              'register_vocab',
                              'register_intent',
                              'recognizer_loop:utterance',
                              'detach_intent',
                              'detach_skill',
                              'add_context',
                              'remove_context',
                              'clear_context',
                              'mycroft.skills.loaded',
                              'intent.service.intent.get',
                              'intent.service.skills.get',
                              'intent.service.adapt.get',
                              'intent.service.adapt.manifest.get',
                              'intent.service.adapt.vocab.manifest.get',
                              'intent.service.padatious.get',
                              'intent.service.padatious.manifest.get',
                              'intent.service.padatious.entities.manifest.get']
                             )


class TestAdaptIntent(TestCase):
    """Test the AdaptIntent wrapper."""

    def test_named_intent(self):
        intent = AdaptIntent("CallEaglesIntent")
        self.assertEqual(intent.name, "CallEaglesIntent")

    def test_unnamed_intent(self):
        intent = AdaptIntent()
        self.assertEqual(intent.name, "")
