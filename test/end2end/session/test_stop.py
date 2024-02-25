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
        SessionManager.default_session.lang = "en-us"
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

        # old style global stop, even if nothing active
        def skill_not_active():
            nonlocal messages, sess
            utt = Message("recognizer_loop:utterance",
                          {"utterances": ["stop"]},
                          {"session": sess.serialize()})
            self.core.bus.emit(utt)

            A = ['recognizer_loop:utterance',
             'mycroft.stop',
             'ovos.common_play.stop',
             'ovos.common_play.stop.response',
             'skill-new-stop.openvoiceos.stop',
             'skill-new-stop.openvoiceos.stop.response',
             'enclosure.active_skill',
             'speak',
             'skill-old-stop.openvoiceos.stop',
             'skill-old-stop.openvoiceos.stop.response']
            # confirm all expected messages are sent
            expected_messages = [
                "recognizer_loop:utterance",
                # global stop trigger
                "mycroft.stop",
                # ocp reporting nothing to stop
                "ovos.common_play.stop",
                "ovos.common_play.stop.response",

                # skill reporting
                f"{self.skill_id}.stop",  # internal, @killable_events
                f"{self.skill_id}.stop.response",  # skill reporting nothing to stop

                # sanity check in test skill that method was indeed called
                "enclosure.active_skill",
                "speak",  # "utterance":"old stop called"

                # NOTE: messages below might show up before enclosure.active_skill
                f"{self.new_skill_id}.stop",  # internal, @killable_events
                f"{self.new_skill_id}.stop.response",  # skill reporting nothing to stop

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

        # get the skill in active list
        def old_world():
            nonlocal messages, sess
            utt = Message("recognizer_loop:utterance",
                          {"utterances": ["old world"]},
                          {"session": sess.serialize()})
            self.core.bus.emit(utt)

            # confirm all expected messages are sent
            expected_messages = [
                "recognizer_loop:utterance",
                # skill selected
                "intent.service.skills.activated",
                f"{self.skill_id}.activate",
                f"{self.skill_id}:OldWorldIntent",
                # skill executing
                "mycroft.skill.handler.start",
                "enclosure.active_skill",
                "speak",
                "mycroft.skill.handler.complete"
            ]

            wait_for_n_messages(len(expected_messages))

            mtypes = [m.msg_type for m in messages]
            for m in expected_messages:
                self.assertTrue(m in mtypes)

            # sanity check correct intent triggered
            self.assertEqual(messages[6].data["utterance"], "hello world")

            # test that active skills list has been updated
            sess = Session.deserialize(messages[-1].context["session"])
            self.assertEqual(sess.active_skills[0][0], self.skill_id)

            messages = []

        # stop should now go over active skills list
        def skill_active():
            nonlocal messages, sess
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
                f"{self.skill_id}.stop.response",  # skill fails to stop  (old style)

                # stop medium
                f"{self.skill_id}.stop.ping",
                "skill.stop.pong",
                f"{self.skill_id}.stop",  # skill specific stop trigger
                f"{self.skill_id}.stop.response",  # skill fails to stop  (old style)

                # stop fallback
                "mycroft.stop",  # global stop for backwards compat
                "ovos.common_play.stop",  # ocp stop ping
                "ovos.common_play.stop.response",  # ocp nothing to stop
                f"{self.skill_id}.stop",
                f"{self.skill_id}.stop.response",  # apparently fails to stop  (old style)

                # test in skill that global stop was called
                "enclosure.active_skill",
                "speak",  # "utterance":"stop"

                # report old-style stop handled event
                "mycroft.stop.handled",  # {"by":"skill:skill-old-stop.openvoiceos"}

                # old style unwanted side effects (global stop is global)
                f"{self.new_skill_id}.stop",
                f"{self.new_skill_id}.stop.response",
                "enclosure.active_skill",  # other test skill also speaks
                "speak"  # "utterance":"old stop called"
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

        # nothing to stop
        skill_not_active()

        # get the skill in active list
        old_world()
        skill_active()

    def test_new_stop(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"
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

        # old style global stop, even if nothing active
        def skill_not_active():
            nonlocal messages, sess
            utt = Message("recognizer_loop:utterance",
                          {"utterances": ["stop"]},
                          {"session": sess.serialize()})
            self.core.bus.emit(utt)

            # confirm all expected messages are sent
            expected_messages = [
                "recognizer_loop:utterance",
                # global stop trigger
                "mycroft.stop",
                "ovos.common_play.stop",
                "ovos.common_play.stop.response",
                f"{self.skill_id}.stop",  # internal, @killable_events
                f"{self.skill_id}.stop.response",  # skill reporting nothing to stop
                f"{self.new_skill_id}.stop",  # internal, @killable_events
                f"{self.new_skill_id}.stop.response",  # skill reporting nothing to stop

                # sanity check in test skill that method was indeed called
                "enclosure.active_skill",
                "speak"  # "utterance":"old stop called"

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

        # get the skill in active list
        def new_world():
            nonlocal messages, sess
            utt = Message("recognizer_loop:utterance",
                          {"utterances": ["new world"]},
                          {"session": sess.serialize()})
            self.core.bus.emit(utt)

            # confirm all expected messages are sent
            expected_messages = [
                "recognizer_loop:utterance",
                # skill selected
                "intent.service.skills.activated",
                f"{self.new_skill_id}.activate",
                f"{self.new_skill_id}:NewWorldIntent",
                # skill executing
                "mycroft.skill.handler.start",
                "enclosure.active_skill",
                "speak",
                "mycroft.skill.handler.complete"
            ]

            wait_for_n_messages(len(expected_messages))

            mtypes = [m.msg_type for m in messages]
            for m in expected_messages:
                self.assertTrue(m in mtypes)

            # sanity check correct intent triggered

            for m in messages:
                # sanity check stop triggered
                if m.msg_type == "speak":
                    self.assertEqual(m.data["utterance"], "hello world")

            # test that active skills list has been updated
            sess = Session.deserialize(messages[-1].context["session"])
            self.assertEqual(sess.active_skills[0][0], self.new_skill_id)

            messages = []

        # stop should now go over active skills list
        def skill_active():
            nonlocal messages, sess
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
                "enclosure.active_skill",
                "speak",  # "utterance":"stop 123"

                f"{self.new_skill_id}.stop.response",  # skill reports it stopped (new style)
                "intent.service.skills.activated",  # pipeline match reports skill_id
                f"{self.new_skill_id}.activate",  # can now converse
            ]

            wait_for_n_messages(len(expected_messages))

            mtypes = [m.msg_type for m in messages]
            for m in expected_messages:
                self.assertTrue(m in mtypes)

            # confirm skill self.stop methods called

            for m in messages:
                # sanity check stop triggered
                if m.msg_type == "speak":
                    self.assertEqual(m.data["utterance"], "stop 123")

            # confirm "skill-new-stop" was the one that reported success
            handler = messages[-3]
            self.assertEqual(handler.msg_type, f"{self.new_skill_id}.stop.response")
            self.assertEqual(handler.data["result"], True)

            messages = []

        def skill_already_stop():
            nonlocal messages, sess
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
                f"{self.new_skill_id}.stop.response",  # dont want to stop (new style)

                # rest of pipeline
                # stop low
                f"{self.new_skill_id}.stop.ping",
                "skill.stop.pong",
                f"{self.new_skill_id}.stop",  # skill specific stop trigger
                f"{self.new_skill_id}.stop.response",  # dont want to stop (new style)

                # global stop fallback
                "mycroft.stop",
                "ovos.common_play.stop",
                "ovos.common_play.stop.response",
                f"{self.skill_id}.stop",  # skill specific stop trigger
                f"{self.skill_id}.stop.response",  # old style, never stops
                f"{self.new_skill_id}.stop",  # skill specific stop trigger
                f"{self.skill_id}.stop.response",  # dont want to stop (new style)

                # check the global stop handlers are called
                "enclosure.active_skill",
                "speak",  # "utterance":"old stop called"
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

        # nothing to stop
        skill_not_active()

        # get the skill in active list
        new_world()
        skill_active()  # reports success

        skill_already_stop()  # reports failure
