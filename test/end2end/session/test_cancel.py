import time
from time import sleep
from unittest import TestCase, skip

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ..minicroft import get_minicroft


class TestCancel(TestCase):

    def setUp(self):
        self.skill_id = "skill-ovos-hello-world.openvoiceos"
        self.core = get_minicroft(self.skill_id)

    def tearDown(self) -> None:
        self.core.stop()

    def test_cancel_plugin(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"
        SessionManager.default_session.active_skills = [(self.skill_id, time.time())]
        SessionManager.default_session.pipeline = [
                           "stop_high",
                           "converse",
                           "padatious_high",
                           "adapt_high",
                           "fallback_high",
                           "stop_medium",
                           "adapt_medium",
                           "padatious_medium",
                           "adapt_low",
                           "common_qa",
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
                      {"utterances": ["hello world , actually, cancel order"]},
                      {"session": SessionManager.default_session.serialize()})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "mycroft.audio.play_sound",
            "ovos.utterance.cancelled",
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        # verify that contexts are kept around
        for m in messages:
            self.assertEqual(m.context["session"]["session_id"], "default")

        # verify sound
        self.assertEqual(messages[1].data["uri"], "snd/cancel.mp3")

