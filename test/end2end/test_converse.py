from copy import deepcopy
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft


class TestConverse(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-parrot.openvoiceos"
        self.minicroft = get_minicroft([self.skill_id])  # reuse for speed, but beware if skills keeping internal state

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_parrot_mode(self):
        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ["ovos-converse-pipeline-plugin", "ovos-padatious-pipeline-plugin-high"]

        message1 = Message("recognizer_loop:utterance",
                           {"utterances": ["start parrot mode"], "lang": session.lang},
                           {"session": session.serialize(), "source": "A", "destination": "B"})
        # NOTE: we dont pass session after first message
        # End2EndTest will inject/update the session from message1
        message2 = Message("recognizer_loop:utterance",
                           {"utterances": ["echo test"], "lang": session.lang},
                           {"source": "A", "destination": "B"})
        message3 = Message("recognizer_loop:utterance",
                           {"utterances": ["stop parrot"], "lang": session.lang},
                           {"source": "A", "destination": "B"})
        message4 = Message("recognizer_loop:utterance",
                           {"utterances": ["echo test"], "lang": session.lang},
                           {"source": "A", "destination": "B"})

        expected1 = [
            message1,
            Message(f"{self.skill_id}.activate",
                    data={},
                    context={"skill_id": self.skill_id}),
            Message(f"{self.skill_id}:start_parrot.intent",
                    data={"utterance": "start parrot mode", "lang": session.lang},
                    context={"skill_id": self.skill_id}),
            Message("mycroft.skill.handler.start",
                    data={"name": "ParrotSkill.handle_start_parrot_intent"},
                    context={"skill_id": self.skill_id}),
            Message("speak",
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
            Message("ovos.utterance.handled",
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
            Message("converse:skill",
                    data={"utterances": ["echo test"], "lang": session.lang, "skill_id": self.skill_id},
                    context={"skill_id": self.skill_id}),
            Message(f"{self.skill_id}.converse.request",
                    data={"utterances": ["echo test"], "lang": session.lang},
                    context={"skill_id": self.skill_id}),
            Message("speak",
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
            Message("ovos.utterance.handled",
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

            Message("converse:skill",
                    data={"utterances": ["stop parrot"], "lang": session.lang, "skill_id": self.skill_id},
                    context={"skill_id": self.skill_id}),
            Message(f"{self.skill_id}.converse.request",
                    data={"utterances": ["stop parrot"], "lang": session.lang},
                    context={"skill_id": self.skill_id}),

            Message("speak",
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
            Message("ovos.utterance.handled",
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
            Message("complete_intent_failure"),
            Message("ovos.utterance.handled")
        ]

        final_session = deepcopy(session)
        final_session.active_skills = [(self.skill_id, 0.0)]

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            final_session=final_session,
            source_message=[message1, message2, message3, message4],
            expected_messages=expected1 + expected2 + expected3 + expected4,
            activation_points=[f"{self.skill_id}:start_parrot.intent"],
            # messages internal to ovos-core, i.e. would not be sent to clients such as hivemind
            keep_original_src=[f"{self.skill_id}.converse.ping",
                               f"{self.skill_id}.converse.request"
                               # f"{self.skill_id}.activate",  # TODO
                               ]
        )
        test.execute(timeout=10)
