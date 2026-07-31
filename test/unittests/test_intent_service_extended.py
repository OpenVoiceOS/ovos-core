# Copyright 2024 OpenVoiceOS
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

import unittest
from collections import defaultdict
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
from ovos_plugin_manager.templates.pipeline import (
    IntentHandlerMatch,
    ConfidenceMatcherPipeline,
)
from ovos_utils.fakebus import FakeBus
from ovos_spec_tools import SpecMessage

from ovos_core.intent_services.service import IntentService
from ovos_core.intent_services.dispatcher import IntentDispatcher
from ovos_core.intent_services.manifest import IntentManifest


def _make_service(config=None) -> IntentService:
    """Construct IntentService without loading real pipelines or plugins."""
    bus = FakeBus()
    svc = IntentService.__new__(IntentService)
    svc.bus = bus
    svc.config = config or {}
    svc.pipeline_plugins = {}
    svc._deactivations = defaultdict(list)
    # PIPELINE-1 §7/§8 dispatcher; timer disabled so unit tests stay deterministic
    svc.intent_dispatcher = IntentDispatcher(bus, timeout=0)

    # Minimal stub objects for transformer services
    ut = MagicMock()
    ut.transform.side_effect = lambda utt, ctx: (utt, ctx)
    svc.utterance_plugins = ut

    mt = MagicMock()
    mt.transform.side_effect = lambda ctx: ctx
    svc.metadata_plugins = mt

    it = MagicMock()
    it.transform.side_effect = lambda intent: intent
    svc.intent_plugins = it

    # INTENT-4 §10 manifest — indexes registration broadcasts
    svc.intent_manifest = IntentManifest(bus)

    svc.status = MagicMock()
    return svc


def _make_match(match_type: str = "test:intent",
                skill_id: str = "test.skill",
                utterance: str = "hello",
                session: Session = None) -> IntentHandlerMatch:
    return IntentHandlerMatch(
        match_type=match_type,
        match_data={"skill_id": skill_id},
        skill_id=skill_id,
        utterance=utterance,
        updated_session=session,
    )


# ---------------------------------------------------------------------------
# _handle_transformers
# ---------------------------------------------------------------------------

class TestHandleTransformers(unittest.TestCase):
    """Tests for IntentService._handle_transformers."""

    def test_utterance_plugins_transform_is_called(self):
        """utterance_plugins.transform is called with utterances and context."""
        svc = _make_service()
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["hello"]},
                      context={"lang": "en-US"})
        with patch("ovos_core.intent_services.service.get_message_lang",
                   return_value="en-US"):
            svc._handle_transformers(msg)
        svc.utterance_plugins.transform.assert_called_once()

    def test_metadata_plugins_transform_is_called(self):
        """metadata_plugins.transform is called after utterance transform."""
        svc = _make_service()
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["hello"]},
                      context={"lang": "en-US"})
        with patch("ovos_core.intent_services.service.get_message_lang",
                   return_value="en-US"):
            svc._handle_transformers(msg)
        svc.metadata_plugins.transform.assert_called_once()

    def test_modified_utterances_written_back_to_message(self):
        """When utterances are modified by plugins they are stored in message.data."""
        svc = _make_service()
        svc.utterance_plugins.transform.side_effect = lambda utt, ctx: (["modified"], ctx)
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["original"]},
                      context={})
        with patch("ovos_core.intent_services.service.get_message_lang",
                   return_value="en-US"):
            result = svc._handle_transformers(msg)
        self.assertEqual(result.data["utterances"], ["modified"])

    def test_lang_set_in_context(self):
        """The message context gets a 'lang' key after _handle_transformers."""
        svc = _make_service()
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["hi"]},
                      context={})
        with patch("ovos_core.intent_services.service.get_message_lang",
                   return_value="de-DE"):
            result = svc._handle_transformers(msg)
        self.assertEqual(result.context["lang"], "de-DE")


# ---------------------------------------------------------------------------
# disambiguate_lang
# ---------------------------------------------------------------------------

class TestDisambiguateLang(unittest.TestCase):
    """Tests for IntentService.disambiguate_lang."""

    def test_returns_default_lang_when_no_context_keys(self):
        """Returns the default language when no lang context keys are present."""
        msg = Message("test", data={}, context={})
        with patch("ovos_core.intent_services.service.get_message_lang",
                   return_value="en-US"), \
             patch("ovos_core.intent_services.service.get_valid_languages",
                   return_value=["en-US"]):
            result = IntentService.disambiguate_lang(msg)
        self.assertEqual(result, "en-US")

    def test_stt_lang_takes_precedence_over_default(self):
        """stt_lang in context overrides the default language."""
        msg = Message("test", data={}, context={"stt_lang": "fr-FR"})
        with patch("ovos_core.intent_services.service.get_message_lang",
                   return_value="en-US"), \
             patch("ovos_core.intent_services.service.get_valid_languages",
                   return_value=["en-US", "fr-FR"]):
            result = IntentService.disambiguate_lang(msg)
        self.assertEqual(result, "fr-FR")

    def test_lang_not_in_valid_langs_falls_through(self):
        """An stt_lang not in valid languages is ignored and falls through to default."""
        msg = Message("test", data={}, context={"stt_lang": "xx-XX"})
        with patch("ovos_core.intent_services.service.get_message_lang",
                   return_value="en-US"), \
             patch("ovos_core.intent_services.service.get_valid_languages",
                   return_value=["en-US"]):
            result = IntentService.disambiguate_lang(msg)
        self.assertEqual(result, "en-US")


# ---------------------------------------------------------------------------
# get_pipeline_matcher
# ---------------------------------------------------------------------------

class TestGetPipelineMatcher(unittest.TestCase):
    """Tests for IntentService.get_pipeline_matcher."""

    def test_returns_none_for_unknown_plugin(self):
        """An unknown matcher_id returns None and logs an error."""
        svc = _make_service()
        result = svc.get_pipeline_matcher("nonexistent-pipeline-plugin")
        self.assertIsNone(result)

    def test_returns_match_high_for_high_suffix(self):
        """A ConfidenceMatcherPipeline plugin with -high suffix returns match_high."""
        plugin = MagicMock(spec=ConfidenceMatcherPipeline)
        plugin.match_high = MagicMock()
        svc = _make_service()
        svc.pipeline_plugins["ovos-adapt-pipeline-plugin"] = plugin
        result = svc.get_pipeline_matcher("ovos-adapt-pipeline-plugin-high")
        self.assertEqual(result, plugin.match_high)

    def test_returns_match_medium_for_medium_suffix(self):
        """A ConfidenceMatcherPipeline plugin with -medium suffix returns match_medium."""
        plugin = MagicMock(spec=ConfidenceMatcherPipeline)
        plugin.match_medium = MagicMock()
        svc = _make_service()
        svc.pipeline_plugins["ovos-adapt-pipeline-plugin"] = plugin
        result = svc.get_pipeline_matcher("ovos-adapt-pipeline-plugin-medium")
        self.assertEqual(result, plugin.match_medium)

    def test_returns_match_low_for_low_suffix(self):
        """A ConfidenceMatcherPipeline plugin with -low suffix returns match_low."""
        plugin = MagicMock(spec=ConfidenceMatcherPipeline)
        plugin.match_low = MagicMock()
        svc = _make_service()
        svc.pipeline_plugins["ovos-adapt-pipeline-plugin"] = plugin
        result = svc.get_pipeline_matcher("ovos-adapt-pipeline-plugin-low")
        self.assertEqual(result, plugin.match_low)

    def test_returns_match_for_non_confidence_plugin(self):
        """A plain pipeline plugin returns its .match method."""
        plugin = MagicMock()
        del plugin.__class__
        plugin.match = MagicMock()
        svc = _make_service()
        # Use a plugin key without high/medium/low
        svc.pipeline_plugins["ovos-plain-pipeline-plugin"] = plugin
        result = svc.get_pipeline_matcher("ovos-plain-pipeline-plugin")
        self.assertEqual(result, plugin.match)

    def test_migration_map_resolves_old_style_names(self):
        """Old-style pipeline names like 'adapt_high' are migrated to the new plugin ID."""
        plugin = MagicMock(spec=ConfidenceMatcherPipeline)
        plugin.match_high = MagicMock()
        svc = _make_service()
        # migration: adapt_high → ovos-adapt-pipeline-plugin-high
        svc.pipeline_plugins["ovos-adapt-pipeline-plugin"] = plugin
        result = svc.get_pipeline_matcher("adapt_high")
        self.assertEqual(result, plugin.match_high)


# ---------------------------------------------------------------------------
# get_pipeline
# ---------------------------------------------------------------------------

class TestGetPipeline(unittest.TestCase):
    """Tests for IntentService.get_pipeline."""

    def test_invalid_matchers_filtered_out(self):
        """Matchers that fail to load (return None) are excluded from the pipeline."""
        svc = _make_service()
        # No plugins installed → all matchers return None
        sess = Session("s")
        sess.pipeline = ["adapt_high", "fallback_high"]
        result = svc.get_pipeline(session=sess)
        self.assertEqual(result, [])

    def test_valid_matcher_included(self):
        """A matcher that resolves to a callable is included."""
        plugin = MagicMock(spec=ConfidenceMatcherPipeline)
        plugin.match_high = MagicMock()
        svc = _make_service()
        svc.pipeline_plugins["ovos-adapt-pipeline-plugin"] = plugin
        sess = Session("s")
        sess.pipeline = ["adapt_high"]
        result = svc.get_pipeline(session=sess)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "adapt_high")


# ---------------------------------------------------------------------------
# get_pipeline - session.blacklisted_pipelines (OVOS-PIPELINE-1 §5.2/§5.5)
# ---------------------------------------------------------------------------

class TestGetPipelineSessionBlacklist(unittest.TestCase):
    """Tests for per-session runtime enforcement of
    `session.blacklisted_pipelines` in IntentService.get_pipeline.

    OVOS-PIPELINE-1 §5.2: `blacklisted_pipelines` is the policy channel and
    MUST NOT be invoked for the session, even if also requested in
    `session.pipeline`. §5.5: policy overrides preference. Filtering is
    orchestrator-only - no `match` call, no bus event; observable only as
    non-invocation. Unknown pipeline_ids are harmless no-ops.
    """

    @staticmethod
    def _svc_with_adapt_fallback():
        svc = _make_service()
        adapt = MagicMock(spec=ConfidenceMatcherPipeline)
        adapt.match_high = MagicMock()
        svc.pipeline_plugins["ovos-adapt-pipeline-plugin"] = adapt
        fallback = MagicMock(spec=ConfidenceMatcherPipeline)
        fallback.match_high = MagicMock()
        svc.pipeline_plugins["ovos-fallback-pipeline-plugin"] = fallback
        return svc

    def test_blacklisted_matcher_skipped_other_session_unaffected(self):
        """A session with a matcher blacklisted skips it; a concurrent
        session without the blacklist still matches it (§5.2)."""
        svc = self._svc_with_adapt_fallback()

        blocked = Session("blocked")
        blocked.pipeline = ["adapt_high", "fallback_high"]
        blocked.blacklisted_pipelines = ["adapt_high"]
        blocked_result = svc.get_pipeline(session=blocked)
        self.assertEqual([m[0] for m in blocked_result], ["fallback_high"])

        free = Session("free")
        free.pipeline = ["adapt_high", "fallback_high"]
        free_result = svc.get_pipeline(session=free)
        self.assertEqual([m[0] for m in free_result], ["adapt_high", "fallback_high"])

    def test_blacklist_overrides_explicit_pipeline_preference(self):
        """A matcher listed in BOTH session.pipeline and
        session.blacklisted_pipelines MUST NOT be invoked - policy overrides
        preference (§5.5 step 3)."""
        svc = self._svc_with_adapt_fallback()

        sess = Session("s")
        sess.pipeline = ["adapt_high", "fallback_high"]
        sess.blacklisted_pipelines = ["adapt_high", "fallback_high"]
        result = svc.get_pipeline(session=sess)
        self.assertEqual(result, [])

    def test_unknown_blacklisted_id_is_harmless_noop(self):
        """Unknown pipeline_ids in blacklisted_pipelines are ignored without
        error and don't affect the effective pipeline (§5.2)."""
        svc = self._svc_with_adapt_fallback()

        sess = Session("s")
        sess.pipeline = ["adapt_high"]
        sess.blacklisted_pipelines = ["totally-unknown-pipeline-id"]
        result = svc.get_pipeline(session=sess)
        self.assertEqual([m[0] for m in result], ["adapt_high"])

    def test_no_bus_emission_accompanies_skip(self):
        """The skip is orchestrator-only: no `match` call and no bus event
        is emitted for a blacklisted matcher (§5.2)."""
        svc = self._svc_with_adapt_fallback()
        emitted = []
        svc.bus.on("message", lambda m: emitted.append(m))

        sess = Session("s")
        sess.pipeline = ["adapt_high", "fallback_high"]
        sess.blacklisted_pipelines = ["adapt_high"]
        result = svc.get_pipeline(session=sess)

        self.assertEqual([m[0] for m in result], ["fallback_high"])
        adapt_plugin = svc.pipeline_plugins["ovos-adapt-pipeline-plugin"]
        adapt_plugin.match_high.assert_not_called()
        self.assertEqual(emitted, [])


# ---------------------------------------------------------------------------
# handle_add_context / handle_remove_context / handle_clear_context
# ---------------------------------------------------------------------------

class TestContextHandlers(unittest.TestCase):
    """Tests for the context management static methods."""

    def test_handle_add_context_injects_entity(self):
        """handle_add_context injects the entity into the session context."""
        sess = Session("s")
        msg = Message("add_context",
                      data={"context": "MyContext", "word": "myword"},
                      context={"session": sess.serialize()})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_add_context(msg)
        # The frame_stack should have an entry
        self.assertGreater(len(sess.context.frame_stack), 0)
        # OVOS-CONTEXT-1: the token is mirrored into the intent_context map,
        # keyed by the context token and carrying its injected value
        self.assertEqual(sess.intent_context.get("MyContext"),
                         {"value": "myword"})

    def test_handle_remove_context_removes_entity(self):
        """handle_remove_context removes the specified context."""
        sess = Session("s")
        # First inject something
        entity = {"confidence": 1.0, "data": [("word", "MyCtx")],
                  "match": "word", "key": "word", "origin": ""}
        sess.context.inject_context(entity)
        msg = Message("remove_context",
                      data={"context": "MyCtx"},
                      context={"session": sess.serialize()})
        sess.intent_context = {"MyCtx": {"value": "word"}}
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_remove_context(msg)
        self.assertEqual(len(sess.context.frame_stack), 0)
        # OVOS-CONTEXT-1: the token is also dropped from the intent_context map
        self.assertNotIn("MyCtx", sess.intent_context or {})

    def test_handle_clear_context_empties_stack(self):
        """handle_clear_context empties the entire frame stack."""
        sess = Session("s")
        entity = {"confidence": 1.0, "data": [("w", "C1")],
                  "match": "w", "key": "w", "origin": ""}
        sess.context.inject_context(entity)
        sess.intent_context = {"C1": {"value": "w"}}
        msg = Message("clear_context",
                      data={},
                      context={"session": sess.serialize()})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_clear_context(msg)
        self.assertEqual(len(sess.context.frame_stack), 0)
        # OVOS-CONTEXT-1: clearing context empties the intent_context map too
        self.assertFalse(sess.intent_context)

    def test_handle_add_context_non_string_word_converted(self):
        """Non-string word is converted to string without raising."""
        sess = Session("s")
        msg = Message("add_context",
                      data={"context": "Ctx", "word": 42},
                      context={"session": sess.serialize()})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_add_context(msg)
        self.assertGreater(len(sess.context.frame_stack), 0)


# ---------------------------------------------------------------------------
# send_complete_intent_failure
# ---------------------------------------------------------------------------

class TestSendCompleteIntentFailure(unittest.TestCase):
    """Tests for IntentService.send_complete_intent_failure."""

    def test_emits_three_messages(self):
        """PIPELINE-1 §9.3/§9.5: play_sound, ovos.intent.unmatched, handled."""
        svc = _make_service()
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)
        msg = Message("test", data={}, context={})
        with patch("ovos_core.intent_services.service.Configuration",
                   return_value={"sounds": {"error": "snd/error.mp3"}}):
            svc.send_complete_intent_failure(msg)
        types = [m.msg_type for m in emitted]
        self.assertIn("mycroft.audio.play_sound", types)
        self.assertIn("ovos.intent.unmatched", types)
        self.assertIn("ovos.utterance.handled", types)
        self.assertNotIn("complete_intent_failure", types)

    def test_error_sound_from_config_used(self):
        """The error sound path from config is used in the play_sound message."""
        svc = _make_service()
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)
        msg = Message("test", data={}, context={})
        with patch("ovos_core.intent_services.service.Configuration",
                   return_value={"sounds": {"error": "custom/error.wav"}}):
            svc.send_complete_intent_failure(msg)
        sound_msg = next(m for m in emitted if m.msg_type == "mycroft.audio.play_sound")
        self.assertEqual(sound_msg.data["uri"], "custom/error.wav")


# ---------------------------------------------------------------------------
# send_cancel_event
# ---------------------------------------------------------------------------

class TestSendCancelEvent(unittest.TestCase):
    """Tests for IntentService.send_cancel_event."""

    def test_emits_cancelled_and_handled(self):
        """Emits ovos.utterance.cancelled and ovos.utterance.handled."""
        svc = _make_service()
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)
        msg = Message("test", data={}, context={"cancel_word": "stop"})
        with patch("ovos_core.intent_services.service.Configuration",
                   return_value={}):
            svc.send_cancel_event(msg)
        types = [m.msg_type for m in emitted]
        self.assertIn("ovos.utterance.cancelled", types)
        self.assertIn("ovos.utterance.handled", types)
        self.assertIn("mycroft.audio.play_sound", types)


# ---------------------------------------------------------------------------
# _handle_deactivate
# ---------------------------------------------------------------------------

class TestHandleDeactivate(unittest.TestCase):
    """Tests for IntentService._handle_deactivate."""

    def test_deactivation_tracked_per_session(self):
        """_handle_deactivate records the skill_id in _deactivations for the session."""
        svc = _make_service()
        sess = Session("test-session")
        msg = Message("intent.service.skills.deactivate",
                      data={"skill_id": "skill_a"},
                      context={"session": sess.serialize()})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            svc._handle_deactivate(msg)
        self.assertIn("skill_a", svc._deactivations["test-session"])


# ---------------------------------------------------------------------------
# _dispatch_match
# ---------------------------------------------------------------------------

class TestEmitMatchMessage(unittest.TestCase):
    """Tests for IntentService._dispatch_match."""

    def test_reply_emitted_on_bus(self):
        """A reply message is emitted on the bus for a valid match."""
        svc = _make_service()
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)
        sess = Session("s")
        match = _make_match(session=sess)
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["hello"]},
                      context={"session": sess.serialize()})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            svc._dispatch_match(match, msg, "en-US")
        types = [m.msg_type for m in emitted]
        self.assertIn("test:intent", types)

    def test_skill_activated_when_not_deactivated(self):
        """skill.activate event is emitted when skill was not previously deactivated."""
        svc = _make_service()
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)
        sess = Session("s")
        match = _make_match(session=sess)
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["hello"]},
                      context={"session": sess.serialize()})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            svc._dispatch_match(match, msg, "en-US")
        types = [m.msg_type for m in emitted]
        self.assertTrue(any("activate" in t for t in types))

    def test_skill_not_activated_when_deactivated(self):
        """skill.activate event is NOT emitted when skill was deactivated this turn."""
        svc = _make_service()
        sess = Session("s")
        svc._deactivations[sess.session_id] = ["test.skill"]
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)
        match = _make_match(session=sess)
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["hello"]},
                      context={"session": sess.serialize()})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            svc._dispatch_match(match, msg, "en-US")
        types = [m.msg_type for m in emitted]
        self.assertFalse(any("activate" in t for t in types))

    def test_intent_transformer_applied(self):
        """intent_plugins.transform is called before emitting the reply."""
        svc = _make_service()
        svc.bus.emit = MagicMock()
        sess = Session("s")
        match = _make_match(session=sess)
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["hello"]},
                      context={"session": sess.serialize()})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            svc._dispatch_match(match, msg, "en-US")
        svc.intent_plugins.transform.assert_called_once()


# ---------------------------------------------------------------------------
# handle_utterance (basic wiring)
# ---------------------------------------------------------------------------

class TestHandleUtterance(unittest.TestCase):
    """Tests for IntentService.handle_utterance basic wiring."""

    def test_cancel_context_triggers_cancel_event(self):
        """When message.context['canceled'] is True, send_cancel_event is called."""
        svc = _make_service()
        svc.send_cancel_event = MagicMock()
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["stop"]},
                      context={"canceled": True})
        with patch.object(svc, "_handle_transformers",
                          side_effect=lambda m: m):
            svc.handle_utterance(msg)
        svc.send_cancel_event.assert_called_once()

    def test_no_match_calls_complete_intent_failure(self):
        """When no pipeline matches, send_complete_intent_failure is called."""
        svc = _make_service()
        svc.send_complete_intent_failure = MagicMock()
        sess = Session("s")
        sess.pipeline = []  # empty pipeline → no matchers
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["xyz"]},
                      context={})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess), \
             patch("ovos_core.intent_services.service.SessionManager.reset_default_session",
                   return_value=sess), \
             patch("ovos_core.intent_services.service.SessionManager.update"), \
             patch("ovos_core.intent_services.service.SessionManager.sync"), \
             patch("ovos_core.intent_services.service.get_message_lang",
                   return_value="en-US"), \
             patch("ovos_core.intent_services.service.get_valid_languages",
                   return_value=["en-US"]):
            svc.handle_utterance(msg)
        svc.send_complete_intent_failure.assert_called_once()


# ---------------------------------------------------------------------------
# handle_get_intent
# ---------------------------------------------------------------------------

class TestHandleGetIntent(unittest.TestCase):
    """Tests for IntentService.handle_get_intent."""

    def test_no_match_emits_none_reply(self):
        """When no pipeline matches, emits intent.service.intent.reply with intent=None."""
        svc = _make_service()
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)
        sess = Session("s")
        sess.pipeline = []
        msg = Message("intent.service.intent.get",
                      data={"utterance": "hello"},
                      context={})
        with patch("ovos_core.intent_services.service.get_message_lang",
                   return_value="en-US"), \
             patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            svc.handle_get_intent(msg)
        reply = next(m for m in emitted if m.msg_type == "intent.service.intent.reply")
        self.assertIsNone(reply.data["intent"])

    def test_match_emits_intent_data(self):
        """A pipeline match emits intent.service.intent.reply with intent data."""
        svc = _make_service()
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)
        sess = Session("s")

        match = _make_match()
        mock_matcher = MagicMock(return_value=match)
        mock_matcher.__name__ = "test_matcher"
        svc.pipeline_plugins["ovos-test-plugin"] = MagicMock()

        get_msg = Message(
            "intent.service.intent.get",
            data={"utterance": "hello"},
            context={})
        with patch.object(svc, "get_pipeline",
                          return_value=[("test_pipeline", mock_matcher)]), \
             patch("ovos_core.intent_services.service.get_message_lang",
                   return_value="en-US"), \
             patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            svc.handle_get_intent(get_msg)
        reply = next(m for m in emitted if m.msg_type == "intent.service.intent.reply")
        self.assertIsNotNone(reply.data["intent"])


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------

class TestShutdown(unittest.TestCase):
    """Tests for IntentService.shutdown."""

    def test_shutdown_removes_bus_listeners(self):
        """shutdown() removes all registered bus listeners."""
        svc = _make_service()
        svc.bus.remove = MagicMock()
        svc.shutdown()
        removed = {c[0][0] for c in svc.bus.remove.call_args_list}
        self.assertIn(SpecMessage.UTTERANCE, removed)
        self.assertIn("add_context", removed)
        self.assertIn("remove_context", removed)
        self.assertIn("clear_context", removed)

    def test_shutdown_calls_status_set_stopping(self):
        """shutdown() calls status.set_stopping()."""
        svc = _make_service()
        svc.bus.remove = MagicMock()
        svc.shutdown()
        svc.status.set_stopping.assert_called_once()

    def test_shutdown_calls_transformer_shutdown(self):
        """shutdown() shuts down utterance_plugins and metadata_plugins."""
        svc = _make_service()
        svc.bus.remove = MagicMock()
        svc.shutdown()
        svc.utterance_plugins.shutdown.assert_called_once()
        svc.metadata_plugins.shutdown.assert_called_once()

    def test_shutdown_calls_pipeline_stop_and_shutdown(self):
        """shutdown() calls stop() and shutdown() on pipeline plugins that have them."""
        svc = _make_service()
        svc.bus.remove = MagicMock()
        pipeline = MagicMock()
        svc.pipeline_plugins["test_plugin"] = pipeline
        svc.shutdown()
        pipeline.stop.assert_called_once()
        pipeline.shutdown.assert_called_once()


# ---------------------------------------------------------------------------
# OVOS-PIPELINE-1 §6.2 required_slots backstop
# ---------------------------------------------------------------------------

class TestRequiredSlotsBackstop(unittest.TestCase):
    # §6.2 sources required_slots from the INTENT-4 §10 manifest.

    def _register(self, svc, required_slots):
        svc.intent_manifest._on_register(Message(
            "ovos.intent.register.template",
            {"skill_id": "test.skill", "intent_name": "intent",
             "lang": "en-US", "samples": ["do it"],
             "required_slots": required_slots},
            {"session": {"session_id": "default"}}))

    def test_intent_not_in_manifest_is_noop(self):
        svc = _make_service()
        m = _make_match(match_type="test.skill:intent")
        m.match_data = {"skill_id": "test.skill"}
        self.assertEqual(svc._missing_required_slots(m, "default", "en-US"), [])

    def test_all_required_slots_present(self):
        svc = _make_service()
        self._register(svc, ["room"])
        m = _make_match(match_type="test.skill:intent")
        m.match_data = {"skill_id": "test.skill", "room": "kitchen"}
        self.assertEqual(svc._missing_required_slots(m, "default", "en-US"), [])

    def test_missing_required_slot_reported(self):
        svc = _make_service()
        self._register(svc, ["room", "device"])
        m = _make_match(match_type="test.skill:intent")
        m.match_data = {"skill_id": "test.skill", "room": "kitchen"}
        self.assertEqual(svc._missing_required_slots(m, "default", "en-US"), ["device"])

    def test_falsy_slot_counts_as_missing(self):
        svc = _make_service()
        self._register(svc, ["room"])
        m = _make_match(match_type="test.skill:intent")
        m.match_data = {"skill_id": "test.skill", "room": ""}
        self.assertEqual(svc._missing_required_slots(m, "default", "en-US"), ["room"])


# ---------------------------------------------------------------------------
# OVOS-PIPELINE-1 §7.1/§7.3 active-handler push + reserved-name suppression
# ---------------------------------------------------------------------------

class TestReservedNameActivation(unittest.TestCase):

    def _dispatch(self, pipeline_id):
        svc = _make_service()
        sess = Session("s1")
        msg = Message("recognizer_loop:utterance", {"utterances": ["hi"]},
                      {"session": sess.serialize()})
        match = _make_match(match_type="test.skill:intent",
                            skill_id="test.skill", session=sess)
        svc._dispatch_match(match, msg, "en-US", pipeline_id=pipeline_id)
        return sess

    def test_regular_pipeline_pushes_active_handler(self):
        sess = self._dispatch("ovos-adapt-pipeline-plugin-high")
        ids = [h.get("skill_id") if isinstance(h, dict) else getattr(h, "skill_id", h)
               for h in sess.active_handlers]
        self.assertIn("test.skill", ids)

    def test_reserved_name_pipeline_suppresses_push(self):
        # §7.3: converse/stop/fallback/common_query dispatches must NOT push
        for pid in ("ovos-converse-pipeline-plugin",
                    "ovos-stop-pipeline-plugin-high",
                    "ovos-fallback-pipeline-plugin-medium",
                    "ovos-common-query-pipeline-plugin"):
            sess = self._dispatch(pid)
            ids = [h.get("skill_id") if isinstance(h, dict) else getattr(h, "skill_id", h)
                   for h in sess.active_handlers]
            self.assertNotIn("test.skill", ids, f"{pid} should suppress the push")


class TestProducesReservedName(unittest.TestCase):

    def test_reserved_roles_true_with_confidence_suffix(self):
        from ovos_core.intent_services.service import _produces_reserved_name
        self.assertTrue(_produces_reserved_name("ovos-stop-pipeline-plugin-high"))
        self.assertTrue(_produces_reserved_name("ovos-converse-pipeline-plugin"))

    def test_regular_role_false(self):
        from ovos_core.intent_services.service import _produces_reserved_name
        self.assertFalse(_produces_reserved_name("ovos-adapt-pipeline-plugin-high"))
        self.assertFalse(_produces_reserved_name(None))


# ---------------------------------------------------------------------------
# handle_reload_pipelines - blacklisted_pipelines
# ---------------------------------------------------------------------------

class TestBlacklistedPipelines(unittest.TestCase):
    """
    Pipeline plugins listed in `intents.blacklisted_pipelines` must never be
    imported/instantiated, even though ovos-core otherwise loads every
    installed pipeline plugin (a remote client/session may select any of
    them at runtime).
    """

    def _make_service_with_installed(self, installed, config=None):
        svc = _make_service(config=config)
        return svc

    @patch("ovos_core.intent_services.service.OVOSPipelineFactory")
    def test_blacklisted_plugin_never_loaded(self, mock_factory):
        mock_factory.get_installed_pipeline_ids.return_value = [
            "ovos-adapt-pipeline-plugin",
            "ovos-m2v-pipeline",
        ]
        mock_factory.load_plugin.side_effect = lambda p, bus=None: MagicMock(name=p)

        svc = _make_service(config={"blacklisted_pipelines": ["ovos-m2v-pipeline"]})
        svc.handle_reload_pipelines(Message("intent.service.pipelines.reload"))

        self.assertIn("ovos-adapt-pipeline-plugin", svc.pipeline_plugins)
        self.assertNotIn("ovos-m2v-pipeline", svc.pipeline_plugins)
        loaded_ids = [c.args[0] for c in mock_factory.load_plugin.call_args_list]
        self.assertNotIn("ovos-m2v-pipeline", loaded_ids)

    @patch("ovos_core.intent_services.service.OVOSPipelineFactory")
    def test_non_blacklisted_plugins_load_as_before(self, mock_factory):
        mock_factory.get_installed_pipeline_ids.return_value = [
            "ovos-adapt-pipeline-plugin",
            "ovos-padatious-pipeline-plugin",
        ]
        mock_factory.load_plugin.side_effect = lambda p, bus=None: MagicMock(name=p)

        svc = _make_service(config={"blacklisted_pipelines": []})
        svc.handle_reload_pipelines(Message("intent.service.pipelines.reload"))

        self.assertIn("ovos-adapt-pipeline-plugin", svc.pipeline_plugins)
        self.assertIn("ovos-padatious-pipeline-plugin", svc.pipeline_plugins)
        self.assertEqual(mock_factory.load_plugin.call_count, 2)

    @patch("ovos_core.intent_services.service.LOG")
    @patch("ovos_core.intent_services.service.OVOSPipelineFactory")
    def test_blacklisted_plugin_still_in_active_pipeline_warns(self, mock_factory, mock_log):
        # config contradiction: plugin blacklisted but also selected as active matcher
        mock_factory.get_installed_pipeline_ids.return_value = ["ovos-m2v-pipeline"]
        mock_factory.load_plugin.side_effect = lambda p, bus=None: MagicMock(name=p)

        svc = _make_service(config={
            "blacklisted_pipelines": ["ovos-m2v-pipeline"],
            "pipeline": ["ovos-m2v-pipeline-high"],
        })
        svc.handle_reload_pipelines(Message("intent.service.pipelines.reload"))

        self.assertNotIn("ovos-m2v-pipeline", svc.pipeline_plugins)
        self.assertTrue(mock_log.warning.called)
        warned = " ".join(str(c) for c in mock_log.warning.call_args_list)
        self.assertIn("ovos-m2v-pipeline", warned)

    @patch("ovos_core.intent_services.service.LOG")
    @patch("ovos_core.intent_services.service.OVOSPipelineFactory")
    def test_blacklisted_plugin_logs_skip_info(self, mock_factory, mock_log):
        mock_factory.get_installed_pipeline_ids.return_value = ["ovos-m2v-pipeline"]

        svc = _make_service(config={"blacklisted_pipelines": ["ovos-m2v-pipeline"]})
        svc.handle_reload_pipelines(Message("intent.service.pipelines.reload"))

        self.assertFalse(mock_factory.load_plugin.called)
        info_calls = " ".join(str(c) for c in mock_log.info.call_args_list)
        self.assertIn("ovos-m2v-pipeline", info_calls)


if __name__ == "__main__":
    unittest.main()
