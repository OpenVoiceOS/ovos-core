import time
from time import sleep
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from .minicroft import get_minicroft


class TestSessions(TestCase):

    def setUp(self):
        self.skill_id = "skill-ovos-schedule.openvoiceos"
        self.core = get_minicroft(self.skill_id)

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

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["schedule event"]})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",  # no session
            "intent.service.skills.activated",  # default session injected
            f"{self.skill_id}.activate",
            f"{self.skill_id}:ScheduleIntent",
            "mycroft.skill.handler.start",
            "enclosure.active_skill",
            "speak",
            "mycroft.scheduler.schedule_event",
            "mycroft.skill.handler.complete",
            "ovos.session.update_default",
            # event triggering after 3 seconds
            "skill-ovos-schedule.openvoiceos:my_event",
            "enclosure.active_skill",
            "speak"
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

        # verify skill is activated by intent service (intent pipeline matched)
        self.assertEqual(messages[1].msg_type, "intent.service.skills.activated")
        self.assertEqual(messages[1].data["skill_id"], self.skill_id)
        self.assertEqual(messages[2].msg_type, f"{self.skill_id}.activate")

        # verify intent triggers
        self.assertEqual(messages[3].msg_type, f"{self.skill_id}:ScheduleIntent")
        self.assertEqual(messages[3].data["intent_type"], f"{self.skill_id}:ScheduleIntent")
        # verify skill_id is now present in every message.context
        for m in messages[3:]:
            self.assertEqual(m.context["skill_id"], self.skill_id)

        # verify intent execution
        self.assertEqual(messages[4].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[4].data["name"], "ScheduleSkill.handle_sched_intent")
        self.assertEqual(messages[5].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[5].data["skill_id"], self.skill_id)
        self.assertEqual(messages[6].msg_type, "speak")
        self.assertEqual(messages[6].data["lang"], "en-us")
        self.assertFalse(messages[6].data["expect_response"])
        self.assertEqual(messages[6].data["meta"]["dialog"], "done")
        self.assertEqual(messages[6].data["meta"]["skill"], self.skill_id)
        self.assertEqual(messages[7].msg_type, "mycroft.scheduler.schedule_event")
        self.assertEqual(messages[8].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[8].data["name"], "ScheduleSkill.handle_sched_intent")

        # verify default session is now updated
        self.assertEqual(messages[9].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[9].data["session_data"]["session_id"], "default")
        # test deserialization of payload
        sess = Session.deserialize(messages[9].data["session_data"])
        self.assertEqual(sess.session_id, "default")

        # test that active skills list has been updated
        self.assertEqual(sess.active_skills[0][0], self.skill_id)
        self.assertEqual(messages[9].data["session_data"]["active_skills"][0][0], self.skill_id)

        # ensure context in triggered event is the same from message that triggered the intent
        intent_context = messages[3].context
        self.assertEqual(messages[10].msg_type, "skill-ovos-schedule.openvoiceos:my_event")
        self.assertEqual(messages[10].context, intent_context)
        self.assertEqual(messages[11].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[11].context, intent_context)
        self.assertEqual(messages[12].msg_type, "speak")
        self.assertEqual(messages[12].data["lang"], "en-us")
        self.assertFalse(messages[12].data["expect_response"])
        self.assertEqual(messages[12].data["meta"]["dialog"], "trigger")
        self.assertEqual(messages[12].data["meta"]["skill"], self.skill_id)
        self.assertEqual(messages[12].context, intent_context)

    def test_explicit_session(self):
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

        sess = Session()
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["schedule event"]},
                      {"session": sess.serialize()})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            f"{self.skill_id}:ScheduleIntent",
            "mycroft.skill.handler.start",
            "enclosure.active_skill",
            "speak",
            "mycroft.scheduler.schedule_event",
            "mycroft.skill.handler.complete",
            # event triggering after 3 seconds
            "skill-ovos-schedule.openvoiceos:my_event",
            "enclosure.active_skill",
            "speak"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        mtypes = [m.msg_type for m in messages]
        for m in expected_messages:
            self.assertTrue(m in mtypes)

        # verify that "session" is the same in all message
        # (missing in utterance message) and kept in all messages
        for m in messages:
            self.assertEqual(m.context["session"]["session_id"], sess.session_id)

        # verify skill is activated by intent service (intent pipeline matched)
        self.assertEqual(messages[1].msg_type, "intent.service.skills.activated")
        self.assertEqual(messages[1].data["skill_id"], self.skill_id)
        self.assertEqual(messages[2].msg_type, f"{self.skill_id}.activate")

        # verify intent triggers
        self.assertEqual(messages[3].msg_type, f"{self.skill_id}:ScheduleIntent")
        self.assertEqual(messages[3].data["intent_type"], f"{self.skill_id}:ScheduleIntent")
        # verify skill_id is now present in every message.context
        for m in messages[3:]:
            self.assertEqual(m.context["skill_id"], self.skill_id)

        # verify intent execution
        self.assertEqual(messages[4].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[4].data["name"], "ScheduleSkill.handle_sched_intent")
        self.assertEqual(messages[5].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[5].data["skill_id"], self.skill_id)
        self.assertEqual(messages[6].msg_type, "speak")
        self.assertEqual(messages[6].data["lang"], "en-us")
        self.assertFalse(messages[6].data["expect_response"])
        self.assertEqual(messages[6].data["meta"]["dialog"], "done")
        self.assertEqual(messages[6].data["meta"]["skill"], self.skill_id)
        self.assertEqual(messages[7].msg_type, "mycroft.scheduler.schedule_event")
        self.assertEqual(messages[8].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[8].data["name"], "ScheduleSkill.handle_sched_intent")

        # ensure context in triggered event is the same from message that triggered the intent
        intent_context = messages[3].context
        self.assertEqual(messages[9].msg_type, "skill-ovos-schedule.openvoiceos:my_event")
        self.assertEqual(messages[9].context, intent_context)
        self.assertEqual(messages[10].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[10].context, intent_context)
        self.assertEqual(messages[11].msg_type, "speak")
        self.assertEqual(messages[11].data["lang"], "en-us")
        self.assertFalse(messages[11].data["expect_response"])
        self.assertEqual(messages[11].data["meta"]["dialog"], "trigger")
        self.assertEqual(messages[11].data["meta"]["skill"], self.skill_id)
        self.assertEqual(messages[11].context, intent_context)

    def tearDown(self) -> None:
        self.core.stop()
