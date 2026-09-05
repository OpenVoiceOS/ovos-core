"""OVOS-SESSION-2 §2.6 — the completion sync.

The session a handler receives on its dispatch is the round's single working
session, and at handler completion the orchestrator syncs that working session
with whatever the handler wrote. The handler runs in another process, so its
writes come back on the framework done-signal, which ovos-workshop forwards
from the handler's own copy of the dispatch Message.

These tests drive the real IntentService and IntentDispatcher over a FakeBus,
simulating the process boundary the way the bus does it: the "skill" reads a
serialize/deserialize round trip of the dispatch, mutates that copy's session,
and answers with a done-signal forwarded from it. They assert what §2.6 fixes:
the §8 terminal and the §9.5 end-marker carry the synced session, the default
store is merged the same way an intake merges, the round's pre-match prune
outranks a stale handler copy, and a write to a field the handler does not own
never lands.
"""
import unittest
from collections import defaultdict
from copy import deepcopy
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from ovos_bus_client.session import DEFAULT_SESSION_ID, Session, SessionManager
from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch
from ovos_spec_tools import SpecMessage
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.dispatcher import IntentDispatcher
from ovos_core.intent_services.manifest import IntentManifest
from ovos_core.intent_services.service import IntentService

SKILL_ID = "lights.skill"
INTENT = "on"
DISPATCH_TOPIC = f"{SKILL_ID}:{INTENT}"


def _make_service(bus, match) -> IntentService:
    """A real IntentService wired to ``bus`` with one pipeline returning
    ``match``, and the real IntentDispatcher wired to both its callbacks."""
    svc = IntentService.__new__(IntentService)
    svc.bus = bus
    svc.config = {}
    svc.pipeline_plugins = {}
    svc._deactivations = defaultdict(list)
    svc.status = MagicMock()

    for attr, transform in (("utterance_plugins", lambda utt, ctx: (utt, ctx)),
                            ("metadata_plugins", lambda ctx: ctx),
                            ("intent_plugins", lambda intent: intent)):
        plugins = MagicMock()
        plugins.transform.side_effect = transform
        setattr(svc, attr, plugins)

    svc.disambiguate_lang = lambda m: "en-US"
    svc.intent_manifest = IntentManifest(bus)
    svc.intent_dispatcher = IntentDispatcher(
        bus, timeout=0, on_terminal=svc._emit_utterance_handled,
        on_done_signal=svc._sync_handler_mutations)
    svc.get_pipeline = lambda session: [
        ("fake-high", lambda utts, lang, msg: match)]
    return svc


def _match() -> IntentHandlerMatch:
    return IntentHandlerMatch(match_type=DISPATCH_TOPIC,
                              match_data={"conf": 1.0},
                              skill_id=SKILL_ID, utterance="turn on")


def _entry(value):
    return {"value": value}


class CompletionSyncTestCase(unittest.TestCase):
    """Drives one utterance with a scripted handler and collects the round's
    terminal events."""

    def setUp(self):
        self.bus = FakeBus()
        SessionManager.sessions.clear()
        SessionManager.reset_default_session()
        SessionManager.bus = None
        self.svc = _make_service(self.bus, _match())
        self.complete = []
        self.errored = []
        self.handled = []
        self.bus.on(SpecMessage.INTENT_HANDLER_COMPLETE, self.complete.append)
        self.bus.on(SpecMessage.INTENT_HANDLER_ERROR, self.errored.append)
        self.bus.on(SpecMessage.UTTERANCE_HANDLED, self.handled.append)

    def tearDown(self):
        self.svc.intent_dispatcher.shutdown()
        SessionManager.sessions.clear()
        SessionManager.reset_default_session()
        SessionManager.bus = None

    def run_utterance(self, handler, carrier=None, done_topic=None,
                      done_from=None):
        """Run one utterance; ``handler`` plays the skill on its own copy of
        the dispatch and returns the Message the done-signal is forwarded from.

        ``handler`` receives the deserialized dispatch — the object a skill in
        another process would get off the bus, never core's own instance.
        """
        signal = done_topic or "mycroft.skill.handler.complete"

        def on_dispatch(dispatch: Message):
            # the process boundary: what the skill sees is a wire round trip
            skill_copy = Message.deserialize(dispatch.serialize())
            handler(skill_copy)
            source = done_from(skill_copy) if done_from else skill_copy
            done = source.forward(signal, {})
            done.context["skill_id"] = SKILL_ID
            self.bus.emit(done)

        self.bus.on(DISPATCH_TOPIC, on_dispatch)
        context = {} if carrier is None else {"session": carrier}
        self.svc.handle_utterance(
            Message("recognizer_loop:utterance",
                    {"utterances": ["turn on"]}, context))
        self.bus.remove(DISPATCH_TOPIC, on_dispatch)

    @staticmethod
    def detached(mutate):
        """A handler playing on a session DETACHED from the orchestrator's.

        A skill runs in another process, so the session it writes to is only
        ever a copy. For the default session that distinction is the whole
        test: ``SessionManager.get`` would hand an in-process handler the
        store itself, and a write through it would land whether or not the
        completion sync exists.
        """
        def handler(dispatch: Message):
            sess = Session.deserialize(dispatch.context["session"])
            mutate(sess)
            dispatch.context["session"] = sess.serialize()
        return handler

    @staticmethod
    def plain_done(skill_copy: Message) -> Message:
        """The done-signal as the other process builds it — carrying that
        process's own session, not one re-stamped from the local store."""
        return Message("done", {}, deepcopy(skill_copy.context))

    def end_session(self) -> dict:
        self.assertEqual(len(self.handled), 1,
                         "expected exactly one ovos.utterance.handled")
        return self.handled[0].context["session"]

    def complete_session(self) -> dict:
        self.assertEqual(len(self.complete), 1,
                         "expected exactly one ovos.intent.handler.complete")
        return self.complete[0].context["session"]


class TestNamedSession(CompletionSyncTestCase):
    """§2.6 — the terminal and the end-marker carry the synced session."""

    def test_handler_write_reaches_the_terminal_and_the_end_marker(self):
        def handler(dispatch):
            # a real handler speaks first; the speak derives its own Message
            # and is not what carries the mutation back
            self.bus.emit(dispatch.forward("speak", {"utterance": "ok"}))
            SessionManager.get(dispatch).set_intent_context(
                "kitchen", _entry(True), owner_id=SKILL_ID)

        self.run_utterance(handler, carrier=Session("client-1").serialize())

        key = f"{SKILL_ID}:kitchen"
        self.assertIn(key, self.complete_session()["intent_context"],
                      "ovos.intent.handler.complete carries the dispatch "
                      "snapshot, not the session synced at completion")
        self.assertIn(key, self.end_session()["intent_context"])

    def test_error_terminal_carries_the_synced_session(self):
        def handler(dispatch):
            SessionManager.get(dispatch).set_intent_context(
                "kitchen", _entry(True), owner_id=SKILL_ID)

        self.run_utterance(handler, carrier=Session("client-1").serialize(),
                           done_topic="mycroft.skill.handler.error")

        key = f"{SKILL_ID}:kitchen"
        self.assertEqual(len(self.errored), 1)
        self.assertIn(key, self.errored[0].context["session"]["intent_context"])
        self.assertIn(key, self.end_session()["intent_context"])

    def test_removal_propagates(self):
        carrier = Session("client-1")
        key = f"{SKILL_ID}:kitchen"
        carrier.intent_context = {key: _entry(True)}

        def handler(dispatch):
            SessionManager.get(dispatch).remove_intent_context(
                "kitchen", owner_id=SKILL_ID)

        self.run_utterance(handler, carrier=carrier.serialize())

        self.assertNotIn(key, self.complete_session().get("intent_context") or {})
        self.assertNotIn(key, self.end_session().get("intent_context") or {})

    def test_a_field_the_handler_does_not_own_is_not_applied(self):
        def handler(dispatch):
            SessionManager.get(dispatch).lang = "pt-PT"

        self.run_utterance(handler, carrier=Session("client-1").serialize())

        self.assertEqual(self.end_session()["lang"], "en-US",
                         "a handler write to lang is forbidden by §2.6 and "
                         "must not be synced onto the round")

    def test_self_removal_from_active_handlers_is_applied(self):
        carrier = Session("client-1")
        carrier.add_active_handler(SKILL_ID)

        def handler(dispatch):
            SessionManager.get(dispatch).remove_active_handler(SKILL_ID)

        self.run_utterance(handler, carrier=carrier.serialize())

        active = {h["skill_id"]
                  for h in self.end_session().get("active_handlers") or []}
        self.assertNotIn(SKILL_ID, active)


class TestDefaultSession(CompletionSyncTestCase):
    """§2.6 / §5.1 — the write also merges into the default-session store.

    These assert the end state, not the sync in isolation: ovos-bus-client
    writes a default-shaped ``Session`` through to the store whatever object
    holds it, so an in-process handler reaches the store on its own. The
    named-session cases above are where the sync is isolated.
    """

    def test_store_reflects_the_handler_write(self):
        handler = self.detached(lambda s: s.set_intent_context(
            "kitchen", _entry(True), owner_id=SKILL_ID))

        self.run_utterance(handler,
                           carrier=Session(DEFAULT_SESSION_ID).serialize(),
                           done_from=self.plain_done)

        key = f"{SKILL_ID}:kitchen"
        self.assertIn(key, self.end_session()["intent_context"])
        self.assertIn(key, SessionManager.get_default_session().intent_context,
                      "the default-session store did not receive the "
                      "handler's §5.1 merge")

    def test_removal_reaches_the_store(self):
        key = f"{SKILL_ID}:kitchen"
        stored = SessionManager.get_default_session()
        stored.intent_context = {key: _entry(True)}

        handler = self.detached(lambda s: s.remove_intent_context(
            "kitchen", owner_id=SKILL_ID))

        self.run_utterance(handler,
                           carrier=Session(DEFAULT_SESSION_ID).serialize(),
                           done_from=self.plain_done)

        self.assertNotIn(key, SessionManager.get_default_session().intent_context)


class TestDecayAuthority(CompletionSyncTestCase):
    """§2.6 — the synced map is authoritative for the round's decay: an entry
    the pre-match prune removed is not resurrected by the handler's copy."""

    def test_a_pruned_entry_is_not_resurrected_by_a_stale_handler_copy(self):
        key = f"{SKILL_ID}:expired"
        stored = SessionManager.get_default_session()
        # dead on arrival: the pre-match prune of this round drops it
        stored.intent_context = {key: {"value": True, "turns_remaining": 0}}
        stale = {key: {"value": True, "turns_remaining": 0}}

        def handler(dispatch):
            # the handler answers with a copy that predates the prune
            SessionManager.get(dispatch)  # bind, as a real handler does
            dispatch.context["session"]["intent_context"] = dict(stale)

        def done_from(skill_copy):
            # forward from the stale copy itself, bypassing the bound session
            return Message("stale", {}, dict(skill_copy.context))

        self.run_utterance(handler,
                           carrier=Session(DEFAULT_SESSION_ID).serialize(),
                           done_from=done_from)

        self.assertNotIn(key, self.end_session().get("intent_context") or {},
                         "the pre-match prune is authoritative; a stale "
                         "handler copy must not put the entry back")
        self.assertNotIn(key,
                         SessionManager.get_default_session().intent_context)

    def test_a_key_the_handler_re_arms_is_not_beaten_by_the_prune(self):
        """The decay outranks a stale carry-over, not a fresh write: a handler
        arming the same key again in the round that pruned its predecessor is
        writing, and the write lands."""
        key = f"{SKILL_ID}:expired"
        carrier = Session("client-1")
        carrier.intent_context = {key: {"value": "stale", "turns_remaining": 0}}

        def handler(dispatch):
            SessionManager.get(dispatch).set_intent_context(
                "expired", "fresh", owner_id=SKILL_ID)

        self.run_utterance(handler, carrier=carrier.serialize())

        entry = (self.end_session().get("intent_context") or {}).get(key)
        self.assertIsNotNone(entry, "the handler's re-arm of a key pruned "
                                    "this round was dropped")
        self.assertEqual(entry["value"], "fresh")


class TestFaultyDoneSignals(CompletionSyncTestCase):
    """A bad done-signal is a fault to log, never a lost round.

    Both cases are driven at the sync callback rather than over the bus: a
    signal whose session names another id does not correlate to any in-flight
    dispatch in the first place, and FakeBus refuses to carry a malformed
    carrier at all. The guard exists for the transports that do deliver them.
    """

    def dispatched_message(self) -> Message:
        dispatched = []
        self.run_utterance(dispatched.append,
                           carrier=Session("client-1").serialize())
        self.assertEqual(len(self.complete), 1)
        self.assertEqual(len(self.handled), 1)
        return dispatched[0]

    def test_a_signal_naming_another_session_is_ignored(self):
        dispatch = self.dispatched_message()
        live = dict(dispatch.context["session"])

        intruder = Message("done", {}, dict(dispatch.context))
        other = Session("someone-else")
        other.intent_context = {f"{SKILL_ID}:kitchen": _entry(True)}
        intruder.context["session"] = other.serialize()

        with patch("ovos_core.intent_services.service.LOG") as log:
            self.svc._sync_handler_mutations(intruder, dispatch)
        log.error.assert_called()
        self.assertEqual(dispatch.context["session"], live,
                         "a done-signal for another session must not write "
                         "into this round")

    def test_a_malformed_carrier_is_logged_and_the_round_still_closes(self):
        """A carrier that is not a JSON object is malformed (SESSION-1 §2.5):
        the sync is skipped, and the round still reached its terminal — the
        dispatcher owns the §8 obligation of one terminal per dispatch."""
        dispatch = self.dispatched_message()

        broken = Message("done", {}, dict(dispatch.context))
        broken.context["session"] = "not-an-object"
        with patch("ovos_core.intent_services.service.LOG") as log:
            self.svc._sync_handler_mutations(broken, dispatch)
        log.error.assert_called()


if __name__ == "__main__":
    unittest.main()
