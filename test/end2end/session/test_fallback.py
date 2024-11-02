import time
from time import sleep
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ..minicroft import get_minicroft


class TestFallback(TestCase):

    def setUp(self):
        self.skill_id = "skill-ovos-fallback-unknown.openvoiceos"
        self.core = get_minicroft(self.skill_id)

    def tearDown(self) -> None:
        self.core.stop()

    def test_fallback(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-US"
        SessionManager.default_session.pipeline = [
            "converse",
            "fallback_high",
            "fallback_medium",
            "fallback_low"
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

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["invalid"]},
                      {"session": SessionManager.default_session.serialize(),  # explicit default sess
                       "x": "xx"})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            # FallbackV2
            "ovos.skills.fallback.ping",
            "ovos.skills.fallback.pong",
            # skill executing
            f"ovos.skills.fallback.{self.skill_id}.request",
            f"ovos.skills.fallback.{self.skill_id}.start",
            "speak",
            f"ovos.skills.fallback.{self.skill_id}.response",
            # activated only after skill returns True
            f"{self.skill_id}.activate",
            "ovos.utterance.handled",  # handle_utterance returned (intent service)
            "ovos.session.update_default"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        # verify that contexts are kept around
        for m in messages:
            self.assertEqual(m.context["session"]["session_id"], "default")
            self.assertEqual(m.context["x"], "xx")
        # verify active skills is empty until "intent.service.skills.activated"
        for m in messages[:7]:
            self.assertEqual(m.context["session"]["session_id"], "default")
            self.assertEqual(m.context["session"]["active_skills"], [])

        # verify fallback ping/pong answer from skill
        self.assertEqual(messages[1].msg_type, "ovos.skills.fallback.ping")
        self.assertEqual(messages[2].msg_type, "ovos.skills.fallback.pong")
        self.assertEqual(messages[2].data["skill_id"], self.skill_id)
        self.assertEqual(messages[2].context["skill_id"], self.skill_id)
        self.assertTrue(messages[2].data["can_handle"])

        # verify skill executes
        self.assertEqual(messages[3].msg_type, f"ovos.skills.fallback.{self.skill_id}.request")
        self.assertEqual(messages[3].data["skill_id"], self.skill_id)
        self.assertEqual(messages[4].msg_type, f"ovos.skills.fallback.{self.skill_id}.start")
        self.assertEqual(messages[5].msg_type, "speak")
        self.assertEqual(messages[5].data["meta"]["dialog"], "unknown")
        self.assertEqual(messages[5].data["meta"]["skill"], self.skill_id)

        # end of fallback
        self.assertEqual(messages[6].msg_type, f"ovos.skills.fallback.{self.skill_id}.response")
        self.assertTrue(messages[6].data["result"])
        self.assertEqual(messages[6].data["fallback_handler"], "UnknownSkill.handle_fallback")

        # verify default session is now updated
        self.assertEqual(messages[-1].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[-1].data["session_data"]["session_id"], "default")

        # test second message with no session resumes default active skills
        messages = []
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["invalid"]})
        self.core.bus.emit(utt)
        # converse ping/pong due being active
        expected_messages.extend([f"{self.skill_id}.converse.ping", "skill.converse.pong"])

        wait_for_n_messages(len(expected_messages))
        self.assertEqual(len(expected_messages), len(messages))

        # verify that contexts are kept around
        for m in messages[1:]:
            self.assertEqual(m.context["session"]["session_id"], "default")
            self.assertEqual(m.context["session"]["active_skills"][0][0], self.skill_id)

    def test_fallback_with_session(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-US"
        SessionManager.default_session.pipeline = [
            "fallback_high",
            "fallback_medium",
            "fallback_low"
        ]
        messages = []

        sess = Session(pipeline=[
            "fallback_high",
            "fallback_medium",
            "fallback_low"
        ])

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

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["invalid"]},
                      {"session": sess.serialize(),  # explicit sess
                       "x": "xx"})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            # FallbackV2
            "ovos.skills.fallback.ping",
            "ovos.skills.fallback.pong",
            # skill executing - TODO "mycroft.skill.handler.start" +  "mycroft.skill.handler.complete" should be added
            f"ovos.skills.fallback.{self.skill_id}.request",
            f"ovos.skills.fallback.{self.skill_id}.start",

            "speak",
            f"ovos.skills.fallback.{self.skill_id}.response",
            f"{self.skill_id}.activate",
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))
        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        # verify that contexts are kept around
        for m in messages:
            self.assertEqual(m.context["session"]["session_id"], sess.session_id)
            self.assertEqual(m.context["x"], "xx")

        # verify fallback ping/pong answer from skill
        self.assertEqual(messages[1].msg_type, "ovos.skills.fallback.ping")
        self.assertEqual(messages[2].msg_type, "ovos.skills.fallback.pong")
        self.assertEqual(messages[2].data["skill_id"], self.skill_id)
        self.assertEqual(messages[2].context["skill_id"], self.skill_id)
        self.assertTrue(messages[2].data["can_handle"])

        # verify skill executes
        self.assertEqual(messages[3].msg_type, f"ovos.skills.fallback.{self.skill_id}.request")
        self.assertEqual(messages[3].data["skill_id"], self.skill_id)
        self.assertEqual(messages[4].msg_type, f"ovos.skills.fallback.{self.skill_id}.start")
        self.assertEqual(messages[5].msg_type, "speak")
        self.assertEqual(messages[5].data["meta"]["dialog"], "unknown")
        self.assertEqual(messages[5].data["meta"]["skill"], self.skill_id)
        self.assertEqual(messages[6].msg_type, f"ovos.skills.fallback.{self.skill_id}.response")
        self.assertTrue(messages[6].data["result"])
        self.assertEqual(messages[6].data["fallback_handler"], "UnknownSkill.handle_fallback")

        # test that active skills list has been updated
        for m in messages[10:]:
            self.assertEqual(m.context["session"]["active_skills"][0][0], self.skill_id)

    def test_deactivate_in_fallback(self):
        messages = []

        sess = Session("123")
        sess.activate_skill(self.skill_id)  # skill is active

        def new_msg(msg):
            nonlocal messages
            m = Message.deserialize(msg)
            if m.msg_type in ["ovos.skills.settings_changed", "ovos.common_play.status"]:
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

        utt = Message("fallback_deactivate")
        self.core.bus.emit(utt)  # set internal test skill flag
        messages = []

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["deactivate fallback"]},
                      {"session":sess.serialize()})
        self.core.bus.emit(utt)

        expected_messages = [
            "recognizer_loop:utterance",
            # skill is active, so we get converse events
            f"{self.skill_id}.converse.ping",
            "skill.converse.pong",
            # FallbackV2
            "ovos.skills.fallback.ping",
            "ovos.skills.fallback.pong",
            # skill executing
            f"ovos.skills.fallback.{self.skill_id}.request",
            f"ovos.skills.fallback.{self.skill_id}.start",

            "speak",
            # deactivate skill in fallback handler
            "intent.service.skills.deactivate",
            "intent.service.skills.deactivated",
            f"{self.skill_id}.deactivate",
            # activate events suppressed
            f"ovos.skills.fallback.{self.skill_id}.response",
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))
        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])


class TestFallbackTimeout(TestCase):

    def setUp(self):
        self.skill_id = "skill-ovos-fallback-unknown.openvoiceos"
        self.skill_id2 = "ovos-skill-slow-fallback.openvoiceos"
        self.core = get_minicroft([self.skill_id, self.skill_id2])

    def tearDown(self) -> None:
        self.core.stop()

    def test_fallback(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-US"
        SessionManager.default_session.pipeline = [
            "fallback_medium",
            "fallback_low"
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

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["invalid"]},
                      {"session": SessionManager.default_session.serialize()})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            # Fallback High
            "ovos.skills.fallback.ping",
            "ovos.skills.fallback.pong",
            "ovos.skills.fallback.pong",

            # slow skill executing
            f"ovos.skills.fallback.{self.skill_id2}.request",
            f"ovos.skills.fallback.{self.skill_id2}.start",
            "ovos.skills.fallback.force_timeout",  # timeout from core
            f"ovos.skills.fallback.{self.skill_id2}.response",
            f"ovos.skills.fallback.{self.skill_id2}.killed",  # killable_event decorator response

            # Fallback Medium
            "ovos.skills.fallback.ping",
            "ovos.skills.fallback.pong",
            "ovos.skills.fallback.pong",

            # skill executing
            f"ovos.skills.fallback.{self.skill_id}.request",
            f"ovos.skills.fallback.{self.skill_id}.start",
            "speak",
            f"ovos.skills.fallback.{self.skill_id}.response",

            # activated only after skill return True
            f"{self.skill_id}.activate",
            "ovos.utterance.handled",  # handle_utterance returned (intent service)
            "ovos.session.update_default"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])
