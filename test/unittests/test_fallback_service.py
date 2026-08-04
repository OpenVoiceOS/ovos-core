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
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.fakebus import FakeBus
from ovos_workshop.permissions import FallbackMode

from ovos_core.intent_services.fallback_service import FallbackService, FallbackRange


def _make_service(config=None) -> FallbackService:
    """Construct a FallbackService backed by a FakeBus, bypassing __init__ config load."""
    bus = FakeBus()
    with patch("ovos_core.intent_services.fallback_service.ConfidenceMatcherPipeline.__init__",
               lambda self, *a, **kw: None):
        svc = FallbackService.__new__(FallbackService)
        svc.bus = bus
        svc.config = config or {}
        svc.registered_fallbacks = {}
        svc._registered_fallbacks_lock = threading.RLock()
        svc._fallback_session_locks = {}
        svc._fallback_session_locks_lock = threading.Lock()
        svc._lifecycle_handlers = {}
        svc.bus.on("ovos.skills.fallback.register", svc.handle_register_fallback)
        svc.bus.on("ovos.skills.fallback.deregister", svc.handle_deregister_fallback)
    return svc


class TestHandleRegisterFallback(unittest.TestCase):
    """Tests for FallbackService.handle_register_fallback."""

    def test_register_stores_skill_and_priority(self):
        """Registering a skill stores it with the given priority."""
        svc = _make_service()
        msg = Message("ovos.skills.fallback.register",
                      {"skill_id": "skill_a", "priority": 50})
        svc.handle_register_fallback(msg)
        self.assertIn("skill_a", svc.registered_fallbacks)
        self.assertEqual(svc.registered_fallbacks["skill_a"], 50)

    def test_register_defaults_priority_to_101_when_missing(self):
        """When priority is absent, default priority 101 is used."""
        svc = _make_service()
        msg = Message("ovos.skills.fallback.register", {"skill_id": "skill_b"})
        svc.handle_register_fallback(msg)
        self.assertEqual(svc.registered_fallbacks["skill_b"], 101)

    def test_register_defaults_priority_to_101_when_none(self):
        """When priority is explicitly None, default priority 101 is used."""
        svc = _make_service()
        msg = Message("ovos.skills.fallback.register",
                      {"skill_id": "skill_c", "priority": None})
        svc.handle_register_fallback(msg)
        self.assertEqual(svc.registered_fallbacks["skill_c"], 101)

    def test_register_with_config_priority_override(self):
        """Config fallback_priorities override the skill-reported priority."""
        svc = _make_service(config={"fallback_priorities": {"skill_a": 10}})
        msg = Message("ovos.skills.fallback.register",
                      {"skill_id": "skill_a", "priority": 80})
        svc.handle_register_fallback(msg)
        self.assertEqual(svc.registered_fallbacks["skill_a"], 10)

    def test_register_no_override_when_skill_not_in_priorities(self):
        """No override applied when skill is not listed in fallback_priorities."""
        svc = _make_service(config={"fallback_priorities": {"other_skill": 5}})
        msg = Message("ovos.skills.fallback.register",
                      {"skill_id": "skill_a", "priority": 60})
        svc.handle_register_fallback(msg)
        self.assertEqual(svc.registered_fallbacks["skill_a"], 60)

    def test_bus_message_triggers_register(self):
        """Emitting the register message on the bus triggers registration."""
        svc = _make_service()
        svc.bus.emit(Message("ovos.skills.fallback.register",
                             {"skill_id": "bus_skill", "priority": 30}))
        self.assertIn("bus_skill", svc.registered_fallbacks)


class TestHandleDeregisterFallback(unittest.TestCase):
    """Tests for FallbackService.handle_deregister_fallback."""

    def test_deregister_removes_known_skill(self):
        """Deregistering a known skill removes it from registered_fallbacks."""
        svc = _make_service()
        svc.registered_fallbacks["skill_a"] = 50
        msg = Message("ovos.skills.fallback.deregister", {"skill_id": "skill_a"})
        svc.handle_deregister_fallback(msg)
        self.assertNotIn("skill_a", svc.registered_fallbacks)

    def test_deregister_unknown_skill_is_noop(self):
        """Deregistering an unknown skill does not raise and leaves dict intact."""
        svc = _make_service()
        svc.registered_fallbacks["skill_b"] = 40
        msg = Message("ovos.skills.fallback.deregister", {"skill_id": "unknown"})
        svc.handle_deregister_fallback(msg)
        self.assertIn("skill_b", svc.registered_fallbacks)

    def test_bus_message_triggers_deregister(self):
        """Emitting the deregister message on the bus triggers removal."""
        svc = _make_service()
        svc.registered_fallbacks["bus_skill"] = 70
        svc.bus.emit(Message("ovos.skills.fallback.deregister",
                             {"skill_id": "bus_skill"}))
        self.assertNotIn("bus_skill", svc.registered_fallbacks)


class TestFallbackAllowed(unittest.TestCase):
    """Tests for FallbackService._fallback_allowed."""

    def test_accept_all_mode_always_returns_true(self):
        """ACCEPT_ALL mode allows any skill."""
        svc = _make_service(config={"fallback_mode": FallbackMode.ACCEPT_ALL})
        self.assertTrue(svc._fallback_allowed("any_skill"))

    def test_default_mode_allows_all_skills(self):
        """When fallback_mode is absent the default is ACCEPT_ALL."""
        svc = _make_service(config={})
        self.assertTrue(svc._fallback_allowed("any_skill"))

    def test_blacklist_mode_blocks_blacklisted_skill(self):
        """BLACKLIST mode denies skills on the blacklist."""
        svc = _make_service(config={
            "fallback_mode": FallbackMode.BLACKLIST,
            "fallback_blacklist": ["bad_skill"],
        })
        self.assertFalse(svc._fallback_allowed("bad_skill"))

    def test_blacklist_mode_allows_non_blacklisted_skill(self):
        """BLACKLIST mode allows skills not on the blacklist."""
        svc = _make_service(config={
            "fallback_mode": FallbackMode.BLACKLIST,
            "fallback_blacklist": ["bad_skill"],
        })
        self.assertTrue(svc._fallback_allowed("good_skill"))

    def test_whitelist_mode_blocks_non_whitelisted_skill(self):
        """WHITELIST mode denies skills absent from the whitelist."""
        svc = _make_service(config={
            "fallback_mode": FallbackMode.WHITELIST,
            "fallback_whitelist": ["ok_skill"],
        })
        self.assertFalse(svc._fallback_allowed("other_skill"))

    def test_whitelist_mode_allows_whitelisted_skill(self):
        """WHITELIST mode allows skills present on the whitelist."""
        svc = _make_service(config={
            "fallback_mode": FallbackMode.WHITELIST,
            "fallback_whitelist": ["ok_skill"],
        })
        self.assertTrue(svc._fallback_allowed("ok_skill"))


class TestCollectFallbackSkills(unittest.TestCase):
    """Tests for FallbackService._collect_fallback_skills ping-pong mechanism."""

    def test_no_registered_fallbacks_returns_empty(self):
        """When no fallbacks are registered the result is empty."""
        svc = _make_service()
        sess = Session("s")
        with patch("ovos_core.intent_services.fallback_service.SessionManager.get",
                   return_value=sess):
            result = svc._collect_fallback_skills(Message("test"))
        self.assertEqual(result, [])

    def test_skill_outside_range_skipped(self):
        """Skills with priority outside the fb_range are not pinged."""
        svc = _make_service()
        svc.registered_fallbacks = {"low_prio_skill": 95}  # outside range(0, 5)
        svc.bus.emit = MagicMock()
        svc.bus.on = MagicMock()
        svc.bus.remove = MagicMock()
        sess = Session("s")
        with patch("ovos_core.intent_services.fallback_service.SessionManager.get",
                   return_value=sess):
            result = svc._collect_fallback_skills(
                Message("test"), fb_range=FallbackRange(0, 5))
        # no emit call for pinging since no in-range skills
        self.assertEqual(result, [])

    def test_skill_in_range_receives_ping_and_responds(self):
        """A skill in range that responds can_handle=True is returned."""
        svc = _make_service()
        svc.registered_fallbacks = {"skill_a": 50}

        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == "skill_a.fallback.pong":
                ack_handler = handler

        svc.bus.on = capture_on
        svc.bus.remove = MagicMock()
        svc.bus.emit = MagicMock()

        sess = Session("s")
        result_holder = []

        def run():
            with patch("ovos_core.intent_services.fallback_service.SessionManager.get",
                       return_value=sess):
                result_holder.append(
                    svc._collect_fallback_skills(
                        Message("test", context={
                            "source": "client",
                            "destination": "skills",
                        }), fb_range=FallbackRange(5, 90)))

        t = None
        try:
            t = threading.Thread(target=run)
            t.start()
            time.sleep(0.05)
            if ack_handler:
                ack_handler(Message("skill_a.fallback.pong",
                                    {"skill_id": "skill_a", "can_handle": True}))
        finally:
            if t is not None:
                t.join(timeout=1)
            svc.shutdown()

        self.assertIn("skill_a", result_holder[0])
        ping = svc.bus.emit.call_args[0][0]
        self.assertEqual(ping.msg_type, "skill_a.fallback.ping")
        self.assertEqual(ping.data, {"utterances": [], "lang": None})
        self.assertNotIn("fallback_request_id", ping.context)
        self.assertEqual(ping.context["source"], "client")
        self.assertEqual(ping.context["destination"], "skills")

    def test_skill_responds_can_handle_false_excluded(self):
        """A skill that replies can_handle=False is not included."""
        svc = _make_service()
        svc.registered_fallbacks = {"skill_a": 50}

        ack_handler = None

        def capture_on(event, handler):
            nonlocal ack_handler
            if event == "skill_a.fallback.pong":
                ack_handler = handler

        svc.bus.on = capture_on
        svc.bus.remove = MagicMock()
        svc.bus.emit = MagicMock()

        sess = Session("s")
        result_holder = []

        def run():
            with patch("ovos_core.intent_services.fallback_service.SessionManager.get",
                       return_value=sess):
                result_holder.append(
                    svc._collect_fallback_skills(
                        Message("test"), fb_range=FallbackRange(5, 90)))

        t = None
        try:
            t = threading.Thread(target=run)
            t.start()
            time.sleep(0.05)
            if ack_handler:
                ack_handler(Message("skill_a.fallback.pong",
                                    {"skill_id": "skill_a", "can_handle": False}))
        finally:
            if t is not None:
                t.join(timeout=1)
            svc.shutdown()

        self.assertEqual(result_holder[0], [])

    def test_first_willing_skill_is_selected_in_priority_order(self):
        """Reply arrival does not override registered fallback priority."""
        svc = _make_service()
        svc.registered_fallbacks = {"skill_low": 80, "skill_high": 10}
        handlers = {}

        def capture_on(event, handler):
            handlers[event] = handler

        def emit(message):
            skill_id = message.msg_type.removesuffix(".fallback.ping")
            handlers[f"{skill_id}.fallback.pong"](message.reply(
                f"{skill_id}.fallback.pong",
                {"skill_id": skill_id,
                 "can_handle": skill_id == "skill_low"}))

        svc.bus.on = capture_on
        svc.bus.remove = MagicMock()
        svc.bus.emit = emit
        sess = Session("s")
        message = Message("test", context={"session": sess.serialize()})

        with patch("ovos_core.intent_services.fallback_service.SessionManager.get",
                   return_value=sess):
            result = svc._collect_fallback_skills(
                message, fb_range=FallbackRange(5, 90))

        self.assertEqual(result, ["skill_low"])

    def test_malformed_pong_is_treated_as_declined(self):
        """A non-boolean can_handle value cannot claim an utterance."""
        svc = _make_service()
        svc.registered_fallbacks = {"skill_a": 50}
        handlers = {}

        svc.bus.on = lambda event, handler: handlers.update({event: handler})
        svc.bus.remove = MagicMock()

        def emit(message):
            handlers["skill_a.fallback.pong"](message.reply(
                "skill_a.fallback.pong",
                {"skill_id": "skill_a", "can_handle": "yes"}))

        svc.bus.emit = emit
        sess = Session("s")
        message = Message("test", context={"session": sess.serialize()})

        with patch("ovos_core.intent_services.fallback_service.SessionManager.get",
                   return_value=sess):
            result = svc._collect_fallback_skills(
                message, fb_range=FallbackRange(5, 90))

        self.assertEqual(result, [])

    def test_fallback_registry_snapshot_is_isolated_from_mutation(self):
        """A match keeps a stable registry while skills register or leave."""
        svc = _make_service()
        svc.registered_fallbacks = {"skill_a": 50}

        snapshot = svc._fallback_registry_snapshot()
        svc.handle_register_fallback(Message(
            "ovos.skills.fallback.register",
            {"skill_id": "skill_b", "priority": 40},
        ))
        svc.handle_deregister_fallback(Message(
            "ovos.skills.fallback.deregister", {"skill_id": "skill_a"}))

        self.assertEqual(snapshot, {"skill_a": 50})
        self.assertEqual(svc.registered_fallbacks, {"skill_b": 40})

    def test_concurrent_sessions_do_not_consume_each_others_pongs(self):
        """Same-topic pongs are correlated by their propagated session."""
        svc = _make_service(config={"fallback_query_timeout": 30})
        svc.registered_fallbacks = {"skill_a": 50}
        handlers = []
        results = {}

        def capture_on(event, handler):
            if event == "skill_a.fallback.pong":
                handlers.append(handler)

        svc.bus.on = capture_on
        svc.bus.remove = MagicMock()
        svc.bus.emit = MagicMock()

        def run(session_id):
            session = Session(session_id)
            message = Message(
                "test", context={"session": session.serialize()})
            results[session_id] = svc._collect_fallback_skills(
                message, fb_range=FallbackRange(5, 90))

        threads = [threading.Thread(target=run, args=(session_id,))
                   for session_id in ("a", "b")]
        for thread in threads:
            thread.start()
        for _ in range(100):
            if len(handlers) == 2:
                break
            time.sleep(0.01)
        self.assertEqual(len(handlers), 2)

        pong_a = Message(
            "skill_a.fallback.pong",
            {"skill_id": "skill_a", "can_handle": True},
            {"session": Session("a").serialize()},
        )
        for handler in handlers:
            handler(pong_a)
        for _ in range(100):
            if "a" in results:
                break
            time.sleep(0.01)
        self.assertEqual(results.get("a"), ["skill_a"])
        self.assertNotIn("b", results)

        pong_b = Message(
            "skill_a.fallback.pong",
            {"skill_id": "skill_a", "can_handle": True},
            {"session": Session("b").serialize()},
        )
        for handler in handlers:
            handler(pong_b)
        for thread in threads:
            thread.join(timeout=1)

        self.assertEqual(results.get("b"), ["skill_a"])

    def test_listener_removed_on_timeout(self):
        """bus.remove must be called even when no skill replies (timeout path)."""
        svc = _make_service(config={"fallback_query_timeout": 0})
        svc.registered_fallbacks = {"slow_skill": 50}
        svc.bus.on = MagicMock()
        svc.bus.remove = MagicMock()
        svc.bus.emit = MagicMock()

        sess = Session("s")
        with patch("ovos_core.intent_services.fallback_service.SessionManager.get",
                   return_value=sess):
            svc._collect_fallback_skills(Message("test"), fb_range=FallbackRange(5, 90))

        svc.bus.remove.assert_called_once()
        args = svc.bus.remove.call_args[0]
        self.assertEqual(args[0], "slow_skill.fallback.pong")

    def test_blacklisted_skill_excluded(self):
        """Skills blacklisted by the session are not collected."""
        svc = _make_service()
        svc.registered_fallbacks = {"bad_skill": 50}
        svc.bus.emit = MagicMock()
        svc.bus.on = MagicMock()
        svc.bus.remove = MagicMock()

        sess = Session("s")
        sess.blacklisted_skills = ["bad_skill"]

        with patch("ovos_core.intent_services.fallback_service.SessionManager.get",
                   return_value=sess):
            result = svc._collect_fallback_skills(
                Message("test"), fb_range=FallbackRange(5, 90))

        # bad_skill is out of in_range because it is blacklisted, no ping emitted
        self.assertEqual(result, [])


class TestFallbackRange(unittest.TestCase):
    """Tests for _fallback_range method."""

    def _make_message(self) -> Message:
        return Message("test", data={"utterances": ["hello"]}, context={})

    def test_returns_none_when_no_skills_available(self):
        """Returns None when _collect_fallback_skills returns empty."""
        svc = _make_service()
        sess = Session("s")
        with patch("ovos_core.intent_services.fallback_service.SessionManager.get",
                   return_value=sess), \
             patch.object(svc, "_collect_fallback_skills", return_value=[]):
            result = svc._fallback_range(
                ["hello"], "en-US", self._make_message(), FallbackRange(5, 90))
        self.assertIsNone(result)

    def test_returns_match_for_allowed_skill(self):
        """Returns IntentHandlerMatch when a registered skill is allowed."""
        svc = _make_service()
        svc.registered_fallbacks = {"skill_a": 50}
        sess = Session("s")
        with patch("ovos_core.intent_services.fallback_service.SessionManager.get",
                   return_value=sess), \
             patch.object(svc, "_collect_fallback_skills", return_value=["skill_a"]), \
             patch.object(svc, "_fallback_allowed", return_value=True):
            result = svc._fallback_range(
                ["hello"], "en-US", self._make_message(), FallbackRange(5, 90))
        self.assertIsNotNone(result)
        self.assertIn("skill_a", result.match_type)

    def test_skips_blacklisted_skill_in_session(self):
        """Skills blacklisted by session are skipped even if collected."""
        svc = _make_service()
        svc.registered_fallbacks = {"skill_a": 50}
        sess = Session("s")
        sess.blacklisted_skills = ["skill_a"]
        with patch("ovos_core.intent_services.fallback_service.SessionManager.get",
                   return_value=sess), \
             patch.object(svc, "_collect_fallback_skills", return_value=["skill_a"]):
            result = svc._fallback_range(
                ["hello"], "en-US", self._make_message(), FallbackRange(5, 90))
        self.assertIsNone(result)

    def test_skips_skill_not_allowed_by_config(self):
        """Skills blocked by _fallback_allowed are skipped."""
        svc = _make_service(config={
            "fallback_mode": FallbackMode.WHITELIST,
            "fallback_whitelist": [],
        })
        svc.registered_fallbacks = {"skill_a": 50}
        sess = Session("s")
        with patch("ovos_core.intent_services.fallback_service.SessionManager.get",
                   return_value=sess), \
             patch.object(svc, "_collect_fallback_skills", return_value=["skill_a"]):
            result = svc._fallback_range(
                ["hello"], "en-US", self._make_message(), FallbackRange(5, 90))
        self.assertIsNone(result)

    def test_skills_sorted_by_priority(self):
        """Lower priority value → matched first."""
        svc = _make_service()
        svc.registered_fallbacks = {"skill_high": 10, "skill_low": 80}
        sess = Session("s")
        with patch("ovos_core.intent_services.fallback_service.SessionManager.get",
                   return_value=sess), \
             patch.object(svc, "_collect_fallback_skills",
                          return_value=["skill_high", "skill_low"]), \
             patch.object(svc, "_fallback_allowed", return_value=True):
            result = svc._fallback_range(
                ["hello"], "en-US", self._make_message(), FallbackRange(5, 90))
        self.assertIsNotNone(result)
        self.assertIn("skill_high", result.match_type)


class TestMatchMethods(unittest.TestCase):
    """Tests for match_high, match_medium, match_low delegation."""

    def _make_message(self) -> Message:
        return Message("test", data={"utterances": ["hello"]}, context={})

    def test_match_high_uses_range_0_to_5(self):
        """match_high delegates to _fallback_range with FallbackRange(0, 5)."""
        svc = _make_service()
        with patch.object(svc, "_fallback_range", return_value=None) as mock_range:
            svc.match_high(["hello"], "en-US", self._make_message())
        args = mock_range.call_args[0]
        self.assertEqual(args[3], FallbackRange(0, 5))

    def test_match_medium_uses_range_5_to_90(self):
        """match_medium delegates to _fallback_range with FallbackRange(5, 90)."""
        svc = _make_service()
        with patch.object(svc, "_fallback_range", return_value=None) as mock_range:
            svc.match_medium(["hello"], "en-US", self._make_message())
        args = mock_range.call_args[0]
        self.assertEqual(args[3], FallbackRange(5, 90))

    def test_match_low_uses_range_90_to_101(self):
        """match_low delegates to _fallback_range with FallbackRange(90, 101)."""
        svc = _make_service()
        with patch.object(svc, "_fallback_range", return_value=None) as mock_range:
            svc.match_low(["hello"], "en-US", self._make_message())
        args = mock_range.call_args[0]
        self.assertEqual(args[3], FallbackRange(90, 101))


class TestShutdown(unittest.TestCase):
    """Tests for FallbackService.shutdown."""

    def test_shutdown_removes_listeners(self):
        """shutdown() removes both registered bus listeners."""
        svc = _make_service()
        svc.bus.remove = MagicMock()
        svc.shutdown()
        removed = {c[0][0] for c in svc.bus.remove.call_args_list}
        self.assertIn("ovos.skills.fallback.register", removed)
        self.assertIn("ovos.skills.fallback.deregister", removed)


class TestFallbackHandlerLifecycle(unittest.TestCase):
    """A registered fallback skill's own lifecycle markers are translated into
    the framework done-signal so an orchestrator (OVOS-PIPELINE-1 §8) can
    resolve a reserved ``fallback`` dispatch instead of hitting its timeout."""

    def _service_with_capture(self):
        svc = _make_service()
        captured = []
        # FakeBus emits the "message" catch-all as a serialized string; parse it
        # back into a Message so assertions can read msg_type/context/data.
        svc.bus.on("message", lambda s: captured.append(Message.deserialize(s)))
        return svc, captured

    def test_register_wires_lifecycle_listeners(self):
        """Registering a fallback skill installs its .start/.response bridge."""
        svc, _ = self._service_with_capture()
        svc.handle_register_fallback(
            Message("ovos.skills.fallback.register",
                    {"skill_id": "skill_a", "priority": 50}))
        self.assertIn("skill_a", svc._lifecycle_handlers)

    def test_concurrent_registration_wires_one_listener_pair(self):
        """Concurrent registration cannot leak duplicate lifecycle handlers."""
        svc = _make_service()
        topics = []
        start = threading.Barrier(8)

        def slow_on(topic, handler):
            topics.append(topic)
            time.sleep(0.01)

        svc.bus.on = slow_on

        def wire():
            start.wait()
            svc._wire_lifecycle("skill_a")

        threads = [threading.Thread(target=wire) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=1)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(topics, [
            "ovos.skills.fallback.skill_a.start",
            "ovos.skills.fallback.skill_a.response",
        ])
        self.assertIn("skill_a", svc._lifecycle_handlers)

    def test_skill_start_emits_handler_start(self):
        """The skill's fallback .start is re-emitted as handler.start with the
        skill_id stamped in context."""
        svc, captured = self._service_with_capture()
        svc.handle_register_fallback(
            Message("ovos.skills.fallback.register", {"skill_id": "skill_a"}))
        captured.clear()

        svc.bus.emit(Message("ovos.skills.fallback.skill_a.start"))
        starts = [m for m in captured
                  if m.msg_type == "mycroft.skill.handler.start"]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0].context.get("skill_id"), "skill_a")

    def test_skill_response_emits_handler_complete(self):
        """The skill's fallback .response is re-emitted as handler.complete,
        regardless of the result bool."""
        svc, captured = self._service_with_capture()
        svc.handle_register_fallback(
            Message("ovos.skills.fallback.register", {"skill_id": "skill_a"}))
        captured.clear()

        svc.bus.emit(Message("ovos.skills.fallback.skill_a.response",
                             {"result": False}))
        completes = [m for m in captured
                     if m.msg_type == "mycroft.skill.handler.complete"]
        self.assertEqual(len(completes), 1)
        self.assertEqual(completes[0].context.get("skill_id"), "skill_a")

    def test_deregister_unwires_lifecycle(self):
        """Deregistering removes the bridge; later markers emit nothing."""
        svc, captured = self._service_with_capture()
        svc.handle_register_fallback(
            Message("ovos.skills.fallback.register", {"skill_id": "skill_a"}))
        svc.handle_deregister_fallback(
            Message("ovos.skills.fallback.deregister", {"skill_id": "skill_a"}))
        self.assertNotIn("skill_a", svc._lifecycle_handlers)
        captured.clear()

        svc.bus.emit(Message("ovos.skills.fallback.skill_a.response",
                             {"result": True}))
        topics = [m.msg_type for m in captured]
        self.assertNotIn("mycroft.skill.handler.complete", topics)

    def test_lifecycle_only_for_targeted_skill(self):
        """A response for skill_a must not be reported under skill_b's id."""
        svc, captured = self._service_with_capture()
        svc.handle_register_fallback(
            Message("ovos.skills.fallback.register", {"skill_id": "skill_a"}))
        svc.handle_register_fallback(
            Message("ovos.skills.fallback.register", {"skill_id": "skill_b"}))
        captured.clear()

        svc.bus.emit(Message("ovos.skills.fallback.skill_a.response",
                             {"result": True}))
        completes = [m for m in captured
                     if m.msg_type == "mycroft.skill.handler.complete"]
        self.assertEqual(len(completes), 1)
        self.assertEqual(completes[0].context.get("skill_id"), "skill_a")

    def test_register_without_skill_id_skips_wiring(self):
        """A register message lacking skill_id must not wire a None lifecycle."""
        svc, _ = self._service_with_capture()
        svc.handle_register_fallback(
            Message("ovos.skills.fallback.register", {}))
        self.assertNotIn(None, svc._lifecycle_handlers)


if __name__ == "__main__":
    unittest.main()
