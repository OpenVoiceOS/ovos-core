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
# PIPELINE-1 orchestrator-emitted matched-path messages: §9.2 ovos.intent.matched
# (before dispatch) and §8.1 ovos.intent.handler.start. The fallback pipeline's
# dispatch carries no mycroft.skill.handler.* done-signal, so its §8 terminal
# resolves via the §8.3 timeout (after the end-marker, not captured here).
INTENT_MATCHED = SpecMessage.INTENT_MATCHED.value
HANDLER_START = SpecMessage.INTENT_HANDLER_START.value

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
                # PIPELINE-1 §9.2: matched notification precedes the dispatch. The
                # fallback match_type is the .request topic; it bears no ':' so
                # skill_id/intent_name resolve to that topic.
                Message(INTENT_MATCHED,
                        data={"intent_name": f"ovos.skills.fallback.{self.skill_id}.request",
                              "utterance": "hello world", "lang": session.lang}),
                # PIPELINE-1 §8.1: orchestrator start immediately before the dispatch
                Message(HANDLER_START,
                        data={"intent_name": f"ovos.skills.fallback.{self.skill_id}.request"}),
                Message(f"ovos.skills.fallback.{self.skill_id}.request",
                        {"utterances": ["hello world"], "lang": session.lang, "range": [90, 101], "skill_id": self.skill_id}),
                Message(f"ovos.skills.fallback.{self.skill_id}.start", {}),
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

                Message(UTTERANCE_HANDLED, {})
            ]
        )

        test.execute(timeout=10)
        minicroft.stop()

    def test_fallback_match(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_fallback_match(namespace)
