"""OVOS-FALLBACK-1 §3.4 — the fallback registry is session-scoped.

§3.4: "Registration is session-scoped per OVOS-INTENT-4 §11.1: the plugin keys
each entry by `context.session.session_id` of the registration Message. Skills
registered under "default" are available to all sessions, because every session
inherits the "default" scope (OVOS-INTENT-4 §11.2). Skills registered under a
specific `session_id` extend the pool for that session only."

§10 makes it a MUST: "key registration and deregistration by
`context.session.session_id`, never by a `session_id` in `Message.data`".

A registry keyed by skill_id alone offers one session's handler to every other
session, which is a handler leak across sessions rather than a tidiness point.
"""
import unittest

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus


def _service():
    from ovos_core.intent_services.fallback_service import FallbackService
    return FallbackService(FakeBus())


def _register(service, skill_id, session_id, priority=50):
    service.handle_register_fallback(Message(
        "ovos.skills.fallback.register",
        {"skill_id": skill_id, "priority": priority},
        {"session": {"session_id": session_id}}))


class TestFallbackSessionScope(unittest.TestCase):

    def test_each_session_sees_only_its_own(self):
        service = _service()
        _register(service, "alice.skill", "session-a")
        _register(service, "bob.skill", "session-b")
        a = service._fallback_registry_snapshot("session-a")
        b = service._fallback_registry_snapshot("session-b")
        self.assertIn("alice.skill", a)
        self.assertNotIn("bob.skill", a, "session-b's handler leaked into session-a")
        self.assertIn("bob.skill", b)
        self.assertNotIn("alice.skill", b, "session-a's handler leaked into session-b")

    def test_default_is_inherited_by_every_session(self):
        service = _service()
        _register(service, "shared.skill", "default")
        _register(service, "alice.skill", "session-a")
        a = service._fallback_registry_snapshot("session-a")
        self.assertIn("shared.skill", a, "every session inherits the default scope")
        self.assertIn("alice.skill", a)
        self.assertNotIn("alice.skill",
                         service._fallback_registry_snapshot("default"))

    def test_a_session_registration_does_not_reach_default(self):
        service = _service()
        _register(service, "alice.skill", "session-a")
        self.assertNotIn("alice.skill",
                         service._fallback_registry_snapshot("default"))

    def test_deregistration_is_scoped_too(self):
        service = _service()
        _register(service, "shared.skill", "default")
        _register(service, "shared.skill", "session-a", priority=10)
        service.handle_deregister_fallback(Message(
            "ovos.skills.fallback.deregister", {"skill_id": "shared.skill"},
            {"session": {"session_id": "session-a"}}))
        self.assertIn("shared.skill",
                      service._fallback_registry_snapshot("default"),
                      "deregistering in one session removed the default entry")

    def test_a_session_id_in_data_is_not_the_key(self):
        """§10: never by a `session_id` in `Message.data`."""
        service = _service()
        service.handle_register_fallback(Message(
            "ovos.skills.fallback.register",
            {"skill_id": "sneaky.skill", "priority": 50,
             "session_id": "session-b"},
            {"session": {"session_id": "session-a"}}))
        self.assertIn("sneaky.skill",
                      service._fallback_registry_snapshot("session-a"))
        self.assertNotIn("sneaky.skill",
                         service._fallback_registry_snapshot("session-b"))
