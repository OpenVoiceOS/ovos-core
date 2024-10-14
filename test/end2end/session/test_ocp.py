import time
from time import sleep
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.ocp import PlayerState, MediaState
from ocp_pipeline.opm import OCPPlayerProxy
from ovos_plugin_manager.ocp import available_extractors
from ..minicroft import get_minicroft


class TestOCPPipeline(TestCase):

    def setUp(self):
        self.skill_id = "skill-fake-fm.openvoiceos"
        self.core = get_minicroft(self.skill_id)

    def tearDown(self) -> None:
        self.core.stop()

    def test_no_match(self):
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
                           "converse",
                           "ocp_high"
                       ])
        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=True,
            player_state=PlayerState.STOPPED, media_state=MediaState.NO_MEDIA)
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["play unknown thing"]},
                      {"session": sess.serialize(),  # explicit
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
            "ovos.common_play.query",
            # skill searching (generic)
            "ovos.common_play.skill.search_start",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.skill.search_end",
            "ovos.common_play.search.end",
            # no good results
            "ovos.common_play.reset",
            "enclosure.active_skill",
            "speak",  # error,
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

    def test_player_info(self):
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

        sess = Session("test-session", pipeline=["ocp_high"])
        if sess.session_id in self.core.intent_service.ocp.ocp_sessions:
            self.core.intent_service.ocp.ocp_sessions.pop(sess.session_id)

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["play something"]},
                      {"session": sess.serialize(),  # explicit
                       })
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "ovos.common_play.status",
            "ovos.common_play.SEI.get",  # request player info
            # no response
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:play",
            "enclosure.active_skill",
            "speak",
            "ovos.common_play.search.start",
            "enclosure.mouth.think",
            "ovos.common_play.search.stop",  # any ongoing previous search
            "ovos.common_play.query",
            "ovos.common_play.skill.search_start",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.skill.search_end",
            "ovos.common_play.search.end",
            "ovos.common_play.reset",
            "enclosure.active_skill",
            "speak",  # nothing to play
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        self.assertFalse(self.core.intent_service.ocp.ocp_sessions[sess.session_id].ocp_available)
        self.assertEqual(self.core.intent_service.ocp.ocp_sessions[sess.session_id].available_extractors,
                         available_extractors())  # stream extractors handled in core before returning result

        # now test with OCP response
        messages = []

        def on_get(m):
            # response that OCP would emit if available
            self.core.bus.emit(m.response(data={"SEI": ["test"]}))

        self.core.bus.on("ovos.common_play.SEI.get", on_get)

        if sess.session_id in self.core.intent_service.ocp.ocp_sessions:
            self.core.intent_service.ocp.ocp_sessions.pop(sess.session_id)

        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "ovos.common_play.status",
            "ovos.common_play.SEI.get",  # request player info
            "ovos.common_play.SEI.get.response",  # OCP response
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:play",
            "enclosure.active_skill",
            "speak",
            "ovos.common_play.search.start",
            "enclosure.mouth.think",
            "ovos.common_play.search.stop",  # any ongoing previous search
            "ovos.common_play.query",
            "ovos.common_play.skill.search_start",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.query.response",
            "ovos.common_play.skill.search_end",
            "ovos.common_play.search.end",
            "ovos.common_play.reset",
            "enclosure.active_skill",
            "speak",  # nothing to play
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        self.assertTrue(self.core.intent_service.ocp.ocp_sessions[sess.session_id].ocp_available)
        self.assertEqual(self.core.intent_service.ocp.ocp_sessions[sess.session_id].available_extractors,
                         ["test"])

        # test OCP player state sync
        self.assertEqual(self.core.intent_service.ocp.ocp_sessions[sess.session_id].player_state,
                         PlayerState.STOPPED)
        messages = []
        utt = Message("ovos.common_play.status.response",
                      {"player_state": PlayerState.PLAYING.value},
                      {"session": sess.serialize(),  # explicit
                       })
        self.core.bus.emit(utt)

        self.assertEqual(self.core.intent_service.ocp.ocp_sessions[sess.session_id].player_state,
                         PlayerState.PLAYING)

    def test_radio_media_match(self):
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
                           "converse",
                           "ocp_high"
                       ])
        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=True,
            player_state=PlayerState.STOPPED, media_state=MediaState.NO_MEDIA)
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["play some radio station"]},
                      {"session": sess.serialize(),  # explicit
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
            "ovos.common_play.search.populate",
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        play = messages[-3]
        self.assertEqual(play.data["media"]["uri"], "https://fake_4.mp3")

    def test_unk_media_match(self):
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
                           "converse",
                           "ocp_high"
                       ])
        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=True,
            player_state=PlayerState.STOPPED, media_state=MediaState.NO_MEDIA)
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["play the alien movie"]},
                      {"session": sess.serialize(),  # explicit
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
            "ovos.common_play.search.stop",  # stop any ongoing previous search
            "ovos.common_play.query",  # generic media type, no movie skills available
            # skill searching (generic)
            "ovos.common_play.skill.search_start",
            "ovos.common_play.query.response",
            "ovos.common_play.skill.search_end",
            "ovos.common_play.search.end",
            # no good results
            "ovos.common_play.reset",
            "enclosure.active_skill",
            "speak",  # error
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

    def test_skill_name_match(self):
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
                           "converse",
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

    def test_legacy_match(self):
        self.assertIsNotNone(self.core.intent_service.ocp)
        self.core.intent_service.ocp.config = {"legacy": True}

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
                           "converse",
                           "ocp_high"
                       ])

        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=False,
            player_state=PlayerState.STOPPED, media_state=MediaState.NO_MEDIA)

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["play some radio station"]},
                      {"session": sess.serialize(),  # explicit
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
            'mycroft.audio.service.play',  # LEGACY api
            "ovos.common_play.search.populate",
            "ovos.utterance.handled",  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        ocp = self.core.intent_service.ocp.ocp_sessions[sess.session_id]
        self.assertEqual(ocp.player_state, PlayerState.PLAYING)
        self.assertEqual(ocp.media_state, MediaState.LOADING_MEDIA)

    def test_legacy_pause(self):
        self.assertIsNotNone(self.core.intent_service.ocp)
        self.core.intent_service.ocp.config = {"legacy": True}
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
                           "converse",
                           "ocp_high"
                       ])
        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=False,
            player_state=PlayerState.PLAYING, media_state=MediaState.LOADED_MEDIA)

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["pause"]},
                      {"session": sess.serialize(),  # explicit
                       })
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "ovos.common_play.status",
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:pause",
            'mycroft.audio.service.pause',  # LEGACY api
            "ovos.utterance.handled",  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        ocp = self.core.intent_service.ocp.ocp_sessions[sess.session_id]
        self.assertEqual(ocp.player_state, PlayerState.PAUSED)

    def test_legacy_resume(self):
        self.assertIsNotNone(self.core.intent_service.ocp)
        self.core.intent_service.ocp.config = {"legacy": True}

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
                           "converse",
                           "ocp_high"
                       ])

        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=False,
            player_state=PlayerState.PAUSED, media_state=MediaState.LOADED_MEDIA)
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["resume"]},
                      {"session": sess.serialize(),  # explicit
                       })
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "ovos.common_play.status",
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:resume",
            'mycroft.audio.service.resume',  # LEGACY api
            "ovos.utterance.handled",  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        ocp = self.core.intent_service.ocp.ocp_sessions[sess.session_id]
        self.assertEqual(ocp.player_state, PlayerState.PLAYING)

    def test_legacy_stop(self):
        self.assertIsNotNone(self.core.intent_service.ocp)
        self.core.intent_service.ocp.config = {"legacy": True}
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
                           "converse",
                           "ocp_high"
                       ])

        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=False,
            player_state=PlayerState.PLAYING, media_state=MediaState.LOADED_MEDIA)

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["stop"]},
                      {"session": sess.serialize(),  # explicit
                       })
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "ovos.common_play.status",
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:media_stop",
            'mycroft.audio.service.stop',  # LEGACY api
            "ovos.utterance.handled",  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        ocp = self.core.intent_service.ocp.ocp_sessions[sess.session_id]
        self.assertEqual(ocp.player_state, PlayerState.STOPPED)

    def test_legacy_next(self):
        self.assertIsNotNone(self.core.intent_service.ocp)
        self.core.intent_service.ocp.config = {"legacy": True}
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
                           "converse",
                           "ocp_high"
                       ])

        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=False,
            player_state=PlayerState.PLAYING, media_state=MediaState.LOADED_MEDIA)

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["next"]},
                      {"session": sess.serialize(),  # explicit
                       })
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "ovos.common_play.status",
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:next",
            'mycroft.audio.service.next',  # LEGACY api
            "ovos.utterance.handled",  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

    def test_legacy_prev(self):
        self.assertIsNotNone(self.core.intent_service.ocp)
        self.core.intent_service.ocp.config = {"legacy": True}
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
                           "converse",
                           "ocp_high"
                       ])
        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=False,
            player_state=PlayerState.PLAYING, media_state=MediaState.LOADED_MEDIA)
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["previous"]},
                      {"session": sess.serialize(),  # explicit
                       })
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "ovos.common_play.status",
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:prev",
            'mycroft.audio.service.prev',  # LEGACY api
            "ovos.utterance.handled",  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

    def test_pause(self):
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
                           "converse",
                           "ocp_high"
                       ])
        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=True,
            player_state=PlayerState.PLAYING, media_state=MediaState.LOADED_MEDIA)
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["pause"]},
                      {"session": sess.serialize(),  # explicit
                       })
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "ovos.common_play.status",
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:pause",
            'ovos.common_play.pause',
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

    def test_resume(self):
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
                           "converse",
                           "ocp_high"
                       ])

        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=True,
            player_state=PlayerState.PAUSED, media_state=MediaState.LOADED_MEDIA)
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["resume"]},
                      {"session": sess.serialize(),  # explicit
                       })
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "ovos.common_play.status",
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:resume",
            'ovos.common_play.resume',
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

    def test_stop(self):
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
                           "converse",
                           "ocp_high"
                       ])
        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=True,
            player_state=PlayerState.PLAYING, media_state=MediaState.LOADED_MEDIA)
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["stop"]},
                      {"session": sess.serialize(),  # explicit
                       })
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "ovos.common_play.status",
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:media_stop",
            'ovos.common_play.stop',
            "ovos.common_play.stop.response",
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

    def test_next(self):
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
                           "converse",
                           "ocp_high"
                       ])
        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=True,
            player_state=PlayerState.PLAYING, media_state=MediaState.LOADED_MEDIA)
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["next"]},
                      {"session": sess.serialize(),  # explicit
                       })
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "ovos.common_play.status",
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:next",
            'ovos.common_play.next',
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

    def test_prev(self):
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
                           "converse",
                           "ocp_high"
                       ])
        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=True,
            player_state=PlayerState.PLAYING, media_state=MediaState.LOADED_MEDIA)
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["previous"]},
                      {"session": sess.serialize(),  # explicit
                       })
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "ovos.common_play.status",
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:prev",
            'ovos.common_play.previous',
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

    def test_status_matches_not_playing(self):
        self.assertIsNotNone(self.core.intent_service.ocp)

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
                           "converse",
                           "ocp_high"
                       ])

        self.core.intent_service.ocp.ocp_sessions[sess.session_id] = OCPPlayerProxy(
            session_id=sess.session_id, available_extractors=[], ocp_available=True,
            player_state=PlayerState.STOPPED, media_state=MediaState.NO_MEDIA)

        # wont match unless PlayerState.Playing
        for t in ["pause", "resume", "stop", "next", "previous"]:
            messages = []

            utt = Message("recognizer_loop:utterance",
                          {"utterances": [t]},
                          {"session": sess.serialize(),  # explicit
                           })
            self.core.bus.emit(utt)

            # confirm all expected messages are sent
            expected_messages = [
                "recognizer_loop:utterance",
                "ovos.common_play.status",
                "mycroft.audio.play_sound",
                "complete_intent_failure",
                "ovos.utterance.handled"  # handle_utterance returned (intent service)
            ]
            wait_for_n_messages(len(expected_messages))

            self.assertEqual(len(expected_messages), len(messages))

            for idx, m in enumerate(messages):
                self.assertEqual(m.msg_type, expected_messages[idx])

    def test_legacy_cps(self):
        self.assertIsNotNone(self.core.intent_service.ocp)

        self.core.intent_service.ocp.config = {"legacy_cps": True}

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
                           "ocp_legacy"
                       ])
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["play rammstein"]},
                      {"session": sess.serialize(),  # explicit
                       })
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:legacy_cps",
            # legacy cps api
            "play:query",
            "mycroft.audio.play_sound",  # error -  no results
            "ovos.utterance.handled",  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])


class TestLegacyCPSPipeline(TestCase):

    def setUp(self):
        self.skill_id = "skill-fake-fm-legacy.openvoiceos"
        self.core = get_minicroft(self.skill_id)
        self.core.intent_service.ocp.config = {"legacy_cps": True}

    def tearDown(self) -> None:
        self.core.stop()

    def test_legacy_cps(self):
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
                           "ocp_legacy"
                       ])
        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["play rammstein"]},
                      {"session": sess.serialize(),  # explicit
                       })
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "intent.service.skills.activated",
            "ovos.common_play.activate",
            "ocp:legacy_cps",
            # legacy cps api
            "play:query",
            "play:query.response",  # searching
            "play:query.response",  # report results
            "play:start",  # skill selected
            "mycroft.audio.service.track_info",  # check is legacy audio service is playing
            # global stop signal
            "mycroft.stop",
            "common_query.openvoiceos.stop",
            "common_query.openvoiceos.stop.response",
            "ovos.common_play.stop",
            "ovos.common_play.stop.response",
            "skill-fake-fm-legacy.openvoiceos.stop",
            "skill-fake-fm-legacy.openvoiceos.stop.response",
            "mycroft.audio.service.track_info",  # check is legacy audio service is playing
            # activate skill
            "intent.service.skills.activate",
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            # skill callback code
            "mycroft.audio.service.play",
            "ovos.utterance.handled"  # handle_utterance returned (intent service)
        ]
        wait_for_n_messages(len(expected_messages))

        #self.assertEqual(len(expected_messages), len(messages))

        for idx, m in enumerate(messages):
            self.assertEqual(m.msg_type, expected_messages[idx])

        play = messages[-2]
        self.assertEqual(play.data["tracks"], ["https://fake.mp3"])
