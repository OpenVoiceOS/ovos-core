import time
from time import sleep
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ..minicroft import get_minicroft


class TestSessions(TestCase):

    def setUp(self):
        self.skill_id = "ovos-tskill-abort.openvoiceos"
        self.other_skill_id = "skill-ovos-hello-world.openvoiceos"
        self.core = get_minicroft([self.skill_id, self.other_skill_id])

    def tearDown(self) -> None:
        self.core.stop()

    def test_no_session(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"
        SessionManager.default_session.pipeline = [
                           "converse",
                           "padatious_high",
                           "adapt_high"
                       ]

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

        ######################################
        # STEP 1
        # triggers intent from converse test skill to make it active
        # no converse ping pong as no skill is active
        # verify active skills list after triggering skill (test)
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["no"]})  # converse returns False
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",  # no session
            # skill selected
            f"{self.skill_id}:converse_off.intent",
            # skill triggering
            "mycroft.skill.handler.start",
            "intent.service.skills.activate",
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            "ovos.session.update_default",
            # intent code executing
            "enclosure.active_skill",
            "speak",
            "mycroft.skill.handler.complete",
            # session updated
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
            self.assertEqual(m.context["session"]["session_id"], "default")
            self.assertEqual(m.context["lang"], "en-us")

        # verify intent triggers
        self.assertEqual(messages[1].msg_type, f"{self.skill_id}:converse_off.intent")
        # verify skill_id is now present in every message.context
        for m in messages[1:]:
            self.assertEqual(m.context["skill_id"], self.skill_id)

        self.assertEqual(messages[2].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[2].data["name"], "TestAbortSkill.handle_converse_off")
        # verify skill is activated
        self.assertEqual(messages[3].msg_type, "intent.service.skills.activate")
        self.assertEqual(messages[3].data["skill_id"], self.skill_id)
        self.assertEqual(messages[4].msg_type, "intent.service.skills.activated")
        self.assertEqual(messages[4].data["skill_id"], self.skill_id)
        self.assertEqual(messages[5].msg_type, f"{self.skill_id}.activate")
        self.assertEqual(messages[6].msg_type, "ovos.session.update_default")
        # verify intent execution
        self.assertEqual(messages[7].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[7].data["skill_id"], self.skill_id)
        self.assertEqual(messages[8].msg_type, "speak")
        self.assertEqual(messages[8].data["lang"], "en-us")
        self.assertFalse(messages[8].data["expect_response"])
        self.assertEqual(messages[8].data["meta"]["skill"], self.skill_id)
        self.assertEqual(messages[9].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[9].data["name"], "TestAbortSkill.handle_converse_off")

        # verify default session is now updated
        self.assertEqual(messages[10].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[10].data["session_data"]["session_id"], "default")
        # test deserialization of payload
        sess = Session.deserialize(messages[10].data["session_data"])
        self.assertEqual(sess.session_id, "default")

        # test that active skills list has been updated
        self.assertEqual(sess.active_skills[0][0], self.skill_id)
        self.assertEqual(messages[10].data["session_data"]["active_skills"][0][0], self.skill_id)

        messages = []

        ######################################
        # STEP 2
        # converse test skill is now active
        # test hello world skill triggers, converse test skill says it does not want to converse
        # verify active skills list (hello, test)
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["hello world"]})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",  # no session
            f"{self.skill_id}.converse.ping",  # default session injected
            "skill.converse.pong",
            f"{self.skill_id}.converse.request",
            "skill.converse.response",  # does not want to converse
            # skill selected
            f"{self.other_skill_id}:HelloWorldIntent",
            "mycroft.skill.handler.start",
            # skill activated
            "intent.service.skills.activate",
            "intent.service.skills.activated",
            f"{self.other_skill_id}.activate",
            "ovos.session.update_default",
            # skill executing
            "enclosure.active_skill",
            "speak",
            "mycroft.skill.handler.complete",
            # session updated
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
            self.assertEqual(m.context["session"]["session_id"], "default")
            self.assertEqual(m.context["lang"], "en-us")

        # verify that "lang" is injected by converse.ping
        # (missing in utterance message) and kept in all messages
        self.assertEqual(messages[1].msg_type, f"{self.skill_id}.converse.ping")

        # verify "pong" answer from converse test skill
        self.assertEqual(messages[2].msg_type, "skill.converse.pong")
        # assert it reports converse method has been implemented by skill
        self.assertTrue(messages[2].data["can_handle"])

        # verify answer from skill that it does not want to converse
        self.assertEqual(messages[3].msg_type, f"{self.skill_id}.converse.request")
        self.assertEqual(messages[4].msg_type, "skill.converse.response")
        self.assertEqual(messages[4].data["skill_id"], self.skill_id)
        self.assertFalse(messages[4].data["result"])  # does not want to converse

        # verify intent triggers
        self.assertEqual(messages[5].msg_type, f"{self.other_skill_id}:HelloWorldIntent")
        # verify skill_id is now present in every message.context
        for m in messages[5:]:
            self.assertEqual(m.context["skill_id"], self.other_skill_id)

        self.assertEqual(messages[6].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[6].data["name"], "HelloWorldSkill.handle_hello_world_intent")

        # verify skill is activated
        self.assertEqual(messages[7].msg_type, "intent.service.skills.activate")
        self.assertEqual(messages[7].data["skill_id"], self.other_skill_id)
        self.assertEqual(messages[8].msg_type, "intent.service.skills.activated")
        self.assertEqual(messages[8].data["skill_id"], self.other_skill_id)
        self.assertEqual(messages[9].msg_type, f"{self.other_skill_id}.activate")
        self.assertEqual(messages[10].msg_type, "ovos.session.update_default")

        # verify intent execution
        self.assertEqual(messages[11].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[11].data["skill_id"], self.other_skill_id)
        self.assertEqual(messages[12].msg_type, "speak")
        self.assertEqual(messages[12].data["lang"], "en-us")
        self.assertFalse(messages[12].data["expect_response"])
        self.assertEqual(messages[12].data["meta"]["skill"], self.other_skill_id)
        self.assertEqual(messages[13].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[13].data["name"], "HelloWorldSkill.handle_hello_world_intent")

        # verify default session is now updated
        self.assertEqual(messages[14].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[14].data["session_data"]["session_id"], "default")
        # test deserialization of payload
        sess = Session.deserialize(messages[14].data["session_data"])
        self.assertEqual(sess.session_id, "default")

        # test that active skills list has been updated
        self.assertEqual(sess.active_skills[0][0], self.other_skill_id)
        self.assertEqual(sess.active_skills[1][0], self.skill_id)
        self.assertEqual(messages[14].data["session_data"]["active_skills"][0][0], self.other_skill_id)
        self.assertEqual(messages[14].data["session_data"]["active_skills"][1][0], self.skill_id)

        messages = []

        ######################################
        # STEP 3
        # both skills are now active
        # trigger skill intent that makes it return True in next converse
        # verify active skills list gets swapped (test, hello)
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["yes"]})  # converse returns True
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",  # no session
            f"{self.skill_id}.converse.ping",  # default session injected
            f"{self.other_skill_id}.converse.ping",
            "skill.converse.pong",
            "skill.converse.pong",
            f"{self.skill_id}.converse.request",
            "skill.converse.response",  # does not want to converse
            # skill selected
            "intent.service.skills.activate",
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            "ovos.session.update_default",

            f"{self.skill_id}:converse_on.intent",
            # skill executing
            "mycroft.skill.handler.start",
            "enclosure.active_skill",
            "speak",
            "mycroft.skill.handler.complete",
            # session updated
            "ovos.session.update_default"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        mtypes = [m.msg_type for m in messages]
        for m in expected_messages:
            self.assertTrue(m in mtypes)

        # verify that "session" and "lang" is injected
        # (missing in utterance message) and kept in all messages
        for m in messages[1:]:
            self.assertEqual(m.context["session"]["session_id"], "default")
            self.assertEqual(m.context["lang"], "en-us")

        # converse
        self.assertEqual(messages[1].msg_type, f"{self.other_skill_id}.converse.ping")
        self.assertEqual(messages[2].msg_type, "skill.converse.pong")
        self.assertEqual(messages[2].data["skill_id"], messages[2].context["skill_id"])
        self.assertFalse(messages[2].data["can_handle"])
        self.assertEqual(messages[3].msg_type, f"{self.skill_id}.converse.ping")
        self.assertEqual(messages[4].msg_type, "skill.converse.pong")
        self.assertEqual(messages[4].data["skill_id"], messages[4].context["skill_id"])
        self.assertTrue(messages[4].data["can_handle"])

        # verify answer from skill that it does not want to converse
        self.assertEqual(messages[5].msg_type, f"{self.skill_id}.converse.request")
        self.assertEqual(messages[6].msg_type, "skill.converse.response")
        self.assertEqual(messages[6].data["skill_id"], self.skill_id)
        self.assertFalse(messages[6].data["result"])  # do not want to converse

        # verify intent triggers
        self.assertEqual(messages[7].msg_type, f"{self.skill_id}:converse_on.intent")
        # verify skill_id is now present in every message.context
        for m in messages[7:]:
            self.assertEqual(m.context["skill_id"], self.skill_id)

        # verify intent execution
        self.assertEqual(messages[8].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[8].data["name"], "TestAbortSkill.handle_converse_on")

        # verify skill is activated by intent service (intent pipeline matched)
        self.assertEqual(messages[9].msg_type, "intent.service.skills.activate")
        self.assertEqual(messages[9].data["skill_id"], self.skill_id)
        self.assertEqual(messages[10].msg_type, "intent.service.skills.activated")
        self.assertEqual(messages[10].data["skill_id"], self.skill_id)
        self.assertEqual(messages[11].msg_type, f"{self.skill_id}.activate")
        self.assertEqual(messages[12].msg_type, "ovos.session.update_default")

        self.assertEqual(messages[13].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[13].data["skill_id"], self.skill_id)
        self.assertEqual(messages[14].msg_type, "speak")
        self.assertEqual(messages[14].data["lang"], "en-us")
        self.assertFalse(messages[14].data["expect_response"])
        self.assertEqual(messages[14].data["meta"]["skill"], self.skill_id)
        self.assertEqual(messages[15].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[15].data["name"], "TestAbortSkill.handle_converse_on")

        # verify default session is now updated
        self.assertEqual(messages[16].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[16].data["session_data"]["session_id"], "default")
        # test deserialization of payload
        sess = Session.deserialize(messages[16].data["session_data"])
        self.assertEqual(sess.session_id, "default")

        # test that active skills list has been updated
        self.assertEqual(sess.active_skills[0][0], self.skill_id)
        self.assertEqual(sess.active_skills[1][0], self.other_skill_id)
        self.assertEqual(messages[16].data["session_data"]["active_skills"][0][0], self.skill_id)
        self.assertEqual(messages[16].data["session_data"]["active_skills"][1][0], self.other_skill_id)

        messages = []

        ######################################
        # STEP 4
        # test converse capture, hello world utterance wont reach hello world skill
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["hello world"]})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",  # no session
            f"{self.skill_id}.converse.ping",  # default session injected
            f"{self.other_skill_id}.converse.ping",
            "skill.converse.pong",
            "skill.converse.pong",
            f"{self.skill_id}.converse.request",
            # skill selected
            "intent.service.skills.activate",
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            "ovos.session.update_default",
            "skill.converse.response",  # CONVERSED
            # session updated
            "ovos.session.update_default"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        mtypes = [m.msg_type for m in messages]
        for m in expected_messages:
            print(m)
            self.assertTrue(m in mtypes)

        # verify that "session" and "lang" is injected
        # (missing in utterance message) and kept in all messages
        for m in messages[1:]:
            self.assertEqual(m.context["session"]["session_id"], "default")
            self.assertEqual(m.context["lang"], "en-us")

        # converse
        self.assertEqual(messages[1].msg_type, f"{self.skill_id}.converse.ping")
        self.assertEqual(messages[2].msg_type, "skill.converse.pong")
        self.assertEqual(messages[2].data["skill_id"], messages[2].context["skill_id"])
        self.assertTrue(messages[2].data["can_handle"])
        self.assertEqual(messages[3].msg_type, f"{self.other_skill_id}.converse.ping")
        self.assertEqual(messages[4].msg_type, "skill.converse.pong")
        self.assertEqual(messages[4].data["skill_id"], messages[4].context["skill_id"])
        self.assertFalse(messages[4].data["can_handle"])

        # verify answer from skill that it does not want to converse
        self.assertEqual(messages[5].msg_type, f"{self.skill_id}.converse.request")

        # verify skill is activated by intent service (intent pipeline matched)
        self.assertEqual(messages[6].msg_type, "intent.service.skills.activate")
        self.assertEqual(messages[6].data["skill_id"], self.skill_id)
        self.assertEqual(messages[7].msg_type, "intent.service.skills.activated")
        self.assertEqual(messages[7].data["skill_id"], self.skill_id)
        self.assertEqual(messages[8].msg_type, f"{self.skill_id}.activate")
        self.assertEqual(messages[9].msg_type, "ovos.session.update_default")

        # verify skill conversed
        self.assertEqual(messages[10].msg_type, "skill.converse.response")
        self.assertEqual(messages[10].data["skill_id"], self.skill_id)
        self.assertTrue(messages[10].data["result"])  # CONVERSED

        # verify default session is now updated
        self.assertEqual(messages[11].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[11].data["session_data"]["session_id"], "default")
        # test deserialization of payload
        sess = Session.deserialize(messages[11].data["session_data"])
        self.assertEqual(sess.session_id, "default")

        # test that active skills list has been updated
        self.assertEqual(sess.active_skills[0][0], self.skill_id)
        self.assertEqual(sess.active_skills[1][0], self.other_skill_id)
        self.assertEqual(messages[11].data["session_data"]["active_skills"][0][0], self.skill_id)
        self.assertEqual(messages[11].data["session_data"]["active_skills"][1][0], self.other_skill_id)

        messages = []

        ######################################
        # STEP 5 - xternal deactivate
        utt = Message("test_deactivate")
        self.core.bus.emit(utt)

        self.assertEqual(SessionManager.default_session.active_skills[0][0], self.other_skill_id)
        # confirm all expected messages are sent
        expected_messages = [
            "test_deactivate",
            "intent.service.skills.deactivate",
            "intent.service.skills.deactivated",
            "ovos-tskill-abort.openvoiceos.deactivate",
            "ovos.session.update_default"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        mtypes = [m.msg_type for m in messages]
        for m in expected_messages:
            self.assertTrue(m in mtypes)

        # verify skill is no longer in active skills
        self.assertEqual(SessionManager.default_session.active_skills[0][0], self.other_skill_id)
        self.assertEqual(len(SessionManager.default_session.active_skills), 1)

        # verify default session is now updated
        self.assertEqual(messages[-1].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[-1].data["session_data"]["session_id"], "default")
        # test deserialization of payload
        sess = Session.deserialize(messages[-1].data["session_data"])
        self.assertEqual(sess.session_id, "default")
        # test that active skills list has been updated
        self.assertEqual(len(sess.active_skills), 1)
        self.assertEqual(sess.active_skills[0][0], self.other_skill_id)
        self.assertEqual(len(messages[-1].data["session_data"]["active_skills"]), 1)
        self.assertEqual(messages[-1].data["session_data"]["active_skills"][0][0], self.other_skill_id)

        messages = []

        ######################################
        # STEP 6 - external activate
        self.assertEqual(SessionManager.default_session.active_skills[0][0], self.other_skill_id)
        utt = Message("test_activate")
        self.core.bus.emit(utt)
        self.assertEqual(SessionManager.default_session.active_skills[0][0], self.skill_id)
        # confirm all expected messages are sent
        expected_messages = [
            "test_activate",
            "intent.service.skills.activate",
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            "ovos.session.update_default"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        mtypes = [m.msg_type for m in messages]
        for m in expected_messages:
            self.assertTrue(m in mtypes)

        # verify skill is again in active skills
        self.assertEqual(SessionManager.default_session.active_skills[0][0], self.skill_id)
        self.assertEqual(len(SessionManager.default_session.active_skills), 2)

        # verify default session is now updated
        self.assertEqual(messages[-1].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[-1].data["session_data"]["session_id"], "default")
        # test deserialization of payload
        sess = Session.deserialize(messages[-1].data["session_data"])
        self.assertEqual(sess.session_id, "default")
        # test that active skills list has been updated
        self.assertEqual(len(sess.active_skills), 2)
        self.assertEqual(sess.active_skills[0][0], self.skill_id)
        self.assertEqual(len(messages[-1].data["session_data"]["active_skills"]), 2)
        self.assertEqual(messages[-1].data["session_data"]["active_skills"][0][0], self.skill_id)

        messages = []
