import time
from time import sleep
from unittest import TestCase, skip

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from .minicroft import get_minicroft


class TestSessions(TestCase):

    def setUp(self):
        self.skill_id = "ovos-tskill-abort.openvoiceos"
        self.other_skill_id = "skill-ovos-hello-world.openvoiceos"
        self.core = get_minicroft([self.skill_id, self.other_skill_id])

    def test_no_session(self):
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

        # triggers intent from test skill to make it active
        # verify active skills list (test)
        def skill_converse_no():

            nonlocal messages

            utt = Message("recognizer_loop:utterance",
                          {"utterances": ["no"]})  # converse returns False
            self.core.bus.emit(utt)

            # confirm all expected messages are sent
            expected_messages = [
                "recognizer_loop:utterance",  # no session
                "skill.converse.ping",  # default session injected
                "skill.converse.pong",
                "skill.converse.pong",
                # skill selected
                "intent.service.skills.activated",
                f"{self.skill_id}.activate",
                f"{self.skill_id}:converse_off.intent",
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

            # verify that "session" is injected
            # (missing in utterance message) and kept in all messages
            for m in messages[1:]:
                self.assertEqual(m.context["session"]["session_id"], "default")

            # verify that "lang" is injected by converse.ping
            # (missing in utterance message) and kept in all messages
            self.assertEqual(messages[1].msg_type, "skill.converse.ping")
            for m in messages[1:]:
                self.assertEqual(m.context["lang"], "en-us")

            # verify "pong" answer from both skills
            self.assertEqual(messages[2].msg_type, "skill.converse.pong")
            self.assertEqual(messages[3].msg_type, "skill.converse.pong")
            self.assertEqual(messages[2].data["skill_id"],messages[2].context["skill_id"])
            self.assertEqual(messages[3].data["skill_id"], messages[3].context["skill_id"])
            # assert it reports converse method has been implemented by skill
            if messages[2].data["skill_id"] == self.skill_id: # we dont know order of pong responses
                self.assertTrue(messages[2].data["can_handle"])
                self.assertFalse(messages[3].data["can_handle"])
            if messages[3].data["skill_id"] == self.skill_id: # we dont know order of pong responses
                self.assertTrue(messages[3].data["can_handle"])
                self.assertFalse(messages[2].data["can_handle"])

            # verify skill is activated by intent service (intent pipeline matched)
            self.assertEqual(messages[4].msg_type, "intent.service.skills.activated")
            self.assertEqual(messages[4].data["skill_id"], self.skill_id)
            self.assertEqual(messages[5].msg_type, f"{self.skill_id}.activate")

            # verify intent triggers
            self.assertEqual(messages[6].msg_type, f"{self.skill_id}:converse_off.intent")
            # verify skill_id is now present in every message.context
            for m in messages[6:]:
                self.assertEqual(m.context["skill_id"], self.skill_id)

            # verify intent execution
            self.assertEqual(messages[7].msg_type, "mycroft.skill.handler.start")
            self.assertEqual(messages[7].data["name"], "TestAbortSkill.handle_converse_off")
            self.assertEqual(messages[8].msg_type, "enclosure.active_skill")
            self.assertEqual(messages[8].data["skill_id"], self.skill_id)
            self.assertEqual(messages[9].msg_type, "speak")
            self.assertEqual(messages[9].data["lang"], "en-us")
            self.assertFalse(messages[9].data["expect_response"])
            self.assertEqual(messages[9].data["meta"]["skill"], self.skill_id)
            self.assertEqual(messages[10].msg_type, "mycroft.skill.handler.complete")
            self.assertEqual(messages[10].data["name"], "TestAbortSkill.handle_converse_off")

            # verify default session is now updated
            self.assertEqual(messages[11].msg_type, "ovos.session.update_default")
            self.assertEqual(messages[11].data["session_data"]["session_id"], "default")
            # test deserialization of payload
            sess = Session.deserialize(messages[11].data["session_data"])
            self.assertEqual(sess.session_id, "default")

            # test that active skills list has been updated
            self.assertEqual(sess.active_skills[0][0], self.skill_id)
            self.assertEqual(messages[11].data["session_data"]["active_skills"][0][0], self.skill_id)

            messages = []

        skill_converse_no()

        # test hello world skill triggers, test skill says it does not want to converse
        # verify active skills list (hello, test)
        def hello_world():
            nonlocal messages
            utt = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"]})
            self.core.bus.emit(utt)

            # confirm all expected messages are sent
            expected_messages = [
                "recognizer_loop:utterance",  # no session
                "skill.converse.ping",  # default session injected
                "skill.converse.pong",
                "skill.converse.pong",
                "skill.converse.request",
                "skill.converse.response",  # does not want to converse
                # skill selected
                "intent.service.skills.activated",
                f"{self.other_skill_id}.activate",
                f"{self.other_skill_id}:HelloWorldIntent",
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

            # verify that "session" is injected
            # (missing in utterance message) and kept in all messages
            for m in messages[1:]:
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

            # verify answer from skill that it does not want to converse
            self.assertEqual(messages[4].msg_type, "skill.converse.request")
            self.assertEqual(messages[4].data["skill_id"], self.skill_id)
            self.assertEqual(messages[5].msg_type, "skill.converse.response")
            self.assertEqual(messages[5].data["skill_id"], self.skill_id)
            self.assertFalse(messages[5].data["result"])  # does not want to converse

            # verify skill is activated by intent service (intent pipeline matched)
            self.assertEqual(messages[6].msg_type, "intent.service.skills.activated")
            self.assertEqual(messages[6].data["skill_id"], self.other_skill_id)
            self.assertEqual(messages[7].msg_type, f"{self.other_skill_id}.activate")

            # verify intent triggers
            self.assertEqual(messages[8].msg_type, f"{self.other_skill_id}:HelloWorldIntent")
            # verify skill_id is now present in every message.context
            for m in messages[8:]:
                self.assertEqual(m.context["skill_id"], self.other_skill_id)

            # verify intent execution
            self.assertEqual(messages[9].msg_type, "mycroft.skill.handler.start")
            self.assertEqual(messages[9].data["name"], "HelloWorldSkill.handle_hello_world_intent")
            self.assertEqual(messages[10].msg_type, "enclosure.active_skill")
            self.assertEqual(messages[10].data["skill_id"], self.other_skill_id)
            self.assertEqual(messages[11].msg_type, "speak")
            self.assertEqual(messages[11].data["lang"], "en-us")
            self.assertFalse(messages[11].data["expect_response"])
            self.assertEqual(messages[11].data["meta"]["skill"], self.other_skill_id)
            self.assertEqual(messages[12].msg_type, "mycroft.skill.handler.complete")
            self.assertEqual(messages[12].data["name"], "HelloWorldSkill.handle_hello_world_intent")

            # verify default session is now updated
            self.assertEqual(messages[13].msg_type, "ovos.session.update_default")
            self.assertEqual(messages[13].data["session_data"]["session_id"], "default")
            # test deserialization of payload
            sess = Session.deserialize(messages[13].data["session_data"])
            self.assertEqual(sess.session_id, "default")

            # test that active skills list has been updated
            self.assertEqual(sess.active_skills[0][0], self.other_skill_id)
            self.assertEqual(sess.active_skills[1][0], self.skill_id)
            self.assertEqual(messages[13].data["session_data"]["active_skills"][0][0], self.other_skill_id)
            self.assertEqual(messages[13].data["session_data"]["active_skills"][1][0], self.skill_id)

            messages = []

        hello_world()

        # trigger skill intent that makes it return True in next converse
        # verify active skills list gets swapped (test, hello)
        def skill_converse_yes():
            nonlocal messages

            utt = Message("recognizer_loop:utterance",
                          {"utterances": ["yes"]})  # converse returns True
            self.core.bus.emit(utt)

            # confirm all expected messages are sent
            expected_messages = [
                "recognizer_loop:utterance",  # no session
                "skill.converse.ping",  # default session injected
                "skill.converse.pong",
                "skill.converse.pong",
                "skill.converse.request",
                "skill.converse.response",  # does not want to converse
                # skill selected
                "intent.service.skills.activated",
                f"{self.skill_id}.activate",
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

            # verify that "session" is injected
            # (missing in utterance message) and kept in all messages
            for m in messages[1:]:
                self.assertEqual(m.context["session"]["session_id"], "default")

            # verify that "lang" is injected by converse.ping
            # (missing in utterance message) and kept in all messages
            self.assertEqual(messages[1].msg_type, "skill.converse.ping")
            for m in messages[1:]:
                self.assertEqual(m.context["lang"], "en-us")

            # verify "pong" answer from both skills
            self.assertEqual(messages[2].msg_type, "skill.converse.pong")
            self.assertEqual(messages[3].msg_type, "skill.converse.pong")
            self.assertEqual(messages[2].data["skill_id"],messages[2].context["skill_id"])
            self.assertEqual(messages[3].data["skill_id"], messages[3].context["skill_id"])
            # assert it reports converse method has been implemented by skill
            if messages[2].data["skill_id"] == self.skill_id: # we dont know order of pong responses
                self.assertTrue(messages[2].data["can_handle"])
                self.assertFalse(messages[3].data["can_handle"])
            if messages[3].data["skill_id"] == self.skill_id: # we dont know order of pong responses
                self.assertTrue(messages[3].data["can_handle"])
                self.assertFalse(messages[2].data["can_handle"])

            # verify answer from skill that it does not want to converse
            self.assertEqual(messages[4].msg_type, "skill.converse.request")
            self.assertEqual(messages[4].data["skill_id"], self.skill_id)
            self.assertEqual(messages[5].msg_type, "skill.converse.response")
            self.assertEqual(messages[5].data["skill_id"], self.skill_id)
            self.assertFalse(messages[5].data["result"])  # do not want to converse

            # verify skill is activated by intent service (intent pipeline matched)
            self.assertEqual(messages[6].msg_type, "intent.service.skills.activated")
            self.assertEqual(messages[6].data["skill_id"], self.skill_id)
            self.assertEqual(messages[7].msg_type, f"{self.skill_id}.activate")

            # verify intent triggers
            self.assertEqual(messages[8].msg_type, f"{self.skill_id}:converse_on.intent")
            # verify skill_id is now present in every message.context
            for m in messages[8:]:
                self.assertEqual(m.context["skill_id"], self.skill_id)

            # verify intent execution
            self.assertEqual(messages[9].msg_type, "mycroft.skill.handler.start")
            self.assertEqual(messages[9].data["name"], "TestAbortSkill.handle_converse_on")
            self.assertEqual(messages[10].msg_type, "enclosure.active_skill")
            self.assertEqual(messages[10].data["skill_id"], self.skill_id)
            self.assertEqual(messages[11].msg_type, "speak")
            self.assertEqual(messages[11].data["lang"], "en-us")
            self.assertFalse(messages[11].data["expect_response"])
            self.assertEqual(messages[11].data["meta"]["skill"], self.skill_id)
            self.assertEqual(messages[12].msg_type, "mycroft.skill.handler.complete")
            self.assertEqual(messages[12].data["name"], "TestAbortSkill.handle_converse_on")

            # verify default session is now updated
            self.assertEqual(messages[13].msg_type, "ovos.session.update_default")
            self.assertEqual(messages[13].data["session_data"]["session_id"], "default")
            # test deserialization of payload
            sess = Session.deserialize(messages[13].data["session_data"])
            self.assertEqual(sess.session_id, "default")

            # test that active skills list has been updated
            self.assertEqual(sess.active_skills[0][0], self.skill_id)
            self.assertEqual(sess.active_skills[1][0], self.other_skill_id)
            self.assertEqual(messages[13].data["session_data"]["active_skills"][0][0], self.skill_id)
            self.assertEqual(messages[13].data["session_data"]["active_skills"][1][0], self.other_skill_id)

            messages = []

        skill_converse_yes()

        # test converse capture, hello world utterance wont reach hello world skill
        def converse_capture():
            nonlocal messages
            utt = Message("recognizer_loop:utterance",
                          {"utterances": ["hello world"]})
            self.core.bus.emit(utt)

            # confirm all expected messages are sent
            expected_messages = [
                "recognizer_loop:utterance",  # no session
                "skill.converse.ping",  # default session injected
                "skill.converse.pong",
                "skill.converse.pong",
                "skill.converse.request",
                "skill.converse.response",  # CONVERSED
                # skill selected
                "intent.service.skills.activated",
                f"{self.skill_id}.activate",
                # session updated
                "ovos.session.update_default"
            ]
            wait_for_n_messages(len(expected_messages))

            self.assertEqual(len(expected_messages), len(messages))

            mtypes = [m.msg_type for m in messages]
            for m in expected_messages:
                print(m)
                self.assertTrue(m in mtypes)

            # verify that "session" is injected
            # (missing in utterance message) and kept in all messages
            for m in messages[1:]:
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

            # verify answer from skill that it does not want to converse
            self.assertEqual(messages[4].msg_type, "skill.converse.request")
            self.assertEqual(messages[4].data["skill_id"], self.skill_id)
            self.assertEqual(messages[5].msg_type, "skill.converse.response")
            self.assertEqual(messages[5].data["skill_id"], self.skill_id)
            self.assertTrue(messages[5].data["result"])  # CONVERSED

            # verify skill is activated by intent service (intent pipeline matched)
            self.assertEqual(messages[6].msg_type, "intent.service.skills.activated")
            self.assertEqual(messages[6].data["skill_id"], self.skill_id)
            self.assertEqual(messages[7].msg_type, f"{self.skill_id}.activate")

            # verify default session is now updated
            self.assertEqual(messages[8].msg_type, "ovos.session.update_default")
            self.assertEqual(messages[8].data["session_data"]["session_id"], "default")
            # test deserialization of payload
            sess = Session.deserialize(messages[8].data["session_data"])
            self.assertEqual(sess.session_id, "default")

            # test that active skills list has been updated
            self.assertEqual(sess.active_skills[0][0], self.skill_id)
            self.assertEqual(sess.active_skills[1][0], self.other_skill_id)
            self.assertEqual(messages[8].data["session_data"]["active_skills"][0][0], self.skill_id)
            self.assertEqual(messages[8].data["session_data"]["active_skills"][1][0], self.other_skill_id)

            messages = []

        converse_capture()

        def external_deactivate():
            nonlocal messages

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

        external_deactivate()

        def external_activate():
            nonlocal messages

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
                "ovos.session.update_default",
                "active_skill_request",  # backwards compat namespace classic core
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

        external_activate()

