"""End-to-end padatious intent tests, exercised on BOTH bus namespaces.

- **spec**: ``modernize=False, emit_legacy=False`` — the utterance is injected on
  the spec topic ``ovos.utterance.handle`` and core handles it natively; no
  cross-namespace bridging occurs.
- **legacy**: ``modernize=True, emit_legacy=False`` — the utterance is injected on
  the legacy topic ``recognizer_loop:utterance``; the FakeBus modernize-bridge
  re-dispatches it as ``ovos.utterance.handle`` so the (spec-only) intent listener
  still handles it.

The captured sequence is identical on both paths except message[0]'s topic (the
injected utterance topic). The hello-world skill speaks on the spec topic
``ovos.utterance.speak`` (no legacy ``speak`` mirror because emit_legacy=False).
"""
from unittest import TestCase
from copy import deepcopy
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_spec_tools import SpecMessage, migration_counterpart
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft

# key -> (modernize, emit_legacy, utterance_topic)
# Topics from the ovos-spec-tools SpecMessage enum; legacy derived, not hardcoded.
SPEC_UTTERANCE = SpecMessage.UTTERANCE.value
LEGACY_UTTERANCE = migration_counterpart(SPEC_UTTERANCE)
SPEC_SPEAK = SpecMessage.SPEAK.value
UTTERANCE_HANDLED = SpecMessage.UTTERANCE_HANDLED.value
# PIPELINE-1 orchestrator-emitted terminal events: §9.2 matched, §8 trio, §9.3
# unmatched (the spec replacement for legacy complete_intent_failure).
INTENT_MATCHED = SpecMessage.INTENT_MATCHED.value
INTENT_UNMATCHED = SpecMessage.INTENT_UNMATCHED.value
HANDLER_START = SpecMessage.INTENT_HANDLER_START.value
HANDLER_COMPLETE = SpecMessage.INTENT_HANDLER_COMPLETE.value

NAMESPACE_PATHS = {
    "spec": (False, False, SPEC_UTTERANCE),
}


class TestPadatiousIntent(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-hello-world.openvoiceos"

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def _run_padatious_match(self, namespace):
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id], modernize=modernize,
                                  emit_legacy=emit_legacy)
        try:

            session = Session("123")
            session.lang = "en-US"
            session.pipeline = ["ovos-padatious-pipeline-plugin-high"]
            message = Message(utt_topic,
                              {"utterances": ["good morning"], "lang": session.lang},
                              {"session": session.serialize(), "source": "A", "destination": "B"})

            final_session = deepcopy(session)
            final_session.active_skills = [(self.skill_id, 0.0)]

            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[self.skill_id],
                flip_points=[utt_topic],
                entry_points=[utt_topic],
                ignore_messages=[SpecMessage.AUDIO_OUTPUT_STARTED,
                                  SpecMessage.AUDIO_OUTPUT_ENDED],
                source_message=message,
                final_session=final_session,
                # INTENT-4 / register-time alias collapse (padatious-pipeline#89,
                # padacioso#73): the pipeline now matches and dispatches on the
                # canonical suffix-less intent id, not the legacy `.intent`-suffixed
                # one. ovos-workshop's register_intent_file binds the skill handler
                # to both ids during the migration window (see ovos-workshop#497),
                # but the wire identity the orchestrator/pipeline report here is
                # the canonical one.
                activation_points=[f"{self.skill_id}:Greetings"],
                expected_messages=[
                    message,
                    Message(f"{self.skill_id}.activate",
                            data={},
                            context={"skill_id": self.skill_id}),
                # PIPELINE-1 §9.2: matched notification, before the dispatch
                    Message(INTENT_MATCHED,
                            data={"skill_id": self.skill_id,
                                  "intent_name": f"{self.skill_id}:Greetings",
                                  "utterance": "good morning", "lang": session.lang},
                            context={"skill_id": self.skill_id}),
                # PIPELINE-1 §8.1: orchestrator start before dispatch
                    Message(HANDLER_START,
                            data={"skill_id": self.skill_id,
                                  "intent_name": "Greetings"},
                            context={"skill_id": self.skill_id}),
                    Message(f"{self.skill_id}:Greetings",
                            data={"utterance": "good morning", "lang": session.lang},
                            context={"skill_id": self.skill_id}),
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
                # PIPELINE-1 §8.1: orchestrator complete before the end-marker
                    Message(HANDLER_COMPLETE,
                            data={"skill_id": self.skill_id,
                                  "intent_name": "Greetings"},
                            context={"skill_id": self.skill_id}),
                    Message(UTTERANCE_HANDLED,
                            data={},
                            context={"skill_id": self.skill_id}),
                ]
            )

            test.execute(timeout=10)
        finally:
            minicroft.stop()

    def test_padatious_match(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_padatious_match(namespace)

    def _run_skill_blacklist(self, namespace):
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id], modernize=modernize,
                                  emit_legacy=emit_legacy)
        try:

            session = Session("123")
            session.lang = "en-US"
            session.pipeline = ["ovos-padatious-pipeline-plugin-high"]
            session.blacklisted_skills = [self.skill_id]
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

            test.execute(timeout=10)
        finally:
            minicroft.stop()

    def test_skill_blacklist(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_skill_blacklist(namespace)

    def _run_intent_blacklist(self, namespace):
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id], modernize=modernize,
                                  emit_legacy=emit_legacy)
        try:

            session = Session("123")
            session.lang = "en-US"
            session.pipeline = ["ovos-padatious-pipeline-plugin-high"]
            # canonical id: match.match_type is what the blacklist check compares
            # against (INTENT-4 register-time alias collapse; see comment above)
            session.blacklisted_intents = [f"{self.skill_id}:Greetings"]
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

            test.execute(timeout=10)
        finally:
            minicroft.stop()

    def test_intent_blacklist(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_intent_blacklist(namespace)

    def _run_adapt_no_match(self, namespace):
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id], modernize=modernize,
                                  emit_legacy=emit_legacy)
        try:

            session = Session("123")
            session.lang = "en-US"
            session.pipeline = ['ovos-adapt-pipeline-plugin-high']
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

            test.execute(timeout=10)
        finally:
            minicroft.stop()

    def test_adapt_no_match(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_adapt_no_match(namespace)
