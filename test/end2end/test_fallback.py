"""End-to-end test for the fallback pipeline, exercised on BOTH bus namespaces.

- **spec**: ``modernize=False, emit_legacy=False`` — utterance injected on the spec
  topic ``ovos.utterance.handle``; core handles it natively, no bridging.
- **legacy**: ``modernize=True, emit_legacy=False`` — utterance injected on the
  legacy topic ``recognizer_loop:utterance``; the FakeBus modernize-bridge
  re-dispatches it as ``ovos.utterance.handle`` so the spec listener handles it.

The fallback skill speaks on the spec topic ``ovos.utterance.speak`` (no legacy
mirror, since ``emit_legacy=False`` on both paths).
"""
from unittest import TestCase
from copy import deepcopy
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_spec_tools import SpecMessage, migration_counterpart
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft

# Topics from the ovos-spec-tools SpecMessage enum; legacy derived, not hardcoded.
SPEC_UTTERANCE = SpecMessage.UTTERANCE.value
LEGACY_UTTERANCE = migration_counterpart(SPEC_UTTERANCE)
SPEC_SPEAK = SpecMessage.SPEAK.value
UTTERANCE_HANDLED = SpecMessage.UTTERANCE_HANDLED.value

# key -> (modernize, emit_legacy, utterance_topic)
NAMESPACE_PATHS = {
    "spec": (False, False, SPEC_UTTERANCE),
    "legacy": (True, False, LEGACY_UTTERANCE),
}


class TestFallback(TestCase):

    skill_id = "ovos-skill-fallback-unknown.openvoiceos"

    def setUp(self):
        LOG.set_level("DEBUG")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def _run_fallback_match(self, namespace: str) -> None:
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id], modernize=modernize,
                                  emit_legacy=emit_legacy)

        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ['ovos-fallback-pipeline-plugin-low']
        message = Message(utt_topic,
                          {"utterances": ["hello world"], "lang": session.lang},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        final_session = deepcopy(session)

        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=[UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            final_session=final_session,
            keep_original_src=[
                "ovos.skills.fallback.ping",
                # "ovos.skills.fallback.pong", # TODO
            ],
            activation_points=[f"ovos.skills.fallback.{self.skill_id}.request"],
            source_message=message,
            expected_messages=[
                message,
                Message("ovos.skills.fallback.ping",
                        {"utterances": ["hello world"], "lang": session.lang, "range": [90, 101]}),
                Message("ovos.skills.fallback.pong", {"skill_id": self.skill_id, "can_handle": True}),
                Message(f"ovos.skills.fallback.{self.skill_id}.request",
                        {"utterances": ["hello world"], "lang": session.lang, "range": [90, 101], "skill_id": self.skill_id}),
                Message(f"ovos.skills.fallback.{self.skill_id}.start", {}),
                # core reports the fallback dispatch lifecycle as the framework
                # done-signal by translating the skill's own .start/.response
                # markers, so an orchestrator can resolve it
                Message("mycroft.skill.handler.start",
                        data={"handler": f"{self.skill_id}.fallback"},
                        context={"skill_id": self.skill_id}),
                Message(SPEC_SPEAK,
                        data={"lang": session.lang,
                              "expect_response": False,
                              "meta": {
                                  "dialog": "unknown",
                                  "data": {},
                                  "skill": self.skill_id
                              }},
                        context={"skill_id": self.skill_id}),
                Message(f"ovos.skills.fallback.{self.skill_id}.response",
                        data={"fallback_handler": "UnknownSkill.handle_fallback"}),
                Message("mycroft.skill.handler.complete",
                        data={"handler": f"{self.skill_id}.fallback"},
                        context={"skill_id": self.skill_id}),

                Message(UTTERANCE_HANDLED, {})
            ]
        )

        test.execute(timeout=10)
        minicroft.stop()

    def test_fallback_match(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_fallback_match(namespace)
