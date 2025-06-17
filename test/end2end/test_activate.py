from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG

from ovos_workshop.skills.converse import ConversationalSkill
from ovoscope import End2EndTest, get_minicroft


class TestSkill(ConversationalSkill):

    def initialize(self):
        self.add_event("test_activate", self.handle_activate_test)
        self.add_event("test_deactivate", self.handle_deactivate_test)

    def handle_activate_test(self, message: Message):
        self.activate()

    def handle_deactivate_test(self, message: Message):
        self.deactivate()

    def can_converse(self, message: Message) -> bool:
        return True

    def converse(self, message: Message):
        self.log.debug("I dont wanna converse anymore")
        self.deactivate()


class TestDeactivate(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "test_activation.openvoiceos"
        self.minicroft = get_minicroft([self.skill_id],
                                       extra_skills={self.skill_id: TestSkill})

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_activate(self):
        session = Session("123")
        session.lang = "en-US"
        session.deactivate_skill(self.skill_id) # start with skill inactive

        message = Message("test_activate",
                          context={"session": session.serialize(),
                                   "source": "A", "destination": "B"})

        final_session = Session("123")
        final_session.lang = "en-US"
        final_session.active_skills = [(self.skill_id, 0.0)]

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            deactivation_points=[message.msg_type],
            final_session=final_session,
            activation_points=["intent.service.skills.activated"],
            # messages internal to ovos-core, i.e. would not be sent to clients such as hivemind
            keep_original_src=[
                #"intent.service.skills.activate", # TODO
                #f"{self.skill_id}.activate", # TODO
            ],
            expected_messages=[
                message,
                # handler code
                Message("intent.service.skills.activate",
                        data={"skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message("intent.service.skills.activated",
                        data={"skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message(f"{self.skill_id}.activate",
                        data={},
                        context={"skill_id": self.skill_id}),
            ]
        )

        test.execute(timeout=10)

    def test_deactivate(self):
        session = Session("123")
        session.lang = "en-US"
        session.activate_skill(self.skill_id) # start with skill active

        message = Message("test_deactivate",
                          context={"session": session.serialize(),
                                   "source": "A", "destination": "B"})

        final_session = Session("123")
        final_session.lang = "en-US"
        final_session.active_skills = []

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            final_session=final_session,
            activation_points=[message.msg_type], # starts activated
            deactivation_points=["intent.service.skills.deactivated"],
            # messages internal to ovos-core, i.e. would not be sent to clients such as hivemind
            keep_original_src=[
                #"intent.service.skills.deactivate", # TODO
                #f"{self.skill_id}.deactivate", # TODO
                #f"{self.skill_id}.activate", # TODO
            ],
            expected_messages=[
                message,
                # handler code
                Message("intent.service.skills.deactivate",
                        data={"skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message("intent.service.skills.deactivated",
                        data={"skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message(f"{self.skill_id}.deactivate",
                        data={},
                        context={"skill_id": self.skill_id}),
            ]
        )

        test.execute(timeout=10)

    def test_deactivate_inside_converse(self):
        session = Session("123")
        session.lang = "en-US"
        session.activate_skill(self.skill_id) # start with skill active

        message = Message("recognizer_loop:utterance",
                          {"utterances": ["deactivate skill from within converse"], "lang": session.lang},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        final_session = Session("123")
        final_session.lang = "en-US"
        final_session.active_skills = []

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            final_session=final_session,
            activation_points=[message.msg_type], # starts activated
            deactivation_points=["intent.service.skills.deactivated"],
            # messages internal to ovos-core, i.e. would not be sent to clients such as hivemind
            keep_original_src=[
                f"{self.skill_id}.converse.ping",
                f"{self.skill_id}.converse.request",
                #"intent.service.skills.deactivate", # TODO
                #f"{self.skill_id}.deactivate", # TODO
                #f"{self.skill_id}.activate", # TODO
            ],
            expected_messages=[
                message,
                Message(f"{self.skill_id}.converse.ping",
                        data={"utterances": ["deactivate skill from within converse"], "skill_id": self.skill_id},
                        context={}),
                Message("skill.converse.pong",
                        data={"can_handle": True, "skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message(f"{self.skill_id}.activate",
                        data={},
                        context={"skill_id": self.skill_id}),
                Message("converse:skill",
                        data={"utterances": ["deactivate skill from within converse"], "lang": session.lang,
                              "skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message(f"{self.skill_id}.converse.request",
                        data={"utterances": ["deactivate skill from within converse"], "lang": session.lang},
                        context={"skill_id": self.skill_id}),
                # converse handler code
                Message("intent.service.skills.deactivate",
                        data={"skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message("intent.service.skills.deactivated",
                        data={"skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message(f"{self.skill_id}.deactivate",
                        data={},
                        context={"skill_id": self.skill_id}),
                # post converse handler
                Message("skill.converse.response",
                        data={"skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message("ovos.utterance.handled",
                        data={},
                        context={"skill_id": self.skill_id})

            ]
        )

        test.execute(timeout=10)
