"""End-to-end converse test, exercised on BOTH bus namespaces.

- **spec**: ``modernize=False, emit_legacy=False`` — utterances injected on the spec
  topic ``ovos.utterance.handle``; core handles them natively, no bridging.
- **legacy**: ``modernize=True, emit_legacy=False`` — utterances injected on the
  legacy topic ``recognizer_loop:utterance``; the FakeBus modernize-bridge
  re-dispatches each as ``ovos.utterance.handle`` so the spec listener handles it.

The parrot skill speaks on the spec topic ``ovos.utterance.speak``. The start/stop
dialog utterances are randomized variants, so only their stable ``meta.dialog`` is
asserted; the deterministic echo reply asserts its full utterance.
"""
from copy import deepcopy
from unittest import TestCase

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
INTENT_MATCHED = SpecMessage.INTENT_MATCHED.value      # ovos.intent.matched (§9.2)
# §8 handler-lifecycle trio wraps every dispatch; this suite asserts converse
# routing, not the trio (covered by the adapt/padatious suites), so it is
# filtered via ignore_messages below.
HANDLER_TRIO = [SpecMessage.INTENT_HANDLER_START.value,
                SpecMessage.INTENT_HANDLER_COMPLETE.value,
                SpecMessage.INTENT_HANDLER_ERROR.value,
                "ovos.skills.settings_changed"]  # keep ovoscope's default ignore
INTENT_UNMATCHED = SpecMessage.INTENT_UNMATCHED.value  # ovos.intent.unmatched (§9.3)

# key -> (modernize, emit_legacy, utterance_topic)
NAMESPACE_PATHS = {
    "spec": (False, False, SPEC_UTTERANCE),
    "legacy": (True, False, LEGACY_UTTERANCE),
}


class TestConverse(TestCase):

    skill_id = "ovos-skill-parrot.openvoiceos"

    def setUp(self):
        LOG.set_level("DEBUG")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def _run_parrot_mode(self, namespace: str) -> None:
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id], modernize=modernize,
                                  emit_legacy=emit_legacy)

        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ["ovos-converse-pipeline-plugin", "ovos-padatious-pipeline-plugin-high"]

        message1 = Message(utt_topic,
                           {"utterances": ["start parrot mode"], "lang": session.lang},
                           {"session": session.serialize(), "source": "A", "destination": "B"})
        # NOTE: we dont pass session after first message
        # End2EndTest will inject/update the session from message1
        message2 = Message(utt_topic,
                           {"utterances": ["echo test"], "lang": session.lang},
                           {"source": "A", "destination": "B"})
        message3 = Message(utt_topic,
                           {"utterances": ["stop parrot"], "lang": session.lang},
                           {"source": "A", "destination": "B"})
        message4 = Message(utt_topic,
                           {"utterances": ["echo test"], "lang": session.lang},
                           {"source": "A", "destination": "B"})

        expected1 = [
            message1,
            Message(f"{self.skill_id}.activate",
                    data={},
                    context={"skill_id": self.skill_id}),
            Message(INTENT_MATCHED,
                    data={"skill_id": self.skill_id,
                          "intent_name": f"{self.skill_id}:start_parrot.intent"},
                    context={"skill_id": self.skill_id}),
            Message(f"{self.skill_id}:start_parrot.intent",
                    data={"utterance": "start parrot mode", "lang": session.lang},
                    context={"skill_id": self.skill_id}),
            Message("mycroft.skill.handler.start",
                    data={"name": "ParrotSkill.handle_start_parrot_intent"},
                    context={"skill_id": self.skill_id}),
            Message(SPEC_SPEAK,
                    data={"expect_response": False,
                          "meta": {
                              "dialog": "parrot_start",
                              "data": {},
                              "skill": self.skill_id
                          }},
                    context={"skill_id": self.skill_id}),
            Message("mycroft.skill.handler.complete",
                    data={"name": "ParrotSkill.handle_start_parrot_intent"},
                    context={"skill_id": self.skill_id}),
            Message(UTTERANCE_HANDLED,
                    data={},
                    context={"skill_id": self.skill_id}),
        ]
        expected2 = [
            message2,
            Message(f"{self.skill_id}.converse.ping",
                    data={"utterances": ["echo test"], "skill_id": self.skill_id},
                    context={}),
            Message("skill.converse.pong",
                    data={"can_handle": True, "skill_id": self.skill_id},
                    context={"skill_id": self.skill_id}),
            Message(f"{self.skill_id}.activate",
                    data={},
                    context={"skill_id": self.skill_id}),
            Message(INTENT_MATCHED,
                    data={"skill_id": self.skill_id, "intent_name": "converse:skill"},
                    context={"skill_id": self.skill_id}),
            Message("converse:skill",
                    data={"utterances": ["echo test"], "lang": session.lang, "skill_id": self.skill_id},
                    context={"skill_id": self.skill_id}),
            Message(f"{self.skill_id}.converse.request",
                    data={"utterances": ["echo test"], "lang": session.lang},
                    context={"skill_id": self.skill_id}),
            Message(SPEC_SPEAK,
                    data={"utterance": "echo test",
                          "expect_response": False,
                          "lang": session.lang,
                          "meta": {
                              "skill": self.skill_id
                          }},
                    context={"skill_id": self.skill_id}),
            Message("skill.converse.response",
                    data={"skill_id": self.skill_id},
                    context={"skill_id": self.skill_id}),
            Message(UTTERANCE_HANDLED,
                    data={},
                    context={"skill_id": self.skill_id})
        ]
        expected3 = [
            message3,
            Message(f"{self.skill_id}.converse.ping",
                    data={"utterances": ["stop parrot"], "skill_id": self.skill_id},
                    context={}),
            Message("skill.converse.pong",
                    data={"can_handle": True, "skill_id": self.skill_id},
                    context={"skill_id": self.skill_id}),
            Message(f"{self.skill_id}.activate",
                    data={},
                    context={"skill_id": self.skill_id}),

            Message(INTENT_MATCHED,
                    data={"skill_id": self.skill_id, "intent_name": "converse:skill"},
                    context={"skill_id": self.skill_id}),
            Message("converse:skill",
                    data={"utterances": ["stop parrot"], "lang": session.lang, "skill_id": self.skill_id},
                    context={"skill_id": self.skill_id}),
            Message(f"{self.skill_id}.converse.request",
                    data={"utterances": ["stop parrot"], "lang": session.lang},
                    context={"skill_id": self.skill_id}),

            Message(SPEC_SPEAK,
                    data={"expect_response": False,
                          "lang": session.lang,
                          "meta": {
                              "dialog": "parrot_stop",
                              "data": {},
                              "skill": self.skill_id
                          }},
                    context={"skill_id": self.skill_id}),
            Message("skill.converse.response",
                    data={"skill_id": self.skill_id},
                    context={"skill_id": self.skill_id}),
            Message(UTTERANCE_HANDLED,
                    data={},
                    context={"skill_id": self.skill_id})
        ]
        expected4 = [
            message4,
            Message(f"{self.skill_id}.converse.ping",
                    data={"utterances": ["echo test"], "skill_id": self.skill_id},
                    context={}),
            Message("skill.converse.pong",
                    data={"can_handle": False, "skill_id": self.skill_id},
                    context={"skill_id": self.skill_id}),
            Message("mycroft.audio.play_sound", data={"uri": "snd/error.mp3"}),
            Message(INTENT_UNMATCHED),
            Message(UTTERANCE_HANDLED)
        ]

        final_session = deepcopy(session)
        final_session.active_skills = [(self.skill_id, 0.0)]

        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=[UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            final_session=final_session,
            source_message=[message1, message2, message3, message4],
            expected_messages=expected1 + expected2 + expected3 + expected4,
            ignore_messages=HANDLER_TRIO,
            activation_points=[f"{self.skill_id}:start_parrot.intent"],
            # messages internal to ovos-core, i.e. would not be sent to clients such as hivemind
            keep_original_src=[f"{self.skill_id}.converse.ping",
                               f"{self.skill_id}.converse.request"
                               # f"{self.skill_id}.activate",  # TODO
                               ]
        )
        test.execute(timeout=10)
        minicroft.stop()

    def test_parrot_mode(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_parrot_mode(namespace)
