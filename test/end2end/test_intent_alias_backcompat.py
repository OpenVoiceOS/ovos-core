"""End-to-end coverage for the two legacy ``.intent``-suffixed intent
surfaces: one that still works, one that is now gone.

``test_padatious.py`` asserts the pipeline reports the CANONICAL suffix-less
intent id (``<skill_id>:<file>``) on the wire, per OVOS-PIPELINE-1 §5.4. This
file pins what happens to a caller that still uses the old spelling.

- ``test_legacy_blacklist_id_suppresses``: a session ``blacklisted_intents``
  entry using the legacy ``<skill_id>:<file>.intent`` id must STILL suppress
  the intent, with a one-time deprecation warning pointing at the canonical
  replacement. This is engine-side compat inside ovos-padatious
  (``_canonicalize_blacklist`` in ``ovos_padatious.opm``), not bus compat, so
  the wire kill-switch leaves it alone.

- ``test_legacy_dispatch_topic_reaches_nothing``: emitting the legacy
  ``<skill_id>:<file>.intent`` bus topic reaches NOBODY. It used to fire the
  handler two ways, and both are gone — ovos-workshop bound the handler under
  both spellings (ovos-workshop#497, dropped by ovos-workshop#500), and the
  bus mirrored a canonical dispatch onto the suffixed twin (bus-client#271,
  dropped by the kill-switch).
"""
import time
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
                    Message(SpecMessage.AUDIO_PLAY_SOUND, {"uri": "snd/error.mp3"}),
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
        """The legacy suffixed dispatch topic must reach nothing.

        Two things used to make it work and both are gone: ovos-workshop
        bound the handler under the legacy AND the canonical name
        (ovos-workshop#497, dropped by ovos-workshop#500), and the bus
        mirrored a canonical dispatch onto the suffixed twin
        (bus-client#271, dropped by the kill-switch). Emitting the old
        spelling now reaches nobody.
        """
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id], modernize=modernize,
                                  emit_legacy=emit_legacy)
        try:
            session = Session("123")
            session.lang = "en-US"
            legacy_intent_topic = f"{self.skill_id}:Greetings.intent"
            canonical_intent_topic = f"{self.skill_id}:Greetings"

            # nothing is bound to the old spelling any more
            self.assertEqual(minicroft.bus.ee.listeners(legacy_intent_topic), [])
            self.assertNotEqual(
                minicroft.bus.ee.listeners(canonical_intent_topic), [])

            seen = []
            minicroft.bus.on(SPEC_SPEAK, lambda m: seen.append(m.msg_type))
            minicroft.bus.on("mycroft.skill.handler.start",
                             lambda m: seen.append(m.msg_type))

            minicroft.bus.emit(Message(
                legacy_intent_topic,
                {"utterance": "good morning", "lang": session.lang},
                {"session": session.serialize(), "source": "A",
                 "destination": "B"}))
            time.sleep(1)
            self.assertEqual(seen, [])
        finally:
            minicroft.stop()

    def test_legacy_dispatch_topic_reaches_nothing(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_legacy_dispatch_topic(namespace)
