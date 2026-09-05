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

import threading
import time
import unittest
from unittest.mock import MagicMock, patch, call
from threading import Event

from ovos_bus_client.handler import HandlerLifecycle
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager, UtteranceState
from ovos_spec_tools import SpecMessage
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.stop_service import StopService
from ovos_core.intent_services.stop_service_legacy import _LegacyStopBridge

GLOBAL_STOP = f"{StopService.pipeline_id}:global_stop"


def _round_message(utterance_id, sess=None):
    """A Message carrying ``context["utterance_id"]`` the way the
    orchestrator stamps it at lifecycle entry (§9.1.1) -- what
    ``_targeted_stop`` needs as its ``message`` argument."""
    context = {"utterance_id": utterance_id}
    if sess is not None:
        context["session"] = sess.serialize()
    return Message("test", {}, context)


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
        svc._pre_drain = {}
        svc._stop_listeners = set()
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


class TestStopRoundCorrelation(unittest.TestCase):
    """A pong must prove which round it answers, or it decides nothing."""

    def _session_with_skills(self, skill_ids):
        sess = Session("test-session")
        for sid in skill_ids:
            sess.activate_skill(sid)
        return sess

    def _run_round(self, svc, ping_msg, pongs):
        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == SpecMessage.STOP_PONG.value:
                ack_handler = handler

        svc.bus.on = capture_on
        svc.bus.remove = MagicMock()
        svc.bus.emit = MagicMock()

        result_holder = []

        def run():
            result_holder.append(svc._collect_stop_skills(ping_msg))

        t = threading.Thread(target=run)
        t.start()
        time.sleep(0.05)
        for pong in pongs:
            if ack_handler:
                ack_handler(pong)
        t.join(timeout=2)
        return result_holder[0]

    def test_stale_pong_from_previous_round_is_discarded(self):
        """skill_a's stale pong must not count as its answer: skill_b answers
        validly and is included, skill_a's discarded pong leaves it un-answered
        (so it is NOT the reason it ends up in the result; want_stop stays
        non-empty from skill_b alone, proving the fallback-to-all path was not
        what produced skill_b)."""
        svc = _make_service()
        sess = self._session_with_skills(["skill_a", "skill_b"])

        round_n = Message("test", {}, {"utterance_id": "round-N",
                                       "session": sess.serialize()})
        stale_pong = Message(SpecMessage.STOP_PONG.value,
                             {"skill_id": "skill_a", "can_handle": True},
                             {"utterance_id": "round-N-minus-1"})
        good_pong = round_n.reply(SpecMessage.STOP_PONG.value,
                                  {"skill_id": "skill_b", "can_handle": True})

        with patch.object(StopService, "get_active_skills",
                          return_value=["skill_a", "skill_b"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            result = self._run_round(svc, round_n, [stale_pong, good_pong])

        self.assertNotIn("skill_a", result,
                         "a pong from an earlier lifecycle decided this round")
        self.assertIn("skill_b", result)

    def test_cross_session_pong_is_discarded(self):
        svc = _make_service()
        sess = self._session_with_skills(["skill_a", "skill_b"])
        other_sess = Session("other")

        round_n = Message("test", {}, {"utterance_id": "round-N",
                                       "session": sess.serialize()})
        foreign_pong = Message(SpecMessage.STOP_PONG.value,
                               {"skill_id": "skill_a", "can_handle": True},
                               {"utterance_id": "round-N",
                                "session": other_sess.serialize()})
        good_pong = round_n.reply(SpecMessage.STOP_PONG.value,
                                  {"skill_id": "skill_b", "can_handle": True})

        with patch.object(StopService, "get_active_skills",
                          return_value=["skill_a", "skill_b"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            result = self._run_round(svc, round_n, [foreign_pong, good_pong])

        self.assertNotIn("skill_a", result,
                         "a pong from a foreign session decided this round")
        self.assertIn("skill_b", result)

    def test_matching_pong_is_accepted(self):
        svc = _make_service()
        sess = self._session_with_skills(["skill_a"])

        round_n = Message("test", {}, {"utterance_id": "round-N",
                                       "session": sess.serialize()})
        good_pong = round_n.reply(SpecMessage.STOP_PONG.value,
                                  {"skill_id": "skill_a", "can_handle": True})

        with patch.object(StopService, "get_active_skills", return_value=["skill_a"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            result = self._run_round(svc, round_n, [good_pong])

        self.assertEqual(result, ["skill_a"])

    def test_unnamed_round_accepts_pongs_as_before(self):
        """V0 compat: a round with no utterance_id keeps the old behaviour."""
        svc = _make_service()
        sess = self._session_with_skills(["skill_a"])

        round_msg = Message("test", {}, {"session": sess.serialize()})
        pong = Message(SpecMessage.STOP_PONG.value,
                       {"skill_id": "skill_a", "can_handle": True})

        with patch.object(StopService, "get_active_skills", return_value=["skill_a"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            result = self._run_round(svc, round_msg, [pong])

        self.assertEqual(result, ["skill_a"])


class TestHandleStopConfirmation(unittest.TestCase):

    def test_error_in_data_is_logged(self):
        svc = _make_service()
        svc.bus.emit = MagicMock()
        sess = Session("s")
        sess.activate_skill("skill_a")
        svc._targeted_stop("skill_a", "stop", sess, _round_message("uid-1"))
        msg = Message("skill_a.stop.response",
                      data={"skill_id": "skill_a", "error": "boom"},
                      context={"utterance_id": "uid-1", "session": sess.serialize()})
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
        svc._targeted_stop("skill_a", "stop", sess, _round_message("uid-1"))

        msg = Message("skill_a.stop.response",
                      data={"skill_id": "skill_a", "result": True},
                      context={"utterance_id": "uid-1", "session": sess.serialize()})

        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            svc.handle_stop_confirmation(msg)

        emitted = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertIn("mycroft.skills.abort_question", emitted)

    def test_no_utterance_id_is_a_no_op(self):
        """A `.stop.response` with no `utterance_id` (a V0/direct-invocation
        caller) has no snapshot to resolve against and must not raise."""
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

        self.assertEqual(svc.bus.emit.call_args_list, [])


class TestAbortQuestionReachable(unittest.TestCase):
    """handle_stop_confirmation's RESPONSE-state check (which emits
    mycroft.skills.abort_question, the killable-event abort for a blocked
    get_response) must consult the pre-drain snapshot: `sess.utterance_states`
    off the .stop.response message is already drained
    (_targeted_stop's disable_response_mode runs before dispatch), so a live
    read is always UtteranceState.INTENT there."""

    def test_targeted_stop_of_response_mode_skill_emits_abort_question(self):
        svc = _make_service()
        svc.bus.emit = MagicMock()

        sess = Session("s")
        sess.enable_response_mode("skill_a")  # UtteranceState.RESPONSE

        # simulate _targeted_stop's pre-drain snapshot + the dispatch carrying
        # the POST-drain session forward to the .stop.response handler.
        match = svc._targeted_stop("skill_a", "stop", sess, _round_message("uid-1"))
        drained_sess = match.updated_session
        self.assertFalse(drained_sess.response_mode)  # sanity: already drained

        msg = Message("skill_a.stop.response",
                      data={"skill_id": "skill_a", "result": True},
                      context={"utterance_id": "uid-1", "session": drained_sess.serialize()})

        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=drained_sess):
            svc.handle_stop_confirmation(msg)

        emitted = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertIn("mycroft.skills.abort_question", emitted,
                      "abort_question must fire for a skill genuinely blocked "
                      "in get_response, even though the session reaching "
                      "handle_stop_confirmation is already drained")

    def test_force_timeout_still_emitted_for_converse_skill(self):
        """force_timeout must still fire for a converse-active skill."""
        svc = _make_service()
        svc.bus.emit = MagicMock()

        sess = Session("s")
        sess.activate_skill("skill_a")  # active, NOT response-mode

        match = svc._targeted_stop("skill_a", "stop", sess, _round_message("uid-1"))
        drained_sess = match.updated_session

        msg = Message("skill_a.stop.response",
                      data={"skill_id": "skill_a", "result": True},
                      context={"utterance_id": "uid-1", "session": drained_sess.serialize()})

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
            result = self.svc.match_high(["stop"], "en-US", Message("test"))

        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, "skill_a:stop")
        self.assertEqual(result.skill_id, "skill_a")
        # PIPELINE-1 §4.3 slots are string->string; the §7.1 push suppression
        # for the reserved `stop` name is the orchestrator's registry lookup,
        # not a Match field.
        self.assertEqual(result.match_data, {"skill_id": "skill_a"})
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
        # PIPELINE-1 §4.3 slots are string->string; the §7.1 push suppression
        # for the reserved `stop` name is the orchestrator's registry lookup,
        # not a Match field.
        self.assertEqual(result.match_data, {"skill_id": "skill_a"})
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
        svc._targeted_stop("skill_a", "stop", sess, _round_message("uid-1"))

        msg = Message("skill_a.stop.response",
                      data={"skill_id": "skill_a", "result": True},
                      context={"utterance_id": "uid-1", "session": sess.serialize()})

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
        svc._targeted_stop("skill_a", "stop", sess, _round_message("uid-1"))

        msg = Message("skill_a.stop.response",
                      data={"skill_id": "skill_a", "result": True},
                      context={"utterance_id": "uid-1", "session": sess.serialize()})

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

    def test_global_stop_voc_without_stop_voc_still_matches(self):
        """A 'global_stop' utterance with no 'stop' vocab match must still
        reach match_low (the dead is_stop-guarded branch never applied)."""
        def voc_match_side_effect(utt, voc, lang, exact):
            return voc == "global_stop"

        with patch.object(self.svc._locale, "voc_match", side_effect=voc_match_side_effect), \
             patch.object(self.svc, "match_low", return_value="LOW_RESULT") as mock_low:
            result = self.svc.match_medium(["global_stop_only"], "en-US", Message("test"))
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
    """With the translator active (default on ``FakeBus``/``MessageBusClient``),
    a legacy skill's ``stop()`` handler — bound the way ovos-workshop
    actually binds it, on BOTH the shared/skill legacy topic AND left
    listening while the bridge also fires its own §9.2 observer re-emit —
    must be invoked exactly once per stop event, not twice.

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

    def test_global_stop_emits_only_the_ovos_stop_broadcast(self):
        """STOP-1 §5.3: the global-stop handler emits `ovos.stop` and nothing
        else. A response_mode holder gets no topic of its own — §5.3 makes
        every component with user-visible activity a subscriber of the
        broadcast — and §4.3/PIPELINE-1 §8 leave the handler-lifecycle trio to
        the orchestrator, so the handler emits no `.complete`/`.error` either.
        """
        sess = Session("s")
        sess.enable_response_mode("blocked_skill")

        match = self.svc._global_stop("stop everything", sess)
        # PIPELINE-1 §4.3: slots are string->string. No `response_mode_holder`,
        # no `conf`.
        self.assertEqual(match.match_data, {})

        self.svc.bus.emit = MagicMock()
        msg = Message(GLOBAL_STOP, dict(match.match_data),
                      {"pipeline_id": StopService.pipeline_id})
        self.svc.handle_global_stop(msg)

        emitted_types = [c[0][0].msg_type for c in self.svc.bus.emit.call_args_list]
        self.assertNotIn("blocked_skill.stop", emitted_types)
        self.assertEqual(
            [t for t in emitted_types if ".skill.handler." not in t],
            [SpecMessage.STOP.value])


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


class TestStaleStopResponseDoesNotResolveUnrelatedEntry(unittest.TestCase):
    """`_targeted_stop` records the `_pre_drain` snapshot and binds the
    (permanent) `.stop.response` listener at MATCH-BUILD time -- allowed by
    OVOS-PIPELINE-1 §4.2. If the orchestrator later DISCARDS this Match
    (blacklisted intent, missing slots, etc: see service.py's blacklist
    check) and never actually dispatches it, the snapshot is stale but keyed
    by this round's own `utterance_id`, so it can only ever resolve a
    `.stop.response` correlated to THIS round -- never an unrelated,
    genuinely in-flight intent for the same skill_id in a different round."""

    def test_stale_snapshot_does_not_resolve_unrelated_running_intent(self):
        from ovos_core.intent_services.dispatcher import IntentDispatcher

        svc = _make_service()
        bus = svc.bus
        disp = IntentDispatcher(bus, timeout=300)
        self.addCleanup(disp.shutdown)

        sess = Session("sessB")
        sess.activate_skill("skillA")

        # 1) a stop match is built for round "uid-discarded" (records the
        #    pre-drain snapshot + permanent listener) but is DISCARDED --
        #    never handed to disp.dispatch().
        svc._targeted_stop("skillA", "stop", sess, _round_message("uid-discarded"))

        # 2) an ordinary, unrelated intent for the SAME skill, a DIFFERENT
        #    round, is genuinely in flight.
        intent_msg = Message("skillA:my.intent", {},
                             {"skill_id": "skillA", "utterance_id": "uid-running",
                              "session": sess.serialize()})
        disp.dispatch(intent_msg, "skillA", "my.intent")

        # 3) later, skillA answers .stop.response for an unrelated reason
        #    (e.g. a global stop's ping-pong), carrying the RUNNING intent's
        #    round id -- the discarded snapshot is keyed on "uid-discarded"
        #    and can never match this.
        bus.emit(Message("skillA.stop.response",
                         {"skill_id": "skillA", "result": True},
                         {"skill_id": "skillA", "utterance_id": "uid-running",
                          "session": sess.serialize()}))

        with disp._lock:
            entries = list(disp._in_flight.get("sessB", []))
        self.assertEqual(
            [(e.skill_id, e.intent_name) for e in entries],
            [("skillA", "my.intent")],
            "the still-running, unrelated intent's dispatcher entry must "
            "survive a stale/foreign .stop.response for a different round")


class TestStopServiceEmitsNoHandlerTrio(unittest.TestCase):
    """PIPELINE-1 §8: "The handler-lifecycle trio is emitted by the
    orchestrator that invokes the handler... The handler itself does not emit
    anything." STOP-1 §4.3 as amended: "the orchestrator alone emits
    `.complete` on normal return or `.error` on exception... The stop handler
    does not emit either event itself."

    StopService used to synthesize `mycroft.skill.handler.complete`/`.error`
    from a skill's `.stop.response` to close the dispatcher's in-flight entry
    early. That is the orchestrator's event, and forging it reports a terminal
    for a handler this component never invoked.
    """

    def _run_round(self, stop_response_data: dict) -> list:
        svc = _make_service()
        bus = svc.bus
        seen = []
        for topic in ("mycroft.skill.handler.complete",
                      "mycroft.skill.handler.error",
                      SpecMessage.INTENT_HANDLER_COMPLETE.value,
                      SpecMessage.INTENT_HANDLER_ERROR.value):
            bus.on(topic, lambda m, topic=topic: seen.append(topic))

        sess = Session("sE")
        sess.activate_skill("skillA")
        svc._targeted_stop("skillA", "stop", sess, _round_message("uid-1"))
        bus.emit(Message("skillA.stop.response", stop_response_data,
                         {"skill_id": "skillA", "utterance_id": "uid-1",
                          "session": sess.serialize()}))
        return seen

    def test_successful_stop_response_emits_no_lifecycle_terminal(self):
        self.assertEqual(
            self._run_round({"skill_id": "skillA", "result": True}), [],
            "StopService must not emit a handler-lifecycle terminal")

    def test_failed_stop_response_emits_no_lifecycle_terminal(self):
        self.assertEqual(
            self._run_round({"skill_id": "skillA",
                             "error": "stop() raised ValueError"}), [],
            "StopService must not forge an error terminal either")


class TestIntentNameFilterIsDataNotContext(unittest.TestCase):
    """The dispatcher's optional intent_name filter must be read from
    `message.data["intent_name"]`, never `message.context["intent_name"]`.
    Context is CLIENT-INHERITED -- `Message.forward` deep-copies the context
    of the message it is called on, which for a dispatch chain traces back
    to the ORIGINATING client utterance. A client that sets
    `context["intent_name"]` on its own utterance would have that value
    survive every forward() down the dispatch chain and land on the skill's
    REAL `mycroft.skill.handler.complete` too -- mismatching the stop-only
    filter and parking a completely unrelated, successfully-completed
    intent on the dispatcher's 5-minute §8.3 timeout."""

    def test_client_supplied_context_intent_name_does_not_break_real_completion(self):
        from ovos_bus_client.handler import HandlerLifecycle
        from ovos_core.intent_services.dispatcher import IntentDispatcher

        svc = _make_service()
        bus = svc.bus
        disp = IntentDispatcher(bus, timeout=300)
        self.addCleanup(disp.shutdown)

        sess = Session("s2")
        # a client-declared context key on the ORIGINATING utterance,
        # propagated verbatim through every forward() down the chain --
        # nothing StopService controls.
        msg = Message("skillA:my.intent", {},
                      {"skill_id": "skillA", "intent_name": "skillA:my.intent",
                       "session": sess.serialize()})
        bus.on("skillA:my.intent",
               lambda m: HandlerLifecycle(bus, m, skill_id="skillA",
                                          data={"name": "x"}).complete())

        disp.dispatch(msg, "skillA", "my.intent")

        with disp._lock:
            entries = list(disp._in_flight.get("s2", []))
        self.assertEqual(
            entries, [],
            "a REAL handler.complete for an ordinary intent must resolve "
            "regardless of what intent_name (if any) the client stamped on "
            "its own utterance context")

    def test_targeted_stop_resolves_when_its_handler_returns(self):
        """PIPELINE-1 §8: the dispatched stop handler's own return is what
        resolves the round. A stop handler wrapped in `HandlerLifecycle` like
        any other dispatched handler closes the dispatcher's in-flight entry;
        StopService contributes nothing to that."""
        from ovos_core.intent_services.dispatcher import IntentDispatcher

        svc = _make_service()
        bus = svc.bus
        disp = IntentDispatcher(bus, timeout=300)
        self.addCleanup(disp.shutdown)

        sess = Session("s3")
        sess.activate_skill("skillA")

        def stop_handler(m):
            with HandlerLifecycle(bus, m, skill_id="skillA",
                                  data={"name": "skillA.stop"}):
                bus.emit(m.reply("skillA.stop.response",
                                 {"skill_id": "skillA", "result": True}))

        bus.on("skillA:stop", stop_handler)

        match = svc._targeted_stop("skillA", "stop", sess, _round_message("uid-1"))
        reply = Message(match.match_type, dict(match.match_data),
                        {"skill_id": "skillA", "utterance_id": "uid-1",
                         "session": match.updated_session.serialize()})
        disp.dispatch(reply, "skillA", "stop")

        with disp._lock:
            entries = list(disp._in_flight.get("s3", []))
        self.assertEqual(entries, [], "targeted stop entry must still resolve")


class TestPreDrainSnapshotsDoNotLeakOnFailedStop(unittest.TestCase):
    """The pre-drain snapshot must be popped for every `.stop.response`,
    not only a successful one: an error, a decline (`result: False`), or a
    response for a dispatch that never completed must not leave
    `(utterance_id, skill_id)` in `_pre_drain` forever, and must not leave the
    `_resolve_dispatch_lifecycle` presence-gate open for that pair."""

    def test_fifty_failed_stops_leave_no_leaked_snapshot_keys(self):
        svc = _make_service()
        for i in range(50):
            sess = Session(f"sess{i}")
            sess.activate_skill("skillA")
            svc._targeted_stop("skillA", "stop", sess, _round_message(f"uid-{i}"))
            svc.handle_stop_confirmation(Message(
                "skillA.stop.response",
                {"skill_id": "skillA", "error": "boom"},
                {"skill_id": "skillA", "utterance_id": f"uid-{i}",
                 "session": sess.serialize()}))
        self.assertEqual(len(svc._pre_drain), 0)

    def test_fifty_declined_stops_leave_no_leaked_snapshot_keys(self):
        svc = _make_service()
        for i in range(50):
            sess = Session(f"x{i}")
            sess.activate_skill("skillA")
            svc._targeted_stop("skillA", "stop", sess, _round_message(f"uid-{i}"))
            svc.handle_stop_confirmation(Message(
                "skillA.stop.response",
                {"skill_id": "skillA", "result": False},
                {"skill_id": "skillA", "utterance_id": f"uid-{i}",
                 "session": sess.serialize()}))
        self.assertEqual(len(svc._pre_drain), 0)

    def test_successful_stop_still_clears_snapshot(self):
        """Regression guard: the success path must keep clearing too."""
        svc = _make_service()
        sess = Session("ok")
        sess.activate_skill("skillA")
        svc._targeted_stop("skillA", "stop", sess, _round_message("uid-1"))
        svc.handle_stop_confirmation(Message(
            "skillA.stop.response",
            {"skill_id": "skillA", "result": True},
            {"skill_id": "skillA", "utterance_id": "uid-1", "session": sess.serialize()}))
        self.assertEqual(len(svc._pre_drain), 0)


class TestPreDrainGateBlocksUnknownPair(unittest.TestCase):
    """`handle_stop_confirmation` must only emit a synthetic
    handler.complete/.error for a (utterance_id, skill_id) pair it actually
    has a pre-drain snapshot for. A `.stop.response` for a pair with NO
    pre-drain snapshot at all (never went through `_targeted_stop`) must
    emit no `mycroft.skill.handler.complete`/`.error` whatsoever."""

    def test_stop_response_with_no_pre_drain_snapshot_emits_no_handler_signal(self):
        svc = _make_service()
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m.msg_type)

        sess = Session("unknown-sess")
        # deliberately skip _targeted_stop -- no pre-drain snapshot exists
        # for ("uid-unknown", "skillA").
        svc.handle_stop_confirmation(Message(
            "skillA.stop.response",
            {"skill_id": "skillA", "result": True},
            {"skill_id": "skillA", "utterance_id": "uid-unknown",
             "session": sess.serialize()}))

        handler_signals = [t for t in emitted
                           if t in ("mycroft.skill.handler.complete",
                                    "mycroft.skill.handler.error")]
        self.assertEqual(
            handler_signals, [],
            "a .stop.response for a (round, skill) pair with no pre-drain "
            f"snapshot must never emit a synthetic handler signal, got {emitted!r}")


class TestShutdown(unittest.TestCase):

    def test_shutdown_removes_listeners(self):
        svc = _make_service()
        svc.bus.remove = MagicMock()
        svc.shutdown()
        calls = {c[0][0] for c in svc.bus.remove.call_args_list}
        self.assertIn(GLOBAL_STOP, calls)
        self.assertIn(SpecMessage.UTTERANCE_HANDLED.value, calls)
        # the legacy listeners are removed by the (mocked) bridge
        svc._legacy.shutdown.assert_called_once()

    def test_shutdown_removes_one_listener_per_skill_regardless_of_dispatch_count(self):
        """50 targeted-stop dispatches for the SAME skill_id must bind the
        `.stop.response` listener exactly once -- shutdown() must remove
        exactly that one registration, not 50."""
        svc = _make_service()
        for i in range(50):
            sess = Session(f"s{i}")
            sess.activate_skill("skillA")
            svc._targeted_stop("skillA", "stop", sess, _round_message(f"uid-{i}"))
        self.assertEqual(svc._stop_listeners, {"skillA"})

        svc.bus.remove = MagicMock()
        svc.shutdown()
        stop_response_removals = [c for c in svc.bus.remove.call_args_list
                                  if c[0][0] == "skillA.stop.response"]
        self.assertEqual(len(stop_response_removals), 1)
        self.assertEqual(svc._stop_listeners, set())


class TestPreDrainSnapshotsAreRoundScoped(unittest.TestCase):
    """`_pre_drain` is keyed by ``(utterance_id, skill_id)``, not bare
    ``skill_id``: two concurrent targeted stops for the same skill_id in
    different rounds must not collide or consume each other's snapshot."""

    def test_interleaved_targeted_stops_same_skill_different_rounds(self):
        svc = _make_service()
        svc.bus.emit = MagicMock()

        # Round A: skill_a is blocked in get_response (RESPONSE state) ->
        # its confirmation must trigger abort_question.
        sess_a = Session("session_a")
        sess_a.enable_response_mode("skill_a")

        # Round B: skill_a is merely active via converse (INTENT state) ->
        # its confirmation must trigger converse.force_timeout, NOT
        # abort_question.
        sess_b = Session("session_b")
        sess_b.activate_skill("skill_a")

        # interleave: A's pre-drain snapshot, then B's pre-drain snapshot,
        # both for the same skill_id, BEFORE either confirmation arrives.
        match_a = svc._targeted_stop("skill_a", "stop", sess_a, _round_message("uid-a"))
        match_b = svc._targeted_stop("skill_a", "stop", sess_b, _round_message("uid-b"))
        drained_a = match_a.updated_session
        drained_b = match_b.updated_session

        self.assertEqual(
            len(svc._pre_drain), 2,
            "both rounds' snapshots must coexist, keyed independently")

        msg_a = Message("skill_a.stop.response",
                        data={"skill_id": "skill_a", "result": True},
                        context={"utterance_id": "uid-a", "session": drained_a.serialize()})
        msg_b = Message("skill_a.stop.response",
                        data={"skill_id": "skill_a", "result": True},
                        context={"utterance_id": "uid-b", "session": drained_b.serialize()})

        # A's confirmation arrives first, then B's.
        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=drained_a):
            svc.handle_stop_confirmation(msg_a)
        emitted_after_a = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertIn("mycroft.skills.abort_question", emitted_after_a,
                      "round A's own RESPONSE-state snapshot must drive its "
                      "confirmation, not round B's")
        self.assertNotIn("ovos.skills.converse.force_timeout", emitted_after_a,
                         "round A was never converse-active; only its own "
                         "snapshot (RESPONSE-state) should be consulted")

        svc.bus.emit.reset_mock()
        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=drained_b):
            svc.handle_stop_confirmation(msg_b)
        emitted_after_b = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertIn("ovos.skills.converse.force_timeout", emitted_after_b,
                      "round B's own converse-active snapshot must drive "
                      "its confirmation, not round A's (already-consumed) one")
        self.assertNotIn("mycroft.skills.abort_question", emitted_after_b,
                         "round B was never in RESPONSE state; the bug would "
                         "have it consume round A's leftover/absent snapshot")

        self.assertEqual(len(svc._pre_drain), 0)


class TestPreDrainEvictedByUtteranceHandled(unittest.TestCase):
    """The ONLY `_pre_drain` eviction is `ovos.utterance.handled` (§9.5): the
    universal, exactly-once-per-round end marker. A discarded Match's
    snapshot dies with its own round's end marker; a barge-in for a NEW
    utterance in the SAME session must never evict a different round's
    still-pending (dispatched) snapshot."""

    def test_discarded_match_snapshot_evicted_by_its_own_end_marker(self):
        svc = _make_service()
        svc.bus.emit = MagicMock()

        sess = Session("discarded-sess")
        sess.activate_skill("skillA")

        # match() builds the Match and records the snapshot, but the
        # orchestrator discards it (e.g. blacklist, missing slots, a
        # higher-priority Match wins) -- never dispatched.
        svc._targeted_stop("skillA", "stop", sess, _round_message("uid-discarded"))
        self.assertEqual(len(svc._pre_drain), 1)

        # this round's own §9.5 end marker fires regardless of whether a
        # Match from it was ever dispatched.
        svc._on_utterance_handled(Message(
            SpecMessage.UTTERANCE_HANDLED.value, {},
            {"utterance_id": "uid-discarded"}))

        self.assertEqual(len(svc._pre_drain), 0,
                         "the discarded Match's snapshot must be evicted by "
                         "its own round's end marker")

        # skillA later answers a genuine, unrelated .stop.response carrying a
        # DIFFERENT round id (e.g. a global stop's own ping-pong round trip
        # in a later utterance) -- no snapshot is left to resolve against.
        svc.handle_stop_confirmation(Message(
            "skillA.stop.response",
            {"skill_id": "skillA", "result": True},
            {"skill_id": "skillA", "utterance_id": "uid-later",
             "session": sess.serialize()}))

        emitted = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertEqual(
            emitted, [],
            "a discarded Match's evicted snapshot must not fire kill signals "
            f"for a stop it never caused, got {emitted!r}")

    def test_barge_in_same_session_does_not_evict_a_different_dispatched_round(self):
        """A NEW utterance (a barge-in) in the SAME session must not evict a
        still-running, dispatched stop's snapshot from an EARLIER round --
        only that earlier round's own end marker may."""
        svc = _make_service()
        svc.bus.emit = MagicMock()

        sess = Session("bargein-sess")
        sess.activate_skill("skillA")

        # round 1: a targeted stop is dispatched (genuinely, not discarded)
        # and is still awaiting its .stop.response.
        match = svc._targeted_stop("skillA", "stop", sess, _round_message("uid-1"))
        self.assertEqual(len(svc._pre_drain), 1)

        # round 2: a NEW utterance barges in on the SAME session and
        # concludes (its own end marker fires) before round 1's stop() ever
        # answers.
        svc._on_utterance_handled(Message(
            SpecMessage.UTTERANCE_HANDLED.value, {},
            {"utterance_id": "uid-2", "session": sess.serialize()}))

        self.assertEqual(len(svc._pre_drain), 1,
                         "a different round's end marker must not evict "
                         "round 1's still-pending snapshot")

        # round 1's stop() finally answers -- it must still resolve.
        svc.handle_stop_confirmation(Message(
            "skillA.stop.response",
            {"skill_id": "skillA", "result": True},
            {"skill_id": "skillA", "utterance_id": "uid-1",
             "session": match.updated_session.serialize()}))

        emitted = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertIn("ovos.skills.converse.force_timeout", emitted,
                      "round 1's dispatched stop must still resolve after "
                      "surviving the barge-in in round 2")
        self.assertEqual(len(svc._pre_drain), 0)

        # round 1's own (belated) end marker is a no-op -- already consumed.
        svc._on_utterance_handled(Message(
            SpecMessage.UTTERANCE_HANDLED.value, {}, {"utterance_id": "uid-1"}))
        self.assertEqual(len(svc._pre_drain), 0)

    def test_dispatched_match_still_registers_and_resolves(self):
        """Sanity companion: a Match that IS dispatched and confirmed
        resolves correctly and clears its own snapshot."""
        svc = _make_service()
        svc.bus.emit = MagicMock()

        sess = Session("dispatched-sess")
        sess.enable_response_mode("skillA")

        match = svc._targeted_stop("skillA", "stop", sess, _round_message("uid-1"))
        self.assertEqual(len(svc._pre_drain), 1)

        svc.handle_stop_confirmation(Message(
            "skillA.stop.response",
            {"skill_id": "skillA", "result": True},
            {"skill_id": "skillA", "utterance_id": "uid-1",
             "session": match.updated_session.serialize()}))

        emitted = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertIn("mycroft.skills.abort_question", emitted)
        self.assertEqual(len(svc._pre_drain), 0)


class TestPreDrainCrossSessionIsolationOnDispatch(unittest.TestCase):
    """Two sessions targeting the same skill_id must both be resolved
    correctly over the real bus: the listener is a single PERMANENT
    `bus.on` per skill_id (not a fresh `bus.once` per dispatch, which pyee
    dedupes by (topic, function) and would silently drop a second
    concurrent session's confirmation for the same skill_id)."""

    def test_two_sessions_same_skill_both_resolve_over_the_bus(self):
        svc = _make_service()
        bus = svc.bus
        emitted = []
        orig_emit = bus.emit

        def capture(m):
            emitted.append(m)
            return orig_emit(m)

        bus.emit = capture

        sess_1 = Session("sess-1")
        sess_1.enable_response_mode("skillA")  # RESPONSE state
        sess_2 = Session("sess-2")
        sess_2.activate_skill("skillA")  # INTENT state (converse-active)

        match_1 = svc._targeted_stop("skillA", "stop", sess_1, _round_message("uid-1"))
        match_2 = svc._targeted_stop("skillA", "stop", sess_2, _round_message("uid-2"))
        self.assertEqual(len(svc._pre_drain), 2)

        # both sessions' skillA answer on the SAME topic, over the real bus
        # (the single permanent listener bound for "skillA").
        bus.emit(Message("skillA.stop.response",
                         {"skill_id": "skillA", "result": True},
                         {"skill_id": "skillA", "utterance_id": "uid-1",
                          "session": match_1.updated_session.serialize()}))
        bus.emit(Message("skillA.stop.response",
                         {"skill_id": "skillA", "result": True},
                         {"skill_id": "skillA", "utterance_id": "uid-2",
                          "session": match_2.updated_session.serialize()}))

        emitted_types = [m.msg_type for m in emitted]
        self.assertIn("mycroft.skills.abort_question", emitted_types,
                      "round 1's RESPONSE-state snapshot must still fire "
                      "abort_question")
        self.assertIn("ovos.skills.converse.force_timeout", emitted_types,
                      "round 2's converse-active snapshot must still fire "
                      "force_timeout, not be dropped by a once() dedupe")
        self.assertEqual(len(svc._pre_drain), 0,
                         "both rounds' snapshots must be consumed")


if __name__ == "__main__":
    unittest.main()


class TestRecencyIsActivatedAtOrdered(unittest.TestCase):
    """PIPELINE-1 §7.1 defines the recency order for `active_handlers` once,
    normatively, and forbids consumers from defining their own: "`activated_at`
    is authoritative: the entry with the highest `activated_at` is the most
    recently activated", and head position is only the tie-break. STOP-1 §4.1's
    recency rule defers to it. Reading the list in its stored order alone
    stops the wrong skill whenever the two disagree."""

    def test_highest_activated_at_wins_over_list_position(self):
        sess = Session("s")
        sess.active_handlers = [
            {"skill_id": "stale_head", "activated_at": 100.0},
            {"skill_id": "genuinely_recent", "activated_at": 900.0},
        ]
        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            self.assertEqual(
                StopService.get_active_skills(Message("test"))[0],
                "genuinely_recent")

    def test_equal_activated_at_breaks_toward_the_head(self):
        sess = Session("s")
        sess.active_handlers = [
            {"skill_id": "pushed_last", "activated_at": 500.0},
            {"skill_id": "pushed_first", "activated_at": 500.0},
        ]
        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            self.assertEqual(
                StopService.get_active_skills(Message("test")),
                ["pushed_last", "pushed_first"])


class TestCandidateFilterExcludesSelf(unittest.TestCase):
    """STOP-1 §4.1 candidate filter: an `active_handlers` entry is skipped
    when "its `skill_id` equals the stop plugin's own `pipeline_id` — the
    entry PIPELINE-1 §7.1 stamps for a preceding `global_stop` dispatch. The
    stop plugin is never its own stop target." §5.2 makes that entry the
    ordinary post-global-stop state, so without the filter the very next
    generic stop targets the stop plugin itself."""

    def test_own_pipeline_id_is_never_a_candidate(self):
        svc = _make_service()
        sess = Session("s")
        sess.active_handlers = [
            {"skill_id": StopService.pipeline_id, "activated_at": 900.0},
            {"skill_id": "music.skill", "activated_at": 100.0},
        ]
        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            candidates = svc._stop_candidates(Message("test"))
        self.assertEqual(candidates, ["music.skill"])

    def test_only_own_entry_leaves_no_candidates(self):
        """§4.1 step 1 treats such a list as empty, so the utterance resolves
        to `global_stop` again rather than to the stop plugin itself."""
        svc = _make_service()
        sess = Session("s")
        sess.active_handlers = [
            {"skill_id": StopService.pipeline_id, "activated_at": 900.0}]
        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            self.assertEqual(svc._stop_candidates(Message("test")), [])

    def test_blacklisted_holder_and_handlers_are_filtered(self):
        svc = _make_service()
        sess = Session("s")
        sess.blacklisted_skills = ["holder_skill", "banned.skill"]
        sess.enable_response_mode("holder_skill")
        sess.active_handlers = [
            {"skill_id": "banned.skill", "activated_at": 900.0},
            {"skill_id": "ok.skill", "activated_at": 100.0},
        ]
        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            self.assertEqual(svc._stop_candidates(Message("test")), ["ok.skill"])


class TestPongCanHandleIsStrictlyBoolean(unittest.TestCase):
    """STOP-1 §4.2: a pong is valid only when it carries "a `can_handle`
    boolean"; the plugin treats the responder as not stoppable when
    `can_handle` "is present but not a JSON boolean — a truthy non-boolean
    value MUST NOT be coerced to `true`".

    Each case pits a truthy NON-boolean pong from the most recent candidate
    against a real `True` from an older one. Coercion makes the recent
    non-boolean responder a positive responder and §4.1 step 4 hands it the
    stop; the spec makes it invisible, so the older genuine responder wins.
    """

    def _select(self, recent_can_handle):
        svc = _make_service()
        sess = Session("s")
        sess.active_handlers = [
            {"skill_id": "recent", "activated_at": 900.0},
            {"skill_id": "older", "activated_at": 100.0},
        ]

        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == SpecMessage.STOP_PONG.value:
                ack_handler = handler

        svc.bus.emit = lambda m: None
        svc.bus.on = capture_on
        svc.bus.remove = MagicMock()

        with patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            holder = []

            def run():
                holder.append(svc._collect_stop_skills(Message("test")))

            t = threading.Thread(target=run)
            t.start()
            time.sleep(0.05)
            ack_handler(Message(SpecMessage.STOP_PONG.value,
                                {"skill_id": "recent",
                                 "can_handle": recent_can_handle}))
            ack_handler(Message(SpecMessage.STOP_PONG.value,
                                {"skill_id": "older", "can_handle": True}))
            t.join(timeout=2)
        return holder[0]

    def test_string_yes_is_not_a_positive_pong(self):
        self.assertEqual(self._select("yes")[0], "older")

    def test_integer_one_is_not_a_positive_pong(self):
        self.assertEqual(self._select(1)[0], "older")

    def test_non_empty_dict_is_not_a_positive_pong(self):
        self.assertEqual(self._select({"why": "not"})[0], "older")

    def test_real_boolean_true_is_a_positive_pong(self):
        """The control: with a genuine boolean the recent skill DOES win, so
        the cases above fail for the coercion rule and not for some unrelated
        reason."""
        self.assertEqual(self._select(True)[0], "recent")


class TestStopPingBroadcast(unittest.TestCase):
    """STOP-1 §4.1 step 2 / §4.2: the cascade emits `ovos.stop.ping` as a
    BROADCAST, derived via `reply` from the inbound utterance Message so it
    carries the inbound session_id and the utterance emitter's routing
    metadata. The pre-spec per-skill `<skill_id>.stop.ping` is emitted
    alongside it for one deprecation cycle."""

    def _ping_round(self, active):
        svc = _make_service()
        sess = Session("s")
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)
        svc.bus.on = lambda *a: None
        svc.bus.remove = MagicMock()
        with patch.object(StopService, "get_active_skills", return_value=active), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            svc._collect_stop_skills(Message("test"))
        return emitted

    def test_exactly_one_spec_broadcast_per_round(self):
        emitted = self._ping_round(["skill_a", "skill_b"])
        pings = [m for m in emitted if m.msg_type == SpecMessage.STOP_PING.value]
        self.assertEqual(len(pings), 1)

    def test_legacy_per_skill_pings_still_go_out(self):
        emitted = self._ping_round(["skill_a", "skill_b"])
        self.assertEqual(
            sorted(m.msg_type for m in emitted if m.msg_type.endswith(".stop.ping")
                   and m.msg_type != SpecMessage.STOP_PING.value),
            ["skill_a.stop.ping", "skill_b.stop.ping"])

    def test_no_ping_at_all_without_candidates(self):
        self.assertEqual(self._ping_round([]), [])


class TestMatchDataCarriesNoInternalKeys(unittest.TestCase):
    """PIPELINE-1 §4.3: `Match.slots` is a `{string: string}` mapping, and
    the orchestrator forwards it verbatim as the dispatch `slots` and the §9.2
    `ovos.intent.matched` payload. Plugin-internal bookkeeping (`conf`, the
    pre-drain holder) is not a slot and must not ride out on the wire."""

    FORBIDDEN = ("conf", "response_mode_holder")

    def test_targeted_stop_slots(self):
        svc = _make_service()
        sess = Session("s")
        sess.activate_skill("skill_a")
        match = svc._targeted_stop("skill_a", "stop", sess, _round_message("uid-1"))
        for key in self.FORBIDDEN:
            self.assertNotIn(key, match.match_data)
        self.assertTrue(all(isinstance(k, str) and isinstance(v, str)
                            for k, v in match.match_data.items()))

    def test_global_stop_slots(self):
        svc = _make_service()
        sess = Session("s")
        sess.enable_response_mode("blocked_skill")
        match = svc._global_stop("stop everything", sess)
        for key in self.FORBIDDEN:
            self.assertNotIn(key, match.match_data)
        self.assertFalse(any(k.startswith("_pre_drain") for k in match.match_data))
