import time
from time import sleep
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ..minicroft import get_minicroft


class TestSessions(TestCase):

    def setUp(self):
        self.skill_id = "skill-ovos-hello-world.openvoiceos"
        self.core = get_minicroft([self.skill_id])

    def tearDown(self) -> None:
        self.core.stop()

    def test_blacklist(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"
        SessionManager.default_session.pipeline = ["adapt_high"]
        SessionManager.default_session.blacklisted_skills = []
        SessionManager.default_session.blacklisted_intents = []

        messages = []

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

        ########################################
        # empty blacklist
        sess = Session("123")

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["hello world"]},
                      {"session": sess.serialize()})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            # skill selected
            f"{self.skill_id}:HelloWorldIntent",
            "mycroft.skill.handler.start",
            "intent.service.skills.activate",
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            # skill code executing
            "enclosure.active_skill",
            "speak",
            "mycroft.skill.handler.complete",
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]

        wait_for_n_messages(len(expected_messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        # sanity check correct intent triggered
        self.assertEqual(messages[7].data["meta"]["dialog"], "hello.world")

        ########################################
        # skill in blacklist
        messages = []
        sess.blacklisted_skills = [self.skill_id]

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["hello world"]},
                      {"session": sess.serialize()})
        self.core.bus.emit(utt)

        # confirm complete intent failure
        expected_messages = [
            "recognizer_loop:utterance",
            # complete intent failure
            "mycroft.audio.play_sound",
            "complete_intent_failure",
            "ovos.utterance.handled"
        ]

        wait_for_n_messages(len(expected_messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        ########################################
        # intent in blacklist
        messages = []
        sess.blacklisted_skills = []
        sess.blacklisted_intents = [f"{self.skill_id}:HelloWorldIntent"]

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["hello world"]},
                      {"session": sess.serialize()})
        self.core.bus.emit(utt)

        # confirm complete intent failure
        expected_messages = [
            "recognizer_loop:utterance",
            # complete intent failure
            "mycroft.audio.play_sound",
            "complete_intent_failure",
            "ovos.utterance.handled"
        ]

        wait_for_n_messages(len(expected_messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])
