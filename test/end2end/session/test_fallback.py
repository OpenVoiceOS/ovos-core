from time import sleep
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from .minicroft import get_minicroft


class TestFallback(TestCase):

    def setUp(self):
        self.skill_id = "skill-ovos-fallback-unknown.openvoiceos"
        self.core = get_minicroft(self.skill_id)

    def test_fallback(self):
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
            while len(messages) < n:
                sleep(0.1)

        self.core.bus.on("message", new_msg)

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["invalid"]},
                      {"session": SessionManager.default_session.serialize(),  # explicit default sess
                       "x": "xx"})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            # Converse
            "skill.converse.ping",
            "skill.converse.pong",
            # FallbackV2
            "ovos.skills.fallback.ping",
            "ovos.skills.fallback.pong",
            # skill executing
            f"ovos.skills.fallback.{self.skill_id}.request",
            f"ovos.skills.fallback.{self.skill_id}.start",
            "enclosure.active_skill",
            "speak",
            f"ovos.skills.fallback.{self.skill_id}.response",
            # intent service post fallback
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            "ovos.session.update_default"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        mtypes = [m.msg_type for m in messages]
        for m in expected_messages:
            self.assertTrue(m in mtypes)

        # verify that contexts are kept around
        for m in messages:
            self.assertEqual(m.context["session"]["session_id"], "default")
            self.assertEqual(m.context["x"], "xx")
        # verify active skills is empty until "intent.service.skills.activated"
        for m in messages[:10]:
            self.assertEqual(m.context["session"]["session_id"], "default")
            self.assertEqual(m.context["session"]["active_skills"], [])

        # verify converse ping/pong answer from skill
        self.assertEqual(messages[1].msg_type, "skill.converse.ping")
        self.assertEqual(messages[2].msg_type, "skill.converse.pong")
        self.assertEqual(messages[2].data["skill_id"], self.skill_id)
        self.assertEqual(messages[2].context["skill_id"], self.skill_id)
        self.assertFalse(messages[2].data["can_handle"])

        # verify fallback ping/pong answer from skill
        self.assertEqual(messages[3].msg_type, "ovos.skills.fallback.ping")
        self.assertEqual(messages[4].msg_type, "ovos.skills.fallback.pong")
        self.assertEqual(messages[4].data["skill_id"], self.skill_id)
        self.assertEqual(messages[4].context["skill_id"], self.skill_id)
        self.assertTrue(messages[4].data["can_handle"])

        # verify skill executes
        self.assertEqual(messages[5].msg_type, f"ovos.skills.fallback.{self.skill_id}.request")
        self.assertEqual(messages[5].data["skill_id"], self.skill_id)
        self.assertEqual(messages[6].msg_type, f"ovos.skills.fallback.{self.skill_id}.start")
        self.assertEqual(messages[7].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[7].data["skill_id"], self.skill_id)
        self.assertEqual(messages[8].msg_type, "speak")
        self.assertEqual(messages[8].data["meta"]["dialog"], "unknown")
        self.assertEqual(messages[8].data["meta"]["skill"], self.skill_id)
        self.assertEqual(messages[9].msg_type, f"ovos.skills.fallback.{self.skill_id}.response")
        self.assertTrue(messages[9].data["result"])
        self.assertEqual(messages[9].data["fallback_handler"], "UnknownSkill.handle_fallback")

        # verify skill is activated
        self.assertEqual(messages[10].msg_type, "intent.service.skills.activated")
        self.assertEqual(messages[10].data["skill_id"], self.skill_id)
        self.assertEqual(messages[11].msg_type, f"{self.skill_id}.activate")

        # verify default session is now updated
        self.assertEqual(messages[12].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[12].data["session_data"]["session_id"], "default")

        # test second message with no session resumes default active skills
        messages = []
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["invalid"]})
        self.core.bus.emit(utt)
        wait_for_n_messages(len(expected_messages))
        self.assertEqual(len(expected_messages), len(messages))

        # verify that contexts are kept around
        for m in messages[1:]:
            self.assertEqual(m.context["session"]["session_id"], "default")
            self.assertEqual(m.context["session"]["active_skills"][0][0], self.skill_id)

    def test_fallback_with_session(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"
        messages = []

        sess = Session()

        def new_msg(msg):
            nonlocal messages
            m = Message.deserialize(msg)
            if m.msg_type in ["ovos.skills.settings_changed"]:
                return  # skip these, only happen in 1st run
            messages.append(m)
            print(len(messages), msg)

        def wait_for_n_messages(n):
            nonlocal messages
            while len(messages) < n:
                sleep(0.1)

        self.core.bus.on("message", new_msg)

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["invalid"]},
                      {"session": sess.serialize(),  # explicit sess
                       "x": "xx"})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            # Converse
            "skill.converse.ping",
            "skill.converse.pong",
            # FallbackV2
            "ovos.skills.fallback.ping",
            "ovos.skills.fallback.pong",
            # skill executing - TODO "mycroft.skill.handler.start" +  "mycroft.skill.handler.complete" should be added
            f"ovos.skills.fallback.{self.skill_id}.request",
            f"ovos.skills.fallback.{self.skill_id}.start",
            "enclosure.active_skill",
            "speak",
            f"ovos.skills.fallback.{self.skill_id}.response",
            # intent service post fallback
            "intent.service.skills.activated",
            f"{self.skill_id}.activate"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        mtypes = [m.msg_type for m in messages]
        for m in expected_messages:
            self.assertTrue(m in mtypes)

        # verify that contexts are kept around
        for m in messages:
            self.assertEqual(m.context["session"]["session_id"], sess.session_id)
            self.assertEqual(m.context["x"], "xx")

        # verify converse ping/pong answer from skill
        self.assertEqual(messages[1].msg_type, "skill.converse.ping")
        self.assertEqual(messages[2].msg_type, "skill.converse.pong")
        self.assertEqual(messages[2].data["skill_id"], self.skill_id)
        self.assertEqual(messages[2].context["skill_id"], self.skill_id)
        self.assertFalse(messages[2].data["can_handle"])

        # verify fallback ping/pong answer from skill
        self.assertEqual(messages[3].msg_type, "ovos.skills.fallback.ping")
        self.assertEqual(messages[4].msg_type, "ovos.skills.fallback.pong")
        self.assertEqual(messages[4].data["skill_id"], self.skill_id)
        self.assertEqual(messages[4].context["skill_id"], self.skill_id)
        self.assertTrue(messages[4].data["can_handle"])

        # verify skill executes
        self.assertEqual(messages[5].msg_type, f"ovos.skills.fallback.{self.skill_id}.request")
        self.assertEqual(messages[5].data["skill_id"], self.skill_id)
        self.assertEqual(messages[6].msg_type, f"ovos.skills.fallback.{self.skill_id}.start")
        self.assertEqual(messages[7].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[7].data["skill_id"], self.skill_id)
        self.assertEqual(messages[8].msg_type, "speak")
        self.assertEqual(messages[8].data["meta"]["dialog"], "unknown")
        self.assertEqual(messages[8].data["meta"]["skill"], self.skill_id)
        self.assertEqual(messages[9].msg_type, f"ovos.skills.fallback.{self.skill_id}.response")
        self.assertTrue(messages[9].data["result"])
        self.assertEqual(messages[9].data["fallback_handler"], "UnknownSkill.handle_fallback")

        # verify skill is activated
        self.assertEqual(messages[10].msg_type, "intent.service.skills.activated")
        self.assertEqual(messages[10].data["skill_id"], self.skill_id)
        self.assertEqual(messages[11].msg_type, f"{self.skill_id}.activate")

        # test that active skills list has been updated
        sess = SessionManager.sessions[sess.session_id]
        self.assertEqual(sess.active_skills[0][0], self.skill_id)
        # test that default session remains unchanged
        self.assertEqual(SessionManager.default_session.active_skills, [])
