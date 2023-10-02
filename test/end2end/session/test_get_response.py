import time
from time import sleep
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from .minicroft import get_minicroft


class TestSessions(TestCase):

    def setUp(self):
        self.skill_id = "ovos-tskill-abort.openvoiceos"
        self.other_skill_id = "skill-ovos-hello-world.openvoiceos"
        self.core = get_minicroft([self.skill_id, self.other_skill_id])

    def test_no_response(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"

        messages = []

        def new_msg(msg):
            nonlocal messages
            m = Message.deserialize(msg)
            if m.msg_type in ["ovos.skills.settings_changed"]:
                return  # skip these, only happen in 1st run
            messages.append(m)
            print(len(messages), msg)

        def wait_for_n_messages(n):
            nonlocal messages
            t = time.time()
            while len(messages) < n:
                sleep(0.1)
                if time.time() - t > 10:
                    raise RuntimeError("did not get the number of expected messages under 10 seconds")

        self.core.bus.on("message", new_msg)

        # trigger get_response
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["test get response"]})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",  # no session
            "skill.converse.ping",  # default session injected
            "skill.converse.pong",  # test skill
            "skill.converse.pong",  # hello world skill

            # skill selected
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            f"{self.skill_id}:test_get_response.intent",

            # skill executing
            "mycroft.skill.handler.start",
            "skill.converse.get_response.enable",  # start of get_response
            "ovos.session.update_default",  # sync get_response status
            "enclosure.active_skill",
            "speak",  # 'mycroft.mic.listen' if no dialog passed to get_response
            # "recognizer_loop:utterance" would be here if user answered
            "skill.converse.get_response.disable",  # end of get_response
            "ovos.session.update_default",  # sync get_response status
            "enclosure.active_skill",  # from speak inside intent
            "speak",  # speak "ERROR" inside intent
            "mycroft.skill.handler.complete",  # original intent finished executing

            # session updated at end of intent pipeline
            "ovos.session.update_default"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        mtypes = [m.msg_type for m in messages]
        for m in expected_messages:
            self.assertTrue(m in mtypes)

        # verify that "session" is injected
        # (missing in utterance message) and kept in all messages
        for m in messages[1:]:
            print(m.msg_type, m.context["session"]["session_id"])
            self.assertEqual(m.context["session"]["session_id"], "default")

        # verify that "lang" is injected by converse.ping
        # (missing in utterance message) and kept in all messages
        self.assertEqual(messages[1].msg_type, "skill.converse.ping")
        for m in messages[1:]:
            self.assertEqual(m.context["lang"], "en-us")

        # verify "pong" answer from both skills
        self.assertEqual(messages[2].msg_type, "skill.converse.pong")
        self.assertEqual(messages[3].msg_type, "skill.converse.pong")
        self.assertEqual(messages[2].data["skill_id"], messages[2].context["skill_id"])
        self.assertEqual(messages[3].data["skill_id"], messages[3].context["skill_id"])
        # assert it reports converse method has been implemented by skill
        if messages[2].data["skill_id"] == self.skill_id:  # we dont know order of pong responses
            self.assertTrue(messages[2].data["can_handle"])
            self.assertFalse(messages[3].data["can_handle"])
        if messages[3].data["skill_id"] == self.skill_id:  # we dont know order of pong responses
            self.assertTrue(messages[3].data["can_handle"])
            self.assertFalse(messages[2].data["can_handle"])

        # verify skill is activated by intent service (intent pipeline matched)
        self.assertEqual(messages[4].msg_type, "intent.service.skills.activated")
        self.assertEqual(messages[4].data["skill_id"], self.skill_id)
        self.assertEqual(messages[5].msg_type, f"{self.skill_id}.activate")

        # verify intent triggers
        self.assertEqual(messages[6].msg_type, f"{self.skill_id}:test_get_response.intent")
        # verify skill_id is now present in every message.context
        for m in messages[6:]:
            self.assertEqual(m.context["skill_id"], self.skill_id)

        # verify intent execution
        self.assertEqual(messages[7].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[7].data["name"], "TestAbortSkill.handle_test_get_response")

        # enable get_response for this session
        self.assertEqual(messages[8].msg_type, "skill.converse.get_response.enable")
        self.assertEqual(messages[9].msg_type, "ovos.session.update_default")

        # question dialog
        self.assertEqual(messages[10].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[10].data["skill_id"], self.skill_id)
        self.assertEqual(messages[11].msg_type, "speak")
        self.assertEqual(messages[11].data["lang"], "en-us")
        self.assertTrue(messages[11].data["expect_response"])  # listen after dialog
        self.assertEqual(messages[11].data["meta"]["skill"], self.skill_id)

        # user response would be here

        # disable get_response for this session
        self.assertEqual(messages[12].msg_type, "skill.converse.get_response.disable")
        self.assertEqual(messages[13].msg_type, "ovos.session.update_default")

        # post self.get_response intent code
        self.assertEqual(messages[14].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[14].data["skill_id"], self.skill_id)
        self.assertEqual(messages[15].msg_type, "speak")
        self.assertEqual(messages[15].data["lang"], "en-us")
        self.assertFalse(messages[15].data["expect_response"])
        self.assertEqual(messages[15].data["utterance"], "ERROR")
        self.assertEqual(messages[15].data["meta"]["skill"], self.skill_id)

        self.assertEqual(messages[16].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[16].data["name"], "TestAbortSkill.handle_test_get_response")

        # verify default session is now updated
        self.assertEqual(messages[17].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[17].data["session_data"]["session_id"], "default")
        # test deserialization of payload
        sess = Session.deserialize(messages[17].data["session_data"])
        self.assertEqual(sess.session_id, "default")

    def test_with_response(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"

        messages = []

        def new_msg(msg):
            nonlocal messages
            m = Message.deserialize(msg)
            if m.msg_type in ["ovos.skills.settings_changed"]:
                return  # skip these, only happen in 1st run
            messages.append(m)
            print(len(messages), msg)

        def wait_for_n_messages(n):
            nonlocal messages
            t = time.time()
            while len(messages) < n:
                sleep(0.1)
                if time.time() - t > 10:
                    raise RuntimeError("did not get the number of expected messages under 10 seconds")

        self.core.bus.on("message", new_msg)

        def answer_get_response(msg):
            if msg.data["utterance"] == "give me an answer":
                sleep(0.5)
                utt = Message("recognizer_loop:utterance",
                              {"utterances": ["ok"]},
                              {"session": SessionManager.default_session.serialize()})
                self.core.bus.emit(utt)

        self.core.bus.on("speak", answer_get_response)

        # trigger get_response
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["test get response"]})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",  # no session
            "skill.converse.ping",  # default session injected
            "skill.converse.pong",  # test skill
            "skill.converse.pong",  # hello world skill

            # skill selected
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            f"{self.skill_id}:test_get_response.intent",

            # intent code before self.get_response
            "mycroft.skill.handler.start",
            "skill.converse.get_response.enable",  # start of get_response
            "ovos.session.update_default",  # sync get_response status
            "enclosure.active_skill",
            "speak",  # 'mycroft.mic.listen' if no dialog passed to get_response

            "recognizer_loop:utterance",  # answer to get_response from user,
            # converse pipeline start
            "skill.converse.ping",
            "skill.converse.pong",
            "skill.converse.pong",
            "skill.converse.get_response",  # returning user utterance to running intent self.get_response
            # skill selected by converse pipeline
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            "ovos.session.update_default",  # sync skill activated by converse

            "skill.converse.get_response.disable",  # end of get_response
            "ovos.session.update_default",  # sync get_response status

            # intent code post self.get_response
            "enclosure.active_skill",  # from speak inside intent
            "speak",  # speak "ok" inside intent
            "mycroft.skill.handler.complete",  # original intent finished executing

            # session updated at end of intent pipeline
            "ovos.session.update_default"

        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        mtypes = [m.msg_type for m in messages]
        for m in expected_messages:
            self.assertTrue(m in mtypes)

        # verify that "session" is injected
        # (missing in utterance message) and kept in all messages
        for m in messages[1:]:
            print(m.msg_type, m.context["session"]["session_id"])
            self.assertEqual(m.context["session"]["session_id"], "default")

        # converse intent pipeline
        self.assertEqual(messages[1].msg_type, "skill.converse.ping")
        self.assertEqual(messages[2].msg_type, "skill.converse.pong")
        self.assertEqual(messages[3].msg_type, "skill.converse.pong")
        self.assertEqual(messages[2].data["skill_id"], messages[2].context["skill_id"])
        self.assertEqual(messages[3].data["skill_id"], messages[3].context["skill_id"])
        # assert it reports converse method has been implemented by skill
        if messages[2].data["skill_id"] == self.skill_id:  # we dont know order of pong responses
            self.assertTrue(messages[2].data["can_handle"])
            self.assertFalse(messages[3].data["can_handle"])
        if messages[3].data["skill_id"] == self.skill_id:  # we dont know order of pong responses
            self.assertTrue(messages[3].data["can_handle"])
            self.assertFalse(messages[2].data["can_handle"])

        # verify skill is activated by intent service (intent pipeline matched)
        self.assertEqual(messages[4].msg_type, "intent.service.skills.activated")
        self.assertEqual(messages[4].data["skill_id"], self.skill_id)
        self.assertEqual(messages[5].msg_type, f"{self.skill_id}.activate")

        # verify intent triggers
        self.assertEqual(messages[6].msg_type, f"{self.skill_id}:test_get_response.intent")

        # verify intent execution
        self.assertEqual(messages[7].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[7].data["name"], "TestAbortSkill.handle_test_get_response")

        # enable get_response for this session
        self.assertEqual(messages[8].msg_type, "skill.converse.get_response.enable")
        self.assertEqual(messages[9].msg_type, "ovos.session.update_default")

        self.assertEqual(messages[10].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[10].data["skill_id"], self.skill_id)
        self.assertEqual(messages[11].msg_type, "speak")
        self.assertEqual(messages[11].data["utterance"], "give me an answer", )
        self.assertEqual(messages[11].data["lang"], "en-us")
        self.assertTrue(messages[11].data["expect_response"])  # listen after dialog
        self.assertEqual(messages[11].data["meta"]["skill"], self.skill_id)

        # check utterance goes through converse cycle
        self.assertEqual(messages[12].msg_type, "recognizer_loop:utterance")
        self.assertEqual(messages[13].msg_type, "skill.converse.ping")
        self.assertEqual(messages[14].msg_type, "skill.converse.pong")
        self.assertEqual(messages[15].msg_type, "skill.converse.pong")

        # captured utterance sent to get_response handler that is waiting
        self.assertEqual(messages[16].msg_type, "skill.converse.get_response")
        self.assertEqual(messages[16].data["skill_id"], self.skill_id)
        self.assertEqual(messages[16].data["utterances"], ["ok"])

        # converse pipeline activates the skill last_used timestamp
        self.assertEqual(messages[17].msg_type, "intent.service.skills.activated")
        self.assertEqual(messages[18].msg_type, f"{self.skill_id}.activate")
        self.assertEqual(messages[19].msg_type, "ovos.session.update_default")

        # disable get_response for this session
        self.assertEqual(messages[20].msg_type, "skill.converse.get_response.disable")
        self.assertEqual(messages[21].msg_type, "ovos.session.update_default")

        # post self.get_response intent code
        self.assertEqual(messages[22].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[22].data["skill_id"], self.skill_id)
        self.assertEqual(messages[23].msg_type, "speak")
        self.assertEqual(messages[23].data["lang"], "en-us")
        self.assertFalse(messages[23].data["expect_response"])
        self.assertEqual(messages[23].data["utterance"], "ok")
        self.assertEqual(messages[23].data["meta"]["skill"], self.skill_id)

        self.assertEqual(messages[24].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[24].data["name"], "TestAbortSkill.handle_test_get_response")

        # verify default session is now updated
        self.assertEqual(messages[25].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[25].data["session_data"]["session_id"], "default")
        # test deserialization of payload
        sess = Session.deserialize(messages[25].data["session_data"])
        self.assertEqual(sess.session_id, "default")
