"""End-to-end tests for the no-skills case, exercised on BOTH bus namespaces.

- **spec**: ``modernize=False, emit_legacy=False`` — utterance injected on the spec
  topic ``ovos.utterance.handle``; core handles it natively, no bridging.
- **legacy**: ``modernize=True, emit_legacy=False`` — utterance injected on the
  legacy topic ``recognizer_loop:utterance``; the FakeBus modernize-bridge
  re-dispatches it as ``ovos.utterance.handle`` so the spec listener handles it.

With no skills loaded the utterance always falls through to
``complete_intent_failure`` and the error sound. The captured sequence is
identical on both paths except for message[0]'s topic (the injected utterance).
"""
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_spec_tools import SpecMessage, migration_counterpart
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft

# key -> (modernize, emit_legacy, utterance_topic)
# Topics from the ovos-spec-tools SpecMessage enum; legacy derived, not hardcoded.
SPEC_UTTERANCE = SpecMessage.UTTERANCE.value
LEGACY_UTTERANCE = migration_counterpart(SPEC_UTTERANCE)
SPEC_SPEAK = SpecMessage.SPEAK.value
UTTERANCE_HANDLED = SpecMessage.UTTERANCE_HANDLED.value
# OVOS-PIPELINE-1 §9.3: no-match terminal is ovos.intent.unmatched; the legacy
# complete_intent_failure is only re-delivered by the emit_legacy bridge.
INTENT_UNMATCHED = SpecMessage.INTENT_UNMATCHED.value

NAMESPACE_PATHS = {
    "spec": (False, False, SPEC_UTTERANCE),
    "legacy": (True, False, LEGACY_UTTERANCE),
}


class TestNoSkills(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def _run_complete_failure(self, namespace: str) -> None:
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([], modernize=modernize, emit_legacy=emit_legacy)

        message = Message(utt_topic,
                          {"utterances": ["hello world"]})

        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=[],
            eof_msgs=[UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message(INTENT_UNMATCHED, {}),
                Message(UTTERANCE_HANDLED, {}),
            ]
        )

        test.execute()
        minicroft.stop()

    def test_complete_failure(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_complete_failure(namespace)

    def _run_routing(self, namespace: str) -> None:
        # this test will validate source and destination are handled properly
        # done automatically if "source" and "destination" are in message.context
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([], modernize=modernize, emit_legacy=emit_legacy)

        message = Message(utt_topic,
                          {"utterances": ["hello world"]},
                          {"source": "A", "destination": "B"})

        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=[],
            eof_msgs=[UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            source_message=message,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message(INTENT_UNMATCHED, {}),
                Message(UTTERANCE_HANDLED, {}),
            ]
        )

        test.execute()
        minicroft.stop()

    def test_routing(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_routing(namespace)
