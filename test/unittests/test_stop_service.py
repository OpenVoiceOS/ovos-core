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
            if event == "skill.stop.pong":
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
        stale_pong = Message("skill.stop.pong",
                             {"skill_id": "skill_a", "can_handle": True},
                             {"utterance_id": "round-N-minus-1"})
        good_pong = round_n.reply("skill.stop.pong",
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
        foreign_pong = Message("skill.stop.pong",
                               {"skill_id": "skill_a", "can_handle": True},
                               {"utterance_id": "round-N",
                                "session": other_sess.serialize()})
        good_pong = round_n.reply("skill.stop.pong",
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
        good_pong = round_n.reply("skill.stop.pong",
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
        pong = Message("skill.stop.pong",
                       {"skill_id": "skill_a", "can_handle": True})

        with patch.object(StopService, "get_active_skills", return_value=["skill_a"]), \
             patch("ovos_core.intent_services.stop_service.SessionManager.get",
                   return_value=sess):
            result = self._run_round(svc, round_msg, [pong])

        self.assertEqual(result, ["skill_a"])


class TestFoldOrderRegistryFirstWrite(unittest.TestCase):
    """match_high / match_low's disable_response_mode write has no wire
    echo (see #858's fold-order contract). A `message` shared across
    pipeline stages this turn can carry a STALE session snapshot relative
    to an incidental write made elsewhere in the live registry entry for
    this session (e.g. a blacklist declared after the message was built).
    Using `registry_session_for_write` instead of a plain
    `SessionManager.get(message)` fold must not let that stale snapshot
    wipe the live registry state out from under the write.
    """

    SESSION_ID = "stale-fold-test-session"

    def setUp(self):
        # isolate from other tests / any real registry state
        SessionManager.sessions.pop(self.SESSION_ID, None)

    def tearDown(self):
        SessionManager.sessions.pop(self.SESSION_ID, None)

    def _live_session_with_incidental_write(self):
        """Simulate a prior incidental write (no wire echo) landing directly
        on the live registry entry, as `registry_session_for_write` itself
        would do."""
        live = Session(self.SESSION_ID)
        live.activate_skill("skill_a")
        # incidental write not reflected in any message's own snapshot
        live.blacklisted_skills = ["other_skill_incidentally_blacklisted"]
        SessionManager.sessions[self.SESSION_ID] = live
        return live

    def _stale_message(self):
        """A message whose embedded session snapshot predates the
        incidental write above (blacklisted_skills is empty). Built without
        touching the live registry entry (unlike `Session.activate_skill`,
        which has registry side effects) - a plain `Session(...)` + manual
        field set + serialize is enough to model a stale wire snapshot."""
        stale = Session(self.SESSION_ID)
        stale.active_skills = [["skill_a", 0.0]]
        return Message("test", {}, {"session": stale.serialize()})

    def test_match_high_write_survives_stale_message_snapshot(self):
        svc = _make_service()
        self._live_session_with_incidental_write()
        msg = self._stale_message()

        svc._locale.voc_match = MagicMock(side_effect=lambda utt, voc, lang, exact: voc == 'stop')
        with patch.object(svc, "_collect_stop_skills", return_value=["skill_a"]), \
             patch.object(svc, "bus") as mock_bus:
            mock_bus.once = MagicMock()
            svc.match_high(["stop"], "en-us", msg)

        self.assertIn("other_skill_incidentally_blacklisted",
                      SessionManager.sessions[self.SESSION_ID].blacklisted_skills,
                      "a stale message fold wiped an incidental write made "
                      "elsewhere in this session's lifecycle")

    def test_match_low_write_survives_stale_message_snapshot(self):
        svc = _make_service()
        self._live_session_with_incidental_write()
        msg = self._stale_message()

        svc._locale.voc_list = MagicMock(return_value=["stop"])
        with patch("ovos_core.intent_services.stop_service.match_one",
                   return_value=("stop", 1.0)), \
             patch.object(svc, "_collect_stop_skills", return_value=["skill_a"]), \
             patch.object(svc, "bus") as mock_bus:
            mock_bus.once = MagicMock()
            svc.match_low(["stop"], "en-us", msg)

        self.assertIn("other_skill_incidentally_blacklisted",
                      SessionManager.sessions[self.SESSION_ID].blacklisted_skills,
                      "a stale message fold wiped an incidental write made "
                      "elsewhere in this session's lifecycle")


class TestHandleStopConfirmationFoldOrder(unittest.TestCase):
    """handle_stop_confirmation fires asynchronously on a `*.stop.response`
    reply - it has no wire echo and is not lifecycle entry, so its
    `SessionManager.get(message)` fold must not be allowed to full-replace
    the live registry entry with a stale snapshot. A stale snapshot can
    resurrect a skill's RESPONSE utterance_state and undo `disable_response_mode`
    writes made earlier in the same session's lifecycle (e.g. by
    match_high/match_low), which previously caused a bogus
    `mycroft.skills.abort_question` re-emit and clobbered other incidental
    registry state (blacklist)."""

    SESSION_ID = "stop-confirmation-fold-test-session"

    def setUp(self):
        SessionManager.sessions.pop(self.SESSION_ID, None)

    def tearDown(self):
        SessionManager.sessions.pop(self.SESSION_ID, None)

    def test_stale_fold_does_not_clobber_incidental_registry_write(self):
        live = Session(self.SESSION_ID)
        live.activate_skill("skill_a")
        SessionManager.sessions[self.SESSION_ID] = live

        # message snapshot taken EARLY (stale): skill_a still in RESPONSE mode
        snap = Session(self.SESSION_ID)
        snap.activate_skill("skill_a")
        snap.enable_response_mode("skill_a")
        msg = Message("skill_a.stop.response",
                      {"skill_id": "skill_a", "result": True},
                      {"session": snap.serialize(), "utterance_id": "u1"})

        # meanwhile, an incidental registry-first write landed on the live
        # entry (what match_high/match_low's disable_response_mode does)
        SessionManager.sessions[self.SESSION_ID].disable_response_mode("skill_a")
        SessionManager.sessions[self.SESSION_ID].blacklisted_skills = ["skill_z"]

        svc = _make_service()
        svc.bus.emit = MagicMock()
        svc.handle_stop_confirmation(msg)

        live_after = SessionManager.sessions[self.SESSION_ID]
        self.assertEqual(live_after.blacklisted_skills, ["skill_z"],
                         "a stale stop.response fold clobbered an incidental "
                         "registry write (blacklist)")
        self.assertNotEqual(
            live_after.utterance_states.get("skill_a"), UtteranceState.RESPONSE,
            "a stale stop.response fold resurrected skill_a's RESPONSE "
            "utterance_state that was already disabled on the live registry")
        emitted = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertNotIn("mycroft.skills.abort_question", emitted,
                         "abort_question was re-emitted from resurrected "
                         "RESPONSE state undone by the stale fold")


class TestHandleStopConfirmation(unittest.TestCase):

    def setUp(self):
        # handle_stop_confirmation now resolves via
        # `registry_session_for_write`, which prefers a live registry entry
        # over the (possibly mocked-away) `SessionManager.get` fold - so
        # stray "s" entries left in the registry by other tests must not
        # bleed in here.
        SessionManager.sessions.pop("s", None)

    def tearDown(self):
        SessionManager.sessions.pop("s", None)

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
        # match_high resolves via `registry_session_for_write`, and
        # Session.touch() (called by disable_response_mode/activate_skill
        # etc.) self-registers the session into the live registry as a side
        # effect - so a stray "s" entry left by another test class must not
        # bleed in here, and this test must not leak "s" onward either.
        SessionManager.sessions.pop("s", None)

    def tearDown(self):
        SessionManager.sessions.pop("s", None)

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
        # see TestMatchHigh.setUp - registry-first resolution + touch()'s
        # self-registration side effect means "s" must be isolated per test.
        SessionManager.sessions.pop("s", None)

    def tearDown(self):
        SessionManager.sessions.pop("s", None)

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

    def setUp(self):
        # see TestHandleStopConfirmation.setUp - registry-first resolution
        # means a stray "s" entry from another test must not bleed in here.
        SessionManager.sessions.pop("s", None)

    def tearDown(self):
        SessionManager.sessions.pop("s", None)

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

    def test_handle_global_stop_emits_mycroft_stop(self):
        svc = _make_service()
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)
        msg = Message("stop:global", {})
        svc.handle_global_stop(msg)
        types = [m.msg_type for m in emitted]
        self.assertIn("mycroft.skill.handler.start", types)
        self.assertIn("mycroft.stop", types)
        self.assertIn("mycroft.skill.handler.complete", types)

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
