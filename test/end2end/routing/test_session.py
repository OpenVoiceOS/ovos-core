import time
from time import sleep
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ..minicroft import get_minicroft


class TestRouting(TestCase):

    def setUp(self):
        self.skill_id = "skill-ovos-hello-world.openvoiceos"
        self.core = get_minicroft(self.skill_id)

    def tearDown(self) -> None:
        self.core.stop()

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
            print(len(messages), m.msg_type, m.context.get("source"), m.context.get("destination"))

        def wait_for_n_messages(n):
            nonlocal messages
            t = time.time()
            while len(messages) < n:
                sleep(0.1)
                if time.time() - t > 10:
                    raise RuntimeError("did not get the number of expected messages under 10 seconds")

        self.core.bus.on("message", new_msg)

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["hello world"]},
                      {"source": "A", "destination": "B"})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",  # no session
            "intent.service.skills.activated",  # default session injected
            f"{self.skill_id}.activate",
            f"{self.skill_id}:HelloWorldIntent",
            "mycroft.skill.handler.start",
            "enclosure.active_skill",
            "speak",
            "mycroft.skill.handler.complete",
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

        # verify that source an destination are kept until intent trigger
        for m in messages[:3]:
            self.assertEqual(m.context["source"], "A")
            self.assertEqual(m.context["destination"], "B")

        # verify that source and destination are swapped after intent trigger
        self.assertEqual(messages[3].msg_type, f"{self.skill_id}:HelloWorldIntent")
        for m in messages[3:]:
            self.assertEqual(m.context["source"], "B")
            self.assertEqual(m.context["destination"], "A")


