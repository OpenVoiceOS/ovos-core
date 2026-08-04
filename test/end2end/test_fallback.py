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
# (before dispatch), §8.1 ovos.intent.handler.start (before the dispatch) and the
# §8 ovos.intent.handler.complete terminal. The fallback service re-emits the
# skill's own .start/.response markers as the mycroft.skill.handler.* done-signal,
# which the dispatcher correlates (by the match_data skill_id) to emit the §8
# terminal promptly — without waiting out the §8.3 handler timeout.
INTENT_MATCHED = SpecMessage.INTENT_MATCHED.value
HANDLER_START = SpecMessage.INTENT_HANDLER_START.value
HANDLER_COMPLETE = SpecMessage.INTENT_HANDLER_COMPLETE.value

# key -> (modernize, emit_legacy, utterance_topic)
NAMESPACE_PATHS = {
    "spec": (False, False, SPEC_UTTERANCE),
    "legacy": (True, False, LEGACY_UTTERANCE),
}


class TestFallback(TestCase):

    skill_id = "ovos-skill-fallback-unknown.openvoiceos"

    @classmethod
    def _wire_skill_addressed_probe(cls, minicroft):
        """Expose the companion Workshop FALLBACK-1 probe in this test.

        The Ovoscope workflow intentionally installs released sibling packages
        while testing this Core checkout.  Until the coordinated Workshop
        change is released, adapt only the loaded test skill's capability probe
        to the skill-addressed FALLBACK-1 topics.  The fallback request itself
        still runs through the real skill and its normal lifecycle handlers.
        """
        skill = minicroft.plugin_skills[cls.skill_id].instance
        ping_type = f"{cls.skill_id}.fallback.ping"
        pong_type = f"{cls.skill_id}.fallback.pong"

        def handle_ping(message: Message) -> None:
            minicroft.bus.emit(message.reply(
                pong_type,
                data={"skill_id": cls.skill_id,
                      "can_handle": skill.can_answer(message)},
                context={"skill_id": cls.skill_id}
            ))

        minicroft.bus.on(ping_type, handle_ping)
        return handle_ping

    def setUp(self):
        LOG.set_level("DEBUG")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def _run_fallback_match(self, namespace: str) -> None:
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id], modernize=modernize,
                                  emit_legacy=emit_legacy)
        probe_handler = self._wire_skill_addressed_probe(minicroft)
        try:

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
                flip_points=[
                    utt_topic,
                    f"{self.skill_id}.fallback.pong",
                ],
                entry_points=[utt_topic],
                final_session=final_session,
                ignore_messages=["recognizer_loop:audio_output_start",
                                  "recognizer_loop:audio_output_end"],
                activation_points=[f"ovos.skills.fallback.{self.skill_id}.request"],
                source_message=message,
                expected_messages=[
                    message,
                    Message(f"{self.skill_id}.fallback.ping",
                            {"utterances": ["hello world"],
                             "lang": session.lang}),
                    Message(f"{self.skill_id}.fallback.pong",
                            {"skill_id": self.skill_id, "can_handle": True},
                            {"source": "A", "destination": "B"}),
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
                            {"utterances": ["hello world"],
                             "lang": session.lang,
                             "skill_id": self.skill_id}),
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
                # PIPELINE-1 §8 terminal: the orchestrator correlates the done-signal
                # to the in-flight fallback dispatch and emits its own complete.
                    Message(HANDLER_COMPLETE,
                            data={"intent_name": f"ovos.skills.fallback.{self.skill_id}.request"}),

                    Message(UTTERANCE_HANDLED, {})
                ]
            )

            test.execute(timeout=10)
        finally:
            minicroft.bus.remove(f"{self.skill_id}.fallback.ping",
                                 probe_handler)
            minicroft.stop()

    def test_fallback_match(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_fallback_match(namespace)
