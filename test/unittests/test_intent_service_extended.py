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

import time
import unittest
from collections import defaultdict
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from ovos_bus_client.session import DEFAULT_SESSION_ID, Session, SessionManager
from ovos_config.config import Configuration
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

    def test_macrolanguage_member_resolves_to_its_macrolanguage(self):
        """A tag at the language-distance threshold resolves (arz -> ar)."""
        for tag in ("arz", "wuu"):
            macro = "ar" if tag == "arz" else "zh"
            with self.subTest(tag=tag):
                msg = Message("test", data={}, context={"stt_lang": tag})
                with patch("ovos_core.intent_services.service.get_message_lang",
                           return_value="en-US"), \
                     patch("ovos_core.intent_services.service.get_valid_languages",
                           return_value=["en-US", macro]):
                    result = IntentService.disambiguate_lang(msg)
                self.assertEqual(result, tag)

    def test_regional_variant_resolves(self):
        """Regional variants stay inside the threshold."""
        for tag, supported in (("ar-SA", "ar"), ("en-AU", "en-GB"), ("pt-BR", "pt-PT")):
            with self.subTest(tag=tag):
                msg = Message("test", data={}, context={"stt_lang": tag})
                with patch("ovos_core.intent_services.service.get_message_lang",
                           return_value="en-US"), \
                     patch("ovos_core.intent_services.service.get_valid_languages",
                           return_value=["en-US", supported]):
                    result = IntentService.disambiguate_lang(msg)
                self.assertEqual(result, tag)

    def test_unrelated_language_is_ignored(self):
        """Distant languages stay outside the threshold and fall through."""
        for tag, supported in (("zh", "en"), ("fr", "es"),
                               ("de-CH", "fr-CH"), ("nl", "af")):
            with self.subTest(tag=tag):
                msg = Message("test", data={}, context={"stt_lang": tag})
                with patch("ovos_core.intent_services.service.get_message_lang",
                           return_value="en-US"), \
                     patch("ovos_core.intent_services.service.get_valid_languages",
                           return_value=[supported]):
                    result = IntentService.disambiguate_lang(msg)
                self.assertEqual(result, "en-US")


# ---------------------------------------------------------------------------
# get_pipeline_matcher
# ---------------------------------------------------------------------------

class TestGetPipelineMatcher(unittest.TestCase):
    """Tests for IntentService.get_pipeline_matcher."""

    @patch("ovos_core.intent_services.service.LOG")
    def test_returns_none_for_unknown_plugin(self, mock_log):
        """An unknown matcher_id returns None and logs an error."""
        svc = _make_service()
        result = svc.get_pipeline_matcher("nonexistent-pipeline-plugin")
        self.assertIsNone(result)
        # Verify error was logged with helpful message
        self.assertTrue(mock_log.error.called)
        error_msg = " ".join(str(c) for c in mock_log.error.call_args_list)
        self.assertIn("nonexistent-pipeline-plugin", error_msg)
        self.assertIn("no installed plugin provides it", error_msg)

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

    def test_plugin_blacklist_skips_all_confidence_matchers_before_lookup(self):
        """A base plugin policy ID blocks its suffixed matcher variants.

        The deployment blacklist is expressed in installed plugin IDs while a
        session pipeline contains confidence-suffixed matcher IDs.  Filtering
        must happen before matcher lookup so an intentionally disabled plugin
        is neither invoked nor reported as unknown.
        """
        svc = self._svc_with_adapt_fallback()
        sess = Session("s")
        sess.pipeline = [
            "ovos-adapt-pipeline-plugin-high",
            "fallback_high",
        ]
        sess.blacklisted_pipelines = ["ovos-adapt-pipeline-plugin"]

        with patch.object(svc, "get_pipeline_matcher",
                          wraps=svc.get_pipeline_matcher) as get_matcher:
            result = svc.get_pipeline(session=sess)

        self.assertEqual([matcher[0] for matcher in result], ["fallback_high"])
        get_matcher.assert_called_once_with("fallback_high")

    def test_suffixed_blacklist_entry_denies_all_tiers_of_the_plugin(self):
        """A confidence-suffixed blacklist entry (legacy spelling) denies the
        whole plugin, not just the matching tier (§3/§5.2: a blacklist entry
        names a plugin, i.e. a single actor, that cannot be denied in one
        tier and invoked in another)."""
        svc = self._svc_with_adapt_fallback()
        sess = Session("s")
        sess.pipeline = [
            "ovos-adapt-pipeline-plugin-high",
            "ovos-adapt-pipeline-plugin-medium",
            "ovos-adapt-pipeline-plugin-low",
            "fallback_high",
        ]
        sess.blacklisted_pipelines = ["adapt_high"]  # legacy suffixed entry

        with patch.object(svc, "get_pipeline_matcher",
                          wraps=svc.get_pipeline_matcher) as get_matcher:
            result = svc.get_pipeline(session=sess)

        self.assertEqual([matcher[0] for matcher in result], ["fallback_high"])
        get_matcher.assert_called_once_with("fallback_high")

    def test_canonical_suffixed_blacklist_entry_denies_all_tiers_of_the_plugin(self):
        """Same as above but with a canonical (non-legacy) suffixed id."""
        svc = self._svc_with_adapt_fallback()
        sess = Session("s")
        sess.pipeline = [
            "ovos-adapt-pipeline-plugin-high",
            "ovos-adapt-pipeline-plugin-medium",
            "ovos-adapt-pipeline-plugin-low",
            "fallback_high",
        ]
        sess.blacklisted_pipelines = ["ovos-adapt-pipeline-plugin-medium"]

        with patch.object(svc, "get_pipeline_matcher",
                          wraps=svc.get_pipeline_matcher) as get_matcher:
            result = svc.get_pipeline(session=sess)

        self.assertEqual([matcher[0] for matcher in result], ["fallback_high"])
        get_matcher.assert_called_once_with("fallback_high")

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

    def setUp(self):
        # The handlers resolve registry-first (_registry_session_for_context_write),
        # so a leftover real SessionManager.sessions["s"] entry from
        # `Session.touch()`'s self-registration (triggered internally by
        # intent_context writes) would otherwise shadow this test's
        # freshly-constructed, mocked-get `Session("s")` in later tests.
        # Keep the shared singleton clean.
        self._saved_sessions = dict(SessionManager.sessions)
        SessionManager.sessions.clear()

    def tearDown(self):
        SessionManager.sessions.clear()
        SessionManager.sessions.update(self._saved_sessions)

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
        # keyed by the context token and carrying its injected value.
        # Also carries an expires_at decay stamp (see
        # test_handle_add_context_stamps_expiry_on_both_spellings) - only
        # "value" is pinned exactly here, expires_at just needs to be present.
        entry = sess.intent_context.get("MyContext")
        self.assertEqual(entry.get("value"), "myword")
        self.assertIn("expires_at", entry)

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

    def test_handle_add_context_mirrors_resolved_private_key(self):
        """OVOS-CONTEXT-1: when the producer (ovos-workshop's set_context)
        names the original unmunged key via data['key'] and the message
        carries a skill_id, handle_add_context must ALSO write the entry
        under resolve_key(key, 'private', skill_id) so the declarative
        gate - which resolves independently of the legacy munged spelling
        - can see it. Both spellings must coexist."""
        sess = Session("s")
        msg = Message("add_context",
                      data={"context": "my_skillkitchen", "word": "kitchen",
                            "key": "kitchen"},
                      context={"session": sess.serialize(),
                               "skill_id": "my.skill"})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_add_context(msg)
        self.assertIn("my_skillkitchen", sess.intent_context)
        self.assertIn("my.skill:kitchen", sess.intent_context)

    def test_handle_add_context_resolved_value_falls_back_to_original_key(self):
        """When no word is given, the resolved twin's fallback 'value' must
        be the original unmunged key, never the munged legacy context
        string - the munged spelling is an internal ADAPT wire detail and
        must not leak into OVOS-CONTEXT-1 §7 slot injection via the
        resolved entry. Munged context and original key are deliberately
        made to differ so a wrong fallback is caught."""
        sess = Session("s")
        msg = Message("add_context",
                      data={"context": "my_skillkitchen", "key": "kitchen"},
                      context={"session": sess.serialize(),
                               "skill_id": "my.skill"})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_add_context(msg)
        self.assertEqual(sess.intent_context["my.skill:kitchen"]["value"],
                         "kitchen")
        self.assertNotEqual(
            sess.intent_context["my.skill:kitchen"]["value"],
            "my_skillkitchen")

    def test_handle_add_context_refreshes_resolved_expiry_on_reset(self):
        """OVOS-CONTEXT-1 §5: a re-set of a key that already exists
        replaces it wholesale, and §5.3: there is no read-back API for a
        caller to notice a stale expiry survived. A re-set of the resolved
        private key must refresh expires_at unconditionally, not keep
        whatever a prior write established, or the resolved key dies out
        of step with the munged legacy key (which inject_context() always
        refreshes on every call). Without this, the resolved key's
        expires_at stays pinned to the first write."""
        sess = Session("s")
        sess.intent_context = {"my.skill:kitchen": {"value": "old",
                                                     "expires_at": 999999999.0,
                                                     "turns_remaining": 3}}
        msg = Message("add_context",
                      data={"context": "my_skillkitchen", "word": "kitchen",
                            "key": "kitchen"},
                      context={"session": sess.serialize(),
                               "skill_id": "my.skill"})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_add_context(msg)
        entry = sess.intent_context["my.skill:kitchen"]
        self.assertEqual(entry["value"], "kitchen")
        # refreshed, not preserved: the old immortal-looking 999999999.0
        # stamp and the stale turns_remaining must both be gone
        self.assertNotEqual(entry.get("expires_at"), 999999999.0)
        self.assertNotIn("turns_remaining", entry)

    def test_handle_add_context_stamps_expiry_on_both_spellings(self):
        """A fresh add_context call must stamp expires_at on BOTH the
        munged legacy key and the resolved private key, sourced from the
        same adapt `context.timeout` config convention ovos-bus-client's
        `_IntentContextView` uses (`Configuration()['context']['timeout']`,
        minutes -> seconds, default 2min). Without a decay field,
        OVOS-CONTEXT-1's `is_live()` treats an entry as immortal and
        `prune()` can never reap it."""
        import time
        from ovos_config.config import Configuration
        sess = Session("s")
        msg = Message("add_context",
                      data={"context": "my_skillkitchen", "word": "kitchen",
                            "key": "kitchen"},
                      context={"session": sess.serialize(),
                               "skill_id": "my.skill"})
        before = time.time()
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_add_context(msg)
        after = time.time()
        timeout_s = Configuration().get('context', {}).get('timeout', 2) * 60

        munged = sess.intent_context["my_skillkitchen"]
        resolved = sess.intent_context["my.skill:kitchen"]
        for entry in (munged, resolved):
            self.assertIn("expires_at", entry)
            self.assertGreaterEqual(entry["expires_at"], before + timeout_s)
            self.assertLessEqual(entry["expires_at"], after + timeout_s)

    def test_handle_add_context_prune_removes_both_spellings_after_expiry(self):
        """ovos_spec_tools.context.prune() must be able to reap BOTH
        dialect keys once their stamped expires_at is in the past - proving
        the decay stamp is real (§4 pre-match pruning), not just present."""
        from ovos_spec_tools.context import prune
        sess = Session("s")
        msg = Message("add_context",
                      data={"context": "my_skillkitchen", "word": "kitchen",
                            "key": "kitchen"},
                      context={"session": sess.serialize(),
                               "skill_id": "my.skill"})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_add_context(msg)
        self.assertIn("my_skillkitchen", sess.intent_context)
        self.assertIn("my.skill:kitchen", sess.intent_context)

        # simulate expiry: prune() at a "now" far past both stamps
        far_future = 99999999999.0
        pruned = prune(dict(sess.intent_context), now=far_future)
        self.assertNotIn("my_skillkitchen", pruned)
        self.assertNotIn("my.skill:kitchen", pruned)

    def test_handle_add_context_does_not_double_clobber_injected_expiry(self):
        """`sess.context.inject_context()` (ovos-bus-client's legacy
        `_IntentContextView`) always stamps a fresh `expires_at` on every
        call, out of this handler's control. What this handler must not do
        is throw that freshly-injected stamp away a second time with its
        own bare-dict overwrite. Assert the handler's own write preserves
        exactly what inject_context() just wrote for the munged key (no
        extra clobber)."""
        sess = Session("s")
        entity = {"confidence": 1.0, "data": [("kitchen", "my_skillkitchen")],
                  "match": "kitchen", "key": "kitchen", "origin": ""}
        sess.context.inject_context(entity)
        injected_entry = dict(sess.intent_context["my_skillkitchen"])
        self.assertIn("expires_at", injected_entry)  # sanity: inject_context did stamp

        msg = Message("add_context",
                      data={"context": "my_skillkitchen", "word": "kitchen"},
                      context={"session": sess.serialize(),
                               "skill_id": "my.skill"})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_add_context(msg)
        entry = sess.intent_context["my_skillkitchen"]
        self.assertEqual(entry["value"], "kitchen")
        # the handler's own write must not have moved expires_at backwards
        # or dropped it - it must be >= what was already stamped
        self.assertIn("expires_at", entry)
        self.assertGreaterEqual(entry["expires_at"], injected_entry["expires_at"])

    def test_handle_add_context_e2e_reachability_unaffected_by_decay_stamp(self):
        """The decay stamp must not break immediate gating - a
        freshly-opened OVOS-CONTEXT-1 gate must still be satisfied right
        after set_context, decay or no decay."""
        from ovos_spec_tools.context import gate_satisfied
        sess = Session("s")
        msg = Message("add_context",
                      data={"context": "my_skillkitchen", "word": "kitchen",
                            "key": "kitchen"},
                      context={"session": sess.serialize(),
                               "skill_id": "my.skill"})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_add_context(msg)
        self.assertTrue(gate_satisfied(sess.intent_context, ["kitchen"], [],
                                       owner_id="my.skill"))

    def test_handle_add_context_reset_refreshes_both_keys_in_lockstep(self):
        """One decay policy for a logical write. A skill re-calling
        set_context (a second handle_add_context for the SAME context/key,
        e.g. re-affirming context mid-conversation) must refresh expires_at
        on BOTH the munged legacy key and the resolved private key
        together. Without a unified refresh, the resolved key's expires_at
        stays pinned to t0 + timeout instead of being refreshed to
        t0 + 100 + timeout, so this assertion fails because prune() at
        t0+150 reaps the resolved key but not the munged key."""
        from ovos_spec_tools.context import prune

        sess = Session("s")
        msg_kwargs = dict(
            data={"context": "my_skillkitchen", "word": "kitchen",
                  "key": "kitchen"},
            context={"session": sess.serialize(), "skill_id": "my.skill"})

        t0 = 1_000_000.0
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess), \
             patch("ovos_core.intent_services.service.time.time",
                   return_value=t0):
            IntentService.handle_add_context(Message("add_context", **msg_kwargs))

        first_munged = sess.intent_context["my_skillkitchen"]["expires_at"]
        first_resolved = sess.intent_context["my.skill:kitchen"]["expires_at"]

        # re-set the SAME context/key 100s later
        t1 = t0 + 100.0
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess), \
             patch("ovos_core.intent_services.service.time.time",
                   return_value=t1):
            IntentService.handle_add_context(Message("add_context", **msg_kwargs))

        second_munged = sess.intent_context["my_skillkitchen"]["expires_at"]
        second_resolved = sess.intent_context["my.skill:kitchen"]["expires_at"]

        # both keys must have refreshed by the same delta - one policy
        self.assertGreater(second_munged, first_munged)
        self.assertGreater(second_resolved, first_resolved)
        self.assertEqual(second_munged, second_resolved)

        # neither key may be reaped by a prune() 150s after the FIRST
        # write, since BOTH were refreshed by the re-set at t0+100
        pruned = prune(dict(sess.intent_context), now=t0 + 150.0)
        self.assertIn("my_skillkitchen", pruned)
        self.assertIn("my.skill:kitchen", pruned)

    def test_handle_remove_context_removes_both_spellings(self):
        """Symmetric with add: removing must drop both the legacy munged
        key and the resolved private-scope key."""
        sess = Session("s")
        sess.intent_context = {"my_skillkitchen": {"value": "kitchen"},
                               "my.skill:kitchen": {"value": "kitchen"}}
        entity = {"confidence": 1.0, "data": [("kitchen", "my_skillkitchen")],
                  "match": "kitchen", "key": "kitchen", "origin": ""}
        sess.context.inject_context(entity)
        msg = Message("remove_context",
                      data={"context": "my_skillkitchen", "key": "kitchen"},
                      context={"session": sess.serialize(),
                               "skill_id": "my.skill"})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_remove_context(msg)
        self.assertNotIn("my_skillkitchen", sess.intent_context or {})
        self.assertNotIn("my.skill:kitchen", sess.intent_context or {})

    def test_handle_add_context_idempotent_on_repeated_identical_write(self):
        """CONTEXT-1 §5.0 (architecture#161): `add_context` is a
        LEGACY-COMPAT input path, not a spec write path - the session is
        the only one. A modern emitter writes `session.intent_context`
        directly first; this legacy handler may ALSO be invoked for the
        exact same key/value (dual-write compat window, or an old-core
        replay). Re-applying the identical key+value here must be a
        no-op / identical-value refresh, never a double-decay (stacking
        turns_remaining) or a double-refresh (accumulating frames/entries)
        on top of what the direct session write already carried."""
        sess = Session("s")
        # simulate the direct session write a modern producer performs
        # BEFORE the legacy compat message is also processed
        sess.intent_context = {"my.skill:kitchen": {"value": "kitchen"}}
        msg = Message("add_context",
                      data={"context": "my_skillkitchen", "word": "kitchen",
                            "key": "kitchen"},
                      context={"session": sess.serialize(),
                               "skill_id": "my.skill"})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_add_context(msg)
        first_entry = dict(sess.intent_context["my.skill:kitchen"])
        first_frame_count = len(sess.context.frame_stack)
        first_key_count = len(sess.intent_context)

        # re-apply the SAME message data a second time (e.g. a duplicate
        # delivery, or a second producer emitting the identical compat
        # message for the same logical write)
        msg2 = Message("add_context",
                       data={"context": "my_skillkitchen", "word": "kitchen",
                             "key": "kitchen"},
                       context={"session": sess.serialize(),
                                "skill_id": "my.skill"})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_add_context(msg2)
        second_entry = sess.intent_context["my.skill:kitchen"]

        # value is identical - no double-decay, no drift
        self.assertEqual(first_entry["value"], second_entry["value"])
        # a legitimate refresh recomputes `now + timeout_s` fresh on every
        # write; it must NOT stack a second decay on top of the prior
        # expiry (e.g. `max(prior_expires_at, now) + timeout_s`, which is
        # `assertGreaterEqual`-compatible with a single refresh but drifts
        # further from "now" with every repeated identical write). Pin the
        # second write's expires_at to a tight tolerance window around
        # `now + timeout_s` computed here, so a compounded/stacked expiry
        # (which lands measurably later, growing per second) fails.
        context_cfg = Configuration().get('context', {})
        timeout_s = context_cfg.get('timeout', 2) * 60
        expected_expires_at = time.time() + timeout_s
        self.assertAlmostEqual(second_entry.get("expires_at", 0),
                                expected_expires_at, delta=2)
        # no duplicate keys and no duplicate legacy frames accumulated -
        # `sess.context` is a derived projection over `intent_context`
        # (one frame per live entry), not a persisted stack, so its count
        # must stay stable across the repeated identical write, whatever
        # its baseline value is (both the munged and resolved spellings
        # legitimately coexist as separate entries/frames by design).
        self.assertEqual(len(sess.intent_context), first_key_count)
        self.assertEqual(len(sess.context.frame_stack), first_frame_count)

    def test_handle_remove_context_idempotent_on_repeated_identical_removal(self):
        """Symmetric with the add-context idempotency test: re-applying an
        identical legacy `remove_context` compat message after the session
        already carries the tombstone (or after a direct session removal)
        is a no-op, not an error and not a double-removal artifact."""
        sess = Session("s")
        sess.intent_context = {"my_skillkitchen": {"value": "kitchen"},
                               "my.skill:kitchen": {"value": "kitchen"}}
        entity = {"confidence": 1.0, "data": [("kitchen", "my_skillkitchen")],
                  "match": "kitchen", "key": "kitchen", "origin": ""}
        sess.context.inject_context(entity)
        msg = Message("remove_context",
                      data={"context": "my_skillkitchen", "key": "kitchen"},
                      context={"session": sess.serialize(),
                               "skill_id": "my.skill"})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_remove_context(msg)
        self.assertNotIn("my_skillkitchen", sess.intent_context or {})
        self.assertNotIn("my.skill:kitchen", sess.intent_context or {})
        # both known keys were the entirety of the map - nothing should
        # remain (leaked/accumulated keys, e.g. an internal bookkeeping
        # entry, would slip past a two-key-only NotIn check)
        self.assertFalse(sess.intent_context)

        # re-apply the identical removal a second time - must not raise
        # and must leave the (already-clean) state unchanged
        msg2 = Message("remove_context",
                       data={"context": "my_skillkitchen", "key": "kitchen"},
                       context={"session": sess.serialize(),
                                "skill_id": "my.skill"})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_remove_context(msg2)
        self.assertNotIn("my_skillkitchen", sess.intent_context or {})
        self.assertNotIn("my.skill:kitchen", sess.intent_context or {})
        self.assertFalse(sess.intent_context)

    def test_handle_add_context_no_key_stores_only_munged_legacy(self):
        """Back-compat pin: a message with no data['key'] (old-workshop /
        legacy ADAPT-only caller) must store ONLY the munged legacy key -
        no regression in the no-key path."""
        sess = Session("s")
        msg = Message("add_context",
                      data={"context": "my_skillkitchen", "word": "kitchen"},
                      context={"session": sess.serialize(),
                               "skill_id": "my.skill"})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            IntentService.handle_add_context(msg)
        self.assertIn("my_skillkitchen", sess.intent_context)
        self.assertNotIn("my.skill:kitchen", sess.intent_context)
        self.assertEqual(len(sess.intent_context), 1)


class TestContextHandlersLiveRegistry(unittest.TestCase):
    """FOLD LAW (see IntentService._registry_session_for_context_write,
    SESSION-2 §2.6): a message's session snapshot folds onto the live
    registry session only at lifecycle entry, never on an incidental
    mid-lifecycle message. `SessionManager.get(message)` folds unconditionally,
    and for NAMED sessions that fold is full-replace (`update_from`), so an
    incidental fold wipes the registry entry's intent_context with a stale
    snapshot - a named session's context can never survive to the terminal
    event.

    These tests exercise the REAL SessionManager.sessions registry (no
    mocking of SessionManager.get) so they fail against an unconditional
    every-call fold.
    """

    def setUp(self):
        self._saved_sessions = dict(SessionManager.sessions)
        SessionManager.sessions.clear()

    def tearDown(self):
        SessionManager.sessions.clear()
        SessionManager.sessions.update(self._saved_sessions)

    def test_add_context_survives_stale_message_snapshot_fold(self):
        """A registry entry's pre-existing intent_context must survive a
        handle_add_context call driven by a message carrying a STALE
        session snapshot (no knowledge of the pre-existing entry) - the
        write must land on the LIVE registry object, not a folded copy."""
        sess = Session("named-r4")
        sess.intent_context = {"Existing": {"value": "existing"}}
        SessionManager.sessions[sess.session_id] = sess

        stale = Session(sess.session_id)  # unaware of "Existing"
        msg = Message("add_context",
                      data={"context": "New", "word": "newword"},
                      context={"session": stale.serialize()})

        IntentService.handle_add_context(msg)

        live = SessionManager.sessions[sess.session_id]
        self.assertIn("Existing", live.intent_context)
        self.assertIn("New", live.intent_context)

    def test_add_context_accumulates_across_two_stale_calls(self):
        """Two handle_add_context calls, each driven by a message with its
        own stale snapshot (mirroring successive mid-lifecycle frames),
        must both survive on the live registry entry."""
        sess = Session("named-r4-2")
        SessionManager.sessions[sess.session_id] = sess

        stale1 = Session(sess.session_id)
        msg1 = Message("add_context",
                       data={"context": "First", "word": "one"},
                       context={"session": stale1.serialize()})
        IntentService.handle_add_context(msg1)

        stale2 = Session(sess.session_id)
        msg2 = Message("add_context",
                       data={"context": "Second", "word": "two"},
                       context={"session": stale2.serialize()})
        IntentService.handle_add_context(msg2)

        live = SessionManager.sessions[sess.session_id]
        self.assertIn("First", live.intent_context)
        self.assertIn("Second", live.intent_context)

    def test_add_context_survives_stale_default_session_snapshot_fold(self):
        """The registry-first fix is load-bearing for the DEVICE-LOCAL
        DEFAULT session too, not only named sessions: `Session.update_from`
        round-trips through full serialize/deserialize for every session
        id, including "default", so it does not preserve omitted fields for
        the default id either. A registry "default" entry's pre-existing
        context must survive a handle_add_context call driven by a message
        carrying a STALE default-session snapshot, exactly like the
        named-session case above."""
        sess = Session(DEFAULT_SESSION_ID)
        sess.intent_context = {"Existing": {"value": "existing"}}
        SessionManager.sessions[DEFAULT_SESSION_ID] = sess

        stale = Session(DEFAULT_SESSION_ID)  # unaware of "Existing"
        msg = Message("add_context",
                      data={"context": "New", "word": "newword"},
                      context={"session": stale.serialize()})

        IntentService.handle_add_context(msg)

        live = SessionManager.sessions[DEFAULT_SESSION_ID]
        self.assertIn("Existing", live.intent_context)
        self.assertIn("New", live.intent_context)


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

    def test_cancelled_event_carries_cancel_reason_and_cancel_by(self):
        """OVOS-TRANSFORM-1 §8.2: ovos.utterance.cancelled surfaces the
        cancel_reason and orchestrator-stamped cancel_by from the §8.1
        signal that triggered the cancellation."""
        svc = _make_service()
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)
        msg = Message("test", data={},
                      context={"cancel_word": "stop",
                               "cancel_reason": "user requested stop",
                               "cancel_by": "some_transformer"})
        with patch("ovos_core.intent_services.service.Configuration",
                   return_value={}):
            svc.send_cancel_event(msg)
        cancelled = next(m for m in emitted
                         if m.msg_type == "ovos.utterance.cancelled")
        self.assertEqual(cancelled.data.get("cancel_reason"), "user requested stop")
        self.assertEqual(cancelled.data.get("cancel_by"), "some_transformer")

    def test_cancelled_event_omits_absent_cancel_fields(self):
        """When cancel_reason/cancel_by are absent from context, they are
        omitted from the emitted data rather than surfaced as None."""
        svc = _make_service()
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)
        msg = Message("test", data={}, context={"cancel_word": "stop"})
        with patch("ovos_core.intent_services.service.Configuration",
                   return_value={}):
            svc.send_cancel_event(msg)
        cancelled = next(m for m in emitted
                         if m.msg_type == "ovos.utterance.cancelled")
        self.assertNotIn("cancel_reason", cancelled.data)
        self.assertNotIn("cancel_by", cancelled.data)


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

    def test_blacklisted_targeted_stop_discards_match_session_unchanged(self):
        """A Match discarded for a blacklisted intent
        (service.py ~607) must never have applied its session mutation. Before
        the fix, StopService._targeted_stop drained the LIVE SessionManager
        session in match() itself, so a discarded stop still left the skill
        deactivated with nothing dispatched — this test fails on that
        unfixed behaviour (active_handlers would come back empty)."""
        from ovos_core.intent_services.stop_service import StopService

        bus = FakeBus()
        svc = _make_service()
        svc.bus = bus
        svc.send_complete_intent_failure = MagicMock()

        stop_svc = StopService.__new__(StopService)
        stop_svc.bus = bus
        stop_svc.config = {}
        stop_svc.suppress_activation = True
        stop_svc._locale = MagicMock()
        stop_svc._locale.voc_match.side_effect = (
            lambda utt, voc, lang, exact=False: voc == "stop")
        stop_svc._legacy = MagicMock()
        stop_svc._pre_drain = {}

        sess = Session("s")
        sess.activate_skill("skill_a")
        sess.pipeline = ["ovos-stop-pipeline-plugin-high"]
        sess.blacklisted_intents = ["skill_a:stop"]
        before = list(sess.active_handlers)

        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["stop"]},
                      context={})

        with patch.object(svc, "get_pipeline",
                          return_value=[("ovos-stop-pipeline-plugin", stop_svc.match_high)]), \
             patch.object(stop_svc, "_collect_stop_skills", return_value=["skill_a"]), \
             patch("ovos_core.intent_services.service.SessionManager.get",
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

        # the match was discarded (blacklisted) — no dispatch, and the live
        # session's active_handlers must be exactly as before.
        self.assertEqual(sess.active_handlers, before)
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

    def _dispatch(self, pipeline_id, suppress_activation=False):
        svc = _make_service()
        sess = Session("s1")
        msg = Message("recognizer_loop:utterance", {"utterances": ["hi"]},
                      {"session": sess.serialize()})
        match = _make_match(match_type="test.skill:intent",
                            skill_id="test.skill", session=sess)
        match.suppress_activation = suppress_activation
        svc._dispatch_match(match, msg, "en-US", pipeline_id=pipeline_id)
        return sess

    def test_regular_pipeline_pushes_active_handler(self):
        sess = self._dispatch("ovos-adapt-pipeline-plugin-high")
        ids = [h.get("skill_id") if isinstance(h, dict) else getattr(h, "skill_id", h)
               for h in sess.active_handlers]
        self.assertIn("test.skill", ids)

    def test_reserved_name_pipeline_suppresses_push(self):
        # §7.3: converse/fallback/common_query dispatches must NOT push
        for pid in ("ovos-converse-pipeline-plugin",
                    "ovos-fallback-pipeline-plugin-medium",
                    "ovos-common-query-pipeline-plugin"):
            sess = self._dispatch(pid)
            ids = [h.get("skill_id") if isinstance(h, dict) else getattr(h, "skill_id", h)
                   for h in sess.active_handlers]
            self.assertNotIn("test.skill", ids, f"{pid} should suppress the push")

    def test_suppress_activation_match_suppresses_push(self):
        # OVOS-STOP-1 §6.2/§7.3: a Match.suppress_activation dispatch (a stop)
        # must NOT push onto active_handlers regardless of its pipeline_id.
        sess = self._dispatch("ovos-adapt-pipeline-plugin-high",
                              suppress_activation=True)
        ids = [h.get("skill_id") if isinstance(h, dict) else getattr(h, "skill_id", h)
               for h in sess.active_handlers]
        self.assertNotIn("test.skill", ids)


class TestProducesReservedName(unittest.TestCase):

    def test_reserved_roles_true_with_confidence_suffix(self):
        from ovos_core.intent_services.service import _produces_reserved_name
        self.assertTrue(_produces_reserved_name("ovos-converse-pipeline-plugin"))
        self.assertTrue(_produces_reserved_name("ovos-fallback-pipeline-plugin-low"))

    def test_stop_role_not_in_reserved_table(self):
        # STOP-1 expresses suppression per-Match (suppress_activation), so the
        # stop pipeline is intentionally absent from the reserved-name table.
        from ovos_core.intent_services.service import _produces_reserved_name
        self.assertFalse(_produces_reserved_name("ovos-stop-pipeline-plugin-high"))

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
    def test_blacklisted_plugin_still_in_active_pipeline_warns_legacy_matcher_id(
            self, mock_factory, mock_log):
        # `intents.pipeline` may list legacy matcher ids (eg "adapt_high")
        # instead of the installed plugin id; the warning must still fire
        # when the blacklisted plugin backs that legacy matcher id
        # (CodeRabbit review, ovos-core#832).
        mock_factory.get_installed_pipeline_ids.return_value = [
            "ovos-adapt-pipeline-plugin",
        ]
        mock_factory.load_plugin.side_effect = lambda p, bus=None: MagicMock(name=p)

        svc = _make_service(config={
            "blacklisted_pipelines": ["ovos-adapt-pipeline-plugin"],
            "pipeline": ["adapt_high"],
        })
        svc.handle_reload_pipelines(Message("intent.service.pipelines.reload"))

        self.assertNotIn("ovos-adapt-pipeline-plugin", svc.pipeline_plugins)
        self.assertTrue(mock_log.warning.called)
        warned = " ".join(str(c) for c in mock_log.warning.call_args_list)
        self.assertIn("ovos-adapt-pipeline-plugin", warned)

    @patch("ovos_core.intent_services.service.LOG")
    @patch("ovos_core.intent_services.service.OVOSPipelineFactory")
    def test_blacklisted_plugin_logs_skip_info(self, mock_factory, mock_log):
        mock_factory.get_installed_pipeline_ids.return_value = ["ovos-m2v-pipeline"]

        svc = _make_service(config={"blacklisted_pipelines": ["ovos-m2v-pipeline"]})
        svc.handle_reload_pipelines(Message("intent.service.pipelines.reload"))

        self.assertFalse(mock_factory.load_plugin.called)
        info_calls = " ".join(str(c) for c in mock_log.info.call_args_list)
        self.assertIn("ovos-m2v-pipeline", info_calls)


class TestUploadMatchData(unittest.TestCase):
    """The intent-metrics payload carries the session pipeline and core version."""

    def _post_payload(self, pipeline):
        captured = {}

        def _fake_post(url, data=None, headers=None, timeout=None):
            captured.update(data)
            return MagicMock(status_code=200)

        cfg = {"open_data": {"intent_urls": ["http://localhost:8000/intents"]}}
        with patch("ovos_core.intent_services.service.Configuration",
                   return_value=cfg), \
                patch("ovos_core.intent_services.service.requests.post",
                      side_effect=_fake_post):
            IntentService._upload_match_data(
                "turn on the lights", "test:intent", "en-US",
                {"skill_id": "test.skill"}, pipeline)
        return captured

    def test_pipeline_joined_into_payload(self):
        captured = self._post_payload(["adapt_high", "padatious_high"])
        self.assertEqual(captured["pipeline"], "adapt_high|padatious_high")

    def test_core_version_in_payload(self):
        from ovos_core.version import OVOS_VERSION_STR
        captured = self._post_payload(["adapt_high"])
        self.assertEqual(captured["core_version"], OVOS_VERSION_STR)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# OVOS-PIPELINE-1 §9.1.1 — the lifecycle identifier
# ---------------------------------------------------------------------------

class TestUtteranceIdStamp(unittest.TestCase):
    """The orchestrator names each utterance lifecycle exactly once."""

    def test_entry_message_gets_an_identifier(self):
        """A Message arriving without one is stamped with a non-empty value."""
        msg = Message("test", {"utterances": ["hello"]})
        uid = IntentService._stamp_utterance_id(msg)
        self.assertTrue(uid)
        self.assertIsInstance(uid, str)
        self.assertEqual(msg.context["utterance_id"], uid)

    def test_two_lifecycles_get_different_identifiers(self):
        """The value is unique per lifecycle."""
        a = IntentService._stamp_utterance_id(Message("test"))
        b = IntentService._stamp_utterance_id(Message("test"))
        self.assertNotEqual(a, b)

    def test_existing_identifier_is_never_overwritten(self):
        """A component that opened the lifecycle out of band already stamped."""
        msg = Message("test", {}, {"utterance_id": "opened-elsewhere"})
        uid = IntentService._stamp_utterance_id(msg)
        self.assertEqual(uid, "opened-elsewhere")
        self.assertEqual(msg.context["utterance_id"], "opened-elsewhere")

    def test_derived_messages_carry_the_identifier(self):
        """`reply` and `forward` deep-copy context, so propagation is free."""
        msg = Message("test", {"utterances": ["hello"]})
        uid = IntentService._stamp_utterance_id(msg)
        self.assertEqual(msg.reply("x").context["utterance_id"], uid)
        self.assertEqual(msg.forward("y").context["utterance_id"], uid)
        self.assertEqual(
            msg.forward("y").reply("z").context["utterance_id"], uid)

    def test_transformer_chain_cannot_detach_the_lifecycle(self):
        """The transformer chain REPLACES message.context wholesale.

        A transformer plugin that returns a fresh dict would otherwise strip
        the identifier and orphan every Message derived after it.
        """
        svc = _make_service()
        svc.send_complete_intent_failure = MagicMock()
        sess = Session("s")
        sess.pipeline = []
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["hello"]}, context={})

        def nuke_context(m):
            m.context = {"lang": "en-US"}  # fresh dict, identifier gone
            return m

        with patch.object(svc, "_handle_transformers", side_effect=nuke_context), \
             patch("ovos_core.intent_services.service.SessionManager.get",
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

        self.assertTrue(msg.context.get("utterance_id"))
