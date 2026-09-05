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
from ovos_bus_client.session import Session, SessionManager, UtteranceState
from ovos_spec_tools import SpecMessage
from ovos_utils.fakebus import FakeBus
from ovos_workshop.permissions import ConverseMode, ConverseActivationMode

from ovos_core.intent_services.converse_service import ConverseService
from ovos_core.intent_services.working_session import close_round, open_round


def _round(msg_type: str, data: dict, session: Session,
           carrier: Session = None) -> Message:
    """A Message inside an open utterance round whose working session is
    ``session``.

    ``carrier`` is what the Message itself declares in
    ``context["session"]`` — pass a stale snapshot to prove the round's
    session is what gets written, per OVOS-SESSION-2 §2.6.
    """
    msg = Message(msg_type, data=data,
                  context={"session": (carrier or session).serialize(),
                           "utterance_id": f"uid-{session.session_id}"})
    open_round(msg, session)
    return msg


def _make_service() -> ConverseService:
    """Construct a ConverseService with a FakeBus, bypassing __init__."""
    svc = ConverseService.__new__(ConverseService)
    svc.bus = FakeBus()
    svc.config = {}
    svc._consecutive_activations = {}
    return svc


# ---------------------------------------------------------------------------
# get_active_skills
# ---------------------------------------------------------------------------

class TestGetActiveSkillsCandidateSet(unittest.TestCase):
    """OVOS-CONVERSE-1 §2.1: "session.converse_handlers is this
    specification's converse eligibility list ... It is distinct from
    session.active_handlers (OVOS-PIPELINE-1 §7.1), which is the
    dispatch-recency record used by the stop cascade." The converse
    plugin's candidate set MUST be read from converse_handlers."""

    def test_reads_converse_handlers_not_active_handlers(self):
        sess = Session("s")
        sess.activate_skill("stopped_skill")  # active_handlers only
        sess.add_converse_handler("converse_skill")  # converse_handlers only

        result = ConverseService.get_active_skills(session=sess)

        self.assertEqual(result, ["converse_skill"])
        self.assertNotIn("stopped_skill", result)

    def test_targeted_stop_survivor_stays_a_candidate(self):
        """§2.1: "A skill removed from active_handlers by a targeted stop
        remains in converse_handlers and may still be offered converse
        turns." """
        sess = Session("s")
        sess.add_converse_handler("skill_a")
        sess.deactivate_skill("skill_a")  # targeted-stop-style removal

        result = ConverseService.get_active_skills(session=sess)

        self.assertEqual(result, ["skill_a"])


# ---------------------------------------------------------------------------
# _prune_converse_handlers
# ---------------------------------------------------------------------------

class TestPruneConverseHandlers(unittest.TestCase):
    """OVOS-CONVERSE-1 §3.2 TTL prune, reusing the existing
    ``converse.timeout`` / ``converse.skill_timeouts`` deployment surface
    (default 300s) rather than a second TTL key."""

    def test_expired_entry_pruned_before_polling(self):
        """§3.2: "prunes any entry whose age (now - activated_at) exceeds T"
        at the "Pre-converse" boundary, "immediately before a converse
        plugin (§4) begins its poll iteration for the current utterance."
        """
        svc = _make_service()
        svc.config = {"timeout": 60}
        sess = Session("s")
        now = time.time()
        sess.add_converse_handler("stale_skill", activated_at=now - 120)
        sess.add_converse_handler("fresh_skill", activated_at=now - 5)

        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            svc._prune_converse_handlers(Message("test"))

        remaining = ConverseService.get_active_skills(session=sess)
        self.assertNotIn("stale_skill", remaining)
        self.assertIn("fresh_skill", remaining)

    def test_default_300s_timeout_applied_when_unconfigured(self):
        """No ``converse.timeout`` configured falls back to the existing
        300s default -- a deployment without any converse config still gets
        a real window, unlike a second, empty TTL key would."""
        svc = _make_service()
        sess = Session("s")
        now = time.time()
        sess.add_converse_handler("old_skill", activated_at=now - 400)
        sess.add_converse_handler("recent_skill", activated_at=now - 10)

        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            svc._prune_converse_handlers(Message("test"))

        remaining = ConverseService.get_active_skills(session=sess)
        self.assertNotIn("old_skill", remaining)
        self.assertIn("recent_skill", remaining)

    def test_per_skill_timeout_override_respected(self):
        """A ``converse.skill_timeouts`` per-skill override takes precedence
        over the default window."""
        svc = _make_service()
        svc.config = {"skill_timeouts": {"short_skill": 5}, "timeout": 300}
        sess = Session("s")
        now = time.time()
        sess.add_converse_handler("short_skill", activated_at=now - 10)
        sess.add_converse_handler("long_skill", activated_at=now - 10)

        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            svc._prune_converse_handlers(Message("test"))

        remaining = ConverseService.get_active_skills(session=sess)
        self.assertNotIn("short_skill", remaining)
        self.assertIn("long_skill", remaining)

    def test_response_mode_holder_exempt_from_prune(self):
        """§2.1: the response-mode holder MUST NOT be pruned by the §3.2
        TTL, even when its entry is otherwise stale."""
        svc = _make_service()
        svc.config = {"timeout": 60}
        sess = Session("s")
        now = time.time()
        sess.add_converse_handler("holder_skill", activated_at=now - 120)
        sess.response_mode = {"skill_id": "holder_skill", "expires_at": now + 60}

        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            svc._prune_converse_handlers(Message("test"))

        self.assertIn("holder_skill", ConverseService.get_active_skills(session=sess))


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

        # both legs of the dual-emit compat window must be unbound
        removed = [call[0][0] for call in svc.bus.remove.call_args_list]
        self.assertEqual(sorted(removed),
                         ["ovos.converse.pong", "skill.converse.pong"])

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
             patch.object(svc, "_prune_converse_handlers"):
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
             patch.object(svc, "_prune_converse_handlers"):
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
             patch.object(svc, "_prune_converse_handlers"):
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
             patch.object(svc, "_prune_converse_handlers"):
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
             patch.object(svc, "_prune_converse_handlers"):
            result = svc.match(["hello"], "en-US", Message("test", context={}))

        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# match() fold-chain threading (adversarial review finding F2)
# ---------------------------------------------------------------------------

class TestMatchFoldChainSurvival(unittest.TestCase):
    """`match()` folds `message` ONCE (legitimate lifecycle entry) and must
    thread that resolved session through `_prune_converse_handlers` and
    `_collect_converse_skills` rather than letting either re-resolve via
    `SessionManager.get(message)` - a second fold of the SAME (now stale
    relative to the TTL prune) message would undo the prune's write. These
    tests exercise the REAL registry end to end (no mocking of
    SessionManager.get / _prune_converse_handlers / _collect_converse_skills)
    so they catch a regression to per-step re-folding."""

    def setUp(self):
        self._saved_sessions = dict(SessionManager.sessions)
        SessionManager.sessions.clear()

    def tearDown(self):
        SessionManager.sessions.clear()
        SessionManager.sessions.update(self._saved_sessions)

    def test_timeout_filtered_skill_stays_filtered_through_collect_converse(self):
        """A skill removed by the TTL prune must not reappear because
        `_collect_converse_skills` re-folded the same stale message and
        restored the client's originally-declared (pre-prune)
        converse_handlers list."""
        bus = FakeBus()
        svc = _make_service()
        now = time.time()
        sess = Session("named-match-1")
        # both skills are converse candidates on the round; skill_old is
        # long expired (past the 300s default converse.timeout)
        sess.add_converse_handler("skill_old", activated_at=now - 400)
        sess.add_converse_handler("skill_new", activated_at=now - 1)

        msg = _round("recognizer_loop:utterance",
                     {"utterances": ["hello"]}, sess)

        # no skill is listening on skill.converse.pong, so _collect_converse_skills
        # will time out its 0.5s wait with an empty want_converse - match()
        # returns None, which is fine, we only care about the working
        # session's converse_handlers state afterward.
        svc.match(["hello"], "en-US", msg)

        remaining = [h["skill_id"] for h in sess.converse_handlers]
        self.assertNotIn("skill_old", remaining)
        self.assertIn("skill_new", remaining)
        close_round(msg)


# ---------------------------------------------------------------------------
# handle_activate_skill_request / handle_deactivate_skill_request
# reject / no-op paths (adversarial review finding F3)
# ---------------------------------------------------------------------------

class TestActivateDeactivateSkillRequestHandlers(unittest.TestCase):
    """`handle_activate_skill_request`/`handle_deactivate_skill_request`
    used to always call a trailing `SessionManager.get(message)` to decide
    whether to sync, including on the reject (blocked activation) / no-op
    (deactivating an already-inactive skill) paths - an unconditional fold
    of a possibly-stale message with nothing to sync. They now reuse the
    session `activate_skill`/`deactivate_skill` returns (None on those
    paths) and skip the fold+sync entirely when nothing changed."""

    def setUp(self):
        self._saved_sessions = dict(SessionManager.sessions)
        SessionManager.sessions.clear()

    def tearDown(self):
        SessionManager.sessions.clear()
        SessionManager.sessions.update(self._saved_sessions)

    def test_activate_skill_request_reject_path_does_not_sync(self):
        """A blocked activation (cross-activation disallowed) must not call
        SessionManager.sync."""
        bus = FakeBus()
        svc = _make_service()
        svc.config = {"cross_activation": False}
        sess = Session("default")
        SessionManager.sessions[sess.session_id] = sess
        msg = Message("intent.service.skills.activate",
                      data={"skill_id": "skill_a"},
                      context={"session": sess.serialize(), "skill_id": "skill_b"})

        with patch("ovos_core.intent_services.converse_service.SessionManager.sync") as mock_sync:
            svc.handle_activate_skill_request(msg)

        mock_sync.assert_not_called()
        live = SessionManager.sessions[sess.session_id]
        self.assertFalse(live.is_active("skill_a"))

    def test_deactivate_skill_request_noop_path_does_not_sync(self):
        """Deactivating a skill that isn't active is a no-op and must not
        call SessionManager.sync."""
        bus = FakeBus()
        svc = _make_service()
        sess = Session("default")
        SessionManager.sessions[sess.session_id] = sess
        msg = Message("intent.service.skills.deactivate",
                      data={"skill_id": "skill_a"},
                      context={"session": sess.serialize()})

        with patch("ovos_core.intent_services.converse_service.SessionManager.sync") as mock_sync:
            svc.handle_deactivate_skill_request(msg)

        mock_sync.assert_not_called()

    def test_activate_skill_request_success_path_syncs_default(self):
        """A successful activation for the default session still syncs."""
        bus = FakeBus()
        svc = _make_service()
        sess = Session("default")
        SessionManager.sessions[sess.session_id] = sess
        msg = Message("intent.service.skills.activate",
                      data={"skill_id": "skill_a"},
                      context={"session": sess.serialize(), "skill_id": "skill_a"})

        with patch("ovos_core.intent_services.converse_service.SessionManager.sync") as mock_sync:
            svc.handle_activate_skill_request(msg)

        mock_sync.assert_called_once()
        live = SessionManager.sessions[sess.session_id]
        self.assertTrue(live.is_active("skill_a"))

    def test_deactivate_skill_request_success_path_syncs_default(self):
        """A successful deactivation for the default session still syncs."""
        bus = FakeBus()
        svc = _make_service()
        sess = Session("default")
        sess.activate_skill("skill_a")
        SessionManager.sessions[sess.session_id] = sess
        msg = Message("intent.service.skills.deactivate",
                      data={"skill_id": "skill_a"},
                      context={"session": sess.serialize()})

        with patch("ovos_core.intent_services.converse_service.SessionManager.sync") as mock_sync:
            svc.handle_deactivate_skill_request(msg)

        mock_sync.assert_called_once()
        live = SessionManager.sessions[sess.session_id]
        self.assertFalse(live.is_active("skill_a"))


# ---------------------------------------------------------------------------
# handle_get_response_enable / handle_get_response_disable
# ---------------------------------------------------------------------------

class TestGetResponseHandlers(unittest.TestCase):
    """Tests for the get_response enable/disable bus handlers.

    A get_response toggle is a bus event a skill emits while its round is in
    flight, so the write belongs on that round's working session
    (OVOS-SESSION-2 §2.6). These tests drive the real handlers inside a real
    open round and assert on the session object the round is running on.
    """

    def tearDown(self):
        SessionManager.sessions.clear()
        SessionManager.reset_default_session()

    def test_handle_get_response_enable_sets_response_state(self):
        """enable handler puts the skill into RESPONSE utterance state."""
        sess = Session("s")
        sess.activate_skill("skill_a")
        msg = _round("skill.converse.get_response.enable",
                     {"skill_id": "skill_a"}, sess)

        ConverseService.handle_get_response_enable(msg)

        self.assertEqual(sess.utterance_states.get("skill_a"),
                         UtteranceState.RESPONSE)
        close_round(msg)

    def test_handle_get_response_disable_restores_intent_state(self):
        """disable handler removes the skill from RESPONSE state."""
        sess = Session("s")
        sess.activate_skill("skill_a")
        sess.enable_response_mode("skill_a")
        msg = _round("skill.converse.get_response.disable",
                     {"skill_id": "skill_a"}, sess)

        ConverseService.handle_get_response_disable(msg)

        self.assertNotEqual(sess.utterance_states.get("skill_a"),
                            UtteranceState.RESPONSE)
        close_round(msg)

    def test_handle_get_response_enable_syncs_default_session(self):
        """enable handler calls SessionManager.sync for the default session."""
        sess = Session("default")
        sess.activate_skill("skill_a")
        SessionManager.sessions[sess.session_id] = sess
        msg = Message("skill.converse.get_response.enable",
                      data={"skill_id": "skill_a"},
                      context={"session": sess.serialize()})

        with patch("ovos_core.intent_services.converse_service.SessionManager.sync") as mock_sync:
            ConverseService.handle_get_response_enable(msg)

        mock_sync.assert_called_once()

    def test_handle_get_response_disable_syncs_default_session(self):
        """disable handler calls SessionManager.sync for the default session."""
        sess = Session("default")
        sess.activate_skill("skill_a")
        sess.enable_response_mode("skill_a")
        SessionManager.sessions[sess.session_id] = sess
        msg = Message("skill.converse.get_response.disable",
                      data={"skill_id": "skill_a"},
                      context={"session": sess.serialize()})

        with patch("ovos_core.intent_services.converse_service.SessionManager.sync") as mock_sync:
            ConverseService.handle_get_response_disable(msg)

        mock_sync.assert_called_once()

    def test_get_response_enable_survives_stale_named_session_snapshot(self):
        """A named session's get_response write lands on the round's working
        session, and the stale snapshot the Message happens to carry does not
        revise it (OVOS-SESSION-2 §2.6).

        The Message declares a snapshot unaware of skill_b's activation. If
        the handler wrote to a session folded from that carrier, skill_b's
        activation would be gone and the write would land on a throwaway the
        round never sees again — a named session has no registry entry to
        fall back on (§2.2)."""
        sess = Session("named-converse-1")
        sess.activate_skill("skill_a")
        sess.activate_skill("skill_b")  # state the stale snapshot doesn't know about

        stale = Session(sess.session_id)  # unaware of skill_b's activation
        msg = _round("skill.converse.get_response.enable",
                     {"skill_id": "skill_a"}, sess, carrier=stale)

        ConverseService.handle_get_response_enable(msg)

        self.assertEqual(sess.utterance_states.get("skill_a"),
                         UtteranceState.RESPONSE)
        self.assertTrue(sess.is_active("skill_b"))
        close_round(msg)

    def test_get_response_disable_survives_stale_named_session_snapshot(self):
        """Same as
        `test_get_response_enable_survives_stale_named_session_snapshot`,
        for `handle_get_response_disable`."""
        sess = Session("named-converse-4")
        sess.activate_skill("skill_a")
        sess.enable_response_mode("skill_a")
        sess.activate_skill("skill_b")  # state the stale snapshot doesn't know about

        stale = Session(sess.session_id)  # unaware of skill_b's activation
        msg = _round("skill.converse.get_response.disable",
                     {"skill_id": "skill_a"}, sess, carrier=stale)

        ConverseService.handle_get_response_disable(msg)

        self.assertNotEqual(sess.utterance_states.get("skill_a"),
                            UtteranceState.RESPONSE)
        self.assertTrue(sess.is_active("skill_b"))
        close_round(msg)

    def test_activate_skill_writes_the_working_session(self):
        """`activate_skill` writes the round's working session and stamps that
        session onto the outgoing wire message.

        The activation request carries a snapshot of its own. Per
        OVOS-SESSION-2 §2.6 that snapshot does not revise the working
        session, so a blacklist the request declares does not reach the round
        — the round's own blacklist, arrived at the §5.1 intake, is what the
        outgoing message carries."""
        bus = FakeBus()
        svc = ConverseService(bus=bus, config={})
        sess = Session("named-converse-2")
        sess.blacklisted_skills = ["skill_y"]

        declaring = Session(sess.session_id)
        declaring.blacklisted_skills = ["skill_x"]
        msg = _round("intent.service.skills.activate",
                     {"skill_id": "skill_a"}, sess, carrier=declaring)

        svc.activate_skill("skill_a", "skill_a", msg)

        self.assertTrue(sess.is_active("skill_a"))
        self.assertEqual(msg.context["session"]["blacklisted_skills"],
                         ["skill_y"])
        close_round(msg)

    def test_deactivate_skill_writes_the_working_session(self):
        """Same as above for `deactivate_skill`.

        The working session must itself have skill_a active, or the write
        branch (and its wire re-stamp) never runs and the assertions would
        pass off the carrier rather than off an actual write."""
        bus = FakeBus()
        svc = ConverseService(bus=bus, config={})
        sess = Session("named-converse-3")
        sess.activate_skill("skill_a")
        sess.blacklisted_skills = ["skill_y"]

        declaring = Session(sess.session_id)
        declaring.blacklisted_skills = ["skill_x"]
        msg = _round("intent.service.skills.deactivate",
                     {"skill_id": "skill_a"}, sess, carrier=declaring)

        svc.deactivate_skill("skill_a", "skill_a", msg)

        self.assertFalse(sess.is_active("skill_a"))
        self.assertEqual(msg.context["session"]["blacklisted_skills"],
                         ["skill_y"])
        close_round(msg)


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


# ---------------------------------------------------------------------------
# OVOS-PIPELINE-1 §9.1.1 / OVOS-CONVERSE-1 §4.2 — round correlation
# ---------------------------------------------------------------------------

class TestConverseRoundCorrelation(unittest.TestCase):
    """A pong must prove which round it answers, or it decides nothing."""

    def _run_round(self, svc, ping_msg, pongs):
        """Drive one _collect_converse_skills round, feeding it `pongs`."""
        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == "skill.converse.pong":
                ack_handler = handler

        svc.bus.on = capture_on
        svc.bus.remove = MagicMock()
        svc.bus.emit = MagicMock()

        result_holder = []

        def run():
            result_holder.append(svc._collect_converse_skills(ping_msg))

        t = threading.Thread(target=run)
        t.start()
        time.sleep(0.05)
        for pong in pongs:
            if ack_handler:
                ack_handler(pong)
        t.join(timeout=2)
        return result_holder[0]

    def test_stale_pong_from_previous_round_is_discarded(self):
        """The late-answer-wins-wrong-round reproducer.

        Round N-1 asks 'set a timer'; skill_a is slow. Round N asks
        'what is the weather'; skill_a's answer to the OLD question lands
        inside the new round's window. Without a correlation key the new
        round accepts it and hands the weather utterance to skill_a.
        """
        svc = _make_service()
        sess = Session("s")
        sess.activate_skill("skill_a")

        round_n = Message("test", {"utterances": ["what is the weather"]},
                          {"utterance_id": "round-N", "session": sess.serialize()})
        # skill_a's pong derives from the PREVIOUS round's ping, so it carries
        # that round's utterance_id (Message.reply deep-copies context).
        stale_pong = Message("skill.converse.pong",
                             {"skill_id": "skill_a", "can_handle": True},
                             {"utterance_id": "round-N-minus-1"})

        with patch.object(ConverseService, "get_active_skills",
                          return_value=["skill_a"]), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            result = self._run_round(svc, round_n, [stale_pong])

        self.assertEqual(result, [],
                         "a pong from an earlier lifecycle decided this round")

    def test_matching_pong_is_accepted(self):
        """The guard does not reject the round's own answer."""
        svc = _make_service()
        sess = Session("s")
        sess.activate_skill("skill_a")

        round_n = Message("test", {"utterances": ["what is the weather"]},
                          {"utterance_id": "round-N", "session": sess.serialize()})
        good_pong = round_n.reply("skill.converse.pong",
                                  {"skill_id": "skill_a", "can_handle": True})

        with patch.object(ConverseService, "get_active_skills",
                          return_value=["skill_a"]), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            result = self._run_round(svc, round_n, [good_pong])

        self.assertEqual(result, ["skill_a"])

    def test_unnamed_round_accepts_pongs_as_before(self):
        """V0 compat: a round with no utterance_id keeps the old behaviour."""
        svc = _make_service()
        sess = Session("s")
        sess.activate_skill("skill_a")

        round_msg = Message("test", {"utterances": ["hello"]},
                            {"session": sess.serialize()})
        pong = Message("skill.converse.pong",
                       {"skill_id": "skill_a", "can_handle": True})

        with patch.object(ConverseService, "get_active_skills",
                          return_value=["skill_a"]), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            result = self._run_round(svc, round_msg, [pong])

        self.assertEqual(result, ["skill_a"])


# ---------------------------------------------------------------------------
# OVOS-CONVERSE-1 §4.1-§4.2 — the broadcast contest
# ---------------------------------------------------------------------------

class _FakeSkill:
    """A candidate on a real FakeBus, at a chosen wire vintage.

    ``legacy`` binds the per-skill ping and answers ``skill.converse.pong``
    with ``can_handle`` — the shape every ovos-workshop vintage up to and
    including 9.3.12a1 speaks. ``broadcast`` binds the static
    ``ovos.converse.ping`` and answers ``ovos.converse.pong`` with ``result``
    — the OVOS-CONVERSE-1 §4.2 shape. A current skill binds both.
    """

    def __init__(self, bus, skill_id, claims, legacy=True, broadcast=True,
                 candidates=None):
        self.bus = bus
        self.skill_id = skill_id
        self.claims = claims
        self.candidates = candidates
        self.pings_seen = []
        if legacy:
            bus.on(f"{skill_id}.converse.ping", self._legacy_ack)
        if broadcast:
            bus.on("ovos.converse.ping", self._broadcast_ack)

    def _legacy_ack(self, message):
        self.pings_seen.append(message.msg_type)
        self.bus.emit(message.reply(
            "skill.converse.pong",
            {"skill_id": self.skill_id, "can_handle": self.claims}))

    def _broadcast_ack(self, message):
        if self.candidates is not None and self.skill_id not in self.candidates:
            return  # not named by this round
        self.pings_seen.append(message.msg_type)
        self.bus.emit(message.reply(
            "ovos.converse.pong",
            {"skill_id": self.skill_id, "result": self.claims}))


class TestBroadcastContest(unittest.TestCase):
    """One broadcast question per round, answered in parallel."""

    def _round(self, svc, sess, active, utterance_id="round-1"):
        msg = Message("test", {"utterances": ["hello"], "lang": "en-US"},
                      {"utterance_id": utterance_id,
                       "session": sess.serialize()})
        with patch.object(ConverseService, "get_active_skills",
                          return_value=active), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            return svc._collect_converse_skills(msg)

    def _session(self, *skill_ids):
        sess = Session("s")
        for skill_id in skill_ids:
            sess.activate_skill(skill_id)
        return sess

    # -- FEATURE: the broadcast leg -------------------------------------

    def test_one_broadcast_ping_carries_no_candidate_identity(self):
        """FEATURE (OVOS-CONVERSE-1 §4.2). The round asks one question.

        The broadcast ping's topic is a static string and its payload names
        no candidate: membership is read from the session the `reply`
        derivation carries.
        """
        svc = _make_service()
        emitted = []
        svc.bus.on("ovos.converse.ping", lambda m: emitted.append(m))
        sess = self._session("skill_a", "skill_b")
        self._round(svc, sess, ["skill_a", "skill_b"])

        self.assertEqual(len(emitted), 1,
                         "the round must ask exactly one broadcast question")
        self.assertNotIn("skill_id", emitted[0].data)
        self.assertEqual(sorted(emitted[0].data), ["lang", "utterances"])

    def test_new_core_new_skill_converses_over_broadcast_leg(self):
        """FEATURE. New core + new skill: the broadcast leg carries the claim."""
        svc = _make_service()
        sess = self._session("skill_a")
        skill = _FakeSkill(svc.bus, "skill_a", claims=True,
                           candidates=["skill_a"])
        result = self._round(svc, sess, ["skill_a"])

        self.assertEqual(result, ["skill_a"])
        self.assertIn("ovos.converse.ping", skill.pings_seen)

    def test_new_core_old_skill_converses_over_legacy_leg(self):
        """V0 COMPAT. New core + a skill that only binds the legacy ping.

        This is every released ovos-workshop up to 9.3.12a1. It never sees
        the broadcast question, so the dual-emit's legacy leg is the only
        thing keeping it in the contest.
        """
        svc = _make_service()
        sess = self._session("skill_a")
        skill = _FakeSkill(svc.bus, "skill_a", claims=True, broadcast=False)
        result = self._round(svc, sess, ["skill_a"])

        self.assertEqual(result, ["skill_a"],
                         "a legacy-only skill lost its converse turn")
        self.assertEqual(skill.pings_seen, ["skill_a.converse.ping"])

    def test_mixed_fleet_both_vintages_counted(self):
        """V0 COMPAT. Old and new skills contest the same round."""
        svc = _make_service()
        sess = self._session("old_skill", "new_skill")
        _FakeSkill(svc.bus, "new_skill", claims=False,
                   candidates=["old_skill", "new_skill"])
        _FakeSkill(svc.bus, "old_skill", claims=True, broadcast=False)
        # recency: new_skill activated last, so it heads the list
        result = self._round(svc, sess, ["new_skill", "old_skill"])

        self.assertEqual(result, ["old_skill"])

    def test_broadcast_candidates_are_converse_handlers_not_active_handlers(self):
        """§2.1/§4.2: the broadcast leg's candidate set is
        session.converse_handlers, read via the real (unpatched)
        get_active_skills -- a skill present only in converse_handlers
        (never activated on active_handlers) is polled and can claim."""
        svc = _make_service()
        sess = Session("s")
        sess.add_converse_handler("skill_a")
        skill = _FakeSkill(svc.bus, "skill_a", claims=True,
                           candidates=["skill_a"])
        msg = Message("test", {"utterances": ["hello"], "lang": "en-US"},
                      {"utterance_id": "round-1", "session": sess.serialize()})

        with patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            result = svc._collect_converse_skills(msg)

        self.assertEqual(result, ["skill_a"])
        self.assertIn("ovos.converse.ping", skill.pings_seen)

    # -- DEFECT: a candidate answering twice was counted twice -----------

    def test_dual_answer_counts_the_skill_once_first_pong_wins(self):
        """DEFECT (red before fix). §4.2 'the first valid pong per candidate wins'.

        A current skill answers the dual-emitted round twice. The two pongs
        disagree — the broadcast leg declines, the legacy leg claims. Before
        the fix the collector took the claim from the second pong, so a
        skill that declined the round still got the converse dispatch.
        """
        svc = _make_service()
        sess = self._session("skill_a")

        def decline_broadcast(message):
            svc.bus.emit(message.reply(
                "ovos.converse.pong", {"skill_id": "skill_a", "result": False}))

        def claim_legacy(message):
            svc.bus.emit(message.reply(
                "skill.converse.pong", {"skill_id": "skill_a", "can_handle": True}))

        svc.bus.on("ovos.converse.ping", decline_broadcast)
        svc.bus.on("skill_a.converse.ping", claim_legacy)
        result = self._round(svc, sess, ["skill_a"])

        self.assertEqual(result, [],
                         "the second pong overrode the candidate's first answer")

    def test_repeated_claim_yields_one_entry(self):
        """DEFECT. A skill answering both legs appears once, not twice."""
        svc = _make_service()
        sess = self._session("skill_a")
        _FakeSkill(svc.bus, "skill_a", claims=True, candidates=["skill_a"])
        result = self._round(svc, sess, ["skill_a"])

        self.assertEqual(result, ["skill_a"])

    # -- DEFECT: selection followed arrival order, not recency -----------

    def test_selection_is_by_recency_not_arrival_order(self):
        """DEFECT (red before fix). §4.1 step 3: 'Selection is never by
        response-arrival order.'

        Both candidates claim. The least-recent one answers first — which is
        exactly what a parallel broadcast round makes likely, since the
        candidates now race instead of being polled in order. The winner
        must still be the head of the recency list.
        """
        svc = _make_service()
        sess = self._session("skill_b", "skill_a")  # skill_a is now head
        pings = []

        def answer_both(message):
            pings.append(message)
            # skill_b (the tail) is quicker off the mark
            for skill_id in ("skill_b", "skill_a"):
                svc.bus.emit(message.reply(
                    "ovos.converse.pong", {"skill_id": skill_id, "result": True}))

        svc.bus.on("ovos.converse.ping", answer_both)
        result = self._round(svc, sess, ["skill_a", "skill_b"])

        self.assertEqual(result, ["skill_a", "skill_b"],
                         "the round was decided by who answered first")

    # -- FEATURE: early close --------------------------------------------

    def test_round_closes_early_when_every_candidate_answered(self):
        """FEATURE (§4.2). The window closes as soon as the answer set is complete.

        Three candidates, all declining. The round must not sit out the
        0.5s collection ceiling once nothing more can arrive.
        """
        svc = _make_service()
        sess = self._session("skill_a", "skill_b", "skill_c")
        for skill_id in ("skill_a", "skill_b", "skill_c"):
            _FakeSkill(svc.bus, skill_id, claims=False,
                       candidates=["skill_a", "skill_b", "skill_c"])

        start = time.monotonic()
        result = self._round(svc, sess, ["skill_a", "skill_b", "skill_c"])
        elapsed = time.monotonic() - start

        self.assertEqual(result, [])
        self.assertLess(elapsed, 0.4,
                        "the round waited out the ceiling after every "
                        "candidate had already answered")

    def test_silent_candidate_waits_out_the_single_window(self):
        """FEATURE (§4.2). The ceiling is one window for the whole round,
        not n x a per-owner wait: three silent candidates still cost 0.5s
        once, and a silent candidate is treated as a decline."""
        svc = _make_service()
        sess = self._session("skill_a", "skill_b", "skill_c")

        start = time.monotonic()
        result = self._round(svc, sess, ["skill_a", "skill_b", "skill_c"])
        elapsed = time.monotonic() - start

        self.assertEqual(result, [])
        self.assertLess(elapsed, 1.0,
                        "the round cost more than one collection window")

    # -- pong hygiene -----------------------------------------------------

    def test_foreign_claim_never_wins_the_round(self):
        """§4.2. A claim from a skill outside the candidate set decides nothing.

        The stranger is the ONLY claimer of the round, so if the candidate-set
        filter on the returned list stops carrying this, the round hands the
        utterance to a skill it never asked. Mutation-checked: returning the
        raw claim set instead of the filtered recency list fails this test.
        """
        svc = _make_service()
        sess = self._session("skill_a")

        def answer_as_stranger(message):
            svc.bus.emit(message.reply(
                "ovos.converse.pong", {"skill_id": "stranger", "result": True}))

        svc.bus.on("ovos.converse.ping", answer_as_stranger)
        result = self._round(svc, sess, ["skill_a"])
        self.assertEqual(result, [])

    def test_foreign_pong_does_not_close_the_round_early(self):
        """§4.2. A stranger's answer must not stand in for a candidate's.

        skill_a is the round's only candidate and stays silent. A stranger
        answers immediately. The round must still wait out its window rather
        than treat the stranger's pong as the answer set being complete.
        """
        svc = _make_service()
        sess = self._session("skill_a")

        def answer_as_stranger(message):
            svc.bus.emit(message.reply(
                "ovos.converse.pong", {"skill_id": "stranger", "result": False}))

        svc.bus.on("ovos.converse.ping", answer_as_stranger)
        start = time.monotonic()
        result = self._round(svc, sess, ["skill_a"])
        elapsed = time.monotonic() - start

        self.assertEqual(result, [])
        self.assertGreaterEqual(elapsed, 0.4,
                                "a stranger's pong satisfied the round's "
                                "answer bookkeeping")

    def test_both_legs_carry_identical_poll_data(self):
        """DEFECT (red before fix). A skill that binds both legs must decide
        from the same input whichever ping reaches it first.

        When the broadcast leg carried a trimmed payload and the legacy leg
        the full inbound data, the same skill answered the same round from
        different inputs and the verdict became a thread race.
        """
        svc = _make_service()
        sess = self._session("skill_a")
        seen = {}

        svc.bus.on("ovos.converse.ping",
                   lambda m: seen.__setitem__("broadcast", dict(m.data)))
        svc.bus.on("skill_a.converse.ping",
                   lambda m: seen.__setitem__("legacy", dict(m.data)))

        msg = Message("test",
                      {"utterances": ["hello"], "lang": "en-US",
                       "confidence": 0.9},
                      {"utterance_id": "round-1", "session": sess.serialize()})
        with patch.object(ConverseService, "get_active_skills",
                          return_value=["skill_a"]), \
             patch("ovos_core.intent_services.converse_service.SessionManager.get",
                   return_value=sess):
            svc._collect_converse_skills(msg)

        legacy = {k: v for k, v in seen["legacy"].items() if k != "skill_id"}
        self.assertEqual(seen["broadcast"], legacy,
                         "the two legs fed can_converse different data")
        # the round's extra inbound fields must survive onto the broadcast leg
        self.assertEqual(seen["broadcast"]["confidence"], 0.9)
        # and the broadcast leg still names no candidate
        self.assertNotIn("skill_id", seen["broadcast"])

    def test_non_boolean_result_is_a_decline(self):
        """§4.2. A missing or non-boolean claim value is treated as False."""
        svc = _make_service()
        sess = self._session("skill_a")

        def answer_garbage(message):
            svc.bus.emit(message.reply(
                "ovos.converse.pong", {"skill_id": "skill_a", "result": "yes"}))

        svc.bus.on("ovos.converse.ping", answer_garbage)
        result = self._round(svc, sess, ["skill_a"])
        self.assertEqual(result, [])
