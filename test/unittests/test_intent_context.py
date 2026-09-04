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
"""OVOS-CONTEXT-1 conformance tests: liveness (§2), decay (§4/§4.1), scope
resolution (§3.1), gating (§6/§6.1), slot fill (§7), plus a live FakeBus
integration check through the real ``SessionManager``."""
import copy
import time
import unittest
from collections import defaultdict
from unittest.mock import MagicMock

import pytest

from ovos_bus_client.message import Message
from ovos_bus_client.session import DEFAULT_SESSION_ID, Session, SessionManager
from ovos_utils.fakebus import FakeBus

from ovos_spec_tools.context import (
    is_live,
    resolve_key,
    normalize_declaration,
    gate_satisfied,
    context_supplied_slots,
    decrement,
    INTENT_CONTEXT_FIELD,
)
from ovos_core.intent_services.service import IntentService


# OVOS-SESSION-2 §2.7: the session snapshot's PRIMARY carrier is
# ``Message.data["session"]``; ``Message.context["session"]`` is the legacy
# carrier, accepted as a fallback. ovos-bus-client#278 teaches
# ``SessionManager.handle_session_sync`` to read the data carrier (preferring
# it when both are present); until it ships, the data-carrier path is a
# no-match on the fallback-only handler in bus-client dev.
_NEEDS_BUS_CLIENT_278 = (
    "requires ovos-bus-client#278 (SESSION-2 §2.7 data carrier); XPASS means "
    "#278 shipped - drop the marker and bump the floor pin")


def _sync_msg(snap: dict, carrier: str = "data") -> Message:
    """Build an ``ovos.session.sync`` carrying ``snap``.

    ``carrier="data"`` is the SESSION-2 §2.7 primary carrier (default);
    ``carrier="context"`` is the legacy fallback shape; ``carrier="both"``
    puts a decoy on ``context`` so a reader that honours §2.7 picks ``data``.
    """
    if carrier == "context":
        return Message("ovos.session.sync", context={"session": snap})
    if carrier == "both":
        decoy = dict(snap)
        decoy[INTENT_CONTEXT_FIELD] = {"carrier.probe": {"value": "context"}}
        return Message("ovos.session.sync", data={"session": snap},
                       context={"session": decoy})
    return Message("ovos.session.sync", data={"session": snap})


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
# live FakeBus integration through the REAL SessionManager
# ---------------------------------------------------------------------------

class TestLiveSessionManagerSync(unittest.TestCase):
    """Drive ``ovos.session.sync`` through the real SessionManager (§5.3)."""

    def setUp(self):
        # isolate the singleton between tests
        SessionManager.sessions = {"default": Session("default")}
        SessionManager.default_session = SessionManager.sessions["default"]
        SessionManager.bus = None

    def tearDown(self):
        SessionManager.sessions = {"default": Session("default")}
        SessionManager.default_session = SessionManager.sessions["default"]
        SessionManager.bus = None

    @pytest.mark.xfail(strict=True, reason=_NEEDS_BUS_CLIENT_278)
    def test_real_sessionmanager_merges_sync(self):
        sess = Session("live-sess")
        sess.intent_context = {"keep": {"value": "k"}}
        SessionManager.update(sess)

        # a skill emits ovos.session.sync with an updated session snapshot
        snap = sess.serialize()
        snap[INTENT_CONTEXT_FIELD] = {
            "tea.skill:confirming_milk": {"value": None, "turns_remaining": 1},
            "keep": None,  # delete
        }
        SessionManager.handle_session_sync(_sync_msg(snap))

        merged = SessionManager.sessions["live-sess"].intent_context
        self.assertIn("tea.skill:confirming_milk", merged)
        self.assertNotIn("keep", merged)

    def test_orchestrator_decays_a_named_session_over_the_wire(self):
        """§4.2 decay on a named session, which the orchestrator holds no
        state for between utterances (SESSION-2 §2.2) — each turn's decayed
        session comes back on the wire and the client sends it on the next."""
        bus = FakeBus()
        SessionManager.connect_to_bus(bus)
        svc = _make_service()
        svc.bus = bus

        carrier = Session("turn-sess")
        carrier.intent_context = {"tea.skill:flag": {"value": None,
                                                     "turns_remaining": 1}}

        def _drive(snapshot):
            handled = []
            bus.on("ovos.utterance.handled", handled.append)
            msg = Message("recognizer_loop:utterance",
                          data={"utterances": ["hello"]},
                          context={"session": snapshot})
            # no pipelines loaded -> no match, decay still runs
            svc.handle_utterance(msg)
            bus.remove("ovos.utterance.handled", handled.append)
            self.assertEqual(len(handled), 1)
            return handled[0].context["session"]

        # turn 1: flag is live during the round, decremented to 0 after
        turn1 = _drive(carrier.serialize())
        self.assertEqual(
            turn1[INTENT_CONTEXT_FIELD]["tea.skill:flag"]["turns_remaining"], 0)
        # turn 2: pre-match prune removes the now-dead flag
        turn2 = _drive(turn1)
        self.assertNotIn("tea.skill:flag",
                         turn2.get(INTENT_CONTEXT_FIELD) or {})

    def test_intake_binds_the_working_session_to_the_message_named(self):
        """The round must run on ONE session object: mid-round, the
        message's bound session (what every ``SessionManager.get(message)``
        and derivation sees) must be the exact working session object the
        orchestrator opened the round with, for a named carrier."""
        from ovos_core.intent_services.working_session import working_session
        bus = FakeBus()
        SessionManager.connect_to_bus(bus)
        svc = _make_service()
        svc.bus = bus

        seen = {}

        def _capture(utts, lang, message):
            seen["bound"] = SessionManager.get(message)
            seen["working"] = working_session(message)
            return None

        svc.get_pipeline = lambda session: [("fake", _capture)]

        carrier = Session("bind-check-sess")
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["hello"]},
                      context={"session": carrier.serialize()})
        svc.handle_utterance(msg)
        self.assertIs(seen["bound"], seen["working"])

    def test_intake_binds_the_working_session_to_the_message_default(self):
        """Same invariant for the default carrier: the object bound must be
        the registry's own default-session store, not a copy, since
        ``SessionManager.bind`` refuses anything else for a default-shaped
        session."""
        bus = FakeBus()
        SessionManager.connect_to_bus(bus)
        svc = _make_service()
        svc.bus = bus

        seen = {}

        def _capture(utts, lang, message):
            seen["bound"] = SessionManager.get(message)
            return None

        svc.get_pipeline = lambda session: [("fake", _capture)]

        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["hello"]},
                      context={})
        svc.handle_utterance(msg)
        self.assertIs(seen["bound"], SessionManager.get_default_session())

    @pytest.mark.xfail(strict=True, reason=_NEEDS_BUS_CLIENT_278)
    def test_midispatch_sync_survives_decay(self):
        # §4.1: a mid-dispatch entry is not decremented by the round it arrived in
        sess = Session("mid-sess")
        sess.intent_context = {"old.skill:flag": {"value": None,
                                                  "turns_remaining": 1}}
        SessionManager.update(sess)

        pre_match_keys = set(sess.intent_context.keys())

        # mid-dispatch sync merges a disjoint new key
        snap = sess.serialize()
        snap[INTENT_CONTEXT_FIELD] = {
            "new.skill:flag": {"value": None, "turns_remaining": 1}}
        SessionManager.handle_session_sync(_sync_msg(snap))

        managed = SessionManager.sessions["mid-sess"]
        post_ctx = dict(managed.intent_context or {})
        decrement(post_ctx, only_keys=pre_match_keys)
        managed.intent_context = post_ctx or None
        SessionManager.update(managed)

        ctx = SessionManager.sessions["mid-sess"].intent_context
        self.assertEqual(ctx["old.skill:flag"]["turns_remaining"], 0)
        self.assertEqual(ctx["new.skill:flag"]["turns_remaining"], 1)

    @pytest.mark.xfail(strict=True, reason=_NEEDS_BUS_CLIENT_278)
    def test_midispatch_sync_refresh_of_existing_key_not_decremented(self):
        # §4.1: a mid-dispatch sync refreshing an existing key must be
        # compared by entry value, not key presence, to avoid decrementing it
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
            SessionManager.handle_session_sync(_sync_msg(snap))
            return None  # no match, decay still runs to completion

        svc.get_pipeline = lambda session: [("fake", _mid_dispatch_refresh)]

        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["hello"]},
                      context={"session":
                               SessionManager.sessions["refresh-sess"].serialize()})
        svc.handle_utterance(msg)

        ctx = SessionManager.sessions["refresh-sess"].intent_context
        self.assertEqual(ctx["tea.skill:flag"]["turns_remaining"], 5)
        self.assertEqual(ctx["tea.skill:flag"]["value"], "b")


class TestDispatchMatchRejectsMismatchedUpdatedSession(unittest.TestCase):
    """OVOS-PIPELINE-1 §4.2 / OVOS-SESSION-2 §5.1: ``updated_session`` is
    defined as the ROUND's own session, updated — never a different
    session. A pipeline plugin handing back one for a different id is a
    plugin bug, and a plugin bug must not kill the utterance."""

    def setUp(self):
        SessionManager.sessions = {"default": Session("default")}
        SessionManager.default_session = SessionManager.sessions["default"]
        SessionManager.bus = None

    tearDown = setUp

    def test_mismatched_updated_session_id_is_rejected_not_fatal(self):
        bus = FakeBus()
        SessionManager.connect_to_bus(bus)
        svc = _make_service()
        svc.bus = bus
        svc.intent_dispatcher = MagicMock()

        carrier = Session("sat-1")
        mismatched = Session("sat-2")
        bad_match = IntentHandlerMatch(
            match_type="test:intent", match_data={}, skill_id=None,
            utterance="hello", updated_session=mismatched)
        svc.get_pipeline = lambda session: [
            ("fake-high", lambda utts, lang, msg: bad_match)]

        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["hello"]},
                      context={"session": carrier.serialize()})

        from ovos_core.intent_services import service as service_module
        with patch.object(service_module.LOG, "error") as mock_error:
            svc.handle_utterance(msg)

        mock_error.assert_called_once()
        logged = mock_error.call_args[0][0]
        self.assertIn("sat-1", logged)
        self.assertIn("sat-2", logged)
        # dispatch proceeded on the round's own session, not the rejected one
        svc.intent_dispatcher.dispatch.assert_called_once()
        dispatched_reply = svc.intent_dispatcher.dispatch.call_args[0][0]
        self.assertEqual(
            dispatched_reply.context["session"]["session_id"], "sat-1")


class TestSessionSyncCarrier(unittest.TestCase):
    """OVOS-SESSION-2 §2.7 — which carrier ``ovos.session.sync`` reads."""

    def setUp(self):
        SessionManager.sessions = {"default": Session("default")}
        SessionManager.default_session = SessionManager.sessions["default"]
        SessionManager.bus = None

    tearDown = setUp

    def _tracked(self, sid):
        sess = Session(sid)
        sess.intent_context = {"keep": {"value": "k"}}
        SessionManager.update(sess)
        return sess

    def _snap(self, sess, entries):
        snap = sess.serialize()
        snap[INTENT_CONTEXT_FIELD] = entries
        return snap

    def test_legacy_context_carrier_is_still_honoured(self):
        """§2.7 fallback: the legacy ``context['session']`` shape must keep
        working for one major.

        Driven on the default session, the only one the orchestrator holds
        state for (§2.3/§5) and so the only one a sync arriving outside an
        utterance has somewhere to land."""
        sess = self._tracked(DEFAULT_SESSION_ID)
        snap = self._snap(sess, {"from.ctx": {"value": "ctx"}})
        SessionManager.handle_session_sync(_sync_msg(snap, carrier="context"))
        merged = SessionManager.get_default_session().intent_context
        self.assertEqual(merged.get("from.ctx"), {"value": "ctx"})

    @pytest.mark.xfail(strict=True, reason=_NEEDS_BUS_CLIENT_278)
    def test_data_carrier_is_honoured(self):
        """§2.7 primary carrier: the snapshot rides ``data['session']``."""
        sess = self._tracked("carrier-data")
        snap = self._snap(sess, {"from.data": {"value": "data"}})
        SessionManager.handle_session_sync(_sync_msg(snap))
        merged = SessionManager.sessions["carrier-data"].intent_context
        self.assertEqual(merged.get("from.data"), {"value": "data"})

    @pytest.mark.xfail(strict=True, reason=_NEEDS_BUS_CLIENT_278)
    def test_data_carrier_wins_over_context_carrier(self):
        """§2.7: when both carriers are present, ``data`` is authoritative;
        the ``context`` decoy must not be merged."""
        sess = self._tracked("carrier-both")
        snap = self._snap(sess, {"from.data": {"value": "data"}})
        SessionManager.handle_session_sync(_sync_msg(snap, carrier="both"))
        merged = SessionManager.sessions["carrier-both"].intent_context
        self.assertEqual(merged.get("from.data"), {"value": "data"})
        self.assertNotIn("carrier.probe", merged)


class TestDecayIgnoresUnknownSession(unittest.TestCase):
    """OVOS-CONTEXT-1 §4.2 — decay must never fall back to the DEFAULT
    session. A pipeline returning an ``updated_session`` with an
    unregistered ``session_id`` would otherwise decay an unrelated
    conversation using this round's pre-match snapshot."""

    def setUp(self):
        SessionManager.sessions = {"default": Session("default")}
        SessionManager.default_session = SessionManager.sessions["default"]
        SessionManager.bus = None

    tearDown = setUp

    def test_named_session_decay_leaves_default_untouched(self):
        default = SessionManager.get_default_session()
        default.intent_context = {"person": {"value": "Bob",
                                             "turns_remaining": 3}}
        before = copy.deepcopy(default.intent_context)

        sess = Session("foreign-session")
        sess.intent_context = {"person": {"value": "Bob", "turns_remaining": 3}}
        svc = _make_service()
        svc._apply_post_match_decay(
            sess, {"person": {"value": "Bob", "turns_remaining": 3}})

        self.assertEqual(sess.intent_context["person"]["turns_remaining"], 2)
        self.assertEqual(
            SessionManager.get_default_session().intent_context, before,
            "the default session's intent_context must be untouched")

    def test_named_session_decays(self):
        sess = Session("real-session")
        sess.intent_context = {"person": {"value": "Bob", "turns_remaining": 3}}
        svc = _make_service()
        svc._apply_post_match_decay(
            sess, {"person": {"value": "Bob", "turns_remaining": 3}})
        self.assertEqual(sess.intent_context["person"]["turns_remaining"], 2)



# ---------------------------------------------------------------------------
# §6/§6.1 — orchestrator gate backstop in the match loop
# ---------------------------------------------------------------------------

from unittest.mock import patch  # noqa: E402
from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch  # noqa: E402
from ovos_core.intent_services.manifest import IntentManifest  # noqa: E402
from ovos_core.intent_services.dispatcher import IntentDispatcher  # noqa: E402


class TestOrchestratorGate(unittest.TestCase):
    """handle_utterance drops a context-gated match whose gate is unsatisfied."""

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
    """§7 slot-fill: an unfilled slot is populated from the live context entry."""

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
        # a declared slot colliding with a reply framework field (e.g.
        # "utterance") must not be treated as utterance-filled
        svc = self._service(requires=["utterance"], slot_names=["utterance"])
        sess = self._session(
            {"lights.skill:utterance": {"value": "kitchen", "turns_remaining": 2}})
        match = IntentHandlerMatch(match_type="lights:on", match_data={"conf": 1.0},
                                   skill_id="lights.skill", utterance="turn on")
        reply = Message("lights:on", dict(match.match_data))
        reply.data["utterance"] = match.utterance
        reply.data["lang"] = "en-US"
        svc._apply_context_slots(match, sess, reply)
        self.assertEqual(reply.data.get("utterance"), "kitchen")

    def test_match_data_slot_still_wins_over_context(self):
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
    """The §4 decrement must be visible on the §8/§9.5 terminal emissions,
    not just on the SessionManager-held session."""

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

        # capture the dispatch instead of completing inline, to preserve the
        # real async gap between dispatch and skill completion
        received = []
        bus.on("lights.skill:on", received.append)

        SessionManager.update(sess)
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["turn on"]},
                      context={"session": sess.serialize()})
        svc.handle_utterance(msg)

        self.assertEqual(len(received), 1, "handler was never dispatched")
        bus.emit(Message("mycroft.skill.handler.complete",
                         {}, {"skill_id": "lights.skill",
                              "session": received[0].context.get("session")}))
        return handled_frames, complete_frames

    def test_decrement_actually_runs(self):
        sess = Session("decay-sanity")
        sess.intent_context = {"person": {"value": "Bob", "turns_remaining": 3}}
        handled_frames, _ = self._run_full_dispatch(sess)
        decayed = handled_frames[0].context["session"][INTENT_CONTEXT_FIELD]
        self.assertEqual(decayed["person"]["turns_remaining"], 2)

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

    @pytest.mark.xfail(strict=True, reason=_NEEDS_BUS_CLIENT_278)
    def test_same_dispatch_exemption_still_holds(self):
        # A key synced mid-round must not be decremented by the very round
        # that produced it.
        sess = Session("exempt-sess")
        sess.intent_context = {"person": {"value": "Bob", "turns_remaining": 3}}
        SessionManager.update(sess)

        def _mid_round_sync(utts, lang, msg):
            snap = SessionManager.sessions["exempt-sess"].serialize()
            snap[INTENT_CONTEXT_FIELD] = {
                "new.skill:flag": {"value": None, "turns_remaining": 1}}
            SessionManager.handle_session_sync(_sync_msg(snap))
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


# ---------------------------------------------------------------------------
# §6.2 x §7 — the missing-required-slots backstop must consult live context
# ---------------------------------------------------------------------------

class TestRequiredSlotFilledFromContext(unittest.TestCase):
    """A required slot that the live ``intent_context`` can fill must not be
    rejected by the §6.2 backstop, which runs BEFORE the §7 fill."""

    def setUp(self):
        SessionManager.sessions = {"default": Session("default")}
        SessionManager.default_session = SessionManager.sessions["default"]
        SessionManager.bus = None

    tearDown = setUp

    def _service(self):
        svc = _make_service()
        svc._handle_transformers = lambda m: m
        svc.disambiguate_lang = lambda m: "en-US"
        svc.send_complete_intent_failure = MagicMock()
        svc.intent_manifest = IntentManifest(svc.bus)
        svc.intent_manifest._on_register(Message(
            "ovos.intent.register.keyword",
            {"skill_id": "weather.skill", "intent_name": "forecast",
             "lang": "en-US",
             "required": ["location"],
             "required_slots": ["location"],
             "requires_context": [{"key": "location", "scope": "shared"}]}, {}))
        match = IntentHandlerMatch(match_type="weather.skill:forecast",
                                   match_data={"conf": 1.0},
                                   skill_id="weather.skill",
                                   utterance="what is the forecast")
        svc.get_pipeline = lambda session: [
            ("fake-high", lambda utts, lang, msg: match)]
        return svc

    def _run(self, intent_context):
        svc = self._service()
        svc.intent_dispatcher = IntentDispatcher(
            svc.bus, timeout=0, on_terminal=svc._emit_utterance_handled)
        sess = Session("slot-sess")
        sess.lang = "en-US"
        sess.pipeline = ["fake-high"]
        sess.intent_context = intent_context
        SessionManager.update(sess)

        received = []
        svc.bus.on("weather.skill:forecast", received.append)
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["what is the forecast"]},
                      context={"session": sess.serialize()})
        with patch.object(svc, "_validate_session", return_value=sess):
            svc.handle_utterance(msg)
        return svc, received

    def test_required_slot_filled_from_context_dispatches(self):
        svc, received = self._run(
            {"location": {"value": "Lisbon", "turns_remaining": 3}})
        self.assertEqual(len(received), 1,
                         "match with a context-fillable required slot must dispatch")
        self.assertEqual(received[0].data.get("location"), "Lisbon",
                         "the slot must be filled from live context (§7)")
        svc.send_complete_intent_failure.assert_not_called()

    def test_required_slot_absent_everywhere_still_rejected(self):
        # regression guard: the §6.2 backstop is consulted, not removed
        svc, received = self._run(None)
        self.assertEqual(received, [],
                         "a genuinely missing required slot must still reject")
        svc.send_complete_intent_failure.assert_called_once()
