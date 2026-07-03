# Copyright 2024 OpenVoiceOS
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest
from unittest.mock import MagicMock, patch, call
from threading import Event

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager, UtteranceState
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.stop_service import StopService

GLOBAL_STOP = f"{StopService.pipeline_id}:global_stop"


def _make_service() -> StopService:
    """Construct a StopService backed by a FakeBus."""
    bus = FakeBus()
    bus.connected_event = Event()
    bus.connected_event.set()
    with patch("ovos_core.intent_services.stop_service.ConfidenceMatcherPipeline.__init__",
               lambda self, *a, **kw: None):
        svc = StopService.__new__(StopService)
        svc.bus = bus
        svc.config = {}
        svc.suppress_activation = True
        # vocabulary matching is delegated to ovos-spec-tools LocaleResources;
        # tests patch svc._locale.voc_match / voc_list.
        svc._locale = MagicMock()
    return svc


class TestCollectStopSkills(unittest.TestCase):
    """Tests for _collect_stop_skills ping-pong mechanism."""

    def _session_with_skills(self, skill_ids):
        """Return a session that reports *skill_ids* as active."""
        sess = Session("test-session")
        for sid in skill_ids:
            sess.activate_skill(sid)
        return sess

    def test_no_active_skills_returns_empty(self):
        svc = _make_service()
        with patch.object(StopService, "get_active_skills", return_value=[]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get") as mock_get:
            mock_get.return_value = Session("s")
            result = svc._collect_stop_skills(Message("test"))
        self.assertEqual(result, [])

    def test_all_skills_say_can_stop(self):
        """Skills that respond with can_handle=True are returned."""
        svc = _make_service()
        sess = self._session_with_skills(["skill_a", "skill_b"])

        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)

        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == "skill.stop.pong":
                ack_handler = handler

        svc.bus.on = capture_on
        svc.bus.remove = MagicMock()

        with patch.object(StopService, "get_active_skills",
                          return_value=["skill_a", "skill_b"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):

            import threading
            result_holder = []

            def run():
                # Simulate both skills replying after registration
                result_holder.append(svc._collect_stop_skills(Message("test")))

            t = threading.Thread(target=run)
            t.start()

            import time
            time.sleep(0.05)  # let the thread register the handler
            if ack_handler:
                ack_handler(Message("skill.stop.pong",
                                    {"skill_id": "skill_a", "can_handle": True}))
                ack_handler(Message("skill.stop.pong",
                                    {"skill_id": "skill_b", "can_handle": True}))
            t.join(timeout=1)

        self.assertEqual(set(result_holder[0]), {"skill_a", "skill_b"})
        # listener must be removed
        svc.bus.remove.assert_called_once_with("skill.stop.pong", ack_handler)

    def test_skills_that_decline_are_excluded(self):
        """Skills that respond with can_handle=False are not in want_stop,
        but the fallback (all active skills) is returned instead."""
        svc = _make_service()
        sess = self._session_with_skills(["skill_a"])

        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == "skill.stop.pong":
                ack_handler = handler

        svc.bus.on = capture_on
        svc.bus.remove = MagicMock()
        svc.bus.emit = MagicMock()

        with patch.object(StopService, "get_active_skills", return_value=["skill_a"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):

            import threading
            result_holder = []

            def run():
                result_holder.append(svc._collect_stop_skills(Message("test")))

            t = threading.Thread(target=run)
            t.start()

            import time
            time.sleep(0.05)
            if ack_handler:
                ack_handler(Message("skill.stop.pong",
                                    {"skill_id": "skill_a", "can_handle": False}))
            t.join(timeout=1)

        # want_stop is empty → fallback returns all active skills
        self.assertEqual(result_holder[0], ["skill_a"])

    def test_listener_removed_on_timeout(self):
        """Listener must be cleaned up even if no skill replies (timeout path)."""
        svc = _make_service()
        sess = self._session_with_skills(["slow_skill"])
        svc.bus.on = MagicMock()
        svc.bus.remove = MagicMock()
        svc.bus.emit = MagicMock()

        with patch.object(StopService, "get_active_skills", return_value=["slow_skill"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess), \
             patch("ovos_core.intent_services.stop_service.Event") as MockEvent:
            mock_evt = MagicMock()
            mock_evt.wait = MagicMock()  # returns immediately (simulates timeout)
            MockEvent.return_value = mock_evt

            svc._collect_stop_skills(Message("test"))

        # bus.remove must have been called regardless of timeout
        svc.bus.remove.assert_called_once()
        args = svc.bus.remove.call_args[0]
        self.assertEqual(args[0], "skill.stop.pong")

    def test_listener_removed_on_handler_exception(self):
        """Listener must be cleaned up even if handle_ack raises."""
        svc = _make_service()
        sess = self._session_with_skills(["bad_skill"])
        svc.bus.emit = MagicMock()
        svc.bus.remove = MagicMock()

        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == "skill.stop.pong":
                ack_handler = handler

        svc.bus.on = capture_on

        with patch.object(StopService, "get_active_skills", return_value=["bad_skill"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):

            import threading
            result_holder = []

            def run():
                try:
                    result_holder.append(svc._collect_stop_skills(Message("test")))
                except Exception:
                    result_holder.append("error")

            t = threading.Thread(target=run)
            t.start()

            import time
            time.sleep(0.05)
            # Send a malformed message that triggers the guard (skill_id missing)
            if ack_handler:
                ack_handler(Message("skill.stop.pong", {}))  # no skill_id → guard fires
            t.join(timeout=1)

        # Listener must still have been removed
        svc.bus.remove.assert_called_once()

    def test_malformed_pong_skill_id_missing_is_ignored(self):
        """A pong with no skill_id should not crash and not pollute want_stop."""
        svc = _make_service()
        sess = self._session_with_skills(["real_skill"])
        svc.bus.emit = MagicMock()
        svc.bus.remove = MagicMock()

        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == "skill.stop.pong":
                ack_handler = handler

        svc.bus.on = capture_on

        with patch.object(StopService, "get_active_skills", return_value=["real_skill"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):

            import threading, time
            result_holder = []

            def run():
                result_holder.append(svc._collect_stop_skills(Message("test")))

            t = threading.Thread(target=run)
            t.start()
            time.sleep(0.05)
            if ack_handler:
                ack_handler(Message("skill.stop.pong", {}))          # bad — no skill_id
                ack_handler(Message("skill.stop.pong",
                                    {"skill_id": "real_skill", "can_handle": True}))  # good
            t.join(timeout=1)

        # only real_skill should be in the result
        self.assertIn("real_skill", result_holder[0])

    def test_blacklisted_skills_excluded(self):
        """Skills blacklisted in the session must not be pinged."""
        svc = _make_service()
        sess = self._session_with_skills(["ok_skill", "bad_skill"])
        sess.blacklisted_skills = ["bad_skill"]
        svc.bus.emit = MagicMock()
        svc.bus.remove = MagicMock()
        svc.bus.on = MagicMock()

        with patch.object(StopService, "get_active_skills",
                          return_value=["ok_skill", "bad_skill"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess), \
             patch("ovos_core.intent_services.stop_service.Event") as MockEvent:
            mock_evt = MagicMock()
            mock_evt.wait = MagicMock()
            MockEvent.return_value = mock_evt

            svc._collect_stop_skills(Message("test"))

        # only ok_skill should have received a ping (check msg_type of emitted messages)
        emitted_types = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertTrue(any("ok_skill" in t for t in emitted_types))
        self.assertFalse(any("bad_skill" in t for t in emitted_types))


class TestHandleStopConfirmation(unittest.TestCase):

    def test_error_in_data_is_logged(self):
        svc = _make_service()
        svc.bus.emit = MagicMock()
        msg = Message("skill_a.stop.response",
                      data={"skill_id": "skill_a", "error": "boom"},
                      context={})
        with patch("ovos_core.intent_services.stop_service.LOG") as mock_log:
            svc.handle_stop_confirmation(msg)
        mock_log.error.assert_called_once()
        self.assertIn("boom", str(mock_log.error.call_args))

    def test_successful_stop_in_response_mode_aborts_question(self):
        svc = _make_service()
        svc.bus.emit = MagicMock()

        sess = Session("s")
        sess.activate_skill("skill_a")
        sess.enable_response_mode("skill_a")

        msg = Message("skill_a.stop.response",
                      data={"skill_id": "skill_a", "result": True},
                      context={"session": sess.serialize()})

        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            svc.handle_stop_confirmation(msg)

        emitted = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertIn("mycroft.skills.abort_question", emitted)

    def test_skill_id_extracted_from_msg_type_fallback(self):
        """skill_id can be inferred from the message type if not in data/context."""
        svc = _make_service()
        svc.bus.emit = MagicMock()
        sess = Session("s")

        msg = Message("some_skill.stop.response",
                      data={"result": False},
                      context={"session": sess.serialize()})

        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            # Should not raise
            svc.handle_stop_confirmation(msg)


class TestMatchHigh(unittest.TestCase):

    def setUp(self):
        self.svc = _make_service()

    def test_no_vocab_returns_none(self):
        """If voc_list is empty for the language, match_high returns None."""
        with patch.object(self.svc._locale, "voc_match", return_value=False):
            result = self.svc.match_high(["stop"], "en-US", Message("test"))
        self.assertIsNone(result)

    def test_exact_stop_with_no_active_skills_is_global_stop(self):
        """'stop' with no active skills → global stop."""
        with patch.object(self.svc._locale, "voc_match",
                          side_effect=lambda utt, voc, lang, exact: voc == "stop"), \
             patch.object(StopService, "get_active_skills", return_value=[]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=Session("s")):
            result = self.svc.match_high(["stop"], "en-US", Message("test"))

        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, GLOBAL_STOP)

    def test_exact_stop_with_active_skills_pings_skills(self):
        """'stop' with active skills → skill stop ping."""
        with patch.object(self.svc._locale, "voc_match",
                          side_effect=lambda utt, voc, lang, exact: voc == "stop"), \
             patch.object(StopService, "get_active_skills", return_value=["skill_a"]), \
             patch.object(self.svc, "_collect_stop_skills", return_value=["skill_a"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=Session("s")):
            self.svc.bus.once = MagicMock()
            result = self.svc.match_high(["stop"], "en-US", Message("test"))

        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, "skill_a:stop")
        self.assertEqual(result.skill_id, "skill_a")
        self.assertTrue(result.suppress_activation)
        self.assertEqual(result.match_data["skill_id"], "skill_a")

    def test_global_stop_voc_triggers_global_stop(self):
        """global_stop vocabulary always triggers global stop regardless of active skills."""
        def voc_match_side_effect(utt, voc, lang, exact):
            return voc == "global_stop"

        with patch.object(self.svc._locale, "voc_match", side_effect=voc_match_side_effect), \
             patch.object(StopService, "get_active_skills", return_value=["skill_a"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=Session("s")):
            result = self.svc.match_high(["stop everything"], "en-US", Message("test"))

        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, GLOBAL_STOP)


class TestMatchLow(unittest.TestCase):

    def setUp(self):
        self.svc = _make_service()

    def test_no_voc_list_returns_none(self):
        """If voc_list returns empty, match_low returns None."""
        with patch.object(self.svc._locale, "voc_list", return_value=[]):
            result = self.svc.match_low(["stop please"], "en-US", Message("test"))
        self.assertIsNone(result)

    def test_low_confidence_below_threshold_returns_none(self):
        """Fuzzy score below min_conf should return None."""
        self.svc.config = {"min_conf": 0.9}
        with patch.object(self.svc._locale, "voc_list", return_value=["stop"]), \
             patch("ovos_core.intent_services.stop_service.match_one",
                   return_value=("stop", 0.3)), \
             patch.object(StopService, "get_active_skills", return_value=[]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=Session("s")):
            result = self.svc.match_low(["unrelated utterance"], "en-US", Message("test"))
        self.assertIsNone(result)

    def test_active_skills_boost_confidence(self):
        """Active skills add 0.1 to the confidence score."""
        self.svc.config = {"min_conf": 0.5}
        with patch.object(self.svc._locale, "voc_list", return_value=["stop"]), \
             patch("ovos_core.intent_services.stop_service.match_one",
                   return_value=("stop", 0.45)), \
             patch.object(StopService, "get_active_skills", return_value=["skill_a"]), \
             patch.object(self.svc, "_collect_stop_skills", return_value=[]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=Session("s")):
            result = self.svc.match_low(["stop"], "en-US", Message("test"))

        # 0.45 + 0.1 = 0.55 ≥ 0.5, and no skills to stop → global stop
        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, GLOBAL_STOP)

    def test_above_threshold_with_stoppable_skill(self):
        """A confident match with a stoppable skill → skill stop."""
        self.svc.config = {"min_conf": 0.5}
        self.svc.bus.once = MagicMock()
        with patch.object(self.svc._locale, "voc_list", return_value=["stop"]), \
             patch("ovos_core.intent_services.stop_service.match_one",
                   return_value=("stop", 0.8)), \
             patch.object(StopService, "get_active_skills", return_value=["skill_a"]), \
             patch.object(self.svc, "_collect_stop_skills", return_value=["skill_a"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=Session("s")):
            result = self.svc.match_low(["stop"], "en-US", Message("test"))

        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, "skill_a:stop")
        self.assertEqual(result.skill_id, "skill_a")
        self.assertTrue(result.suppress_activation)
        self.assertEqual(result.match_data["skill_id"], "skill_a")


class TestHandleStopConfirmationExtra(unittest.TestCase):

    def test_converse_force_timeout_emitted_when_skill_active(self):
        """When the skill is still in converse (is_active), force converse timeout."""
        svc = _make_service()
        svc.bus.emit = MagicMock()

        sess = Session("s")
        sess.activate_skill("skill_a")
        # INTENT state (not RESPONSE) — should NOT trigger abort_question
        # but skill is still active → should trigger converse force_timeout

        msg = Message("skill_a.stop.response",
                      data={"skill_id": "skill_a", "result": True},
                      context={"session": sess.serialize()})

        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            svc.handle_stop_confirmation(msg)

        emitted = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertIn("ovos.skills.converse.force_timeout", emitted)
        self.assertNotIn("mycroft.skills.abort_question", emitted)

    def test_tts_stop_emitted_when_speaking(self):
        """If the session is speaking, TTS stop should be emitted."""
        svc = _make_service()
        svc.bus.emit = MagicMock()

        sess = Session("s")
        sess.activate_skill("skill_a")
        sess.is_speaking = True

        msg = Message("skill_a.stop.response",
                      data={"skill_id": "skill_a", "result": True},
                      context={"session": sess.serialize()})

        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            svc.handle_stop_confirmation(msg)

        emitted = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertIn("mycroft.audio.speech.stop", emitted)


class TestMatchMedium(unittest.TestCase):

    def setUp(self):
        self.svc = _make_service()

    def test_no_stop_voc_and_no_global_stop_returns_none(self):
        with patch.object(self.svc._locale, "voc_match", return_value=False), \
             patch.object(StopService, "get_active_skills", return_value=[]):
            result = self.svc.match_medium(["hello"], "en-US", Message("test"))
        self.assertIsNone(result)

    def test_stop_voc_match_delegates_to_match_low(self):
        with patch.object(self.svc._locale, "voc_match", return_value=True), \
             patch.object(self.svc, "match_low", return_value="LOW_RESULT") as mock_low:
            result = self.svc.match_medium(["stop"], "en-US", Message("test"))
        self.assertEqual(result, "LOW_RESULT")
        mock_low.assert_called_once()

    def test_global_stop_voc_delegates_to_match_low(self):
        def voc_match_side_effect(utt, voc, lang, exact):
            return voc == "global_stop"

        with patch.object(self.svc._locale, "voc_match", side_effect=voc_match_side_effect), \
             patch.object(StopService, "get_active_skills", return_value=[]), \
             patch.object(self.svc, "match_low", return_value="LOW_RESULT") as mock_low:
            result = self.svc.match_medium(["stop everything"], "en-US", Message("test"))
        self.assertEqual(result, "LOW_RESULT")
        mock_low.assert_called_once()


class TestGetActiveSkills(unittest.TestCase):

    def test_returns_skill_ids_in_order(self):
        sess = Session("s")
        sess.activate_skill("skill_b")
        sess.activate_skill("skill_a")
        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            result = StopService.get_active_skills(Message("test"))
        # skill_a activated last → first in active_skills list
        self.assertIn("skill_a", result)
        self.assertIn("skill_b", result)


class TestShutdown(unittest.TestCase):

    def test_shutdown_removes_listeners(self):
        svc = _make_service()
        svc.bus.remove = MagicMock()
        svc.shutdown()
        calls = {c[0][0] for c in svc.bus.remove.call_args_list}
        self.assertIn(GLOBAL_STOP, calls)


if __name__ == "__main__":
    unittest.main()
