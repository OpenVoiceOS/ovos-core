"""End-to-end back-compat coverage for the INTENT-4 register-time alias
collapse (ovos-padatious 2.0.1a1 / padacioso 2.2.2a1) and the canonical <->
legacy intent DISPATCH topic bridge (``ovos_spec_tools.intent_topics``,
carried by ``ovos-utils`` >= 0.13.10a1 and ``ovos-bus-client``).

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
- ``test_legacy_dispatch_topic_fires_handler``: current ``ovos-workshop``
  (>= 9.3.11a2) registers a skill's intent handler on the CANONICAL dispatch
  topic only — it no longer dual-binds both spellings. What now reaches a
  handler from a legacy ``.intent``-suffixed emission is the bus's own
  receive-side bridge: a ``FakeBus``/``MessageBusClient`` with the namespace
  ``modernize`` flag on re-dispatches any suffixed intent topic it sees onto
  its canonical twin (RULE 2 in ``FakeBus._bridge_intent_topic`` /
  ``MessageBusClient._modernize_intent_topic``). With ``modernize`` off — the
  "spec" namespace below — that bridge does not run, and OVOS-PIPELINE-1 §4
  only obliges a canonical-only skill to listen on the canonical topic, so a
  raw legacy-suffixed emission is expected to reach nobody.

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
            # Current ovos-workshop registers the skill handler on the
            # CANONICAL topic ONLY (no dual-bind). Whether this legacy
            # emission still reaches the handler depends entirely on the
            # bus's own receive-side bridge (RULE 2), which only runs when
            # the bus's namespace ``modernize`` flag is on.
            legacy_intent_topic = f"{self.skill_id}:Greetings.intent"
            message = Message(legacy_intent_topic,
                              {"utterance": "good morning", "lang": session.lang},
                              {"session": session.serialize(), "source": "A", "destination": "B"})

            if modernize:
                # "legacy" namespace: modernize is on, so FakeBus/RULE 2
                # re-dispatches this suffixed frame onto its canonical twin
                # and the canonical-bound handler fires.
                test = End2EndTest(
                    minicroft=minicroft,
                    skill_ids=[self.skill_id],
                    # a raw direct injection on the legacy intent topic
                    # (bypassing the orchestrator/pipeline entirely) does not
                    # flip source/destination the way a routed
                    # utterance->dispatch cycle does, so no flip/entry points
                    # are declared here — the generic source/destination
                    # routing check then compares every message against the
                    # injected message's own (A, B), which is what a raw
                    # bridged dispatch preserves.
                    ignore_messages=["recognizer_loop:audio_output_start",
                                      "recognizer_loop:audio_output_end"],
                    # a raw dispatch is not an utterance: the orchestrator
                    # never ran, so it emits no PIPELINE-1 §9.5
                    # ``ovos.utterance.handled`` end-marker (ovoscope's
                    # default). The workshop done-signal is the terminal
                    # message of this scenario.
                    eof_msgs=["mycroft.skill.handler.complete"],
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
            else:
                # "spec" namespace: modernize is off, so RULE 2 never runs.
                # The skill is bound canonical-only, so nobody is listening on
                # the raw legacy-suffixed topic — the emission reaches no
                # handler at all. Assert that precisely: capture the full
                # message stream for a bounded window and require it to be
                # EMPTY of any handler-lifecycle or speak message, not just
                # "no crash before a timeout". FakeBus.emit() dispatches
                # synchronously, so by the time bus.emit() returns any local
                # (would-be) listener has already had its chance to run — a
                # short settle sleep only guards against handler code that
                # itself hands off to another thread, which the hello-world
                # skill's handler does not, but keeps the assertion honest
                # under a stricter build too.
                captured = []
                bus = minicroft.bus
                capture_types = [
                    "mycroft.skill.handler.start",
                    "mycroft.skill.handler.complete",
                    "mycroft.skill.handler.error",
                    SPEC_SPEAK,
                    "speak",
                ]

                def _capture(msg, _t=None):
                    captured.append(msg)

                for t in capture_types:
                    bus.on(t, _capture)
                try:
                    bus.emit(message)
                    from time import sleep
                    sleep(0.5)
                finally:
                    for t in capture_types:
                        bus.remove(t, _capture)

                self.assertEqual(
                    captured, [],
                    "modernize=False must not bridge a raw legacy-suffixed "
                    f"dispatch to the canonical-only handler, but observed: "
                    f"{[m.msg_type for m in captured]}"
                )

        finally:
            minicroft.stop()

    def test_legacy_dispatch_topic_fires_handler(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_legacy_dispatch_topic(namespace)
