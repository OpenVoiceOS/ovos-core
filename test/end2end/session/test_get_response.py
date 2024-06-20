import time
from time import sleep
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ..minicroft import get_minicroft


class TestSessions(TestCase):

    def setUp(self):
        self.skill_id = "ovos-tskill-abort.openvoiceos"
        self.other_skill_id = "skill-ovos-hello-world.openvoiceos"
        self.core = get_minicroft([self.skill_id, self.other_skill_id])

    def tearDown(self) -> None:
        self.core.stop()

    def test_no_response(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"
        SessionManager.default_session.pipeline = [
                           "converse",
                           "padatious_high",
                           "adapt_high"
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

        def on_speak(msg):
            self.core.bus.emit(msg.forward("recognizer_loop:audio_output_start"))
            sleep(1)  # simulate TTS playback
            self.core.bus.emit(msg.forward("recognizer_loop:audio_output_end"))

        self.core.bus.on("message", new_msg)
        self.core.bus.on("speak", on_speak)

        # trigger get_response
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["test get response"]})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",  # trigger intent to start the test
            # skill selected
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            f"{self.skill_id}:test_get_response.intent",
            "mycroft.skill.handler.start",
            # intent code
            "skill.converse.get_response.enable",  # start of get_response
            "ovos.session.update_default",  # sync get_response status
            "enclosure.active_skill",
            "speak",  # 'mycroft.mic.listen' if no dialog passed to get_response
            "recognizer_loop:audio_output_start",
            "recognizer_loop:audio_output_end",

            # "recognizer_loop:utterance" would be here if user answered
            "skill.converse.get_response.disable",  # end of get_response
            "ovos.session.update_default",  # sync get_response status
            # intent code post self.get_response
            "enclosure.active_skill",  # from speak inside intent
            "speak",  # speak "ERROR" inside intent
            "recognizer_loop:audio_output_start",
            "recognizer_loop:audio_output_end",
            "mycroft.skill.handler.complete",  # original intent finished executing
            "ovos.utterance.handled",
            # session updated at end of intent pipeline
            "ovos.session.update_default"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        # verify that "session" is injected
        # (missing in utterance message) and kept in all messages
        for m in messages[1:]:
            self.assertEqual(m.context["session"]["session_id"], "default")
            self.assertEqual(m.context["lang"], "en-us")

        # verify intent triggers
        self.assertEqual(messages[3].msg_type, f"{self.skill_id}:test_get_response.intent")
        # verify skill_id is now present in every message.context
        for m in messages[1:]:
            self.assertEqual(m.context["skill_id"], self.skill_id)

        # verify intent execution
        self.assertEqual(messages[4].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[4].data["name"], "TestAbortSkill.handle_test_get_response")

        # verify skill is activated
        self.assertEqual(messages[1].msg_type, "intent.service.skills.activated")
        self.assertEqual(messages[1].data["skill_id"], self.skill_id)
        self.assertEqual(messages[2].msg_type, f"{self.skill_id}.activate")

        # enable get_response for this session
        self.assertEqual(messages[5].msg_type, "skill.converse.get_response.enable")
        self.assertEqual(messages[6].msg_type, "ovos.session.update_default")

        # question dialog
        self.assertEqual(messages[7].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[7].data["skill_id"], self.skill_id)
        self.assertEqual(messages[8].msg_type, "speak")
        self.assertEqual(messages[8].data["lang"], "en-us")
        self.assertTrue(messages[8].data["expect_response"])  # listen after dialog
        self.assertEqual(messages[8].data["meta"]["skill"], self.skill_id)
        self.assertEqual(messages[9].msg_type, "recognizer_loop:audio_output_start")
        self.assertEqual(messages[10].msg_type, "recognizer_loop:audio_output_end")

        # user response would be here

        # disable get_response for this session
        self.assertEqual(messages[11].msg_type, "skill.converse.get_response.disable")
        self.assertEqual(messages[12].msg_type, "ovos.session.update_default")

        # post self.get_response intent code
        self.assertEqual(messages[13].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[13].data["skill_id"], self.skill_id)
        self.assertEqual(messages[14].msg_type, "speak")
        self.assertEqual(messages[14].data["lang"], "en-us")
        self.assertFalse(messages[14].data["expect_response"])
        self.assertEqual(messages[14].data["utterance"], "ERROR")
        self.assertEqual(messages[14].data["meta"]["skill"], self.skill_id)

        self.assertEqual(messages[15].msg_type, "recognizer_loop:audio_output_start")
        self.assertEqual(messages[16].msg_type, "recognizer_loop:audio_output_end")

        self.assertEqual(messages[17].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[18].data["name"], "TestAbortSkill.handle_test_get_response")

        # verify default session is now updated
        self.assertEqual(messages[-1].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[-1].data["session_data"]["session_id"], "default")
        # test deserialization of payload
        sess = Session.deserialize(messages[-1].data["session_data"])
        self.assertEqual(sess.session_id, "default")

    def test_with_response(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"
        SessionManager.default_session.pipeline = [
                           "converse",
                           "padatious_high",
                           "adapt_high"
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

        def answer_get_response(msg):
            self.core.bus.emit(msg.forward("recognizer_loop:audio_output_start"))
            sleep(1)  # simulate TTS playback
            self.core.bus.emit(msg.forward("recognizer_loop:audio_output_end"))  # end wait=True in self.speak
            if msg.data["utterance"] == "give me an answer":
                sleep(0.5)
                utt = Message("recognizer_loop:utterance",
                              {"utterances": ["ok"]},
                              {"session": SessionManager.default_session.serialize()})
                self.core.bus.emit(utt)

        self.core.bus.on("speak", answer_get_response)

        # trigger get_response
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["test get response"]})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",  # trigger intent to start the test
            # skill selected
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            f"{self.skill_id}:test_get_response.intent",
            "mycroft.skill.handler.start",
            # intent code
            "skill.converse.get_response.enable",  # start of get_response
            "ovos.session.update_default",  # sync get_response status
            "enclosure.active_skill",
            "speak",  # 'mycroft.mic.listen' if no dialog passed to get_response
            "recognizer_loop:audio_output_start",
            "recognizer_loop:audio_output_end",

            "recognizer_loop:utterance",  # answer to get_response from user,
            # converse check
            f"{self.skill_id}.converse.ping",
            "skill.converse.pong",
            # get response handling
            f"{self.skill_id}.converse.get_response",  # returning user utterance to running intent self.get_response
            "ovos.session.update_default",  # sync skill activated by converse
            "skill.converse.get_response.disable",  # end of get_response
            "ovos.session.update_default",  # sync get_response status
            # intent code post self.get_response
            "enclosure.active_skill",  # from speak inside intent
            "speak",  # speak "ok" inside intent
            "recognizer_loop:audio_output_start",
            "recognizer_loop:audio_output_end",
            "mycroft.skill.handler.complete",  # original intent finished executing
            "ovos.utterance.handled",
            # session updated at end of intent pipeline
            "ovos.session.update_default"

        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        # verify skill is activated
        self.assertEqual(messages[1].msg_type, "intent.service.skills.activated")
        self.assertEqual(messages[1].data["skill_id"], self.skill_id)
        self.assertEqual(messages[2].msg_type, f"{self.skill_id}.activate")

        # verify that "session" is injected
        # (missing in utterance message) and kept in all messages
        for m in messages[1:]:
            self.assertEqual(m.context["session"]["session_id"], "default")

        # verify intent triggers
        self.assertEqual(messages[3].msg_type, f"{self.skill_id}:test_get_response.intent")

        # verify intent execution
        self.assertEqual(messages[4].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[4].data["name"], "TestAbortSkill.handle_test_get_response")


        # enable get_response for this session
        self.assertEqual(messages[5].msg_type, "skill.converse.get_response.enable")
        self.assertEqual(messages[6].msg_type, "ovos.session.update_default")

        # question dialog
        self.assertEqual(messages[7].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[7].data["skill_id"], self.skill_id)
        self.assertEqual(messages[8].msg_type, "speak")
        self.assertEqual(messages[8].data["utterance"], "give me an answer", )
        self.assertEqual(messages[8].data["lang"], "en-us")
        self.assertTrue(messages[8].data["expect_response"])  # listen after dialog
        self.assertEqual(messages[8].data["meta"]["skill"], self.skill_id)
        # ovos-audio speak execution (simulated)
        self.assertEqual(messages[9].msg_type, "recognizer_loop:audio_output_start")
        self.assertEqual(messages[10].msg_type, "recognizer_loop:audio_output_end")

        # check utterance goes through converse cycle
        self.assertEqual(messages[11].msg_type, "recognizer_loop:utterance")
        self.assertEqual(messages[12].msg_type, f"{self.skill_id}.converse.ping")
        self.assertEqual(messages[13].msg_type, "skill.converse.pong")

        # captured utterance sent to get_response handler that is waiting
        self.assertEqual(messages[14].msg_type, f"{self.skill_id}.converse.get_response")
        self.assertEqual(messages[14].data["utterances"], ["ok"])

        # converse pipeline activates the skill last_used timestamp
        self.assertEqual(messages[15].msg_type, "ovos.session.update_default")

        # disable get_response for this session
        self.assertEqual(messages[16].msg_type, "skill.converse.get_response.disable")
        self.assertEqual(messages[17].msg_type, "ovos.session.update_default")

        # post self.get_response intent code
        self.assertEqual(messages[18].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[18].data["skill_id"], self.skill_id)
        self.assertEqual(messages[19].msg_type, "speak")
        self.assertEqual(messages[19].data["lang"], "en-us")
        self.assertFalse(messages[19].data["expect_response"])
        self.assertEqual(messages[19].data["utterance"], "ok")
        self.assertEqual(messages[19].data["meta"]["skill"], self.skill_id)
        # ovos-audio speak execution (simulated)
        self.assertEqual(messages[20].msg_type, "recognizer_loop:audio_output_start")
        self.assertEqual(messages[21].msg_type, "recognizer_loop:audio_output_end")

        self.assertEqual(messages[22].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[22].data["name"], "TestAbortSkill.handle_test_get_response")

        # verify default session is now updated
        self.assertEqual(messages[-1].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[-1].data["session_data"]["session_id"], "default")
        # test deserialization of payload
        sess = Session.deserialize(messages[-1].data["session_data"])
        self.assertEqual(sess.session_id, "default")

    def test_cancel_response(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"
        SessionManager.default_session.pipeline = [
                           "converse",
                           "padatious_high",
                           "adapt_high"]

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

        def answer_get_response(msg):
            self.core.bus.emit(msg.forward("recognizer_loop:audio_output_start"))
            sleep(1)  # simulate TTS playback
            self.core.bus.emit(msg.forward("recognizer_loop:audio_output_end"))  # end wait=True in self.speak
            if msg.data["utterance"] == "give me an answer":
                sleep(0.5)
                utt = Message("recognizer_loop:utterance",
                              {"utterances": ["cancel"]},
                              {"session": SessionManager.default_session.serialize()})
                self.core.bus.emit(utt)

        self.core.bus.on("speak", answer_get_response)

        # trigger get_response
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["test get response"]})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",  # trigger intent to start the test
            # skill selected
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            f"{self.skill_id}:test_get_response.intent",
            "mycroft.skill.handler.start",
            # intent code
            "skill.converse.get_response.enable",  # start of get_response
            "ovos.session.update_default",  # sync get_response status
            "enclosure.active_skill",
            "speak",  # 'mycroft.mic.listen' if no dialog passed to get_response
            "recognizer_loop:audio_output_start",
            "recognizer_loop:audio_output_end",

            "recognizer_loop:utterance",  # answer to get_response from user,
            # converse check
            f"{self.skill_id}.converse.ping",
            "skill.converse.pong",
            # get response handling
            f"{self.skill_id}.converse.get_response",  # returning user utterance to running intent self.get_response
            "ovos.session.update_default",  # sync skill activated by converse
            "skill.converse.get_response.disable",  # end of get_response
            "ovos.session.update_default",  # sync get_response status
            # intent code post self.get_response
            "enclosure.active_skill",  # from speak inside intent
            "speak",  # speak "ERROR" inside intent
            "recognizer_loop:audio_output_start",
            "recognizer_loop:audio_output_end",
            "mycroft.skill.handler.complete",  # original intent finished executing

            "ovos.utterance.handled",  # handle_utterance returned (intent service)
            # session updated at end of intent pipeline
            "ovos.session.update_default"

        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        # verify that "session" is injected
        # (missing in utterance message) and kept in all messages
        for m in messages[1:]:
            self.assertEqual(m.context["session"]["session_id"], "default")

        # verify intent triggers
        self.assertEqual(messages[3].msg_type, f"{self.skill_id}:test_get_response.intent")

        # verify intent execution
        self.assertEqual(messages[4].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[4].data["name"], "TestAbortSkill.handle_test_get_response")

        # verify skill is activated
        self.assertEqual(messages[1].msg_type, "intent.service.skills.activated")
        self.assertEqual(messages[1].data["skill_id"], self.skill_id)
        self.assertEqual(messages[2].msg_type, f"{self.skill_id}.activate")

        # enable get_response for this session
        self.assertEqual(messages[5].msg_type, "skill.converse.get_response.enable")
        self.assertEqual(messages[6].msg_type, "ovos.session.update_default")

        # question dialog
        self.assertEqual(messages[7].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[7].data["skill_id"], self.skill_id)
        self.assertEqual(messages[8].msg_type, "speak")
        self.assertEqual(messages[8].data["utterance"], "give me an answer", )
        self.assertEqual(messages[8].data["lang"], "en-us")
        self.assertTrue(messages[8].data["expect_response"])  # listen after dialog
        self.assertEqual(messages[8].data["meta"]["skill"], self.skill_id)
        # ovos-audio speak execution (simulated)
        self.assertEqual(messages[9].msg_type, "recognizer_loop:audio_output_start")
        self.assertEqual(messages[10].msg_type, "recognizer_loop:audio_output_end")

        # check utterance goes through converse cycle
        self.assertEqual(messages[11].msg_type, "recognizer_loop:utterance")
        self.assertEqual(messages[12].msg_type, f"{self.skill_id}.converse.ping")
        self.assertEqual(messages[13].msg_type, "skill.converse.pong")

        # captured utterance sent to get_response handler that is waiting
        self.assertEqual(messages[14].msg_type, f"{self.skill_id}.converse.get_response")
        self.assertEqual(messages[14].data["utterances"], ["cancel"])  # was canceled by user, returned None

        # converse pipeline activates the skill last_used timestamp
        self.assertEqual(messages[15].msg_type, "ovos.session.update_default")

        # disable get_response for this session
        self.assertEqual(messages[16].msg_type, "skill.converse.get_response.disable")
        self.assertEqual(messages[17].msg_type, "ovos.session.update_default")

        # post self.get_response intent code
        self.assertEqual(messages[18].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[18].data["skill_id"], self.skill_id)
        self.assertEqual(messages[19].msg_type, "speak")
        self.assertEqual(messages[19].data["lang"], "en-us")
        self.assertFalse(messages[19].data["expect_response"])
        self.assertEqual(messages[19].data["utterance"], "ERROR")
        self.assertEqual(messages[19].data["meta"]["skill"], self.skill_id)
        # ovos-audio speak execution (simulated)
        self.assertEqual(messages[20].msg_type, "recognizer_loop:audio_output_start")
        self.assertEqual(messages[21].msg_type, "recognizer_loop:audio_output_end")

        self.assertEqual(messages[22].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[22].data["name"], "TestAbortSkill.handle_test_get_response")

        # verify default session is now updated
        self.assertEqual(messages[-1].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[-1].data["session_data"]["session_id"], "default")
        # test deserialization of payload
        sess = Session.deserialize(messages[-1].data["session_data"])
        self.assertEqual(sess.session_id, "default")

    def test_with_reprompt(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"
        SessionManager.default_session.pipeline = [
                           "converse",
                           "padatious_high",
                           "adapt_high"
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

        counter = 0

        def answer_get_response(msg):
            nonlocal counter
            counter += 1
            if counter == 3:  # answer on 3rd prompt only
                sleep(0.5)
                utt = Message("recognizer_loop:utterance",
                              {"utterances": ["ok"]},
                              {"session": SessionManager.default_session.serialize()})
                self.core.bus.emit(utt)

        self.core.bus.on("mycroft.mic.listen", answer_get_response)

        # trigger get_response
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["3 prompts"]})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",  # trigger intent to start the test
            # skill selected
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            f"{self.skill_id}:test_get_response3.intent",
            "mycroft.skill.handler.start",
            # intent code
            "skill.converse.get_response.enable",  # start of get_response
            "ovos.session.update_default",  # sync get_response status
            "mycroft.mic.listen",  # no dialog in self.get_response
            "mycroft.mic.listen",
            "mycroft.mic.listen",

            "recognizer_loop:utterance",  # answer to get_response from user,
            # converse check
            f"{self.skill_id}.converse.ping",
            "skill.converse.pong",
            # get response handling
            f"{self.skill_id}.converse.get_response",  # returning user utterance to running intent self.get_response
            "ovos.session.update_default",  # sync skill activated by converse
            "skill.converse.get_response.disable",  # end of get_response
            "ovos.session.update_default",  # sync get_response status
            # intent code post self.get_response
            "enclosure.active_skill",  # from speak inside intent
            "speak",  # speak "ok" inside intent
            "mycroft.skill.handler.complete",  # original intent finished executing

            "ovos.utterance.handled",  # handle_utterance returned (intent service)
            # session updated at end of intent pipeline
            "ovos.session.update_default"

        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        # verify that "session" is injected
        # (missing in utterance message) and kept in all messages
        for m in messages[1:]:
            self.assertEqual(m.context["session"]["session_id"], "default")

        # verify intent triggers
        self.assertEqual(messages[3].msg_type, f"{self.skill_id}:test_get_response3.intent")

        # verify intent execution
        self.assertEqual(messages[4].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[4].data["name"], "TestAbortSkill.handle_test_get_response3")

        # verify skill is activated
        self.assertEqual(messages[1].msg_type, "intent.service.skills.activated")
        self.assertEqual(messages[1].data["skill_id"], self.skill_id)
        self.assertEqual(messages[2].msg_type, f"{self.skill_id}.activate")

        # enable get_response for this session
        self.assertEqual(messages[5].msg_type, "skill.converse.get_response.enable")
        self.assertEqual(messages[6].msg_type, "ovos.session.update_default")

        # 3 sound prompts (no dialog in this test)
        self.assertEqual(messages[7].msg_type, "mycroft.mic.listen")
        self.assertEqual(messages[8].msg_type, "mycroft.mic.listen")
        self.assertEqual(messages[9].msg_type, "mycroft.mic.listen")

        # check utterance goes through converse cycle
        self.assertEqual(messages[10].msg_type, "recognizer_loop:utterance")
        self.assertEqual(messages[11].msg_type, f"{self.skill_id}.converse.ping")
        self.assertEqual(messages[12].msg_type, "skill.converse.pong")

        # captured utterance sent to get_response handler that is waiting
        self.assertEqual(messages[13].msg_type, f"{self.skill_id}.converse.get_response")
        self.assertEqual(messages[13].data["utterances"], ["ok"])
        self.assertEqual(messages[14].msg_type, "ovos.session.update_default")

        # disable get_response for this session
        self.assertEqual(messages[15].msg_type, "skill.converse.get_response.disable")
        self.assertEqual(messages[16].msg_type, "ovos.session.update_default")

        # post self.get_response intent code
        self.assertEqual(messages[17].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[17].data["skill_id"], self.skill_id)
        self.assertEqual(messages[18].msg_type, "speak")
        self.assertEqual(messages[18].data["lang"], "en-us")
        self.assertFalse(messages[18].data["expect_response"])
        self.assertEqual(messages[18].data["utterance"], "ok")
        self.assertEqual(messages[18].data["meta"]["skill"], self.skill_id)

        self.assertEqual(messages[19].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[19].data["name"], "TestAbortSkill.handle_test_get_response3")

        # verify default session is now updated
        self.assertEqual(messages[-1].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[-1].data["session_data"]["session_id"], "default")
        # test deserialization of payload
        sess = Session.deserialize(messages[-1].data["session_data"])
        self.assertEqual(sess.session_id, "default")

    def test_nested(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"
        SessionManager.default_session.pipeline = [
                           "converse",
                           "padatious_high",
                           "adapt_high"
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

        items = ["A", "B", "C"]

        def answer_get_response(msg):
            nonlocal items
            sleep(0.5)
            if not len(items):
                utt = Message("recognizer_loop:utterance",
                              {"utterances": ["cancel"]},
                              {"session": SessionManager.default_session.serialize()})
            else:
                utt = Message("recognizer_loop:utterance",
                              {"utterances": [items[0]]},
                              {"session": SessionManager.default_session.serialize()})
            self.core.bus.emit(utt)
            items = items[1:]

        self.core.bus.on("mycroft.mic.listen", answer_get_response)

        # trigger get_response
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["test get items"]})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",  # no session

            # skill selected
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",

            f"{self.skill_id}:test_get_response_cascade.intent",
            "mycroft.skill.handler.start",

            # intent code before self.get_response
            "enclosure.active_skill",
            "speak",  # "give me items"

            # first get_response
            "skill.converse.get_response.enable",  # start of get_response
            "ovos.session.update_default",  # sync get_response status
            "mycroft.mic.listen",  # no dialog in self.get_response
            "recognizer_loop:utterance",  # A
            f"{self.skill_id}.converse.ping",
            "skill.converse.pong",
            f"{self.skill_id}.converse.get_response",  # A
            "ovos.session.update_default",
            "skill.converse.get_response.disable",
            "ovos.session.update_default",  # sync get_response status

            # second get_response
            "skill.converse.get_response.enable",  # start of get_response
            "ovos.session.update_default",  # sync get_response status
            "mycroft.mic.listen",  # no dialog in self.get_response
            "recognizer_loop:utterance",  # B
            f"{self.skill_id}.converse.ping",
            "skill.converse.pong",
            f"{self.skill_id}.converse.get_response",  # B
            "ovos.session.update_default",  # sync skill trigger
            "skill.converse.get_response.disable",
            "ovos.session.update_default",  # sync get_response status

            # 3rd get_response
            "skill.converse.get_response.enable",  # start of get_response
            "ovos.session.update_default",  # sync get_response status
            "mycroft.mic.listen",  # no dialog in self.get_response
            "recognizer_loop:utterance",  # C
            f"{self.skill_id}.converse.ping",
            "skill.converse.pong",
            f"{self.skill_id}.converse.get_response",  # C
            "ovos.session.update_default",  # sync skill trigger
            "skill.converse.get_response.disable",
            "ovos.session.update_default",  # sync get_response status

            # cancel get_response
            "skill.converse.get_response.enable",  # start of get_response
            "ovos.session.update_default",  # sync get_response status
            "mycroft.mic.listen",  # no dialog in self.get_response
            "recognizer_loop:utterance",  # cancel
            f"{self.skill_id}.converse.ping",
            "skill.converse.pong",
            f"{self.skill_id}.converse.get_response",  # cancel
            "ovos.session.update_default",  # sync skill trigger
            "skill.converse.get_response.disable",
            "ovos.session.update_default",  # sync get_response status

            "skill_items",  # skill emitted message [A, B, C]

            "mycroft.skill.handler.complete",  # original intent finished executing

            "ovos.utterance.handled",  # handle_utterance returned (intent service)
            # session updated at end of intent pipeline
            "ovos.session.update_default"

        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        # verify that "session" is injected
        # (missing in utterance message) and kept in all messages
        for m in messages[1:]:
            self.assertEqual(m.context["session"]["session_id"], "default")

        # verify intent triggers
        self.assertEqual(messages[3].msg_type, f"{self.skill_id}:test_get_response_cascade.intent")

        # verify intent execution
        self.assertEqual(messages[4].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[4].data["name"], "TestAbortSkill.handle_test_get_response_cascade")

        # verify skill is activated
        self.assertEqual(messages[1].msg_type, "intent.service.skills.activated")
        self.assertEqual(messages[1].data["skill_id"], self.skill_id)
        self.assertEqual(messages[2].msg_type, f"{self.skill_id}.activate")

        # post self.get_response intent code
        self.assertEqual(messages[5].msg_type, "enclosure.active_skill")
        self.assertEqual(messages[5].data["skill_id"], self.skill_id)
        self.assertEqual(messages[6].msg_type, "speak")
        self.assertEqual(messages[6].data["lang"], "en-us")
        self.assertFalse(messages[6].data["expect_response"])
        self.assertEqual(messages[6].data["utterance"], "give me items")
        self.assertEqual(messages[6].data["meta"]["skill"], self.skill_id)

        responses = ["A", "B", "C", "cancel"]
        for response in responses:
            i = 6 + responses.index(response) * 10
            print(i, response)
            # enable get_response for this session
            self.assertEqual(messages[i + 1].msg_type, "skill.converse.get_response.enable")
            self.assertEqual(messages[i + 2].msg_type, "ovos.session.update_default")

            # 3 sound prompts (no dialog in this test)
            self.assertEqual(messages[i + 3].msg_type, "mycroft.mic.listen")

            # check utterance goes through converse cycle
            self.assertEqual(messages[i + 4].msg_type, "recognizer_loop:utterance")
            self.assertEqual(messages[i + 5].msg_type, f"{self.skill_id}.converse.ping")
            self.assertEqual(messages[i + 6].msg_type, "skill.converse.pong")

            # captured utterance sent to get_response handler that is waiting
            self.assertEqual(messages[i + 7].msg_type, f"{self.skill_id}.converse.get_response")
            self.assertEqual(messages[i + 7].data["utterances"], [response])

            # converse pipeline activates the skill last_used timestamp
            self.assertEqual(messages[i + 8].msg_type,  "ovos.session.update_default")

            # disable get_response for this session
            self.assertEqual(messages[i + 9].msg_type, "skill.converse.get_response.disable")
            self.assertEqual(messages[i + 10].msg_type, "ovos.session.update_default")

        # intent return
        self.assertEqual(messages[-4].msg_type, "skill_items")
        self.assertEqual(messages[-4].data, {"items": ["A", "B", "C"]})

        # report handler complete
        self.assertEqual(messages[-3].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[-3].data["name"], "TestAbortSkill.handle_test_get_response_cascade")

        self.assertEqual(messages[-1].msg_type, "ovos.session.update_default")
