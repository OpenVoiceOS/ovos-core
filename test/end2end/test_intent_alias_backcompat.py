"""End-to-end back-compat coverage for the INTENT-4 register-time alias
collapse (ovos-padatious 2.0.1a1 / padacioso 2.2.2a1) and workshop dual-bind
(ovos-workshop 9.3.2a1, see ovos-workshop#497).

``test_padatious.py`` now asserts the pipeline reports the CANONICAL
suffix-less intent id (``<skill_id>:<file>``) on the wire. That is correct per
OVOS-PIPELINE-1 §5.4, but nothing proves the LEGACY ``.intent``-suffixed
surfaces — which ovos-core#831 explicitly promises to keep working during the
migration window — still function. This file closes that gap:

- ``test_legacy_blacklist_id_suppresses``: a session ``blacklisted_intents``
  entry using the legacy ``<skill_id>:<file>.intent`` id must still suppress
  the intent (the padatious/padacioso engines canonicalize the blacklist at
  match time — see ``_canonicalize_blacklist`` in ``ovos_padatious.opm``) and
  must log a one-time deprecation warning pointing at the canonical
  replacement.
- ``test_legacy_dispatch_topic_fires_handler``: emitting the legacy
  ``<skill_id>:<file>.intent`` bus topic directly still fires the skill
  handler, because ``register_intent_file`` binds both the legacy and
  canonical names (ovos_workshop.skills.ovos.OVOSSkill.register_intent_file).

Both are exercised on both bus namespaces (spec / legacy), matching the
parametrization style of ``test_padatious.py``.
"""
from unittest import TestCase
from unittest.mock import patch
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_padatious import opm as padatious_opm
from ovos_spec_tools import SpecMessage, migration_counterpart
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft

SPEC_UTTERANCE = SpecMessage.UTTERANCE.value
LEGACY_UTTERANCE = migration_counterpart(SPEC_UTTERANCE)
SPEC_SPEAK = SpecMessage.SPEAK.value
UTTERANCE_HANDLED = SpecMessage.UTTERANCE_HANDLED.value
INTENT_UNMATCHED = SpecMessage.INTENT_UNMATCHED.value
HANDLER_START = SpecMessage.INTENT_HANDLER_START.value
HANDLER_COMPLETE = SpecMessage.INTENT_HANDLER_COMPLETE.value

NAMESPACE_PATHS = {
    "spec": (False, False, SPEC_UTTERANCE),
    "legacy": (True, False, LEGACY_UTTERANCE),
}


class TestLegacyIntentIdBackCompat(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-hello-world.openvoiceos"
        self._reset_padatious_caches()

    def tearDown(self):
        LOG.set_level("CRITICAL")
        self._reset_padatious_caches()

    @staticmethod
    def _reset_padatious_caches():
        # the one-time-warning dedup set is process-global; clear it so each
        # subtest observes its own deprecation warning instead of inheriting
        # suppression from a prior subtest/run. ``_calc_padatious_intent`` is
        # ``lru_cache``d and a cache hit skips ``_canonicalize_blacklist``
        # entirely (no warning call at all), so the match cache must also be
        # cleared or a cached hit from an earlier subtest silently swallows
        # the warning this test asserts on.
        padatious_opm._warned_legacy_blacklist_entries.clear()
        padatious_opm._calc_padatious_intent.cache_clear()

    def _run_legacy_blacklist(self, namespace):
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id], modernize=modernize,
                                  emit_legacy=emit_legacy)
        try:
            session = Session("123")
            session.lang = "en-US"
            session.pipeline = ["ovos-padatious-pipeline-plugin-high"]
            # LEGACY id: the pre-INTENT-4 `.intent`-suffixed identity. Engine
            # matches are canonical by construction (register-time alias
            # collapse), so the engine must dealias this before comparing —
            # see ovos_padatious.opm._canonicalize_blacklist.
            legacy_intent_id = f"{self.skill_id}:Greetings.intent"
            session.blacklisted_intents = [legacy_intent_id]
            message = Message(utt_topic,
                              {"utterances": ["good morning"], "lang": session.lang},
                              {"session": session.serialize(), "source": "A", "destination": "B"})

            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[self.skill_id],
                flip_points=[utt_topic],
                entry_points=[utt_topic],
                source_message=message,
                final_session=session,
                expected_messages=[
                    message,
                    Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                    Message(INTENT_UNMATCHED, {}),
                    Message(UTTERANCE_HANDLED, {})
                ]
            )

            # the intent must still be suppressed (legacy id compat) AND a
            # one-time deprecation warning logged pointing at the canonical
            # id. ovos_utils.log.LOG builds a per-callsite logger with
            # propagate=False (see create_logger), so stdlib assertLogs
            # cannot observe it — patch the LOG.warning classmethod used by
            # ovos_padatious.opm instead and inspect the calls it recorded.
            with patch.object(padatious_opm.LOG, "warning") as mock_warning:
                test.execute(timeout=10)
            warnings = "\n".join(
                str(a) for call in mock_warning.call_args_list for a in call.args)
            self.assertIn(legacy_intent_id, warnings)
            self.assertIn(f"{self.skill_id}:Greetings", warnings)
        finally:
            minicroft.stop()

    def test_legacy_blacklist_id_suppresses(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._reset_padatious_caches()
                self._run_legacy_blacklist(namespace)

    def _run_legacy_dispatch_topic(self, namespace):
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id], modernize=modernize,
                                  emit_legacy=emit_legacy)
        try:
            session = Session("123")
            session.lang = "en-US"

            # LEGACY dispatch: bypass intent matching entirely and emit
            # directly on the pre-INTENT-4 `<skill_id>:<file>.intent` topic.
            # ovos_workshop.skills.ovos.OVOSSkill.register_intent_file binds
            # the skill handler under BOTH the legacy and canonical names
            # (ovos-workshop#497), so this must still fire the handler.
            legacy_intent_topic = f"{self.skill_id}:Greetings.intent"
            message = Message(legacy_intent_topic,
                              {"utterance": "good morning", "lang": session.lang},
                              {"session": session.serialize(), "source": "A", "destination": "B"})

            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[self.skill_id],
                # a raw direct injection on the legacy intent topic (bypassing
                # the orchestrator/pipeline entirely) does not flip
                # source/destination the way a routed utterance->dispatch
                # cycle does, so no flip/entry points are declared here — the
                # generic source/destination routing check then compares
                # every message against the injected message's own (A, B),
                # which is what a raw dual-bound handler dispatch preserves.
                ignore_messages=["recognizer_loop:audio_output_start",
                                  "recognizer_loop:audio_output_end"],
                source_message=message,
                final_session=session,
                expected_messages=[
                    message,
                    Message("mycroft.skill.handler.start",
                            data={"name": "HelloWorldSkill.handle_greetings"},
                            context={"skill_id": self.skill_id}),
                    Message(SPEC_SPEAK,
                            data={"expect_response": False,
                                  "meta": {
                                      "dialog": "hello",
                                      "data": {},
                                      "skill": self.skill_id
                                  }},
                            context={"skill_id": self.skill_id}),
                    Message("mycroft.skill.handler.complete",
                            data={"name": "HelloWorldSkill.handle_greetings"},
                            context={"skill_id": self.skill_id}),
                ]
            )

            test.execute(timeout=10)
        finally:
            minicroft.stop()

    def test_legacy_dispatch_topic_fires_handler(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_legacy_dispatch_topic(namespace)
