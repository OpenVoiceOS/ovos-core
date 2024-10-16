import time
from time import sleep
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ..minicroft import get_minicroft


class TestSched(TestCase):

    def setUp(self):
        self.skill_id = "skill-ovos-schedule.openvoiceos"
        self.core = get_minicroft(self.skill_id)

    def test_no_session(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-US"
        SessionManager.pipeline = ["adapt_high"]

        messages = []

        def new_msg(msg):
            nonlocal messages
            m = Message.deserialize(msg)
            if m.msg_type in ["ovos.skills.settings_changed", "ovos.common_play.status"]:
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
                      {"utterances": ["schedule event"]},
                      {"source": "A", "destination": "B"})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",  # no session
            "intent.service.skills.activated",  # response (from core)
            f"{self.skill_id}.activate",  # skill callback
            f"{self.skill_id}:ScheduleIntent",  # intent trigger
            "mycroft.skill.handler.start",  # intent code start
            "enclosure.active_skill",
            "speak",
            "mycroft.scheduler.schedule_event",

            "mycroft.skill.handler.complete",  # intent code end
            "ovos.utterance.handled",  # handle_utterance returned (intent service)
            "ovos.session.update_default",  # session update (end of utterance default sync)

            # skill event triggering after 3 seconds
            "skill-ovos-schedule.openvoiceos:my_event",
            "enclosure.active_skill",
            "speak"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        # verify that source and destination are swapped after intent trigger
        self.assertEqual(messages[3].msg_type, f"{self.skill_id}:ScheduleIntent")
        for m in messages:
            # messages FOR ovos-core
            if m.msg_type in ["recognizer_loop:utterance",
                              "ovos.session.update_default"]:
                self.assertEqual(messages[0].context["source"], "A")
                self.assertEqual(messages[0].context["destination"], "B")
            # messages FROM ovos-core
            else:
                self.assertEqual(m.context["source"], "B")
                self.assertEqual(m.context["destination"], "A")

    def tearDown(self) -> None:
        self.core.stop()
