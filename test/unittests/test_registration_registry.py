"""Unit tests for the orchestrator-owned registration registry.

OVOS-INTENT-4 §10: registration broadcasts are load-time announcements with
no catch-up channel, and the orchestrator indexes every registration it
observes. The registry is that passive index extended to the engine-level
registration topics: it records the raw broadcasts and can rebuild the
compiled state of freshly (re)loaded pipeline plugins by re-delivering them
to in-process listeners — no message ever goes (back) on the wire.
"""
import unittest

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.registry import RegistrationRegistry

SKILL = "test-skill.test"
OTHER = "other-skill.test"


def _ctx(skill_id=SKILL):
    return {"skill_id": skill_id}


class TestRegistrationRegistry(unittest.TestCase):

    def setUp(self):
        self.bus = FakeBus()
        self.registry = RegistrationRegistry(self.bus)

    def _register_default_set(self):
        self.bus.emit(Message("register_vocab",
                              {"entity_value": "hello",
                               "entity_type": "test_skillHelloKeyword",
                               "lang": "en-US"}, _ctx()))
        self.bus.emit(Message("register_vocab",
                              {"regex": "(?P<Thing>.*)", "lang": "en-US"},
                              _ctx()))
        self.bus.emit(Message("register_intent",
                              {"name": f"{SKILL}:hello.intent",
                               "requires": [["test_skillHelloKeyword",
                                             "test_skillHelloKeyword"]],
                               "at_least_one": [], "optional": [],
                               "excludes": [], "lang": "en-US"}, _ctx()))
        self.bus.emit(Message("padatious:register_intent",
                              {"name": f"{SKILL}:file.intent",
                               "samples": ["hello world"],
                               "lang": "en-US"}, _ctx()))
        self.bus.emit(Message("padatious:register_entity",
                              {"name": f"{SKILL}:thing.entity",
                               "samples": ["thing"], "lang": "en-US"},
                              _ctx()))
        self.bus.emit(Message("ovos.skills.fallback.register",
                              {"skill_id": SKILL, "priority": 80}, _ctx()))

    def _replayed(self):
        replayed = []
        self.registry.replay(replayed.append)
        return replayed

    def test_replays_recorded_registrations(self):
        self._register_default_set()
        replayed = self._replayed()
        types = [m.msg_type for m in replayed]
        self.assertEqual(types.count("register_vocab"), 2)
        self.assertEqual(types.count("register_intent"), 1)
        self.assertEqual(types.count("padatious:register_intent"), 1)
        self.assertEqual(types.count("padatious:register_entity"), 1)
        self.assertEqual(types.count("ovos.skills.fallback.register"), 1)

    def test_replay_detaches_skill_before_reregistering(self):
        # matchers that survived (e.g. after a websocket reconnect) must not
        # end up with duplicate compiled entries: the replay leads with a
        # detach so the rebuild is idempotent
        self._register_default_set()
        types = [m.msg_type for m in self._replayed()]
        self.assertEqual(types[0], "detach_skill")
        self.assertLess(types.index("detach_skill"),
                        types.index("register_vocab"))

    def test_replay_orders_vocab_before_intents(self):
        self._register_default_set()
        types = [m.msg_type for m in self._replayed()]
        self.assertLess(types.index("register_vocab"),
                        types.index("register_intent"))

    def test_reregistration_replaces(self):
        # OVOS-INTENT-4 §8.1 — same intent registered again replaces the
        # previous record instead of accumulating
        self._register_default_set()
        self.bus.emit(Message("register_intent",
                              {"name": f"{SKILL}:hello.intent",
                               "requires": [], "at_least_one": [],
                               "optional": [], "excludes": [],
                               "lang": "en-US"}, _ctx()))
        replayed = [m for m in self._replayed()
                    if m.msg_type == "register_intent"]
        self.assertEqual(len(replayed), 1)
        self.assertEqual(replayed[0].data["requires"], [])

    def test_duplicate_vocab_not_accumulated(self):
        self._register_default_set()
        self.bus.emit(Message("register_vocab",
                              {"entity_value": "hello",
                               "entity_type": "test_skillHelloKeyword",
                               "lang": "en-US"}, _ctx()))
        replayed = [m for m in self._replayed()
                    if m.msg_type == "register_vocab"]
        self.assertEqual(len(replayed), 2)

    def test_detach_intent_removes_record(self):
        self._register_default_set()
        self.bus.emit(Message("detach_intent",
                              {"intent_name": f"{SKILL}:hello.intent"},
                              _ctx()))
        types = [m.msg_type for m in self._replayed()]
        self.assertNotIn("register_intent", types)
        self.assertIn("padatious:register_intent", types)

    def test_detach_skill_removes_all_records(self):
        self._register_default_set()
        self.bus.emit(Message("register_vocab",
                              {"entity_value": "bye",
                               "entity_type": "other_skillByeKeyword",
                               "lang": "en-US"}, _ctx(OTHER)))
        self.bus.emit(Message("detach_skill", {"skill_id": SKILL}, _ctx()))
        replayed = self._replayed()
        skills = {m.context.get("skill_id") or m.data.get("skill_id")
                  for m in replayed}
        self.assertNotIn(SKILL, skills)
        self.assertIn(OTHER, skills)

    def test_fallback_deregister_removes_record(self):
        self._register_default_set()
        self.bus.emit(Message("ovos.skills.fallback.deregister",
                              {"skill_id": SKILL}, _ctx()))
        types = [m.msg_type for m in self._replayed()]
        self.assertNotIn("ovos.skills.fallback.register", types)

    def test_records_intent4_spec_registrations(self):
        self.bus.emit(Message("ovos.intent.register.template",
                              {"skill_id": SKILL, "intent_name": "hello",
                               "lang": "en-US",
                               "definition": {"samples": ["hello world"]}},
                              _ctx()))
        types = [m.msg_type for m in self._replayed()]
        self.assertIn("ovos.intent.register.template", types)

    def test_shutdown_detaches_listeners(self):
        self.registry.shutdown()
        self._register_default_set()
        self.assertEqual([m for m in self._replayed()
                          if m.msg_type != "detach_skill"], [])


if __name__ == "__main__":
    unittest.main()
