import time
from time import sleep
from unittest import TestCase
from ovos_core.intent_services.ocp_service import PlayerState, MediaState, OCPPlayerProxy

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
        SessionManager.pipeline = ["adapt_high"]

        messages = []

        def new_msg(msg):
            nonlocal messages
            m = Message.deserialize(msg)
            if m.msg_type in ["ovos.skills.settings_changed", "ovos.common_play.status"]:
                return  # skip these
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
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            f"{self.skill_id}:HelloWorldIntent",
            "mycroft.skill.handler.start",
            "enclosure.active_skill",
            "speak",
            "mycroft.skill.handler.complete",
            "ovos.utterance.handled",  # handle_utterance returned (intent service)
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

        # verify that source and destination are swapped after intent trigger
        self.assertEqual(messages[3].msg_type, f"{self.skill_id}:HelloWorldIntent")
        for m in messages:
            if m.msg_type in ["recognizer_loop:utterance", "ovos.session.update_default"]:
                self.assertEqual(messages[0].context["source"], "A")
                self.assertEqual(messages[0].context["destination"], "B")
            else:
                self.assertEqual(m.context["source"], "B")
                self.assertEqual(m.context["destination"], "A")


class TestOCPRouting(TestCase):

    def setUp(self):
        self.skill_id = "skill-fake-fm.openvoiceos"
        self.core = get_minicroft(self.skill_id)

    def tearDown(self) -> None:
        self.core.stop()

    def test_no_session(self):
        self.assertIsNotNone(self.core.intent_service.ocp)
        messages = []

        def new_msg(msg):
            nonlocal messages
            m = Message.deserialize(msg)
            if m.msg_type in ["gui.status.request",
                              "ovos.common_play.status",
                              "ovos.skills.settings_changed"]:
                return  # skip these
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

        sess = Session("test-session",
                       pipeline=[
                           "converse",
                           "ocp_high"
                       ])
        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=True,
            player_state=PlayerState.STOPPED, media_state=MediaState.NO_MEDIA)
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["play some radio station"]},
                      {"session": sess.serialize(),  # explicit
                       "source": "A", "destination": "B"})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:play",
            "enclosure.active_skill",
            "speak",
            "ovos.common_play.search.start",
            "enclosure.mouth.think",
            "ovos.common_play.search.stop",  # any ongoing previous search
            "ovos.common_play.query",  # media type radio
            # skill searching (radio)
            "ovos.common_play.skill.search_start",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.skill.search_end",
            "ovos.common_play.search.end",
            # good results because of radio media type
            "ovos.common_play.reset",
            "add_context",  # NowPlaying context
            "ovos.common_play.play",  # OCP api,
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        # verify that source and destination are swapped after utterance
        for m in messages:
            if m.msg_type in ["recognizer_loop:utterance"]:
                self.assertEqual(m.context["source"], "A")
                self.assertEqual(m.context["destination"], "B")
            elif m.msg_type in ["ovos.common_play.play",
                                "ovos.common_play.reset",
                                "ovos.common_play.query"]:
                # OCP messages that should make it to the client
                self.assertEqual(m.context["source"], "B")
                self.assertEqual(m.context["destination"], "A")
            elif m.msg_type.startswith("ovos.common_play"):
                # internal search messages, should not leak to external clients
                self.assertEqual(messages[0].context["source"], "A")
                self.assertEqual(messages[0].context["destination"], "B")
            else:
                self.assertEqual(m.context["source"], "B")
                self.assertEqual(m.context["destination"], "A")
