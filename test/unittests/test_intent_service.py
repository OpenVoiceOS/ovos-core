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
import threading
import time
import unittest
from copy import deepcopy
from unittest import TestCase, mock

from ovos_bus_client.message import Message
from ovos_bus_client.session import IntentContextManager as ContextManager
from ovos_bus_client.session import Session, SessionManager
from ovos_bus_client.util import get_message_lang
from ovos_config import Configuration
from ovos_config import LocalConf, DEFAULT_CONFIG
from ovos_config.locale import setup_locale
from ovos_core.intent_services import IntentService
from ovos_core.intent_services import service as intent_service_module
from ovos_utils.fakebus import FakeBus
from ovos_workshop.intents import IntentBuilder
from ovos_workshop.skills.ovos import OVOSSkill

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


class TestContextWriteLockRace(TestCase):
    """Finding 30a: `IntentService.handle_add_context` copy-modify-assigns
    `Session.intent_context` (`ctx = dict(sess.intent_context); ...;
    sess.intent_context = ctx`) OUTSIDE `ovos_bus_client.session._CONTEXT_LOCK`,
    while a concurrent skill-side write (`ovos-workshop` >=9.3.13a1's
    registry-first `set_context`/`remove_context`, calling
    `Session.set_intent_context`/`remove_intent_context` directly) mutates the
    SAME map under that lock. If the skill's write lands between core's
    snapshot read and its write-back, the stale snapshot silently overwrites
    it - the skill's write is lost with no error and no trace.

    This interleave is sequenced deterministically with `threading.Event`s
    (no `sleep`-based timing): a patched `resolve_key` - called by
    `handle_add_context` right after it snapshots `sess.intent_context` and
    right before it writes the result back - signals readiness and then
    blocks, giving the "skill" thread a bounded window to run its own
    registry write before core's write-back proceeds.
    """

    def setUp(self):
        self.bus = FakeBus()
        self.skill = OVOSSkill(bus=self.bus, skill_id="race.skill")
        self.sess = Session(session_id="s-race-lock-test")
        SessionManager.update(self.sess)
        # seed a live layer0 entry, as if an earlier turn set it
        self.sess.set_intent_context("layer0", "1", scope="private",
                                     owner_id="race.skill")

    def tearDown(self):
        SessionManager.sessions.pop("s-race-lock-test", None)

    def test_concurrent_skill_write_survives_core_add_context(self):
        skill_msg = Message("some.intent", {}, {
            "skill_id": "race.skill",
            "session": SessionManager.sessions["s-race-lock-test"].serialize()})
        # core processing a (possibly stale/duplicate) add_context for the
        # skill's OWN previously-set key, concurrently with the skill moving
        # on to a new context layer
        core_msg = Message("add_context",
                           {"context": "racskilllayer0", "word": "1",
                            "key": "layer0"},
                           {"skill_id": "race.skill",
                            "session": SessionManager.sessions[
                                "s-race-lock-test"].serialize()})

        core_ready = threading.Event()
        skill_done = threading.Event()
        orig_resolve_key = intent_service_module.resolve_key

        def patched_resolve_key(*args, **kwargs):
            # fires between `handle_add_context`'s `ctx = dict(...)` snapshot
            # and its `sess.intent_context = ctx` write-back
            core_ready.set()
            skill_done.wait(timeout=5)
            return orig_resolve_key(*args, **kwargs)

        def skill_turn(triggering_msg):
            # `triggering_msg` is a positional arg on THIS frame so
            # `dig_for_message()` (walked internally by
            # `skill.remove_context`/`set_context`) resolves the right
            # session - mirroring a real skill handler.
            self.skill.remove_context("layer0")  # tombstone layer0
            self.skill.set_context("layer1", "1")

        core_thread = threading.Thread(
            target=IntentService.handle_add_context, args=(core_msg,))
        intent_service_module.resolve_key = patched_resolve_key
        try:
            core_thread.start()
            self.assertTrue(core_ready.wait(timeout=5),
                            "core thread never reached the snapshot window")
            skill_turn(skill_msg)
            skill_done.set()
            core_thread.join(timeout=5)
            self.assertFalse(core_thread.is_alive(),
                             "core thread did not finish")
        finally:
            intent_service_module.resolve_key = orig_resolve_key

        final_ctx = SessionManager.sessions["s-race-lock-test"].intent_context
        # the skill's new write (layer1) must not be silently dropped
        self.assertIn("race.skill:layer1", final_ctx)
        self.assertEqual(final_ctx["race.skill:layer1"]["value"], "1")
        # the skill's tombstone (layer0 removal), applied after core's
        # write-back completed (it was blocked on `_CONTEXT_LOCK` until
        # then), must stick - not be silently un-done by a leftover stale
        # snapshot
        self.assertIsNone(final_ctx.get("race.skill:layer0"))

