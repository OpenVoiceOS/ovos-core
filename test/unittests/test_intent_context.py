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
"""OVOS-CONTEXT-1 conformance tests for the core-resident helpers.

The §5.3 ``ovos.session.sync`` entry-by-entry merge is owned by the
``SessionManager`` singleton and is covered there; core does **not**
re-implement it. This module covers the stateless helpers the
orchestrator applies to a session's ``intent_context`` map:

- §2 the flat entry shape + liveness predicate + cap eviction;
- §4 / §4.1 prune-then-decrement decay across turns;
- §3.1 scope resolution, §6 / §6.1 gating predicates;
- §7 context-supplied slot fill.

Plus a live FakeBus integration check that drives ``ovos.session.sync``
through the **real** ``SessionManager`` and asserts the orchestrator sees
the merged-then-decayed context on the session.
"""
import time
import unittest
from collections import defaultdict
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.intent_context import (
    is_live,
    resolve_key,
    normalize_declaration,
    gate_satisfied,
    context_supplied_slots,
    prune,
    decrement,
    enforce_cap,
    INTENT_CONTEXT_FIELD,
)
from ovos_core.intent_services.service import IntentService


def _make_service(config=None) -> IntentService:
    """Construct IntentService without loading real pipelines/plugins."""
    bus = FakeBus()
    svc = IntentService.__new__(IntentService)
    svc.bus = bus
    svc.config = config or {}
    svc.pipeline_plugins = {}
    svc._deactivations = defaultdict(list)

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
# §4 — decay lifecycle (stateless helpers over a passed-in map)
# ---------------------------------------------------------------------------

class TestDecay(unittest.TestCase):
    def test_prune_removes_dead(self):
        ctx = {"live": {"value": "a", "turns_remaining": 1},
               "dead": {"value": "b", "turns_remaining": 0}}
        prune(ctx)
        self.assertIn("live", ctx)
        self.assertNotIn("dead", ctx)

    def test_prune_is_in_place_and_returns_map(self):
        ctx = {"dead": {"value": "b", "turns_remaining": 0}}
        out = prune(ctx)
        self.assertIs(out, ctx)
        self.assertEqual(ctx, {})

    def test_decrement_counts_down(self):
        ctx = {"k": {"value": None, "turns_remaining": 2}}
        decrement(ctx)
        self.assertEqual(ctx["k"]["turns_remaining"], 1)

    def test_turns_one_lives_exactly_next_round(self):
        # §4: turns_remaining 1 is live for the next match round, gone after
        ctx = {"k": {"value": None, "turns_remaining": 1}}
        # round 1: prune keeps it (live), then decrement -> 0
        prune(ctx)
        self.assertIn("k", ctx)
        decrement(ctx)
        # round 2: prune removes it (turns 0 is dead)
        prune(ctx)
        self.assertNotIn("k", ctx)

    def test_decrement_decrements_unmatched_turn(self):
        # §4: decrement runs whether or not an intent matched
        ctx = {"k": {"value": None, "turns_remaining": 1}}
        decrement(ctx)
        self.assertEqual(ctx["k"]["turns_remaining"], 0)

    def test_decrement_only_keys_skips_midispatch(self):
        # §4.1: an entry synced mid-dispatch is not decremented this turn
        ctx = {"old": {"value": None, "turns_remaining": 1}}
        pre = set(ctx.keys())
        # mid-dispatch sync writes a fresh entry
        ctx["new"] = {"value": None, "turns_remaining": 1}
        decrement(ctx, only_keys=pre)
        self.assertEqual(ctx["old"]["turns_remaining"], 0)
        self.assertEqual(ctx["new"]["turns_remaining"], 1)

    def test_decrement_leaves_untimed_entries(self):
        ctx = {"perm": {"value": "x"}}
        decrement(ctx)
        self.assertNotIn("turns_remaining", ctx["perm"])


# ---------------------------------------------------------------------------
# §2 — live-entry cap eviction
# ---------------------------------------------------------------------------

class TestCapEviction(unittest.TestCase):
    def test_cap_evicts_entry_closest_to_expiry(self):
        ctx = {"near": {"value": "x", "turns_remaining": 1},
               "far": {"value": "y", "turns_remaining": 99},
               "perm": {"value": "z"}}
        enforce_cap(ctx, max_entries=2)
        self.assertEqual(len(ctx), 2)
        # the entry closest to expiry (smallest turns_remaining) is evicted
        self.assertNotIn("near", ctx)

    def test_cap_noop_under_limit(self):
        ctx = {"a": {"value": "1"}, "b": {"value": "2"}}
        enforce_cap(ctx, max_entries=10)
        self.assertEqual(set(ctx.keys()), {"a", "b"})


# ---------------------------------------------------------------------------
# live FakeBus integration through the REAL SessionManager
# ---------------------------------------------------------------------------

class TestLiveSessionManagerSync(unittest.TestCase):
    """Drive ``ovos.session.sync`` through the real SessionManager (which
    owns the §5.3 merge, bus-client #239) and assert the orchestrator sees
    the merged-then-decayed context on the session."""

    def setUp(self):
        # isolate the singleton between tests
        SessionManager.sessions = {"default": Session("default")}
        SessionManager.default_session = SessionManager.sessions["default"]
        SessionManager.bus = None

    def tearDown(self):
        SessionManager.sessions = {"default": Session("default")}
        SessionManager.default_session = SessionManager.sessions["default"]
        SessionManager.bus = None

    def test_real_sessionmanager_merges_sync(self):
        # the merge itself lives in SessionManager (bus-client #239); here
        # we drive the *real* handler to confirm core consumes a managed
        # session whose intent_context the singleton has merged. The full
        # set + null-delete matrix is covered by bus-client's own suite —
        # we assert the additive set + delete is visible on the session.
        sess = Session("live-sess")
        sess.intent_context = {"keep": {"value": "k"}}
        SessionManager.update(sess)

        # a skill emits ovos.session.sync with an updated session snapshot
        snap = sess.serialize()
        snap[INTENT_CONTEXT_FIELD] = {
            "tea.skill:confirming_milk": {"value": None, "turns_remaining": 1},
            "keep": None,  # delete
        }
        SessionManager.handle_session_sync(
            Message("ovos.session.sync", context={"session": snap}))

        merged = SessionManager.sessions["live-sess"].intent_context
        self.assertIn("tea.skill:confirming_milk", merged)
        self.assertNotIn("keep", merged)

    def test_orchestrator_decays_managed_session(self):
        bus = FakeBus()
        SessionManager.connect_to_bus(bus)
        svc = _make_service()
        svc.bus = bus

        sess = Session("turn-sess")
        sess.intent_context = {"tea.skill:flag": {"value": None,
                                                  "turns_remaining": 1}}
        SessionManager.update(sess)

        def _drive():
            msg = Message("recognizer_loop:utterance",
                          data={"utterances": ["hello"]},
                          context={"session":
                                   SessionManager.sessions["turn-sess"].serialize()})
            # no pipelines loaded -> no match, decay still runs
            svc.handle_utterance(msg)

        # turn 1: flag is live during the round, decremented to 0 after
        _drive()
        self.assertEqual(
            SessionManager.sessions["turn-sess"].intent_context["tea.skill:flag"]["turns_remaining"],
            0)
        # turn 2: pre-match prune removes the now-dead flag
        _drive()
        self.assertNotIn(
            "tea.skill:flag",
            SessionManager.sessions["turn-sess"].intent_context or {})

    def test_midispatch_sync_survives_decay(self):
        # §4.1: an entry merged onto the managed session mid-dispatch (via
        # the real SessionManager handler) is NOT decremented by the
        # dispatch it arrived in — it lands alive for exactly the next match
        # round. Exercises core's post-match decrement (only_keys) against a
        # session the real singleton has merged into.
        sess = Session("mid-sess")
        sess.intent_context = {"old.skill:flag": {"value": None,
                                                  "turns_remaining": 1}}
        SessionManager.update(sess)

        # pre-match snapshot, as core captures it before the match round
        pre_match_keys = set(sess.intent_context.keys())

        # mid-dispatch: a skill emits ovos.session.sync; the REAL handler
        # merges the disjoint new key onto the managed session.
        snap = sess.serialize()
        snap[INTENT_CONTEXT_FIELD] = {
            "new.skill:flag": {"value": None, "turns_remaining": 1}}
        SessionManager.handle_session_sync(
            Message("ovos.session.sync", context={"session": snap}))

        # core's post-match decrement: re-read authoritative session, skip
        # mid-dispatch keys (only_keys) so they are not decremented.
        managed = SessionManager.sessions["mid-sess"]
        post_ctx = dict(managed.intent_context or {})
        decrement(post_ctx, only_keys=pre_match_keys)
        managed.intent_context = post_ctx or None
        SessionManager.update(managed)

        ctx = SessionManager.sessions["mid-sess"].intent_context
        # the pre-existing entry was decremented (present at match time)
        self.assertEqual(ctx["old.skill:flag"]["turns_remaining"], 0)
        # the mid-dispatch entry was NOT decremented (arrived after prune)
        self.assertEqual(ctx["new.skill:flag"]["turns_remaining"], 1)

    def test_midispatch_sync_refresh_of_existing_key_not_decremented(self):
        # §4.1: a mid-dispatch ``ovos.session.sync`` MAY refresh an
        # *existing* key (not just add a disjoint one) --
        # ``merge_intent_context`` replaces the entry content in place. A
        # bare pre-match key snapshot cannot tell a refreshed entry apart
        # from an untouched one (the key was present both times), so the
        # orchestrator must compare entry *value*, not just key presence,
        # or it wrongly decrements the freshly-synced entry the same turn.
        bus = FakeBus()
        SessionManager.connect_to_bus(bus)
        svc = _make_service()
        svc.bus = bus

        sess = Session("refresh-sess")
        sess.intent_context = {"tea.skill:flag": {"value": "a",
                                                  "turns_remaining": 1}}
        SessionManager.update(sess)

        def _mid_dispatch_refresh(utterances, lang, message):
            # a skill refreshes the SAME key mid-dispatch via a real sync
            snap = SessionManager.sessions["refresh-sess"].serialize()
            snap[INTENT_CONTEXT_FIELD] = {
                "tea.skill:flag": {"value": "b", "turns_remaining": 5}}
            SessionManager.handle_session_sync(
                Message("ovos.session.sync", context={"session": snap}))
            return None  # no match, decay still runs to completion

        svc.get_pipeline = lambda session: [("fake", _mid_dispatch_refresh)]

        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["hello"]},
                      context={"session":
                               SessionManager.sessions["refresh-sess"].serialize()})
        svc.handle_utterance(msg)

        ctx = SessionManager.sessions["refresh-sess"].intent_context
        # refreshed mid-dispatch -> lands alive for exactly the next round,
        # NOT decremented by the very dispatch that refreshed it
        self.assertEqual(ctx["tea.skill:flag"]["turns_remaining"], 5)
        self.assertEqual(ctx["tea.skill:flag"]["value"], "b")


# ---------------------------------------------------------------------------
# §6/§6.1 — orchestrator gate backstop in the match loop
# ---------------------------------------------------------------------------

from unittest.mock import patch  # noqa: E402
from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch  # noqa: E402
from ovos_core.intent_services.manifest import IntentManifest  # noqa: E402
from ovos_core.intent_services.dispatcher import IntentDispatcher  # noqa: E402


class TestOrchestratorGate(unittest.TestCase):
    """handle_utterance drops a context-gated match whose gate — declared in
    the passive §10 manifest, not on the Match — is unsatisfied, and dispatches
    it once the required context is live."""

    def _gated_service(self, match, requires=("kitchen",)):
        svc = _make_service()
        svc._handle_transformers = lambda m: m
        svc.disambiguate_lang = lambda m: "en-US"
        svc.send_complete_intent_failure = MagicMock()
        svc._dispatch_match = MagicMock()
        svc.get_pipeline = lambda session: [("fake-high", lambda utts, lang, msg: match)]
        # declare the intent's requires_context in the passive manifest
        svc.intent_manifest = IntentManifest(svc.bus)
        if requires:
            svc.intent_manifest._on_register(Message(
                "ovos.intent.register.keyword",
                {"skill_id": "lights.skill", "intent_name": "on",
                 "lang": "en-US", "requires_context": list(requires)}, {}))
        return svc

    def _session(self, intent_context=None):
        sess = Session("s1")
        sess.lang = "en-US"
        sess.pipeline = ["fake-high"]
        sess.intent_context = intent_context
        SessionManager.update(sess)
        return sess

    def _match(self):
        return IntentHandlerMatch(match_type="lights:on",
                                  match_data={"conf": 1.0},
                                  skill_id="lights.skill",
                                  utterance="turn on")

    def _utterance(self, sess):
        return Message("ovos.utterance.handle",
                       {"utterances": ["turn on"], "lang": "en-US"},
                       {"session": sess.serialize()})

    def test_gate_unsatisfied_drops_match(self):
        match = self._match()
        svc = self._gated_service(match)
        sess = self._session(intent_context=None)  # no 'kitchen' context
        with patch.object(svc, "_validate_session", return_value=sess):
            svc.handle_utterance(self._utterance(sess))
        svc._dispatch_match.assert_not_called()
        svc.send_complete_intent_failure.assert_called_once()

    def test_gate_satisfied_dispatches(self):
        match = self._match()
        svc = self._gated_service(match)
        # private 'kitchen' under the declaring skill_id, live
        ctx = {"lights.skill:kitchen": {"value": "kitchen", "turns_remaining": 2}}
        sess = self._session(intent_context=ctx)
        with patch.object(svc, "_validate_session", return_value=sess):
            svc.handle_utterance(self._utterance(sess))
        svc._dispatch_match.assert_called_once()
        svc.send_complete_intent_failure.assert_not_called()

    def test_ungated_match_unaffected(self):
        match = IntentHandlerMatch(match_type="lights:on", match_data={"conf": 1.0},
                                   skill_id="lights.skill", utterance="turn on")
        svc = self._gated_service(match, requires=None)  # nothing declared
        sess = self._session(intent_context=None)
        with patch.object(svc, "_validate_session", return_value=sess):
            svc.handle_utterance(self._utterance(sess))
        svc._dispatch_match.assert_called_once()


class TestOrchestratorSlotFill(unittest.TestCase):
    """The orchestrator's §7 slot-fill pass reads ``requires_context`` and the
    slot names from the passive §10 manifest (never off the Match) and populates
    an unfilled slot on the dispatch from the live context entry."""

    def _service(self, requires, slot_names):
        svc = _make_service()
        svc.intent_manifest = IntentManifest(svc.bus)
        svc.intent_manifest._on_register(Message(
            "ovos.intent.register.keyword",
            {"skill_id": "lights.skill", "intent_name": "on", "lang": "en-US",
             "requires_context": list(requires), "required": list(slot_names)}, {}))
        return svc

    def _session(self, intent_context):
        sess = Session("s1")
        sess.lang = "en-US"
        sess.intent_context = intent_context
        return sess

    def _match(self):
        return IntentHandlerMatch(match_type="lights:on", match_data={"conf": 1.0},
                                  skill_id="lights.skill", utterance="turn on")

    def test_context_fills_unfilled_slot(self):
        svc = self._service(requires=["room"], slot_names=["room"])
        sess = self._session(
            {"lights.skill:room": {"value": "kitchen", "turns_remaining": 2}})
        reply = Message("lights:on", {})
        svc._apply_context_slots(self._match(), sess, reply)
        self.assertEqual(reply.data.get("room"), "kitchen")

    def test_utterance_value_wins(self):
        # the slot was filled by the pipeline itself (present on
        # ``match.match_data``, mirrored onto ``reply.data`` by
        # ``_dispatch_match`` as real flows do) -- that value must win
        # over the live context entry.
        svc = self._service(requires=["room"], slot_names=["room"])
        sess = self._session(
            {"lights.skill:room": {"value": "kitchen", "turns_remaining": 2}})
        match = IntentHandlerMatch(match_type="lights:on",
                                   match_data={"room": "bedroom"},
                                   skill_id="lights.skill", utterance="turn on")
        reply = Message("lights:on", dict(match.match_data))
        svc._apply_context_slots(match, sess, reply)
        self.assertEqual(reply.data.get("room"), "bedroom")

    def test_ungated_intent_is_noop(self):
        svc = self._service(requires=[], slot_names=[])
        sess = self._session(
            {"lights.skill:room": {"value": "kitchen", "turns_remaining": 2}})
        reply = Message("lights:on", {})
        svc._apply_context_slots(self._match(), sess, reply)
        self.assertNotIn("room", reply.data)

    def test_reply_framework_field_does_not_block_context_fill(self):
        # a declared slot colliding with a dispatch-reply framework field
        # (e.g. "utterance") must NOT be treated as utterance-filled just
        # because ``reply.data["utterance"]`` is always set by
        # ``_dispatch_match`` -- the §7 rule judges "did the utterance fill
        # slot k" against the pipeline's own ``match.match_data``, not the
        # reply payload.
        svc = self._service(requires=["utterance"], slot_names=["utterance"])
        sess = self._session(
            {"lights.skill:utterance": {"value": "kitchen", "turns_remaining": 2}})
        match = IntentHandlerMatch(match_type="lights:on", match_data={"conf": 1.0},
                                   skill_id="lights.skill", utterance="turn on")
        reply = Message("lights:on", dict(match.match_data))
        # mirrors what _dispatch_match does before calling _apply_context_slots
        reply.data["utterance"] = match.utterance
        reply.data["lang"] = "en-US"
        svc._apply_context_slots(match, sess, reply)
        self.assertEqual(reply.data.get("utterance"), "kitchen")

    def test_match_data_slot_still_wins_over_context(self):
        # the pipeline DID fill the colliding slot itself -- that value
        # must still win over context, even though it is echoed onto
        # reply.data too.
        svc = self._service(requires=["room"], slot_names=["room"])
        sess = self._session(
            {"lights.skill:room": {"value": "kitchen", "turns_remaining": 2}})
        match = IntentHandlerMatch(match_type="lights:on",
                                   match_data={"room": "bedroom"},
                                   skill_id="lights.skill", utterance="turn on")
        reply = Message("lights:on", dict(match.match_data))
        svc._apply_context_slots(match, sess, reply)
        self.assertEqual(reply.data.get("room"), "bedroom")


# ---------------------------------------------------------------------------
# §4.2 — decayed session must be folded onto the terminal emissions
# ---------------------------------------------------------------------------

class TestDecayPropagatesToTerminalEmissions(unittest.TestCase):
    """The post-match §4 decrement must be visible on the §8/§9.5 terminal
    emissions the matched dispatch eventually produces -- not just on the
    SessionManager-held session (which only helps the *next* turn for a
    remote client, per SESSION-1 wholesale-replace semantics)."""

    def setUp(self):
        SessionManager.sessions = {"default": Session("default")}
        SessionManager.default_session = SessionManager.sessions["default"]
        SessionManager.bus = None

    def tearDown(self):
        SessionManager.sessions = {"default": Session("default")}
        SessionManager.default_session = SessionManager.sessions["default"]
        SessionManager.bus = None

    def _run_full_dispatch(self, sess):
        bus = FakeBus()
        SessionManager.connect_to_bus(bus)
        svc = _make_service()
        svc.bus = bus
        svc._handle_transformers = lambda m: m
        svc.disambiguate_lang = lambda m: "en-US"
        svc.intent_manifest = IntentManifest(bus)
        svc.intent_dispatcher = IntentDispatcher(
            bus, timeout=0, on_terminal=svc._emit_utterance_handled)

        match = IntentHandlerMatch(match_type="lights.skill:on",
                                   match_data={"conf": 1.0},
                                   skill_id="lights.skill", utterance="turn on")
        svc.get_pipeline = lambda session: [
            ("fake-high", lambda utts, lang, msg: match)]

        handled_frames = []
        complete_frames = []
        bus.on("ovos.utterance.handled", handled_frames.append)
        bus.on("ovos.intent.handler.complete", complete_frames.append)

        # a real skill handler runs on a separate process/thread, over an
        # actual websocket -- its "done" signal always arrives well after
        # this synchronous match round (including the post-match decrement)
        # has finished. Capture the dispatch instead of completing inline,
        # so the test doesn't collapse that async gap the fix relies on.
        received = []
        bus.on("lights.skill:on", received.append)

        SessionManager.update(sess)
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["turn on"]},
                      context={"session": sess.serialize()})
        svc.handle_utterance(msg)

        self.assertEqual(len(received), 1, "handler was never dispatched")
        # simulate the skill's async completion arriving now, i.e. after
        # the orchestrator's post-match decrement has already run.
        bus.emit(Message("mycroft.skill.handler.complete",
                         {}, {"skill_id": "lights.skill",
                              "session": received[0].context.get("session")}))
        return handled_frames, complete_frames

    def test_decrement_actually_runs(self):
        # first, rule out that decrement isn't running at all: the managed
        # session's own intent_context must show the decayed value.
        sess = Session("decay-sanity")
        sess.intent_context = {"person": {"value": "Bob", "turns_remaining": 3}}
        self._run_full_dispatch(sess)
        managed = SessionManager.sessions["decay-sanity"].intent_context
        self.assertEqual(managed["person"]["turns_remaining"], 2)

    def test_terminal_emissions_carry_decayed_context(self):
        sess = Session("wire-sess")
        sess.intent_context = {"person": {"value": "Bob", "turns_remaining": 3}}
        handled_frames, complete_frames = self._run_full_dispatch(sess)

        self.assertEqual(len(handled_frames), 1)
        self.assertEqual(len(complete_frames), 1)

        handled_ctx = handled_frames[0].context["session"][INTENT_CONTEXT_FIELD]
        complete_ctx = complete_frames[0].context["session"][INTENT_CONTEXT_FIELD]
        self.assertEqual(handled_ctx["person"]["turns_remaining"], 2,
                         "ovos.utterance.handled must carry the decayed map (§4.2)")
        self.assertEqual(complete_ctx["person"]["turns_remaining"], 2,
                         "ovos.intent.handler.complete must carry the decayed map (§4.2)")

    def test_two_turn_wire_decay_3_2_1(self):
        # a remote client feeds back exactly what it was handed (SESSION-1
        # wholesale-replace); decay must still progress turn over turn.
        sess = Session("client-sess")
        sess.intent_context = {"person": {"value": "Bob", "turns_remaining": 3}}
        handled_frames, _ = self._run_full_dispatch(sess)
        turn1_session = handled_frames[0].context["session"]
        self.assertEqual(
            turn1_session[INTENT_CONTEXT_FIELD]["person"]["turns_remaining"], 2)

        sess2 = Session.deserialize(turn1_session)
        handled_frames2, _ = self._run_full_dispatch(sess2)
        turn2_session = handled_frames2[0].context["session"]
        self.assertEqual(
            turn2_session[INTENT_CONTEXT_FIELD]["person"]["turns_remaining"], 1)

    def test_same_dispatch_exemption_still_holds(self):
        # regression guard (commit eec4ae03): a key genuinely synced mid-round
        # (before this round's single §4.2 decrement point, e.g. from another
        # matcher's synchronous side effect) must NOT be decremented by the
        # very round that produced it.
        sess = Session("exempt-sess")
        sess.intent_context = {"person": {"value": "Bob", "turns_remaining": 3}}
        SessionManager.update(sess)

        def _mid_round_sync(utts, lang, msg):
            # a matcher earlier in the pipeline chain (still strictly before
            # the eventual match's §4.2 decrement point) syncs a disjoint
            # new key. It must land alive for exactly the next round.
            snap = SessionManager.sessions["exempt-sess"].serialize()
            snap[INTENT_CONTEXT_FIELD] = {
                "new.skill:flag": {"value": None, "turns_remaining": 1}}
            SessionManager.handle_session_sync(
                Message("ovos.session.sync", context={"session": snap}))
            return None  # this matcher itself does not match

        match = IntentHandlerMatch(match_type="lights.skill:on",
                                   match_data={"conf": 1.0},
                                   skill_id="lights.skill", utterance="turn on")

        bus = FakeBus()
        SessionManager.connect_to_bus(bus)
        svc = _make_service()
        svc.bus = bus
        svc._handle_transformers = lambda m: m
        svc.disambiguate_lang = lambda m: "en-US"
        svc.intent_manifest = IntentManifest(bus)
        svc.intent_dispatcher = IntentDispatcher(
            bus, timeout=0, on_terminal=svc._emit_utterance_handled)
        svc.get_pipeline = lambda session: [
            ("mid-round-sync", _mid_round_sync),
            ("fake-high", lambda utts, lang, msg: match)]

        handled_frames = []
        bus.on("ovos.utterance.handled", handled_frames.append)

        received = []

        def _fake_handler(message):
            # a real skill only ever folds the session it was actually
            # dispatched -- which, per the fix, already carries the
            # decremented map. This fold must be a no-op, not a re-clobber.
            SessionManager.get(message)
            received.append(message)
        bus.on("lights.skill:on", _fake_handler)

        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["turn on"]},
                      context={"session": SessionManager.sessions["exempt-sess"].serialize()})
        svc.handle_utterance(msg)

        self.assertEqual(len(received), 1, "handler was never dispatched")
        bus.emit(Message("mycroft.skill.handler.complete",
                         {}, {"skill_id": "lights.skill",
                              "session": received[0].context.get("session")}))

        ctx = handled_frames[0].context["session"][INTENT_CONTEXT_FIELD]
        self.assertEqual(ctx["person"]["turns_remaining"], 2)
        self.assertEqual(ctx["new.skill:flag"]["turns_remaining"], 1)
