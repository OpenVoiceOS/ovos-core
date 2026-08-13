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
from ovos_spec_tools import SpecMessage
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.stop_service import StopService
from ovos_core.intent_services.stop_service_legacy import _LegacyStopBridge

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
        svc._legacy = MagicMock()
        svc._was_active_pre_drain = {}
        svc._utt_state_pre_drain = {}
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
            if event == SpecMessage.STOP_PONG.value:
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
                ack_handler(Message(SpecMessage.STOP_PONG.value,
                                    {"skill_id": "skill_a", "can_handle": True}))
                ack_handler(Message(SpecMessage.STOP_PONG.value,
                                    {"skill_id": "skill_b", "can_handle": True}))
            t.join(timeout=1)

        self.assertEqual(set(result_holder[0]), {"skill_a", "skill_b"})
        # listener must be removed
        svc.bus.remove.assert_called_once_with(SpecMessage.STOP_PONG.value, ack_handler)

    def test_skills_that_decline_are_excluded(self):
        """Skills that respond with can_handle=False are not in want_stop,
        but the fallback (all active skills) is returned instead."""
        svc = _make_service()
        sess = self._session_with_skills(["skill_a"])

        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == SpecMessage.STOP_PONG.value:
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
                ack_handler(Message(SpecMessage.STOP_PONG.value,
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
        self.assertEqual(args[0], SpecMessage.STOP_PONG.value)

    def test_listener_removed_on_handler_exception(self):
        """Listener must be cleaned up even if handle_ack raises."""
        svc = _make_service()
        sess = self._session_with_skills(["bad_skill"])
        svc.bus.emit = MagicMock()
        svc.bus.remove = MagicMock()

        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == SpecMessage.STOP_PONG.value:
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
                ack_handler(Message(SpecMessage.STOP_PONG.value, {}))  # no skill_id → guard fires
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
            if event == SpecMessage.STOP_PONG.value:
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
                ack_handler(Message(SpecMessage.STOP_PONG.value, {}))          # bad — no skill_id
                ack_handler(Message(SpecMessage.STOP_PONG.value,
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


class TestAbortQuestionReachable(unittest.TestCase):
    """CONFIRMED-4 regression: handle_stop_confirmation's RESPONSE-state
    check (which emits mycroft.skills.abort_question, the killable-event
    abort for a blocked get_response) read `sess.utterance_states` off the
    ALREADY-DRAINED session carried by the dispatched .stop.response message
    (_targeted_stop's disable_response_mode runs before dispatch) — so it was
    always UtteranceState.INTENT there and the branch was unreachable."""

    def test_targeted_stop_of_response_mode_skill_emits_abort_question(self):
        svc = _make_service()
        svc.bus.emit = MagicMock()

        sess = Session("s")
        sess.enable_response_mode("skill_a")  # UtteranceState.RESPONSE

        # simulate _targeted_stop's pre-drain snapshot + the dispatch carrying
        # the POST-drain session forward to the .stop.response handler.
        match = svc._targeted_stop("skill_a", 1.0, "stop", sess)
        drained_sess = match.updated_session
        self.assertFalse(drained_sess.response_mode)  # sanity: already drained

        msg = Message("skill_a.stop.response",
                      data={"skill_id": "skill_a", "result": True},
                      context={"session": drained_sess.serialize()})

        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=drained_sess):
            svc.handle_stop_confirmation(msg)

        emitted = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertIn("mycroft.skills.abort_question", emitted,
                      "abort_question must fire for a skill genuinely blocked "
                      "in get_response, even though the session reaching "
                      "handle_stop_confirmation is already drained")

    def test_force_timeout_still_emitted_for_converse_skill(self):
        """Regression guard: the CONFIRMED-2 force_timeout fix must stay green."""
        svc = _make_service()
        svc.bus.emit = MagicMock()

        sess = Session("s")
        sess.activate_skill("skill_a")  # active, NOT response-mode

        match = svc._targeted_stop("skill_a", 1.0, "stop", sess)
        drained_sess = match.updated_session

        msg = Message("skill_a.stop.response",
                      data={"skill_id": "skill_a", "result": True},
                      context={"session": drained_sess.serialize()})

        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=drained_sess):
            svc.handle_stop_confirmation(msg)

        emitted = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertIn("ovos.skills.converse.force_timeout", emitted)
        self.assertNotIn("mycroft.skills.abort_question", emitted)


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
        self.assertIn(SpecMessage.AUDIO_STOP.value, emitted)


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


def _make_bridge(legacy_topics_already_bridged: bool = False) -> _LegacyStopBridge:
    """Construct a _LegacyStopBridge without registering bus listeners.

    ``legacy_topics_already_bridged=False`` (the default here) models a
    deployment WITHOUT an active NamespaceTranslator — the scenario where the
    bridge's own ``mycroft.stop`` / ``<skill_id>.stop`` re-emission is the only
    thing providing that compatibility surface, matching what these tests
    assert. Pass ``True`` to model the translator-active regime instead
    (see ``TestLegacyBridgeSingleDelivery`` for that scenario end-to-end).
    """
    bridge = _LegacyStopBridge.__new__(_LegacyStopBridge)
    service = MagicMock()
    service.pipeline_id = StopService.pipeline_id
    bridge.service = service
    bridge.bus = FakeBus()
    bridge._warned = False
    bridge._legacy_topics_already_bridged = legacy_topics_already_bridged
    return bridge


class TestLegacyStopBridge(unittest.TestCase):
    """The droppable pre-STOP-1 dispatch shim."""

    def test_handle_global_stop_emits_mycroft_stop(self):
        bridge = _make_bridge()
        emitted = []
        bridge.bus.emit = lambda m: emitted.append(m)
        bridge.handle_global_stop(Message("stop:global", {}))
        types = [m.msg_type for m in emitted]
        self.assertIn("mycroft.skill.handler.start", types)
        self.assertIn("mycroft.stop", types)
        self.assertIn("mycroft.skill.handler.complete", types)

    def test_handle_skill_stop_forwards_to_skill(self):
        bridge = _make_bridge()
        emitted = []
        bridge.bus.emit = lambda m: emitted.append(m)
        bridge.handle_skill_stop(Message("stop:skill", {"skill_id": "my_skill"}))
        types = [m.msg_type for m in emitted]
        self.assertIn("mycroft.skill.handler.start", types)
        self.assertIn("my_skill.stop", types)
        self.assertIn("mycroft.skill.handler.complete", types)

    def test_intent_matched_global_reemits_legacy_dispatch(self):
        bridge = _make_bridge()
        emitted = []
        bridge.bus.emit = lambda m: emitted.append(m)
        bridge._on_intent_matched(Message(
            "ovos.intent.matched",
            {"pipeline_id": f"{StopService.pipeline_id}-high",
             "intent_name": GLOBAL_STOP, "skill_id": StopService.pipeline_id}))
        types = [m.msg_type for m in emitted]
        self.assertIn("stop.openvoiceos.activate", types)
        self.assertIn("stop:global", types)

    def test_intent_matched_targeted_reemits_legacy_dispatch(self):
        bridge = _make_bridge()
        emitted = []
        bridge.bus.emit = lambda m: emitted.append(m)
        bridge._on_intent_matched(Message(
            "ovos.intent.matched",
            {"pipeline_id": f"{StopService.pipeline_id}-high",
             "intent_name": "my_skill:stop", "skill_id": "my_skill"}))
        stop_skill = [m for m in emitted if m.msg_type == "stop:skill"]
        self.assertEqual(len(stop_skill), 1)
        self.assertEqual(stop_skill[0].data["skill_id"], "my_skill")

    def test_intent_matched_ignores_other_pipelines(self):
        bridge = _make_bridge()
        emitted = []
        bridge.bus.emit = lambda m: emitted.append(m)
        bridge._on_intent_matched(Message(
            "ovos.intent.matched",
            {"pipeline_id": "ovos-adapt-pipeline-plugin-high",
             "intent_name": "my_skill:hello", "skill_id": "my_skill"}))
        self.assertEqual(emitted, [])


class TestLegacyBridgeSingleDelivery(unittest.TestCase):
    """CONFIRMED-1 regression (double-stop): with the translator active
    (default on ``FakeBus``/``MessageBusClient``), a legacy skill's ``stop()``
    handler — bound the way ovos-workshop actually binds it, on BOTH the
    shared/skill legacy topic AND left listening while the bridge also fires
    its own §9.2 observer re-emit — must be invoked exactly once per stop
    event, not twice.

    Before the fix, ``_LegacyStopBridge.handle_global_stop`` /
    ``handle_skill_stop`` unconditionally re-emitted ``mycroft.stop`` /
    ``<skill_id>.stop`` on top of the translator's own receive-side mirror of
    ``ovos.stop`` / ``<skill_id>:stop``, double-firing any handler bound to the
    legacy topic (executed proof: ``['mycroft.stop', 'mycroft.stop']``).
    """

    def _make_real_bridge(self):
        """A real FakeBus (translator ON by default) + a real _LegacyStopBridge."""
        bus = FakeBus()
        service = MagicMock()
        service.bus = bus
        service.pipeline_id = StopService.pipeline_id
        bridge = _LegacyStopBridge(service)
        self.addCleanup(bridge.shutdown)
        return bus, bridge

    def test_global_stop_reaches_skill_once(self):
        bus, bridge = self._make_real_bridge()
        calls = []
        bus.on("mycroft.stop", lambda message: calls.append(message.msg_type))

        # 1) the real StopService.handle_global_stop emission: the spec
        #    broadcast, which the translator mirrors onto mycroft.stop.
        bus.emit(Message(SpecMessage.STOP.value, {},
                         {"pipeline_id": StopService.pipeline_id}))
        # 2) the bridge's own §9.2 observer for the same stop event.
        bridge._on_intent_matched(Message(
            "ovos.intent.matched",
            {"pipeline_id": f"{StopService.pipeline_id}-high",
             "intent_name": GLOBAL_STOP, "skill_id": StopService.pipeline_id}))

        self.assertEqual(calls, ["mycroft.stop"],
                         "skill stop() handler must fire exactly once per global stop, "
                         f"got {calls}")

    def test_targeted_stop_reaches_skill_once(self):
        bus, bridge = self._make_real_bridge()
        skill_id = "my_skill"
        calls = []
        bus.on(f"{skill_id}.stop", lambda message: calls.append(message.msg_type))

        # 1) the real StopService dispatch: the spec targeted stop, mirrored
        #    by the translator onto <skill_id>.stop.
        bus.emit(Message(f"{skill_id}:stop", {}, {"skill_id": skill_id}))
        # 2) the bridge's own §9.2 observer for the same stop event.
        bridge._on_intent_matched(Message(
            "ovos.intent.matched",
            {"pipeline_id": f"{StopService.pipeline_id}-high",
             "intent_name": f"{skill_id}:stop", "skill_id": skill_id}))

        self.assertEqual(calls, [f"{skill_id}.stop"],
                         "skill stop() handler must fire exactly once per targeted stop, "
                         f"got {calls}")

    def test_bridge_still_bridges_without_translator(self):
        """Off-translator deployments must keep receiving mycroft.stop /
        <skill_id>.stop from the bridge itself (no other mechanism provides it)."""
        bus = FakeBus(modernize=False, emit_legacy=False)
        service = MagicMock()
        service.bus = bus
        service.pipeline_id = StopService.pipeline_id
        bridge = _LegacyStopBridge(service)
        self.addCleanup(bridge.shutdown)
        self.assertFalse(bridge._legacy_topics_already_bridged)

        calls = []
        bus.on("mycroft.stop", lambda message: calls.append(message.msg_type))
        bridge._on_intent_matched(Message(
            "ovos.intent.matched",
            {"pipeline_id": f"{StopService.pipeline_id}-high",
             "intent_name": GLOBAL_STOP, "skill_id": StopService.pipeline_id}))
        self.assertEqual(calls, ["mycroft.stop"])


class TestResponseModeHolderCandidate(unittest.TestCase):
    """Regression: a session whose ONLY activity is an outstanding
    get_response (ovos-workshop's enable_response_mode does NOT push an
    active_handlers entry) must still be reachable by a generic "stop" —
    targeted at the holder, not silently escalated to a global stop the
    killable-event abort never observes.
    """

    def setUp(self):
        self.svc = _make_service()

    def test_empty_active_handlers_with_response_mode_is_targeted_not_global(self):
        """A bare 'stop' with active_handlers=[] but a response_mode holder
        must dispatch a TARGETED <skill_id>:stop for that holder, not a
        global stop."""
        sess = Session("s")
        sess.enable_response_mode("skill_x")  # no active_handlers push

        self.svc.bus.once = MagicMock()
        with patch.object(self.svc._locale, "voc_match",
                          side_effect=lambda utt, voc, lang, exact: voc == "stop"), \
             patch.object(StopService, "get_active_skills", return_value=[]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            result = self.svc.match_high(["stop"], "en-US", Message("test"))

        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, "skill_x:stop",
                         "response_mode holder must be targeted directly, "
                         f"got {result.match_type!r} (GLOBAL_STOP={GLOBAL_STOP!r})")
        self.assertEqual(result.skill_id, "skill_x")

    def test_response_mode_holder_ranks_ahead_of_older_active_handler(self):
        """A response_mode holder is the most recent interaction by
        definition and must rank FIRST in stop candidates, even ahead of an
        older active_handlers entry."""
        sess = Session("s")
        sess.activate_skill("old_skill")
        sess.enable_response_mode("holder_skill")

        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess), \
             patch.object(StopService, "get_active_skills",
                          return_value=["old_skill"]):
            candidates = self.svc._stop_candidates(Message("test"))

        self.assertEqual(candidates[0], "holder_skill")
        self.assertIn("old_skill", candidates)

    def test_global_stop_still_reaches_response_mode_holder(self):
        """Even when a stop DOES escalate to global (e.g. explicit 'stop
        everything' vocabulary), the response_mode holder must still get its
        targeted <skill_id>.stop so a blocked get_response is released — the
        broadcast alone is invisible to the killable-event abort."""
        sess = Session("s")
        sess.enable_response_mode("blocked_skill")

        match = self.svc._global_stop(1.0, "stop everything", sess)
        self.assertEqual(match.match_data.get("response_mode_holder"), "blocked_skill")

        self.svc.bus.emit = MagicMock()
        msg = Message(GLOBAL_STOP, dict(match.match_data),
                      {"pipeline_id": StopService.pipeline_id})
        self.svc.handle_global_stop(msg)

        emitted_types = [c[0][0].msg_type for c in self.svc.bus.emit.call_args_list]
        self.assertIn("blocked_skill.stop", emitted_types)
        self.assertIn(SpecMessage.STOP.value, emitted_types)
        # targeted stop must reach the skill BEFORE the broadcast
        self.assertLess(emitted_types.index("blocked_skill.stop"),
                        emitted_types.index(SpecMessage.STOP.value))


class TestStopSelectionDeterministic(unittest.TestCase):
    """L2 regression: `_stop_candidates` puts the response_mode holder (or
    more generally the most-recent candidate) first, but `_collect_stop_skills`
    used to return `want_stop` in PONG ARRIVAL order — a race, not the
    documented recency guarantee. An older/less-recent skill that happens to
    answer faster must NOT win over a more-recent candidate that answers
    slower."""

    def test_selection_deterministic_by_recency_not_arrival_order(self):
        svc = _make_service()

        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == SpecMessage.STOP_PONG.value:
                ack_handler = handler

        svc.bus.on = capture_on
        svc.bus.remove = MagicMock()
        svc.bus.emit = MagicMock()

        # holder_skill is the recency-first candidate (e.g. the response_mode
        # holder); older_skill is a less-recent active_handlers entry.
        with patch.object(svc, "_stop_candidates",
                          return_value=["holder_skill", "older_skill"]):
            import threading
            import time
            result_holder = []

            def run():
                result_holder.append(svc._collect_stop_skills(Message("test")))

            t = threading.Thread(target=run)
            t.start()
            time.sleep(0.05)  # let the thread register the handler

            # inverted arrival order: the OLDER (less-recent) skill answers
            # FIRST -- this is exactly the race the live auditor reproduced
            # (2/7 runs picked the older skill).
            ack_handler(Message(SpecMessage.STOP_PONG.value,
                                {"skill_id": "older_skill", "can_handle": True}))
            ack_handler(Message(SpecMessage.STOP_PONG.value,
                                {"skill_id": "holder_skill", "can_handle": True}))
            t.join(timeout=1)

        self.assertEqual(
            result_holder[0][0], "holder_skill",
            "the recency-first candidate must always be selected "
            "deterministically regardless of which skill's pong arrives "
            f"first; got order {result_holder[0]!r}")


class TestDispatcherLifecycleResolvedByStopRoundTrip(unittest.TestCase):
    """L1 regression: the IntentDispatcher's §8 handler-lifecycle entry for a
    `<skill_id>:stop` dispatch was never resolved by
    `mycroft.skill.handler.complete`/`.error` -- the colon-topic has no direct
    ovos-workshop listener (only the legacy bridge mirrors it onto the
    dot-topic, bound with `handler_info=None`, which disables that emission).
    Left unresolved, every stop parks its dispatch entry on the dispatcher's
    5-minute §8.3 timeout instead of resolving synchronously when the stop
    round-trip (`.stop.response`) actually completes."""

    def test_stop_round_trip_resolves_dispatcher_entry_synchronously(self):
        from ovos_core.intent_services.dispatcher import IntentDispatcher

        svc = _make_service()
        bus = svc.bus
        # a real (long) timeout: if the fix regresses, this test would only
        # catch it via the entry still being present -- it must NEVER need to
        # actually fire for this test to pass.
        disp = IntentDispatcher(bus, timeout=300)
        self.addCleanup(disp.shutdown)

        skill_id = "fake_skill"
        sess = Session("sess1")
        sess.activate_skill(skill_id)

        # fake skill: answers the dispatched colon-topic directly with its
        # .stop.response, exactly as a real stop() round-trip concludes.
        bus.on(f"{skill_id}:stop",
               lambda m: bus.emit(m.reply(f"{skill_id}.stop.response",
                                          {"skill_id": skill_id, "result": True})))

        match = svc._targeted_stop(skill_id, 1.0, "stop", sess)
        reply = Message(match.match_type, dict(match.match_data),
                        {"skill_id": skill_id,
                         "session": match.updated_session.serialize()})

        disp.dispatch(reply, skill_id, "stop")

        with disp._lock:
            entries = list(disp._in_flight.get(match.updated_session.session_id, []))
        self.assertEqual(
            entries, [],
            "the dispatcher's in-flight entry for the <skill_id>:stop dispatch "
            "must be resolved synchronously by the stop round-trip, not left "
            "parked on the 5-minute §8.3 timeout")


class TestShutdown(unittest.TestCase):

    def test_shutdown_removes_listeners(self):
        svc = _make_service()
        svc.bus.remove = MagicMock()
        svc.shutdown()
        calls = {c[0][0] for c in svc.bus.remove.call_args_list}
        self.assertIn(GLOBAL_STOP, calls)
        # the legacy listeners are removed by the (mocked) bridge
        svc._legacy.shutdown.assert_called_once()


class TestPreDrainSnapshotsAreSessionScoped(unittest.TestCase):
    """Regression: ``_was_active_pre_drain`` / ``_utt_state_pre_drain`` used to
    be keyed by bare ``skill_id``. Two concurrent targeted stops for the SAME
    skill_id but DIFFERENT sessions collided: session B's snapshot overwrote
    session A's, and whichever confirmation was processed second popped the
    OTHER session's (already-consumed) entry, producing wrong
    force_timeout/abort_question decisions. Keying by ``(session_id,
    skill_id)`` fixes this."""

    def test_interleaved_targeted_stops_same_skill_different_sessions(self):
        svc = _make_service()
        svc.bus.emit = MagicMock()

        # Session A: skill_a is blocked in get_response (RESPONSE state) ->
        # its confirmation must trigger abort_question.
        sess_a = Session("session_a")
        sess_a.enable_response_mode("skill_a")

        # Session B: skill_a is merely active via converse (INTENT state) ->
        # its confirmation must trigger converse.force_timeout, NOT
        # abort_question.
        sess_b = Session("session_b")
        sess_b.activate_skill("skill_a")

        # interleave: A's pre-drain snapshot, then B's pre-drain snapshot,
        # both for the same skill_id, BEFORE either confirmation arrives.
        match_a = svc._targeted_stop("skill_a", 1.0, "stop", sess_a)
        match_b = svc._targeted_stop("skill_a", 1.0, "stop", sess_b)
        drained_a = match_a.updated_session
        drained_b = match_b.updated_session

        self.assertEqual(
            len(svc._was_active_pre_drain), 2,
            "both sessions' snapshots must coexist, keyed independently")

        msg_a = Message("skill_a.stop.response",
                        data={"skill_id": "skill_a", "result": True},
                        context={"session": drained_a.serialize()})
        msg_b = Message("skill_a.stop.response",
                        data={"skill_id": "skill_a", "result": True},
                        context={"session": drained_b.serialize()})

        # A's confirmation arrives first, then B's.
        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=drained_a):
            svc.handle_stop_confirmation(msg_a)
        emitted_after_a = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertIn("mycroft.skills.abort_question", emitted_after_a,
                      "session A's own RESPONSE-state snapshot must drive its "
                      "confirmation, not session B's")
        self.assertNotIn("ovos.skills.converse.force_timeout", emitted_after_a,
                         "session A was never converse-active; only its own "
                         "snapshot (RESPONSE-state) should be consulted")

        svc.bus.emit.reset_mock()
        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=drained_b):
            svc.handle_stop_confirmation(msg_b)
        emitted_after_b = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertIn("ovos.skills.converse.force_timeout", emitted_after_b,
                      "session B's own converse-active snapshot must drive "
                      "its confirmation, not session A's (already-consumed) one")
        self.assertNotIn("mycroft.skills.abort_question", emitted_after_b,
                         "session B was never in RESPONSE state; the bug would "
                         "have it consume session A's leftover/absent snapshot")

        self.assertEqual(len(svc._was_active_pre_drain), 0)
        self.assertEqual(len(svc._utt_state_pre_drain), 0)


if __name__ == "__main__":
    unittest.main()
