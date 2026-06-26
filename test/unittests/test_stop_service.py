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
            if event == "ovos.stop.pong":  # OVOS-STOP-1 §4.2 spec pong topic
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
                ack_handler(Message("ovos.stop.pong",
                                    {"skill_id": "skill_a", "can_handle": True}))
                ack_handler(Message("ovos.stop.pong",
                                    {"skill_id": "skill_b", "can_handle": True}))
            t.join(timeout=1)

        self.assertEqual(set(result_holder[0]), {"skill_a", "skill_b"})
        # listener must be removed
        svc.bus.remove.assert_called_once_with("ovos.stop.pong", ack_handler)

    def test_skills_that_decline_are_excluded(self):
        """Skills that respond with can_handle=False are not in want_stop,
        but the fallback (all active skills) is returned instead."""
        svc = _make_service()
        sess = self._session_with_skills(["skill_a"])

        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == "ovos.stop.pong":  # OVOS-STOP-1 §4.2 spec pong topic
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
                ack_handler(Message("ovos.stop.pong",
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
        self.assertEqual(args[0], "ovos.stop.pong")

    def test_listener_removed_on_handler_exception(self):
        """Listener must be cleaned up even if handle_ack raises."""
        svc = _make_service()
        sess = self._session_with_skills(["bad_skill"])
        svc.bus.emit = MagicMock()
        svc.bus.remove = MagicMock()

        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == "ovos.stop.pong":  # OVOS-STOP-1 §4.2 spec pong topic
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
                ack_handler(Message("ovos.stop.pong", {}))  # no skill_id → guard fires
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
            if event == "ovos.stop.pong":  # OVOS-STOP-1 §4.2 spec pong topic
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
                ack_handler(Message("ovos.stop.pong", {}))          # bad — no skill_id
                ack_handler(Message("ovos.stop.pong",
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

        # only ok_skill should have received a per-skill ping (check msg_type)
        emitted_types = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertTrue(any("ok_skill" in t for t in emitted_types))
        self.assertFalse(any("bad_skill" in t for t in emitted_types))

    def test_spec_broadcast_ping_emitted(self):
        """OVOS-STOP-1 §4.1/§4.2: a single ``ovos.stop.ping`` broadcast is emitted,
        and the spec ``ovos.stop.pong`` topic is the one subscribed."""
        svc = _make_service()
        sess = self._session_with_skills(["skill_a"])
        svc.bus.emit = MagicMock()
        svc.bus.remove = MagicMock()
        svc.bus.on = MagicMock()

        with patch.object(StopService, "get_active_skills", return_value=["skill_a"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess), \
             patch("ovos_core.intent_services.stop_service.Event") as MockEvent:
            mock_evt = MagicMock()
            mock_evt.wait = MagicMock()
            MockEvent.return_value = mock_evt

            svc._collect_stop_skills(Message("test"))

        emitted_types = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        # spec broadcast emitted exactly once
        self.assertEqual(emitted_types.count("ovos.stop.ping"), 1)
        # spec pong topic is the one subscribed (back-compat per-skill ping kept)
        self.assertEqual(svc.bus.on.call_args[0][0], "ovos.stop.pong")


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
        self.assertEqual(result.match_type, "stop:global")

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
        self.assertEqual(result.match_type, "stop:skill")
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
        self.assertEqual(result.match_type, "stop:global")


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
        self.assertEqual(result.match_type, "stop:global")

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
        self.assertEqual(result.match_type, "stop:skill")
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


class TestBusHandlers(unittest.TestCase):

    def test_handle_global_stop_emits_ovos_stop(self):
        # OVOS-STOP-1 §5.3: global-stop handler emits the spec topic ``ovos.stop``.
        # Back-compat: it ALSO emits the legacy ``mycroft.stop`` directly, because the
        # spec->legacy bus bridge is not guaranteed (opt-in / off on the pure-spec
        # path) and skills have not migrated their stop handler off ``mycroft.stop``.
        svc = _make_service()
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)
        msg = Message("stop:global", {})
        svc.handle_global_stop(msg)
        types = [m.msg_type for m in emitted]
        self.assertIn("mycroft.skill.handler.start", types)
        self.assertIn("ovos.stop", types)
        self.assertIn("mycroft.stop", types)
        self.assertIn("mycroft.skill.handler.complete", types)
        # the spec broadcast is emitted before the legacy back-compat one
        self.assertLess(types.index("ovos.stop"), types.index("mycroft.stop"))

    def test_handle_skill_stop_forwards_to_skill(self):
        svc = _make_service()
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)
        msg = Message("stop:skill", {"skill_id": "my_skill"})
        svc.handle_skill_stop(msg)
        types = [m.msg_type for m in emitted]
        self.assertIn("mycroft.skill.handler.start", types)
        self.assertIn("my_skill.stop", types)
        self.assertIn("mycroft.skill.handler.complete", types)


class TestStop1Draining(unittest.TestCase):
    """OVOS-STOP-1 §4.1 step 4 / §5.2 / §6.2 — recency selection + session draining."""

    def setUp(self):
        self.svc = _make_service()

    # ---- §4.1 step 4: single-target recency selection ----------------------

    def test_select_stop_target_picks_highest_activated_at(self):
        """Multi-pong: select the handler with the highest activated_at,
        not the legacy active_skills list order."""
        sess = Session("s")
        # stamp out of recency order: skill_b is most recently activated
        sess.active_handlers = [
            {"skill_id": "skill_a", "activated_at": 100.0},
            {"skill_id": "skill_b", "activated_at": 200.0},
            {"skill_id": "skill_c", "activated_at": 150.0},
        ]
        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            target = StopService._select_stop_target(
                ["skill_a", "skill_b", "skill_c"], Message("test"))
        self.assertEqual(target, "skill_b")

    def test_select_stop_target_tie_breaks_on_head(self):
        """On an activated_at tie, the head (most recently stamped) wins."""
        sess = Session("s")
        sess.active_handlers = [
            {"skill_id": "skill_head", "activated_at": 200.0},
            {"skill_id": "skill_tail", "activated_at": 200.0},
        ]
        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            target = StopService._select_stop_target(
                ["skill_head", "skill_tail"], Message("test"))
        self.assertEqual(target, "skill_head")

    def test_select_stop_target_only_considers_candidates(self):
        """A more-recent handler that is NOT a positive responder is ignored."""
        sess = Session("s")
        sess.active_handlers = [
            {"skill_id": "not_pong", "activated_at": 300.0},
            {"skill_id": "pong_skill", "activated_at": 100.0},
        ]
        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            target = StopService._select_stop_target(["pong_skill"], Message("test"))
        self.assertEqual(target, "pong_skill")

    def test_select_stop_target_empty_candidates_returns_none(self):
        sess = Session("s")
        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            self.assertIsNone(StopService._select_stop_target([], Message("test")))

    def test_match_high_multi_pong_selects_most_recent(self):
        """Integration: match_high dispatches the single highest-activated_at target."""
        sess = Session("s")
        sess.active_handlers = [
            {"skill_id": "old_skill", "activated_at": 100.0},
            {"skill_id": "new_skill", "activated_at": 500.0},
        ]
        self.svc.bus.once = MagicMock()
        with patch.object(self.svc, "voc_match",
                          side_effect=lambda utt, voc, lang, exact: voc == "stop"), \
             patch.object(StopService, "get_active_skills",
                          return_value=["new_skill", "old_skill"]), \
             patch.object(self.svc, "_collect_stop_skills",
                          return_value=["old_skill", "new_skill"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            result = self.svc.match_high(["stop"], "en-US", Message("test"))

        self.assertEqual(result.match_type, "stop:skill")
        self.assertEqual(result.match_data["skill_id"], "new_skill")

    # ---- §6.2: targeted stop removes only the target -----------------------

    def test_targeted_stop_removes_only_target_from_active_handlers(self):
        """A targeted stop drains ONLY the dispatch target from active_handlers."""
        sess = Session("s")
        sess.active_handlers = [
            {"skill_id": "keep_skill", "activated_at": 100.0},
            {"skill_id": "target_skill", "activated_at": 500.0},
        ]
        self.svc.bus.once = MagicMock()
        with patch.object(self.svc, "voc_match",
                          side_effect=lambda utt, voc, lang, exact: voc == "stop"), \
             patch.object(StopService, "get_active_skills",
                          return_value=["target_skill", "keep_skill"]), \
             patch.object(self.svc, "_collect_stop_skills",
                          return_value=["target_skill", "keep_skill"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            result = self.svc.match_high(["stop"], "en-US", Message("test"))

        remaining = [h["skill_id"] for h in result.updated_session.active_handlers]
        self.assertEqual(remaining, ["keep_skill"])
        self.assertNotIn("target_skill", remaining)

    def test_targeted_stop_clears_target_response_mode_only(self):
        """§6.1: only the dispatch target's response_mode entry is cleared."""
        sess = Session("s")
        sess.active_handlers = [{"skill_id": "target_skill", "activated_at": 500.0}]
        sess.set_response_mode("target_skill", 9999999999.0)
        self.svc.bus.once = MagicMock()
        with patch.object(self.svc, "voc_match",
                          side_effect=lambda utt, voc, lang, exact: voc == "stop"), \
             patch.object(StopService, "get_active_skills",
                          return_value=["target_skill"]), \
             patch.object(self.svc, "_collect_stop_skills",
                          return_value=["target_skill"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            result = self.svc.match_high(["stop"], "en-US", Message("test"))

        self.assertIsNone(result.updated_session.response_mode)

    # ---- §5.2: global_stop drains both lists + clears response_mode --------

    def test_global_stop_drains_both_lists_and_response_mode(self):
        """§5.2: global_stop updated_session sets active_handlers=[],
        converse_handlers=[], and removes response_mode."""
        sess = Session("s")
        sess.active_handlers = [{"skill_id": "a", "activated_at": 1.0}]
        sess.converse_handlers = [{"skill_id": "b", "activated_at": 1.0}]
        sess.set_response_mode("c", 9999999999.0)

        with patch.object(self.svc, "voc_match",
                          side_effect=lambda utt, voc, lang, exact: voc == "global_stop"), \
             patch.object(StopService, "get_active_skills", return_value=["a"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            result = self.svc.match_high(["stop everything"], "en-US", Message("test"))

        self.assertEqual(result.match_type, "stop:global")
        self.assertEqual(result.updated_session.active_handlers, [])
        self.assertEqual(result.updated_session.converse_handlers, [])
        self.assertIsNone(result.updated_session.response_mode)

    def test_global_stop_no_positive_pong_drains_session(self):
        """§4.1 step 5 → §5.2: stop with active skills but no positive pong
        escalates to global_stop and drains the session."""
        sess = Session("s")
        sess.active_handlers = [{"skill_id": "a", "activated_at": 1.0}]
        sess.converse_handlers = [{"skill_id": "a", "activated_at": 1.0}]
        sess.set_response_mode("a", 9999999999.0)

        self.svc.config = {"min_conf": 0.5}
        with patch.object(self.svc, "voc_list", return_value=["stop"]), \
             patch("ovos_core.intent_services.stop_service.match_one",
                   return_value=("stop", 0.9)), \
             patch.object(StopService, "get_active_skills", return_value=["a"]), \
             patch.object(self.svc, "_collect_stop_skills", return_value=[]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            result = self.svc.match_low(["stop"], "en-US", Message("test"))

        self.assertEqual(result.match_type, "stop:global")
        self.assertEqual(result.updated_session.active_handlers, [])
        self.assertEqual(result.updated_session.converse_handlers, [])
        self.assertIsNone(result.updated_session.response_mode)


class TestShutdown(unittest.TestCase):

    def test_shutdown_removes_listeners(self):
        svc = _make_service()
        svc.bus.remove = MagicMock()
        svc.shutdown()
        calls = {c[0][0] for c in svc.bus.remove.call_args_list}
        self.assertIn("stop:global", calls)
        self.assertIn("stop:skill", calls)


if __name__ == "__main__":
    unittest.main()
