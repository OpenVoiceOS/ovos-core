"""OVOS-SESSION-2 intake: where an inbound session enters the orchestrator.

§5.1 merges an inbound default-session carrier into the store, §2.6 forbids
any later Message from revising the working session with its own snapshot,
§2.7 defines the sync merge, and §2.2 leaves the orchestrator holding nothing
for a named session between utterances. These tests drive the real
IntentService over a FakeBus for each of those.
"""
import unittest
from collections import defaultdict
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import DEFAULT_SESSION_ID, Session, SessionManager
from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch
from ovos_spec_tools import SpecMessage
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.dispatcher import IntentDispatcher
from ovos_core.intent_services.manifest import IntentManifest
from ovos_core.intent_services.service import IntentService

INTENT_CONTEXT_FIELD = "intent_context"


def _make_service(bus, match=None) -> IntentService:
    """A real IntentService wired to ``bus``, with the plugin machinery stubbed
    and a single pipeline that returns ``match`` (or never matches)."""
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
        bus, timeout=0, on_terminal=svc._emit_utterance_handled)
    svc.get_pipeline = lambda session: (
        [("fake-high", lambda utts, lang, msg: match)] if match else [])
    return svc


def _utterance(session_snapshot=None, utterance="hello") -> Message:
    context = {} if session_snapshot is None else {"session": session_snapshot}
    return Message("recognizer_loop:utterance",
                   data={"utterances": [utterance]}, context=context)


class SessionIntakeTestCase(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        SessionManager.sessions.clear()
        SessionManager.reset_default_session()
        SessionManager.bus = None

    tearDown = setUp

    def drive(self, svc, message):
        """Run one utterance and return the session on its end-marker."""
        handled = []
        self.bus.on(SpecMessage.UTTERANCE_HANDLED, handled.append)
        svc.handle_utterance(message)
        self.bus.remove(SpecMessage.UTTERANCE_HANDLED, handled.append)
        self.assertEqual(len(handled), 1,
                         "expected exactly one ovos.utterance.handled")
        return handled[0].context["session"]


class TestDefaultSessionArrival(SessionIntakeTestCase):
    """§5.1 first bullet — an inbound default-session carrier is merged into
    the store as part of the utterance lifecycle."""

    def test_context_declared_on_one_utterance_gates_the_next(self):
        """The device declares an intent_context gate on its utterance; the
        next utterance, which declares nothing, still sees the gate.

        This is the whole point of the store. The device may omit its session
        entirely (§6.5) precisely because the orchestrator holds it, so a
        carrier that arrives and is not merged leaves every context-gated
        skill unreachable from the second turn onwards.
        """
        svc = _make_service(self.bus)

        declared = Session(DEFAULT_SESSION_ID)
        declared.intent_context = {"naptime.skill:awake": {"value": "yes"}}
        self.drive(svc, _utterance(declared.serialize()))

        # a bare follow-up: no session carrier at all, as §6.5 permits
        second = self.drive(svc, _utterance())
        self.assertIn("naptime.skill:awake",
                      second.get(INTENT_CONTEXT_FIELD) or {})

    def test_omitted_field_keeps_the_stored_value(self):
        """§5.1 merge semantics: a field the carrier omits is not cleared."""
        svc = _make_service(self.bus)

        declared = Session(DEFAULT_SESSION_ID)
        declared.blacklisted_intents = ["skill_x"]
        self.drive(svc, _utterance(declared.serialize()))

        second = self.drive(svc, _utterance(Session(DEFAULT_SESSION_ID).serialize()))
        self.assertEqual(second.get("blacklisted_intents"), ["skill_x"])

    def test_present_field_replaces_the_stored_value(self):
        """§5.1 merge semantics: a field the carrier sends does replace."""
        svc = _make_service(self.bus)

        first = Session(DEFAULT_SESSION_ID)
        first.blacklisted_intents = ["skill_x"]
        self.drive(svc, _utterance(first.serialize()))

        second = Session(DEFAULT_SESSION_ID)
        second.blacklisted_intents = ["skill_y"]
        result = self.drive(svc, _utterance(second.serialize()))
        self.assertEqual(result.get("blacklisted_intents"), ["skill_y"])


class TestArrivalHappensOnceAnUtterance(SessionIntakeTestCase):
    """§5.1 — the orchestrator takes an arrival exactly once per utterance,
    at the lifecycle entry, and its own write paths never take another."""

    def test_one_arrival_per_utterance(self):
        svc = _make_service(self.bus)
        arrivals = []
        real_fold = SessionManager.fold_inbound
        SessionManager.fold_inbound = classmethod(
            lambda cls, message: arrivals.append(message) or real_fold(message))
        try:
            self.drive(svc, _utterance(Session(DEFAULT_SESSION_ID).serialize()))
            self.assertEqual(len(arrivals), 1)

            # a legacy context write and a converse toggle arrive on their own
            # Messages mid-round; neither is an arrival (§2.6)
            frame = Message("add_context", {"context": "Kitchen"},
                            dict(arrivals[0].context))
            IntentService.handle_add_context(frame)
            self.assertEqual(len(arrivals), 1)

            self.drive(svc, _utterance())
            self.assertEqual(len(arrivals), 2)
        finally:
            SessionManager.fold_inbound = real_fold

    def test_a_context_write_does_not_adopt_the_frames_carrier(self):
        """§2.6: a mid-round frame's own snapshot does not revise the working
        session, so a stale one cannot wipe what the round accumulated."""
        svc = _make_service(self.bus)

        declared = Session(DEFAULT_SESSION_ID)
        declared.intent_context = {"naptime.skill:awake": {"value": "yes"}}
        message = _utterance(declared.serialize())
        svc.handle_utterance(message)

        stale = Message("add_context", {"context": "Kitchen"},
                        {"session": Session(DEFAULT_SESSION_ID).serialize(),
                         "utterance_id": message.context["utterance_id"]})
        IntentService.handle_add_context(stale)

        stored = SessionManager.get_default_session()
        self.assertIn("naptime.skill:awake", stored.intent_context or {})
        self.assertIn("Kitchen", stored.intent_context or {})


class TestSessionSyncConsumer(SessionIntakeTestCase):
    """§2.7 / §6.2 — ``ovos.session.sync`` carries a snapshot in
    ``Message.data["session"]`` and the orchestrator honours it."""

    def _sync(self, snapshot, carrier=None):
        context = {} if carrier is None else {"session": carrier}
        return Message(SpecMessage.SESSION_SYNC, {"session": snapshot}, context)

    def test_sync_merges_the_data_carrier_into_the_store(self):
        svc = _make_service(self.bus)
        stored = SessionManager.get_default_session()
        stored.blacklisted_intents = ["skill_x"]

        synced = Session(DEFAULT_SESSION_ID)
        synced.intent_context = {"tea.skill:brewing": {"value": "yes"}}
        svc.handle_session_sync(self._sync(synced.serialize()))

        stored = SessionManager.get_default_session()
        self.assertIn("tea.skill:brewing", stored.intent_context or {})
        # §5.1: what the snapshot omits keeps its stored value
        self.assertEqual(stored.blacklisted_intents, ["skill_x"])

    def test_sync_for_an_unknown_named_session_is_dropped(self):
        """§2.2: no round is open for it, so there is nothing to revise — and
        certainly not the default store."""
        svc = _make_service(self.bus)

        synced = Session("nobody-here")
        synced.intent_context = {"tea.skill:brewing": {"value": "yes"}}
        svc.handle_session_sync(
            self._sync(synced.serialize(), carrier=synced.serialize()))

        self.assertEqual(SessionManager.sessions.get("nobody-here"), None)
        self.assertEqual(
            SessionManager.get_default_session().intent_context or {}, {})

    def test_sync_reaches_the_named_session_of_an_open_round(self):
        """§2.7 directs a named-session sync at the utterance in progress."""
        received = []
        self.bus.on("lights.skill:on", received.append)
        match = IntentHandlerMatch(match_type="lights.skill:on",
                                   match_data={"conf": 1.0},
                                   skill_id="lights.skill", utterance="turn on")
        svc = _make_service(self.bus, match=match)

        carrier = Session("client-1")
        message = _utterance(carrier.serialize(), utterance="turn on")
        handled = []
        self.bus.on(SpecMessage.UTTERANCE_HANDLED, handled.append)
        svc.handle_utterance(message)
        self.assertEqual(len(received), 1, "handler was never dispatched")

        # the skill syncs a context entry mid-round, on its own dispatch frame
        synced = Session("client-1")
        synced.intent_context = {"lights.skill:room": {"value": "kitchen"}}
        svc.handle_session_sync(
            Message(SpecMessage.SESSION_SYNC, {"session": synced.serialize()},
                    dict(received[0].context)))

        self.bus.emit(Message("mycroft.skill.handler.complete", {},
                              {"skill_id": "lights.skill",
                               "session": received[0].context.get("session")}))
        self.assertEqual(len(handled), 1)
        self.assertIn("lights.skill:room",
                      handled[0].context["session"].get(INTENT_CONTEXT_FIELD) or {})


class TestNamedSessionThreading(SessionIntakeTestCase):
    """§2.2 — the orchestrator holds no named session between utterances, so
    the round's own session is what every step reads and writes."""

    def _dispatch_named(self, svc, session_id="client-1"):
        received = []
        self.bus.on("lights.skill:on", received.append)
        carrier = Session(session_id)
        message = _utterance(carrier.serialize(), utterance="turn on")
        handled = []
        self.bus.on(SpecMessage.UTTERANCE_HANDLED, handled.append)
        svc.handle_utterance(message)
        self.assertEqual(len(received), 1, "handler was never dispatched")
        return received[0], handled

    def test_tracked_deactivation_is_replayed_onto_the_end_marker(self):
        """A skill that deactivated itself mid-dispatch must not be active on
        the §9.5 end-marker of a named session's round."""
        match = IntentHandlerMatch(match_type="lights.skill:on",
                                   match_data={"conf": 1.0},
                                   skill_id="lights.skill", utterance="turn on")
        svc = _make_service(self.bus, match=match)
        dispatch, handled = self._dispatch_named(svc)

        svc._handle_deactivate(
            Message("intent.service.skills.deactivate",
                    {"skill_id": "lights.skill"}, dict(dispatch.context)))

        self.bus.emit(Message("mycroft.skill.handler.complete", {},
                              {"skill_id": "lights.skill",
                               "session": dispatch.context.get("session")}))

        self.assertEqual(len(handled), 1)
        end_session = Session.deserialize(handled[0].context["session"])
        self.assertFalse(end_session.is_active("lights.skill"))

    def test_decay_ticks_on_a_named_session(self):
        """§4.2 decay reaches a named session's context and rides the wire
        back, which is the only channel it has (§2.2)."""
        svc = _make_service(self.bus)

        carrier = Session("client-2")
        carrier.intent_context = {"person": {"value": "Bob",
                                             "turns_remaining": 3}}
        end_session = self.drive(svc, _utterance(carrier.serialize()))
        self.assertEqual(
            end_session[INTENT_CONTEXT_FIELD]["person"]["turns_remaining"], 2)


if __name__ == "__main__":
    unittest.main()
