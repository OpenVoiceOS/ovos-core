import time
from time import sleep
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ovos_utils.ocp import PlayerState, MediaState
from ocp_pipeline.opm import OCPPlayerProxy
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
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            f"{self.skill_id}:HelloWorldIntent",
            "mycroft.skill.handler.start",
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
        self.assertEqual(messages[-3].data["meta"]["dialog"], "hello.world")

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


class TestOCP(TestCase):

    def setUp(self):
        self.skill_id = "skill-fake-fm.openvoiceos"
        self.core = get_minicroft([self.skill_id])

    def tearDown(self) -> None:
        self.core.stop()

    def test_ocp(self):
        self.assertIsNotNone(self.core.intent_service.ocp)
        messages = []

        def new_msg(msg):
            nonlocal messages
            m = Message.deserialize(msg)
            if m.msg_type in ["ovos.skills.settings_changed", "gui.status.request"]:
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

        sess = Session("test-session",
                       pipeline=[
                           "ocp_high"
                       ])
        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=True,
            player_state=PlayerState.STOPPED, media_state=MediaState.NO_MEDIA)
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["play Fake FM"]},  # auto derived from skill class name in this case
                      {"session": sess.serialize(),
                       })
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "ovos.common_play.status",
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:play",
            "enclosure.active_skill",
            "speak",
            "ovos.common_play.search.start",
            "enclosure.mouth.think",
            "ovos.common_play.search.stop",  # any ongoing previous search
            f"ovos.common_play.query.{self.skill_id}",  # explicitly search skill
            # skill searching (explicit)
            "ovos.common_play.skill.search_start",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.skill.search_end",
            "ovos.common_play.search.end",
            # good results
            "ovos.common_play.reset",
            "add_context",  # NowPlaying context
            "ovos.common_play.play",  # OCP api
            "ovos.common_play.search.populate",
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        ########################################
        # skill in blacklist - generic search
        messages = []
        sess.blacklisted_skills = [self.skill_id]

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["play some radio station"]},
                      {"session": sess.serialize()})
        self.core.bus.emit(utt)

        # confirm complete intent failure
        expected_messages = [
            "recognizer_loop:utterance",
            "ovos.common_play.status",
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:play",
            "enclosure.active_skill",
            "speak",
            "ovos.common_play.search.start",
            "enclosure.mouth.think",
            "ovos.common_play.search.stop",  # any ongoing previous search
            f"ovos.common_play.query",
            # skill searching
            "ovos.common_play.skill.search_start",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.skill.search_end",
            "ovos.common_play.search.end",
            'ovos.common_play.reset',
            # playback failure - would play if not blacklisted
            "enclosure.active_skill",
            "speak",  # "dialog":"cant.play"
            "ovos.utterance.handled"
        ]

        wait_for_n_messages(len(expected_messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        ########################################
        # skill in blacklist - search by name
        messages = []
        sess.blacklisted_skills = [self.skill_id]

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["play Fake FM"]},
                      {"session": sess.serialize()})
        self.core.bus.emit(utt)

        # confirm complete intent failure
        expected_messages = [
            "recognizer_loop:utterance",
            "ovos.common_play.status",
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:play",
            "enclosure.active_skill",
            "speak",
            "ovos.common_play.search.start",
            "enclosure.mouth.think",
            "ovos.common_play.search.stop",  # any ongoing previous search
            f"ovos.common_play.query",  # NOT explicitly searching skill, unlike first test
            # skill searching (generic)
            "ovos.common_play.skill.search_start",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.skill.search_end",
            "ovos.common_play.search.end",
            'ovos.common_play.reset',
            # playback failure
            "enclosure.active_skill",
            "speak",  # "dialog":"cant.play"
            "ovos.utterance.handled"
        ]

        wait_for_n_messages(len(expected_messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])


class TestFallback(TestCase):

    def setUp(self):
        self.skill_id = "skill-ovos-fallback-unknown.openvoiceos"
        self.core = get_minicroft(self.skill_id)

    def tearDown(self) -> None:
        self.core.stop()

    def test_fallback(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"
        SessionManager.default_session.pipeline = [
            "fallback_high"
        ]
        messages = []

        def new_msg(msg):
            nonlocal messages
            m = Message.deserialize(msg)
            if m.msg_type in ["ovos.skills.settings_changed",
                              "ovos.common_play.status"]:
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

        sess = Session("123")
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["invalid"]},
                      {"session": sess.serialize()})
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
            "enclosure.active_skill",
            "speak",
            # activated only after skill return True
            "intent.service.skills.activate",
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            f"ovos.skills.fallback.{self.skill_id}.response",
            "ovos.utterance.handled"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        messages = []
        sess.blacklisted_skills = [self.skill_id]
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["invalid"]},
                      {"session": sess.serialize()})
        self.core.bus.emit(utt)

        # confirm intent failure
        expected_messages = [
            "recognizer_loop:utterance",
            "mycroft.audio.play_sound",
            "complete_intent_failure",
            "ovos.utterance.handled"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])


class TestCommonQuery(TestCase):

    def setUp(self):
        self.skill_id = "ovos-skill-fakewiki.openvoiceos"
        self.core = get_minicroft(self.skill_id)
        # self.core.intent_service.common_qa.common_query_skills = [self.skill_id]

    def tearDown(self) -> None:
        self.core.stop()

    def test_common_qa(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"
        SessionManager.default_session.pipeline = ["common_qa"]
        messages = []

        def new_msg(msg):
            nonlocal messages
            m = Message.deserialize(msg)
            if m.msg_type in ["ovos.skills.settings_changed",
                              "ovos.common_play.status"]:
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
                       blacklisted_skills=[],
                       pipeline=["common_qa"])
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["what is the speed of light"]},
                      {"session": sess.serialize()})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "enclosure.mouth.think",
            "question:query",
            "question:query.response",  # searching
            "question:query.response",  # response
            "enclosure.mouth.reset",
            "question:action",
            "intent.service.skills.activate",
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            "enclosure.active_skill",
            "speak",  # answer
            "enclosure.active_skill",
            "speak",  # callback
            "mycroft.skill.handler.complete",
            "ovos.utterance.handled"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        messages = []
        sess.blacklisted_skills = [self.skill_id]
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["invalid"]},
                      {"session": sess.serialize()})
        self.core.bus.emit(utt)

        # confirm intent failure
        expected_messages = [
            "recognizer_loop:utterance",
            "mycroft.audio.play_sound",
            "complete_intent_failure",
            "ovos.utterance.handled"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])
