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

import time
import threading
import unittest
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, UtteranceState
from ovos_utils.fakebus import FakeBus
from ovos_workshop.permissions import ConverseMode, ConverseActivationMode

from ovos_core.intent_services.converse_service import ConverseService


def _make_service() -> ConverseService:
    """Construct a ConverseService with a FakeBus, bypassing __init__."""
    svc = ConverseService.__new__(ConverseService)
    svc.bus = FakeBus()
    svc.config = {}
    svc._consecutive_activations = {}
    return svc


# ---------------------------------------------------------------------------
# _collect_converse_skills
# ---------------------------------------------------------------------------

class TestCollectConverseSkills(unittest.TestCase):
    """Tests for the ping-pong mechanism in _collect_converse_skills."""

    def test_no_active_skills_returns_empty(self):
        """When there are no active skills the result is an empty list."""
        svc = _make_service()
        with patch.object(ConverseService, "get_active_skills", return_value=[]), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=Session("s")):
            result = svc._collect_converse_skills(Message("test"))
        self.assertEqual(result, [])

    def test_skill_responds_can_handle_true_is_included(self):
        """A skill that replies can_handle=True appears in the result."""
        svc = _make_service()
        sess = Session("s")
        sess.activate_skill("skill_a")

        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == "skill.converse.pong":
                ack_handler = handler

        svc.bus.on = capture_on
        svc.bus.remove = MagicMock()
        svc.bus.emit = MagicMock()

        with patch.object(ConverseService, "get_active_skills", return_value=["skill_a"]), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):

            result_holder = []

            def run():
                result_holder.append(svc._collect_converse_skills(Message("test")))

            t = threading.Thread(target=run)
            t.start()
            time.sleep(0.05)
            if ack_handler:
                ack_handler(Message("skill.converse.pong",
                                    {"skill_id": "skill_a", "can_handle": True}))
            t.join(timeout=1)

        self.assertIn("skill_a", result_holder[0])

    def test_skill_responds_can_handle_false_excluded(self):
        """A skill that replies can_handle=False is not included."""
        svc = _make_service()
        sess = Session("s")
        sess.activate_skill("skill_a")

        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == "skill.converse.pong":
                ack_handler = handler

        svc.bus.on = capture_on
        svc.bus.remove = MagicMock()
        svc.bus.emit = MagicMock()

        with patch.object(ConverseService, "get_active_skills", return_value=["skill_a"]), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):

            result_holder = []

            def run():
                result_holder.append(svc._collect_converse_skills(Message("test")))

            t = threading.Thread(target=run)
            t.start()
            time.sleep(0.05)
            if ack_handler:
                ack_handler(Message("skill.converse.pong",
                                    {"skill_id": "skill_a", "can_handle": False}))
            t.join(timeout=1)

        self.assertEqual(result_holder[0], [])

    def test_malformed_pong_no_skill_id_is_ignored(self):
        """A pong without skill_id does not crash and does not pollute results."""
        svc = _make_service()
        sess = Session("s")
        sess.activate_skill("real_skill")

        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == "skill.converse.pong":
                ack_handler = handler

        svc.bus.on = capture_on
        svc.bus.remove = MagicMock()
        svc.bus.emit = MagicMock()

        with patch.object(ConverseService, "get_active_skills", return_value=["real_skill"]), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):

            result_holder = []

            def run():
                result_holder.append(svc._collect_converse_skills(Message("test")))

            t = threading.Thread(target=run)
            t.start()
            time.sleep(0.05)
            if ack_handler:
                ack_handler(Message("skill.converse.pong", {}))   # bad — no skill_id
                ack_handler(Message("skill.converse.pong",
                                    {"skill_id": "real_skill", "can_handle": True}))
            t.join(timeout=1)

        self.assertIn("real_skill", result_holder[0])

    def test_listener_always_removed_on_timeout(self):
        """bus.remove must be called even when no skill replies (timeout path)."""
        svc = _make_service()
        sess = Session("s")
        sess.activate_skill("slow_skill")
        svc.bus.on = MagicMock()
        svc.bus.remove = MagicMock()
        svc.bus.emit = MagicMock()

        with patch.object(ConverseService, "get_active_skills", return_value=["slow_skill"]), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess), \
             patch("ovos_core.intent_services.converse_service.Event") as MockEvent:
            mock_evt = MagicMock()
            mock_evt.wait = MagicMock()  # returns immediately — simulates timeout
            MockEvent.return_value = mock_evt

            svc._collect_converse_skills(Message("test"))

        svc.bus.remove.assert_called_once()
        args = svc.bus.remove.call_args[0]
        self.assertEqual(args[0], "skill.converse.pong")

    def test_response_state_skills_excluded_from_active_skills(self):
        """Skills whose utterance_state is RESPONSE are not included in active_skills ping list."""
        svc = _make_service()
        sess = Session("s")
        sess.activate_skill("skill_a")
        sess.activate_skill("skill_b")
        # Put skill_b in RESPONSE state — should be excluded from ping list
        sess.utterance_states["skill_b"] = UtteranceState.RESPONSE

        svc.bus.on = MagicMock()
        svc.bus.remove = MagicMock()
        svc.bus.emit = MagicMock()

        with patch.object(ConverseService, "get_active_skills",
                          return_value=["skill_a", "skill_b"]), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess), \
             patch("ovos_core.intent_services.converse_service.Event") as MockEvent:
            mock_evt = MagicMock()
            mock_evt.wait = MagicMock()
            MockEvent.return_value = mock_evt

            svc._collect_converse_skills(Message("test"))

        # Only skill_a should have received a ping
        emitted_types = [c[0][0].msg_type for c in svc.bus.emit.call_args_list]
        self.assertTrue(any("skill_a" in t for t in emitted_types))
        self.assertFalse(any("skill_b" in t for t in emitted_types))


# ---------------------------------------------------------------------------
# _check_converse_timeout
# ---------------------------------------------------------------------------

class TestCheckConverseTimeout(unittest.TestCase):
    """Tests for the timestamp-based skill timeout filtering."""

    def test_skills_within_default_timeout_stay(self):
        """Skills whose timestamp is recent enough survive the filter."""
        svc = _make_service()
        sess = Session("s")
        now = time.time()
        sess.active_handlers = [
            {"skill_id": "skill_a", "activated_at": now - 10}
        ]  # 10 s ago — within 300 s default

        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            svc._check_converse_timeout(Message("test"))

        self.assertEqual(len(sess.active_handlers), 1)
        self.assertEqual(sess.active_handlers[0]["skill_id"], "skill_a")

    def test_skills_past_default_timeout_removed(self):
        """Skills older than the default timeout (300 s) are removed."""
        svc = _make_service()
        sess = Session("s")
        now = time.time()
        sess.active_handlers = [
            {"skill_id": "old_skill", "activated_at": now - 400}
        ]  # 400 s ago — beyond default

        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            svc._check_converse_timeout(Message("test"))

        self.assertEqual(sess.active_handlers, [])

    def test_per_skill_timeout_override_respected(self):
        """A per-skill timeout override takes precedence over the default."""
        svc = _make_service()
        svc.config = {"skill_timeouts": {"short_skill": 5}, "timeout": 300}
        sess = Session("s")
        now = time.time()
        # short_skill has a 5-second timeout; 10 seconds old → should be removed
        sess.active_handlers = [
            {"skill_id": "short_skill", "activated_at": now - 10},
            {"skill_id": "long_skill", "activated_at": now - 10},
        ]

        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            svc._check_converse_timeout(Message("test"))

        remaining = [handler["skill_id"] for handler in sess.active_handlers]
        self.assertNotIn("short_skill", remaining)
        self.assertIn("long_skill", remaining)


# ---------------------------------------------------------------------------
# _activate_allowed / activate_skill
# ---------------------------------------------------------------------------

class TestActivateAllowed(unittest.TestCase):
    """Tests for the activation permission logic."""

    def test_skill_activates_itself_always_allowed(self):
        """source_skill == skill_id is always permitted regardless of cross_activation."""
        svc = _make_service()
        svc.config = {"cross_activation": False}
        svc._consecutive_activations = {}
        self.assertTrue(svc._activate_allowed("skill_a", "skill_a"))

    def test_cross_activation_false_blocks_different_skill(self):
        """When cross_activation is False a different skill cannot activate skill_a."""
        svc = _make_service()
        svc.config = {"cross_activation": False}
        self.assertFalse(svc._activate_allowed("skill_a", "skill_b"))

    def test_whitelist_mode_blocks_non_whitelisted(self):
        """WHITELIST mode prevents skills not in the whitelist from activating."""
        svc = _make_service()
        svc.config = {
            "cross_activation": True,
            "converse_activation": ConverseActivationMode.WHITELIST,
            "converse_whitelist": ["allowed_skill"],
        }
        self.assertFalse(svc._activate_allowed("not_allowed_skill"))

    def test_whitelist_mode_allows_whitelisted(self):
        """WHITELIST mode allows skills that are in the whitelist."""
        svc = _make_service()
        svc.config = {
            "cross_activation": True,
            "converse_activation": ConverseActivationMode.WHITELIST,
            "converse_whitelist": ["allowed_skill"],
        }
        self.assertTrue(svc._activate_allowed("allowed_skill"))

    def test_blacklist_mode_blocks_blacklisted(self):
        """BLACKLIST mode prevents blacklisted skills from activating."""
        svc = _make_service()
        svc.config = {
            "cross_activation": True,
            "converse_activation": ConverseActivationMode.BLACKLIST,
            "converse_blacklist": ["bad_skill"],
        }
        self.assertFalse(svc._activate_allowed("bad_skill"))

    def test_blacklist_mode_allows_non_blacklisted(self):
        """BLACKLIST mode allows skills not on the blacklist."""
        svc = _make_service()
        svc.config = {
            "cross_activation": True,
            "converse_activation": ConverseActivationMode.BLACKLIST,
            "converse_blacklist": ["bad_skill"],
        }
        self.assertTrue(svc._activate_allowed("good_skill"))

    def test_max_activations_zero_blocks_all(self):
        """max_activations=0 blocks any skill from activating."""
        svc = _make_service()
        svc.config = {"max_activations": 0}
        self.assertFalse(svc._activate_allowed("skill_a", "skill_a"))

    def test_max_activations_exceeded_blocks(self):
        """Exceeding max_activations blocks further activations."""
        svc = _make_service()
        svc.config = {"max_activations": 2}
        svc._consecutive_activations = {"skill_a": 3}
        self.assertFalse(svc._activate_allowed("skill_a", "skill_a"))

    def test_within_max_activations_allowed(self):
        """Not yet at max_activations permits activation."""
        svc = _make_service()
        svc.config = {"max_activations": 5}
        svc._consecutive_activations = {"skill_a": 2}
        self.assertTrue(svc._activate_allowed("skill_a", "skill_a"))

    def test_activate_skill_increments_counter(self):
        """Successful activation increments _consecutive_activations."""
        svc = _make_service()
        svc._consecutive_activations = {"skill_a": 0}
        sess = Session("s")

        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            svc.bus.emit = MagicMock()
            svc.activate_skill("skill_a", "skill_a", Message("test", context={}))

        self.assertEqual(svc._consecutive_activations["skill_a"], 1)

    def test_activate_skill_emits_activated_event(self):
        """Successful activation emits intent.service.skills.activated on the bus."""
        svc = _make_service()
        svc._consecutive_activations = {"skill_a": 0}
        sess = Session("s")
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)

        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            svc.activate_skill("skill_a", "skill_a", Message("test", context={}))

        types = [m.msg_type for m in emitted]
        self.assertIn("intent.service.skills.activated", types)

    def test_activate_skill_blocked_does_not_emit(self):
        """Blocked activation (max_activations=0) does not emit any bus event."""
        svc = _make_service()
        svc.config = {"max_activations": 0}
        svc.bus.emit = MagicMock()

        svc.activate_skill("skill_a", "skill_a", Message("test", context={}))
        svc.bus.emit.assert_not_called()


# ---------------------------------------------------------------------------
# _deactivate_allowed / deactivate_skill
# ---------------------------------------------------------------------------

class TestDeactivateAllowed(unittest.TestCase):
    """Tests for the deactivation permission logic."""

    def test_skill_can_deactivate_itself(self):
        """A skill is always permitted to deactivate itself."""
        svc = _make_service()
        svc.config = {"cross_activation": False}
        self.assertTrue(svc._deactivate_allowed("skill_a", "skill_a"))

    def test_cross_activation_false_blocks_different_skill_deactivation(self):
        """When cross_activation is False a foreign skill cannot deactivate another."""
        svc = _make_service()
        svc.config = {"cross_activation": False}
        self.assertFalse(svc._deactivate_allowed("skill_a", "skill_b"))

    def test_cross_activation_true_allows_foreign_deactivation(self):
        """When cross_activation is True any skill may deactivate another."""
        svc = _make_service()
        svc.config = {"cross_activation": True}
        self.assertTrue(svc._deactivate_allowed("skill_a", "skill_b"))

    def test_deactivate_skill_resets_consecutive_activations(self):
        """Successful deactivation resets the consecutive activation counter to 0."""
        svc = _make_service()
        svc._consecutive_activations = {"skill_a": 5}
        sess = Session("s")
        sess.activate_skill("skill_a")
        svc.bus.emit = MagicMock()

        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            svc.deactivate_skill("skill_a", "skill_a", Message("test", context={}))

        self.assertEqual(svc._consecutive_activations["skill_a"], 0)

    def test_deactivate_skill_emits_deactivated_event(self):
        """Successful deactivation emits intent.service.skills.deactivated."""
        svc = _make_service()
        svc._consecutive_activations = {}
        sess = Session("s")
        sess.activate_skill("skill_a")
        emitted = []
        svc.bus.emit = lambda m: emitted.append(m)

        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            svc.deactivate_skill("skill_a", "skill_a", Message("test", context={}))

        types = [m.msg_type for m in emitted]
        self.assertIn("intent.service.skills.deactivated", types)

    def test_deactivate_skill_blocked_does_not_emit(self):
        """Blocked deactivation (cross_activation=False, different skill) does not emit."""
        svc = _make_service()
        svc.config = {"cross_activation": False}
        svc.bus.emit = MagicMock()

        sess = Session("s")
        sess.activate_skill("skill_a")
        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            svc.deactivate_skill("skill_a", "skill_b", Message("test", context={}))

        svc.bus.emit.assert_not_called()


# ---------------------------------------------------------------------------
# _converse_allowed
# ---------------------------------------------------------------------------

class TestConverseAllowed(unittest.TestCase):
    """Tests for the converse-mode permission logic."""

    def test_accept_all_always_true(self):
        """ACCEPT_ALL mode permits any skill to converse."""
        svc = _make_service()
        svc.config = {"converse_mode": ConverseMode.ACCEPT_ALL}
        self.assertTrue(svc._converse_allowed("any_skill"))

    def test_blacklist_mode_blocks_blacklisted_skill(self):
        """BLACKLIST mode blocks skills on the blacklist."""
        svc = _make_service()
        svc.config = {
            "converse_mode": ConverseMode.BLACKLIST,
            "converse_blacklist": ["bad_skill"],
        }
        self.assertFalse(svc._converse_allowed("bad_skill"))

    def test_blacklist_mode_allows_non_blacklisted(self):
        """BLACKLIST mode allows skills not on the blacklist."""
        svc = _make_service()
        svc.config = {
            "converse_mode": ConverseMode.BLACKLIST,
            "converse_blacklist": ["bad_skill"],
        }
        self.assertTrue(svc._converse_allowed("good_skill"))

    def test_whitelist_mode_blocks_non_whitelisted(self):
        """WHITELIST mode blocks skills absent from the whitelist."""
        svc = _make_service()
        svc.config = {
            "converse_mode": ConverseMode.WHITELIST,
            "converse_whitelist": ["ok_skill"],
        }
        self.assertFalse(svc._converse_allowed("other_skill"))

    def test_whitelist_mode_allows_whitelisted(self):
        """WHITELIST mode permits skills on the whitelist."""
        svc = _make_service()
        svc.config = {
            "converse_mode": ConverseMode.WHITELIST,
            "converse_whitelist": ["ok_skill"],
        }
        self.assertTrue(svc._converse_allowed("ok_skill"))


# ---------------------------------------------------------------------------
# match
# ---------------------------------------------------------------------------

class TestMatch(unittest.TestCase):
    """Tests for the top-level match() pipeline method."""

    def test_message_session_is_folded_once_and_reused(self):
        """One matcher call must operate on one live session snapshot."""
        svc = _make_service()
        sess = Session("s")
        message = Message("test", context={})

        with patch(
            "ovos_core.intent_services.converse_service.SessionManager.get",
            return_value=sess,
        ) as get_session, patch.object(
            svc, "_check_converse_timeout"
        ) as check_timeout, patch.object(
            svc, "_collect_converse_skills", return_value=[]
        ) as collect_skills:
            result = svc.match(["hello"], "en-US", message)

        self.assertIsNone(result)
        get_session.assert_called_once_with(message)
        check_timeout.assert_called_once_with(message, sess)
        collect_skills.assert_called_once_with(message, sess)

    def test_expired_skill_is_not_refolded_before_poll(self):
        """Timeout filtering survives until converse candidates are polled."""
        svc = _make_service()
        sess = Session("s")
        sess.active_handlers = [
            {"skill_id": "expired", "activated_at": time.time() - 400}
        ]
        svc.bus.emit = MagicMock()
        message = Message("test", context={})

        with patch(
            "ovos_core.intent_services.converse_service.SessionManager.get",
            return_value=sess,
        ) as get_session:
            result = svc.match(["hello"], "en-US", message)

        self.assertIsNone(result)
        self.assertEqual(sess.active_handlers, [])
        get_session.assert_called_once_with(message)
        svc.bus.emit.assert_not_called()

    def test_skill_in_response_state_captured_by_get_response(self):
        """A skill in RESPONSE state is matched as get_response, not converse."""
        svc = _make_service()
        sess = Session("s")
        sess.activate_skill("skill_a")
        sess.utterance_states["skill_a"] = UtteranceState.RESPONSE

        with patch.object(ConverseService, "get_active_skills", return_value=["skill_a"]), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            result = svc.match(["hello"], "en-US", Message("test", context={}))

        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, "skill_a.converse.get_response")
        self.assertEqual(result.skill_id, "skill_a")

    def test_skill_in_intent_state_wants_converse_returns_converse_match(self):
        """A skill in INTENT state that wants to converse returns a converse:skill match."""
        svc = _make_service()
        sess = Session("s")
        sess.activate_skill("skill_a")
        # Default utterance_state is INTENT

        with patch.object(ConverseService, "get_active_skills", return_value=["skill_a"]), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess), \
             patch.object(svc, "_collect_converse_skills", return_value=["skill_a"]), \
             patch.object(svc, "_check_converse_timeout"):
            result = svc.match(["hello"], "en-US", Message("test", context={}))

        self.assertIsNotNone(result)
        self.assertEqual(result.match_type, "converse:skill")
        self.assertEqual(result.skill_id, "skill_a")

    def test_blacklisted_skill_skipped_in_response_state(self):
        """A session-blacklisted skill in RESPONSE state is skipped entirely."""
        svc = _make_service()
        sess = Session("s")
        sess.activate_skill("skill_a")
        sess.utterance_states["skill_a"] = UtteranceState.RESPONSE
        sess.blacklisted_skills = ["skill_a"]

        with patch.object(ConverseService, "get_active_skills", return_value=["skill_a"]), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess), \
             patch.object(svc, "_collect_converse_skills", return_value=[]), \
             patch.object(svc, "_check_converse_timeout"):
            result = svc.match(["hello"], "en-US", Message("test", context={}))

        self.assertIsNone(result)

    def test_blacklisted_skill_skipped_in_converse(self):
        """A session-blacklisted skill that wants to converse is skipped."""
        svc = _make_service()
        sess = Session("s")
        sess.activate_skill("skill_a")
        sess.blacklisted_skills = ["skill_a"]

        with patch.object(ConverseService, "get_active_skills", return_value=["skill_a"]), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess), \
             patch.object(svc, "_collect_converse_skills", return_value=["skill_a"]), \
             patch.object(svc, "_check_converse_timeout"):
            result = svc.match(["hello"], "en-US", Message("test", context={}))

        self.assertIsNone(result)

    def test_no_willing_skills_returns_none(self):
        """When no skill wants to converse, match returns None."""
        svc = _make_service()
        sess = Session("s")

        with patch.object(ConverseService, "get_active_skills", return_value=[]), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess), \
             patch.object(svc, "_collect_converse_skills", return_value=[]), \
             patch.object(svc, "_check_converse_timeout"):
            result = svc.match(["hello"], "en-US", Message("test", context={}))

        self.assertIsNone(result)

    def test_converse_blacklisted_skill_skipped(self):
        """A skill blocked by _converse_allowed is skipped even if it wants to converse."""
        svc = _make_service()
        svc.config = {
            "converse_mode": ConverseMode.BLACKLIST,
            "converse_blacklist": ["skill_a"],
        }
        sess = Session("s")
        sess.activate_skill("skill_a")

        with patch.object(ConverseService, "get_active_skills", return_value=["skill_a"]), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess), \
             patch.object(svc, "_collect_converse_skills", return_value=["skill_a"]), \
             patch.object(svc, "_check_converse_timeout"):
            result = svc.match(["hello"], "en-US", Message("test", context={}))

        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# handle_get_response_enable / handle_get_response_disable
# ---------------------------------------------------------------------------

class TestGetResponseHandlers(unittest.TestCase):
    """Tests for the get_response enable/disable bus handlers."""

    def test_handle_get_response_enable_sets_response_state(self):
        """enable handler puts the skill into RESPONSE utterance state."""
        sess = Session("s")
        sess.activate_skill("skill_a")
        msg = Message("skill.converse.get_response.enable",
                      data={"skill_id": "skill_a"},
                      context={"session": sess.serialize()})

        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess), \
             patch("ovos_core.intent_services.converse_service.SessionManager.sync"):
            ConverseService.handle_get_response_enable(msg)

        self.assertEqual(sess.utterance_states.get("skill_a"), UtteranceState.RESPONSE)

    def test_handle_get_response_disable_restores_intent_state(self):
        """disable handler removes the skill from RESPONSE state."""
        sess = Session("s")
        sess.activate_skill("skill_a")
        sess.enable_response_mode("skill_a")
        msg = Message("skill.converse.get_response.disable",
                      data={"skill_id": "skill_a"},
                      context={"session": sess.serialize()})

        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess), \
             patch("ovos_core.intent_services.converse_service.SessionManager.sync"):
            ConverseService.handle_get_response_disable(msg)

        self.assertNotEqual(sess.utterance_states.get("skill_a"), UtteranceState.RESPONSE)

    def test_handle_get_response_enable_syncs_default_session(self):
        """enable handler calls SessionManager.sync for the default session."""
        sess = Session("default")
        sess.activate_skill("skill_a")
        msg = Message("skill.converse.get_response.enable",
                      data={"skill_id": "skill_a"},
                      context={"session": sess.serialize()})

        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess), \
             patch("ovos_core.intent_services.converse_service.SessionManager.sync") as mock_sync:
            ConverseService.handle_get_response_enable(msg)

        mock_sync.assert_called_once()

    def test_handle_get_response_disable_syncs_default_session(self):
        """disable handler calls SessionManager.sync for the default session."""
        sess = Session("default")
        sess.activate_skill("skill_a")
        sess.enable_response_mode("skill_a")
        msg = Message("skill.converse.get_response.disable",
                      data={"skill_id": "skill_a"},
                      context={"session": sess.serialize()})

        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess), \
             patch("ovos_core.intent_services.converse_service.SessionManager.sync") as mock_sync:
            ConverseService.handle_get_response_disable(msg)

        mock_sync.assert_called_once()


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------

class TestShutdown(unittest.TestCase):
    """Tests for ConverseService.shutdown cleanup."""

    def test_shutdown_removes_all_listeners(self):
        """shutdown() must call bus.remove for every registered event."""
        svc = _make_service()
        svc.bus.remove = MagicMock()
        svc.shutdown()

        removed = {c[0][0] for c in svc.bus.remove.call_args_list}
        expected = {
            "converse:skill",
            "intent.service.skills.deactivate",
            "intent.service.skills.activate",
            "intent.service.active_skills.get",
            "skill.converse.get_response.enable",
            "skill.converse.get_response.disable",
        }
        self.assertEqual(removed, expected)


class TestConverseHandlerLifecycle(unittest.TestCase):
    """The converse dispatch hop emits the framework done-signal so an
    orchestrator (OVOS-PIPELINE-1 §8) can resolve the lifecycle of a reserved
    ``converse`` dispatch instead of hitting its handler timeout."""

    def _service_with_capture(self):
        svc = _make_service()
        bus = FakeBus()
        captured = []
        # FakeBus emits the "message" catch-all as a serialized string; parse it
        # back into a Message so assertions can read msg_type/context/data.
        bus.on("message", lambda s: captured.append(Message.deserialize(s)))
        svc.bus = bus
        return svc, captured

    def test_dispatch_emits_handler_start_with_skill_id(self):
        """handle_converse emits mycroft.skill.handler.start at dispatch,
        stamped with the targeted skill_id, then the converse.request."""
        svc, captured = self._service_with_capture()
        msg = Message("converse:skill", {"skill_id": "skill_a",
                                         "utterances": ["hello"]})
        svc.handle_converse(msg)

        topics = [m.msg_type for m in captured]
        self.assertIn("mycroft.skill.handler.start", topics)
        self.assertIn("skill_a.converse.request", topics)
        # start fires before the dispatch
        self.assertLess(topics.index("mycroft.skill.handler.start"),
                        topics.index("skill_a.converse.request"))
        start = next(m for m in captured
                     if m.msg_type == "mycroft.skill.handler.start")
        self.assertEqual(start.context.get("skill_id"), "skill_a")

    def test_skill_response_emits_handler_complete(self):
        """When the targeted skill replies skill.converse.response, the
        lifecycle completes (mycroft.skill.handler.complete, same skill_id)."""
        svc, captured = self._service_with_capture()
        msg = Message("converse:skill", {"skill_id": "skill_a",
                                         "utterances": ["hello"]})
        svc.handle_converse(msg)
        captured.clear()

        svc.bus.emit(Message("skill.converse.response",
                             {"skill_id": "skill_a", "result": True}))

        topics = [m.msg_type for m in captured]
        self.assertIn("mycroft.skill.handler.complete", topics)
        complete = next(m for m in captured
                        if m.msg_type == "mycroft.skill.handler.complete")
        self.assertEqual(complete.context.get("skill_id"), "skill_a")

    def test_response_from_other_skill_does_not_complete(self):
        """A converse.response from a different skill must not resolve the
        lifecycle for the targeted skill."""
        svc, captured = self._service_with_capture()
        msg = Message("converse:skill", {"skill_id": "skill_a",
                                         "utterances": ["hello"]})
        svc.handle_converse(msg)
        captured.clear()

        svc.bus.emit(Message("skill.converse.response",
                             {"skill_id": "other_skill", "result": True}))
        topics = [m.msg_type for m in captured]
        self.assertNotIn("mycroft.skill.handler.complete", topics)

    def test_exactly_one_terminal_on_repeated_response(self):
        """Only the first converse.response resolves the lifecycle; a duplicate
        does not emit a second terminal."""
        svc, captured = self._service_with_capture()
        msg = Message("converse:skill", {"skill_id": "skill_a",
                                         "utterances": ["hello"]})
        svc.handle_converse(msg)
        captured.clear()

        svc.bus.emit(Message("skill.converse.response",
                             {"skill_id": "skill_a", "result": True}))
        svc.bus.emit(Message("skill.converse.response",
                             {"skill_id": "skill_a", "result": True}))
        completes = [m for m in captured
                     if m.msg_type == "mycroft.skill.handler.complete"]
        self.assertEqual(len(completes), 1)

    def test_timeout_emits_handler_error(self):
        """When no converse.response arrives, the lifecycle errors out (a
        mycroft.skill.handler.error terminal), patched to a tiny timeout."""
        svc, captured = self._service_with_capture()
        msg = Message("converse:skill", {"skill_id": "skill_a",
                                         "utterances": ["hello"]})
        with patch("ovos_core.intent_services.converse_service.CONVERSE_HANDLER_TIMEOUT", 0.05):
            svc.handle_converse(msg)
            time.sleep(0.2)
        topics = [m.msg_type for m in captured]
        self.assertIn("mycroft.skill.handler.error", topics)
        err = next(m for m in captured
                   if m.msg_type == "mycroft.skill.handler.error")
        self.assertEqual(err.context.get("skill_id"), "skill_a")
        self.assertIn("exception", err.data)


if __name__ == "__main__":
    unittest.main()
