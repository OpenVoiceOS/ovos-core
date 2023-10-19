import time
from time import sleep
from unittest import TestCase, skip

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ..minicroft import get_minicroft


class TestSessions(TestCase):

    def setUp(self):
        self.skill_id = "skill-ovos-hello-world.openvoiceos"
        self.core = get_minicroft(self.skill_id)

    def tearDown(self) -> None:
        self.core.stop()

    def test_complete_failure(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"
        SessionManager.default_session.active_skills = [(self.skill_id, time.time())]
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
            # Converse
            f"{self.skill_id}.converse.ping",
            "skill.converse.pong",
            # FallbackV1
            "mycroft.skills.fallback",
            "mycroft.skill.handler.start",
            "mycroft.skill.handler.complete",
            "mycroft.skills.fallback.response",

            "mycroft.skills.fallback",
            "mycroft.skill.handler.start",
            "mycroft.skill.handler.complete",
            "mycroft.skills.fallback.response",

            "mycroft.skills.fallback",
            "mycroft.skill.handler.start",
            "mycroft.skill.handler.complete",
            "mycroft.skills.fallback.response",
            # complete intent failure
            "mycroft.audio.play_sound",
            "complete_intent_failure",
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

        # verify ping/pong answer from hello world skill
        self.assertEqual(messages[1].msg_type, f"{self.skill_id}.converse.ping")
        self.assertEqual(messages[2].msg_type, "skill.converse.pong")
        self.assertEqual(messages[2].data["skill_id"], self.skill_id)
        self.assertEqual(messages[2].context["skill_id"], self.skill_id)
        self.assertFalse(messages[2].data["can_handle"])

        # high prio fallback
        self.assertEqual(messages[3].msg_type, "mycroft.skills.fallback")
        self.assertEqual(messages[3].data["fallback_range"], [0, 5])
        self.assertEqual(messages[4].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[4].data["handler"], "fallback")
        self.assertEqual(messages[5].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[5].data["handler"], "fallback")
        self.assertEqual(messages[6].msg_type, "mycroft.skills.fallback.response")
        self.assertFalse(messages[6].data["handled"])

        # medium prio fallback
        self.assertEqual(messages[7].msg_type, "mycroft.skills.fallback")
        self.assertEqual(messages[7].data["fallback_range"], [5, 90])
        self.assertEqual(messages[8].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[8].data["handler"], "fallback")
        self.assertEqual(messages[9].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[9].data["handler"], "fallback")
        self.assertEqual(messages[10].msg_type, "mycroft.skills.fallback.response")
        self.assertFalse(messages[10].data["handled"])

        # low prio fallback
        self.assertEqual(messages[11].msg_type, "mycroft.skills.fallback")
        self.assertEqual(messages[11].data["fallback_range"], [90, 101])
        self.assertEqual(messages[12].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[12].data["handler"], "fallback")
        self.assertEqual(messages[13].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[13].data["handler"], "fallback")
        self.assertEqual(messages[14].msg_type, "mycroft.skills.fallback.response")
        self.assertFalse(messages[14].data["handled"])

        # complete intent failure
        self.assertEqual(messages[15].msg_type, "mycroft.audio.play_sound")
        self.assertEqual(messages[15].data["uri"], "snd/error.mp3")
        self.assertEqual(messages[16].msg_type, "complete_intent_failure")

        # verify default session is now updated
        self.assertEqual(messages[17].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[17].data["session_data"]["session_id"], "default")

    @skip("TODO works if run standalone, otherwise has side effects in other tests")
    def test_complete_failure_lang_detect(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"
        SessionManager.default_session.active_skills = [(self.skill_id, time.time())]

        stt_lang_detect = "pt-pt"

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

        SessionManager.default_session.valid_languages = ["en-us", stt_lang_detect, "fr-fr"]
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["hello world"]},
                      {"session": SessionManager.default_session.serialize(),
                       "stt_lang": stt_lang_detect,  # lang detect plugin
                       "detected_lang": "not-valid"  # text lang detect
                       })
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "ovos.session.update_default",  # language changed
            f"{self.skill_id}.converse.ping",
            "skill.converse.pong",
            "mycroft.skills.fallback",
            "mycroft.skill.handler.start",
            "mycroft.skill.handler.complete",
            "mycroft.skills.fallback.response",
            "mycroft.skills.fallback",
            "mycroft.skill.handler.start",
            "mycroft.skill.handler.complete",
            "mycroft.skills.fallback.response",
            "mycroft.skills.fallback",
            "mycroft.skill.handler.start",
            "mycroft.skill.handler.complete",
            "mycroft.skills.fallback.response",
            "mycroft.audio.play_sound",
            "complete_intent_failure",
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
            self.assertEqual(m.context["stt_lang"], stt_lang_detect)
            self.assertEqual(m.context["detected_lang"], "not-valid")

        # verify session lang updated with pt-pt from lang disambiguation step
        self.assertEqual(messages[1].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[1].data["session_data"]["session_id"], "default")
        self.assertEqual(messages[1].data["session_data"]["lang"], stt_lang_detect)

        # verify ping/pong answer from hello world skill
        self.assertEqual(messages[2].msg_type, f"{self.skill_id}.converse.ping")
        self.assertEqual(messages[3].msg_type, "skill.converse.pong")
        self.assertEqual(messages[3].data["skill_id"], self.skill_id)
        self.assertEqual(messages[3].context["skill_id"], self.skill_id)
        self.assertFalse(messages[3].data["can_handle"])

        # verify fallback is triggered with pt-pt from lang disambiguation step
        self.assertEqual(messages[4].msg_type, "mycroft.skills.fallback")
        self.assertEqual(messages[4].data["lang"], stt_lang_detect)

        # high prio fallback
        self.assertEqual(messages[4].data["fallback_range"], [0, 5])
        self.assertEqual(messages[5].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[5].data["handler"], "fallback")
        self.assertEqual(messages[6].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[6].data["handler"], "fallback")
        self.assertEqual(messages[7].msg_type, "mycroft.skills.fallback.response")
        self.assertFalse(messages[7].data["handled"])

        # medium prio fallback
        self.assertEqual(messages[8].msg_type, "mycroft.skills.fallback")
        self.assertEqual(messages[8].data["lang"], stt_lang_detect)
        self.assertEqual(messages[8].data["fallback_range"], [5, 90])
        self.assertEqual(messages[9].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[9].data["handler"], "fallback")
        self.assertEqual(messages[10].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[10].data["handler"], "fallback")
        self.assertEqual(messages[11].msg_type, "mycroft.skills.fallback.response")
        self.assertFalse(messages[11].data["handled"])

        # low prio fallback
        self.assertEqual(messages[12].msg_type, "mycroft.skills.fallback")
        self.assertEqual(messages[12].data["lang"], stt_lang_detect)
        self.assertEqual(messages[12].data["fallback_range"], [90, 101])
        self.assertEqual(messages[13].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[13].data["handler"], "fallback")
        self.assertEqual(messages[14].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[14].data["handler"], "fallback")
        self.assertEqual(messages[15].msg_type, "mycroft.skills.fallback.response")
        self.assertFalse(messages[15].data["handled"])

        # complete intent failure
        self.assertEqual(messages[16].msg_type, "mycroft.audio.play_sound")
        self.assertEqual(messages[16].data["uri"], "snd/error.mp3")
        self.assertEqual(messages[17].msg_type, "complete_intent_failure")

        # verify default session is now updated
        self.assertEqual(messages[18].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[18].data["session_data"]["session_id"], "default")
        self.assertEqual(messages[18].data["session_data"]["lang"], "pt-pt")
        self.assertEqual(SessionManager.default_session.lang, "pt-pt")

        SessionManager.default_session.lang = "en-us"
