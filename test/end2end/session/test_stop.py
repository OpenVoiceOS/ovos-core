import time
from time import sleep
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ..minicroft import get_minicroft


class TestSessions(TestCase):

    def setUp(self):
        self.skill_id = "skill-old-stop.openvoiceos"
        self.new_skill_id = "skill-new-stop.openvoiceos"
        self.core = get_minicroft([self.skill_id, self.new_skill_id])

    def tearDown(self) -> None:
        self.core.stop()

    def test_old_stop(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-US"
        SessionManager.default_session.pipeline = [
            "stop_high",
            "adapt_high"
            "stop_medium"
        ]

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

        sess = Session("123",
                       pipeline=[
                           "stop_high",
                           "adapt_high",
                           "stop_medium"
                       ])
        ########################################
        # STEP 1
        # nothing to stop
        # old style global stop, even if nothing active
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["stop"]},
                      {"session": sess.serialize()})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            # global stop trigger
            "mycroft.stop",
            "common_query.openvoiceos.stop.response",
            "ovos.common_play.stop.response",
            f"{self.skill_id}.stop.response",
            # sanity check in test skill that method was indeed called
            "speak",  # "utterance":"old stop called"
            f"{self.new_skill_id}.stop.response", # nothing to stop

            "ovos.utterance.handled"
        ]

        wait_for_n_messages(len(expected_messages))

        mtypes = [m.msg_type for m in messages]
        for m in expected_messages:
            self.assertTrue(m in mtypes)

        # sanity check stop triggered
        for m in messages:
            if m.msg_type == "speak":
                self.assertEqual(m.data["utterance"], "old stop called")

        messages = []

        ########################################
        # STEP 2
        # get the skill in active list
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["old world"]},
                      {"session": sess.serialize()})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            # skill selected
            f"{self.skill_id}.activate",
            f"{self.skill_id}:OldWorldIntent",
            "mycroft.skill.handler.start",
            # skill code executing
            "speak",
            "mycroft.skill.handler.complete",
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]

        wait_for_n_messages(len(expected_messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        # sanity check correct intent triggered
        self.assertEqual(messages[-3].data["utterance"], "hello world")

        # test that active skills list has been updated
        sess = Session.deserialize(messages[-1].context["session"])
        self.assertEqual(sess.active_skills[0][0], self.skill_id)

        messages = []

        ########################################
        # STEP 3
        # stop should now go over active skills list
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["stop"]},
                      {"session": sess.serialize()})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",

            # stop_high
            f"{self.skill_id}.stop.ping",  # check if active skill wants to stop
            "skill.stop.pong",  # "can_handle":true
            f"{self.skill_id}.stop",  # skill specific stop trigger
            "speak",  # "old stop called" in the test skill stop method
            f"{self.skill_id}.stop.response",  # skill stops and reports back

            # skill reports it stopped, so core ensures any threaded activity is also killed
            "mycroft.skills.abort_question",  # core kills any ongoing get_response
            "ovos.skills.converse.force_timeout",  # core kills any ongoing converse
            "mycroft.audio.speech.stop",  # core kills any ongoing TTS

            f"{self.skill_id}.activate", # update of skill last usage timestamp
            "ovos.utterance.handled"

        ]

        wait_for_n_messages(len(expected_messages))

        mtypes = [m.msg_type for m in messages]
        for m in expected_messages:
            self.assertTrue(m in mtypes)

        # confirm all skills self.stop methods called
        for m in messages:
            # sanity check stop triggered
            if m.msg_type == "speak":
                self.assertIn(m.data["utterance"],
                              ["old stop called", "stop"])
            # confirm "skill-old-stop" was the one that reported success
            if m.msg_type == "mycroft.stop.handled":
                self.assertEqual(m.data["by"], f"skill:{self.skill_id}")

        messages = []

    def test_new_stop(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-US"
        SessionManager.default_session.pipeline = [
            "stop_high",
            "adapt_high",
            "stop_medium"
        ]

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

        sess = Session("123",
                       pipeline=[
                           "stop_high",
                           "adapt_high",
                           "stop_medium"
                       ])

        ########################################
        # STEP 1
        # no skills active yet, nothing to stop
        # old style global stop, even if nothing active
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["stop"]},
                      {"session": sess.serialize()})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            # global stop trigger
            "mycroft.stop",
            "common_query.openvoiceos.stop.response", # common_query framework reporting nothing to stop
            "ovos.common_play.stop.response",  # OCP framework reporting nothing to stop
            f"{self.skill_id}.stop.response",  # skill reporting nothing to stop

            # sanity check in test skill that method was indeed called
            "speak",  # "utterance":"old stop called"

            f"{self.new_skill_id}.stop.response",  # skill reporting it stopped

            "ovos.utterance.handled",

        ]

        wait_for_n_messages(len(expected_messages))

        mtypes = [m.msg_type for m in messages]
        for m in expected_messages:
            self.assertTrue(m in mtypes)

        for m in messages:
            # sanity check stop triggered
            if m.msg_type == "speak":
                self.assertEqual(m.data["utterance"], "old stop called")

        messages = []

        ########################################
        # STEP 2
        # get a skill in active list
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["new world"]},
                      {"session": sess.serialize()})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            # skill selected
            f"{self.new_skill_id}.activate",
            f"{self.new_skill_id}:NewWorldIntent",
            "mycroft.skill.handler.start",
            # skill code executing
            "speak",
            "mycroft.skill.handler.complete",
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]

        wait_for_n_messages(len(expected_messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        # sanity check correct intent triggered

        for m in messages:
            # sanity check stop triggered
            if m.msg_type == "speak":
                self.assertEqual(m.data["utterance"], "hello world")

        # test that active skills list has been updated
        sess = Session.deserialize(messages[-1].context["session"])
        self.assertEqual(sess.active_skills[0][0], self.new_skill_id)

        messages = []

        ########################################
        # STEP 3
        # we got active skills
        # stop should now go over active skills list
        # reports success
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["stop"]},
                      {"session": sess.serialize()})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",

            # stop_high
            f"{self.new_skill_id}.stop.ping",  # check if active skill wants to stop
            "skill.stop.pong",  # "can_handle":true
            f"{self.new_skill_id}.stop",  # skill specific stop trigger

            # test session specific stop was called
            "speak",  # "utterance":"stop 123"
            f"{self.new_skill_id}.stop.response",  # skill reports it stopped (new style),

            "mycroft.skills.abort_question", # core kills any ongoing get_response
            "ovos.skills.converse.force_timeout", # core kills any ongoing converse
            "mycroft.audio.speech.stop", # core kills any ongoing TTS
            f"{self.new_skill_id}.activate",  # update timestamp of last interaction with skill
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]

        wait_for_n_messages(len(expected_messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        # confirm skill self.stop methods called

        for m in messages:
            # sanity check stop triggered
            if m.msg_type == "speak":
                self.assertEqual(m.data["utterance"], "stop 123")

        # confirm "skill-new-stop" was the one that reported success
        handler = messages[-6]
        self.assertEqual(handler.msg_type, f"{self.new_skill_id}.stop.response")
        self.assertEqual(handler.data["result"], True)

        messages = []

        ########################################
        # STEP 4
        # skill already stopped
        # reports failure
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["stop"]},
                      {"session": sess.serialize()})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",

            # stop_high
            f"{self.new_skill_id}.stop.ping",  # check if active skill wants to stop
            "skill.stop.pong",  # "can_handle":true
            f"{self.new_skill_id}.stop",  # skill specific stop trigger
            "speak", # it's in the stop method even if it returns False!
            f"{self.new_skill_id}.stop.response",  # dont want to stop (new style)

            # rest of pipeline
            # stop low
            f"{self.new_skill_id}.stop.ping",
            "skill.stop.pong",
            f"{self.new_skill_id}.stop",  # skill specific stop trigger
            "speak", # it's in the stop method even if it returns False!
            f"{self.new_skill_id}.stop.response",  # dont want to stop (new style)

            # global stop fallback
            "mycroft.stop",
            "common_query.openvoiceos.stop.response", # dont want to stop
            "ovos.common_play.stop.response", # dont want to stop

            f"{self.skill_id}.stop.response",  # old style, never stops
            "speak", # it's in the stop method even if it returns False!
            f"{self.new_skill_id}.stop.response",  # dont want to stop (new style)

            "ovos.utterance.handled"
        ]

        wait_for_n_messages(len(expected_messages))

        mtypes = [m.msg_type for m in messages]
        for m in expected_messages:
            self.assertTrue(m in mtypes)

        # confirm self.stop method called
        for m in messages:
            # sanity check stop triggered
            if m.msg_type == "speak":
                self.assertEqual(m.data["utterance"], "old stop called")

        messages = []
