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
"""OVOS-CONTEXT-1 conformance tests for the core-resident subsystem.

Covers the orchestrator MUST clauses this implementation flips:

- §2 the flat entry shape + liveness predicate;
- §4 prune-then-decrement decay across turns;
- §5.3 ``ovos.session.sync`` entry-by-entry merge (set + null-delete);
- §3.1 scope resolution, §6 / §6.1 gating predicates;
- §7 context-supplied slot fill.

Plus a live FakeBus integration check exercising the orchestrator wiring
in ``IntentService``.
"""
import time
import unittest
from collections import defaultdict
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.intent_context import (
    IntentContextStore,
    is_live,
    resolve_key,
    normalize_declaration,
    gate_satisfied,
    context_supplied_slots,
    INTENT_CONTEXT_FIELD,
)
from ovos_core.intent_services.service import IntentService, SESSION_SYNC


def _make_service(config=None) -> IntentService:
    """Construct IntentService without loading real pipelines/plugins."""
    bus = FakeBus()
    svc = IntentService.__new__(IntentService)
    svc.bus = bus
    svc.config = config or {}
    svc.pipeline_plugins = {}
    svc._deactivations = defaultdict(list)
    svc.intent_context = IntentContextStore()

    ut = MagicMock()
    ut.transform.side_effect = lambda utt, ctx: (utt, ctx)
    svc.utterance_plugins = ut
    mt = MagicMock()
    mt.transform.side_effect = lambda ctx: ctx
    svc.metadata_plugins = mt
    it = MagicMock()
    it.transform.side_effect = lambda intent: intent
    svc.intent_plugins = it
    svc.status = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# §2 — entry shape & liveness predicate
# ---------------------------------------------------------------------------

class TestLiveness(unittest.TestCase):
    def test_entry_with_neither_timer_is_live(self):
        self.assertTrue(is_live({"value": "Bob"}))

    def test_turns_zero_is_dead(self):
        # §4: turns_remaining 0 is dead on arrival
        self.assertFalse(is_live({"value": None, "turns_remaining": 0}))

    def test_turns_positive_is_live(self):
        self.assertTrue(is_live({"value": None, "turns_remaining": 1}))

    def test_turns_negative_is_dead(self):
        self.assertFalse(is_live({"value": None, "turns_remaining": -1}))

    def test_null_turns_is_live(self):
        self.assertTrue(is_live({"value": "x", "turns_remaining": None}))

    def test_expired_wallclock_is_dead(self):
        self.assertFalse(is_live({"value": "x", "expires_at": time.time() - 1}))

    def test_future_wallclock_is_live(self):
        self.assertTrue(is_live({"value": "x", "expires_at": time.time() + 60}))

    def test_both_must_hold(self):
        # live turns but expired wallclock -> dead
        self.assertFalse(is_live({"value": "x", "turns_remaining": 5,
                                  "expires_at": time.time() - 1}))


# ---------------------------------------------------------------------------
# §3 / §3.1 — scope resolution
# ---------------------------------------------------------------------------

class TestScopeResolution(unittest.TestCase):
    def test_private_resolves_to_prefixed_key(self):
        self.assertEqual(resolve_key("confirming_milk", "private", "tea.skill"),
                         "tea.skill:confirming_milk")

    def test_shared_resolves_to_bare_key(self):
        self.assertEqual(resolve_key("person", "shared", "bio.skill"), "person")

    def test_private_without_owner_is_none(self):
        self.assertIsNone(resolve_key("k", "private", None))

    def test_bare_string_defaults_to_private(self):
        self.assertEqual(normalize_declaration("person"),
                         {"key": "person", "scope": "private"})

    def test_long_form_shared(self):
        self.assertEqual(
            normalize_declaration({"key": "active_room", "scope": "shared"}),
            {"key": "active_room", "scope": "shared"})


# ---------------------------------------------------------------------------
# §6 / §6.1 — gating predicates
# ---------------------------------------------------------------------------

class TestGating(unittest.TestCase):
    def test_private_gate_satisfied(self):
        ctx = {"tea.skill:confirming_milk": {"value": None, "turns_remaining": 1}}
        self.assertTrue(gate_satisfied(ctx, ["confirming_milk"], None, "tea.skill"))

    def test_private_gate_not_satisfied_by_shared(self):
        # §3.1: a shared entry of the same name does not satisfy a private gate
        ctx = {"confirming_milk": {"value": None, "turns_remaining": 1}}
        self.assertFalse(gate_satisfied(ctx, ["confirming_milk"], None, "tea.skill"))

    def test_shared_gate_satisfied(self):
        ctx = {"person": {"value": "Bob", "turns_remaining": 3}}
        self.assertTrue(gate_satisfied(
            ctx, [{"key": "person", "scope": "shared"}], None, "bio.skill"))

    def test_shared_gate_not_satisfied_by_other_skills_private(self):
        # §3.2 step 3: people.skill's private entry invisible to bio.skill
        ctx = {"people.skill:person": {"value": "Bob", "turns_remaining": 3}}
        self.assertFalse(gate_satisfied(
            ctx, [{"key": "person", "scope": "shared"}], None, "bio.skill"))

    def test_dead_entry_does_not_satisfy(self):
        ctx = {"tea.skill:flag": {"value": None, "turns_remaining": 0}}
        self.assertFalse(gate_satisfied(ctx, ["flag"], None, "tea.skill"))

    def test_excludes_blocks_when_live(self):
        ctx = {"greet.skill:said_hello": {"value": None}}
        self.assertFalse(gate_satisfied(ctx, None, ["said_hello"], "greet.skill"))

    def test_excludes_permits_when_absent(self):
        self.assertTrue(gate_satisfied({}, None, ["said_hello"], "greet.skill"))

    def test_both_lists_apply(self):
        ctx = {"s.skill:need": {"value": None}}
        self.assertTrue(gate_satisfied(ctx, ["need"], ["forbid"], "s.skill"))
        ctx["s.skill:forbid"] = {"value": None}
        self.assertFalse(gate_satisfied(ctx, ["need"], ["forbid"], "s.skill"))


# ---------------------------------------------------------------------------
# §7 — context-supplied slot fill
# ---------------------------------------------------------------------------

class TestSlotFill(unittest.TestCase):
    def test_shared_value_fills_unfilled_slot(self):
        ctx = {"person": {"value": "Bob", "turns_remaining": 3}}
        supplied = context_supplied_slots(
            ctx, [{"key": "person", "scope": "shared"}],
            slot_names=["person"], owner_id="bio.skill", filled_slots={})
        self.assertEqual(supplied, {"person": "Bob"})

    def test_utterance_value_wins(self):
        ctx = {"person": {"value": "Bob"}}
        supplied = context_supplied_slots(
            ctx, [{"key": "person", "scope": "shared"}],
            slot_names=["person"], owner_id="bio.skill",
            filled_slots={"person": "Alice"})
        self.assertEqual(supplied, {})

    def test_flag_context_supplies_nothing(self):
        ctx = {"bio.skill:person": {"value": None}}
        supplied = context_supplied_slots(
            ctx, ["person"], slot_names=["person"],
            owner_id="bio.skill", filled_slots={})
        self.assertEqual(supplied, {})

    def test_gated_only_key_not_a_slot(self):
        ctx = {"bio.skill:mode": {"value": "x"}}
        supplied = context_supplied_slots(
            ctx, ["mode"], slot_names=["person"],
            owner_id="bio.skill", filled_slots={})
        self.assertEqual(supplied, {})


# ---------------------------------------------------------------------------
# §4 — decay lifecycle on the store
# ---------------------------------------------------------------------------

class TestDecay(unittest.TestCase):
    def test_prune_removes_dead(self):
        store = IntentContextStore()
        store.set("s", {"live": {"value": "a", "turns_remaining": 1},
                        "dead": {"value": "b", "turns_remaining": 0}})
        store.prune("s")
        self.assertIn("live", store.get("s"))
        self.assertNotIn("dead", store.get("s"))

    def test_decrement_counts_down(self):
        store = IntentContextStore()
        store.set("s", {"k": {"value": None, "turns_remaining": 2}})
        store.decrement("s")
        self.assertEqual(store.get("s")["k"]["turns_remaining"], 1)

    def test_turns_one_lives_exactly_next_round(self):
        # §4: turns_remaining 1 is live for the next match round, gone after
        store = IntentContextStore()
        store.set("s", {"k": {"value": None, "turns_remaining": 1}})
        # round 1: prune keeps it (live), then decrement -> 0
        store.prune("s")
        self.assertIn("k", store.get("s"))
        store.decrement("s")
        # round 2: prune removes it (turns 0 is dead)
        store.prune("s")
        self.assertNotIn("k", store.get("s"))

    def test_decrement_decrements_unmatched_turn(self):
        # §4: decrement runs whether or not an intent matched
        store = IntentContextStore()
        store.set("s", {"k": {"value": None, "turns_remaining": 1}})
        store.decrement("s")
        self.assertEqual(store.get("s")["k"]["turns_remaining"], 0)

    def test_decrement_only_keys_skips_midispatch(self):
        # §4.1: an entry synced mid-dispatch is not decremented this turn
        store = IntentContextStore()
        store.set("s", {"old": {"value": None, "turns_remaining": 1}})
        pre = set(store.get("s").keys())
        # mid-dispatch sync writes a fresh entry
        store.merge_sync("s", {"new": {"value": None, "turns_remaining": 1}})
        store.decrement("s", only_keys=pre)
        self.assertEqual(store.get("s")["old"]["turns_remaining"], 0)
        self.assertEqual(store.get("s")["new"]["turns_remaining"], 1)


# ---------------------------------------------------------------------------
# §5.3 — ovos.session.sync entry-by-entry merge
# ---------------------------------------------------------------------------

class TestSyncMerge(unittest.TestCase):
    def test_set_and_replace(self):
        store = IntentContextStore()
        store.merge_sync("s", {"k": {"value": "a"}})
        self.assertEqual(store.get("s")["k"]["value"], "a")
        store.merge_sync("s", {"k": {"value": "b"}})
        self.assertEqual(store.get("s")["k"]["value"], "b")

    def test_null_deletes(self):
        store = IntentContextStore()
        store.merge_sync("s", {"k": {"value": "a"}, "j": {"value": "b"}})
        store.merge_sync("s", {"k": None})
        self.assertNotIn("k", store.get("s"))
        self.assertIn("j", store.get("s"))  # disjoint key untouched

    def test_disjoint_keys_do_not_overwrite(self):
        store = IntentContextStore()
        store.merge_sync("s", {"a.skill:x": {"value": "1"}})
        store.merge_sync("s", {"b.skill:y": {"value": "2"}})
        self.assertEqual(set(store.get("s").keys()),
                         {"a.skill:x", "b.skill:y"})

    def test_cap_eviction(self):
        store = IntentContextStore(max_entries=2)
        store.merge_sync("s", {"near": {"value": "x", "turns_remaining": 1},
                               "far": {"value": "y", "turns_remaining": 99},
                               "perm": {"value": "z"}})
        ctx = store.get("s")
        self.assertEqual(len(ctx), 2)
        # the entry closest to expiry (smallest turns_remaining) is evicted
        self.assertNotIn("near", ctx)


# ---------------------------------------------------------------------------
# live FakeBus integration through IntentService
# ---------------------------------------------------------------------------

class TestSessionSyncHandler(unittest.TestCase):
    def test_sync_handler_merges_set_and_delete(self):
        svc = _make_service()
        sess = Session("live-sess")
        # seed an existing entry directly
        svc.intent_context.set(sess.session_id, {"keep": {"value": "k"}})

        payload = {INTENT_CONTEXT_FIELD: {
            "tea.skill:confirming_milk": {"value": None, "turns_remaining": 1},
            "keep": None,  # delete
        }}
        msg = Message(SESSION_SYNC, data={"session": payload},
                      context={"session": sess.serialize()})
        with patch("ovos_core.intent_services.service.SessionManager.get",
                   return_value=sess):
            svc.handle_session_sync(msg)

        ctx = svc.intent_context.get(sess.session_id)
        self.assertIn("tea.skill:confirming_milk", ctx)
        self.assertNotIn("keep", ctx)

    def test_decay_over_turns_via_handle_utterance(self):
        svc = _make_service()
        sess = Session("turn-sess")
        svc.intent_context.set(sess.session_id,
                               {"tea.skill:flag": {"value": None,
                                                   "turns_remaining": 1}})

        def _drive():
            msg = Message("recognizer_loop:utterance",
                          data={"utterances": ["hello"]},
                          context={"session": sess.serialize()})
            with patch.object(svc, "get_pipeline", return_value=[]), \
                 patch("ovos_core.intent_services.service.SessionManager.get",
                       return_value=sess), \
                 patch.object(svc, "_validate_session", return_value=sess), \
                 patch("ovos_core.intent_services.service.SessionManager.sync"):
                svc.handle_utterance(msg)

        # turn 1: flag is live during the round, decremented to 0 after
        _drive()
        self.assertEqual(
            svc.intent_context.get(sess.session_id)["tea.skill:flag"]["turns_remaining"],
            0)
        # turn 2: pre-match prune removes the now-dead flag
        _drive()
        self.assertNotIn("tea.skill:flag",
                         svc.intent_context.get(sess.session_id))


if __name__ == "__main__":
    unittest.main()
