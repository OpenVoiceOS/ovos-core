"""OVOS-SESSION-1 §2.5 — a malformed session carrier (a present ``session``
that is not a JSON object) must never crash a consumer, and must never be
folded into the default session (that would pollute shared default-session
state with an identity nobody named).

These drive the real entry points a forged/corrupted carrier can reach:
utterance intake (``IntentService.handle_utterance``), where the Message is
dropped before any transformer or dispatch runs but PIPELINE-1 §9.5 still
owes it exactly one ``ovos.utterance.handled`` end-marker, and the
``IntentDispatcher`` framework done-signal path, where there is no round to
safely resolve so the signal is dropped and every in-flight entry is left
untouched.
"""
import unittest
from collections import defaultdict
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.dispatcher import IntentDispatcher
from ovos_core.intent_services.manifest import IntentManifest
from ovos_core.intent_services.service import IntentService

MALFORMED_CARRIERS = ["notanobject", [1], 5, True]


def _make_service(bus) -> IntentService:
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
    svc.get_pipeline = lambda session: []
    return svc


def _utterance(session_carrier, utterance="hello") -> Message:
    return Message("recognizer_loop:utterance",
                   data={"utterances": [utterance]},
                   context={"session": session_carrier})


class TestMalformedCarrierAtIntake(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        SessionManager.sessions.clear()
        SessionManager.reset_default_session()
        SessionManager.bus = None

    tearDown = setUp

    def test_malformed_carrier_is_dropped_but_gets_its_end_marker(self):
        for carrier in MALFORMED_CARRIERS:
            with self.subTest(carrier=carrier):
                svc = _make_service(self.bus)
                default_before = SessionManager.get_default_session().serialize()

                # A bare `bus.emit` mock, not FakeBus's own listener dispatch:
                # FakeBus.on_message replicates MessageBusClient's inbound
                # session-take for realism, but (unlike the real client) does
                # not catch MalformedSession around it, so an emit carrying
                # a malformed carrier straight back through a live FakeBus
                # loop would raise there -- a FakeBus test-harness gap, not a
                # crash a real bus client hits (client.py's own
                # ``_take_inbound_session`` call is wrapped in exactly that
                # try/except). Patching emit isolates the one thing under
                # test here: what IntentService itself emits.
                handled = []
                with patch.object(svc.bus, "emit", side_effect=handled.append):
                    svc.handle_utterance(_utterance(carrier))  # must not raise

                svc.utterance_plugins.transform.assert_not_called()
                svc.metadata_plugins.transform.assert_not_called()
                self.assertEqual(svc.intent_dispatcher._in_flight, {},
                                 "a dropped Message is never dispatched")
                self.assertEqual(
                    SessionManager.get_default_session().serialize(),
                    default_before,
                    "malformed carrier must not touch the default session")

                self.assertEqual(len(handled), 1,
                                 "PIPELINE-1 §9.5 owes exactly one "
                                 "ovos.utterance.handled per entry-topic "
                                 "Message, even a dropped one")
                marker = handled[0]
                self.assertEqual(marker.context["session"], carrier,
                                 "the end-marker's context propagates the "
                                 "original carrier unchanged; nothing is "
                                 "fabricated")
                self.assertIsNotNone(marker.context.get("utterance_id"),
                                     "§9.1.1 stamps utterance_id before the "
                                     "carrier check runs")

    def test_service_keeps_working_after_a_malformed_carrier(self):
        svc = _make_service(self.bus)

        emitted = []
        with patch.object(svc.bus, "emit", side_effect=emitted.append):
            svc.handle_utterance(_utterance("notanobject"))  # dropped, end-marker owed
            svc.handle_utterance(_utterance(None))  # a normal follow-up
        handled = [m for m in emitted if m.msg_type == "ovos.utterance.handled"]
        self.assertEqual(len(handled), 2,
                         "both the dropped and the normal utterance must "
                         "get their end-marker")


class TestMalformedCarrierAtDispatcherDoneSignal(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()

    def test_malformed_done_signal_does_not_crash_or_lose_other_rounds(self):
        dispatcher = IntentDispatcher(self.bus, timeout=0)

        good_dispatch = Message("lights.skill:on", {},
                                {"session": {"session_id": "client-1"}})
        dispatcher.dispatch(good_dispatch)

        for carrier in MALFORMED_CARRIERS:
            with self.subTest(carrier=carrier):
                bad_signal = Message("mycroft.skill.handler.complete",
                                     {"intent_name": "on"},
                                     {"skill_id": "some.skill",
                                      "session": carrier})
                dispatcher._on_skill_complete(bad_signal)  # must not raise

        # the unrelated, well-formed in-flight dispatch is still tracked
        self.assertIn("client-1", dispatcher._in_flight)

        good_signal = Message("mycroft.skill.handler.complete",
                              {"intent_name": "on"},
                              {"skill_id": "lights.skill",
                               "session": {"session_id": "client-1"}})
        dispatcher._on_skill_complete(good_signal)
        self.assertNotIn("client-1", dispatcher._in_flight)

    def test_malformed_done_signal_does_not_misroute_across_sessions(self):
        """A malformed carrier on the done-signal gives no trustworthy session
        id. With the same skill/intent in flight on two different sessions
        (A and B), a done-signal that can only be matched by
        skill_id/intent_name is ambiguous between them — guessing which one
        it concludes risks popping the WRONG session's entry and misrouting
        its terminal into the other round (OVOS-SESSION-1 §2.5: never
        fabricate an identity; dropping is safer). So the malformed signal
        must be dropped outright, logged once, with every in-flight entry
        left untouched -- each then resolves through its own correct
        done-signal."""
        for carrier in MALFORMED_CARRIERS:
            with self.subTest(carrier=carrier):
                terminals = []
                dispatcher = IntentDispatcher(self.bus, timeout=0,
                                              on_terminal=terminals.append)

                dispatch_a = Message("some.skill:greet", {},
                                     {"session": {"session_id": "session-a"}})
                dispatch_b = Message("some.skill:greet", {},
                                     {"session": {"session_id": "session-b"}})
                dispatcher.dispatch(dispatch_a)
                dispatcher.dispatch(dispatch_b)

                bad_signal = Message("mycroft.skill.handler.complete",
                                     {"intent_name": "greet"},
                                     {"skill_id": "some.skill", "session": carrier})
                with patch("ovos_core.intent_services.dispatcher.LOG") as mock_log:
                    dispatcher._on_skill_complete(bad_signal)  # must not raise

                self.assertEqual(len(terminals), 0,
                                 "a malformed done-signal must not fabricate "
                                 "which in-flight round it concludes")
                self.assertIn("session-a", dispatcher._in_flight,
                             "session A's round must be left untouched")
                self.assertIn("session-b", dispatcher._in_flight,
                             "session B's round must be left untouched")
                self.assertEqual(mock_log.error.call_count, 1,
                                 "exactly one ERROR for the dropped signal")

                # session A's own, correctly-carried done-signal resolves only A
                good_signal = Message("mycroft.skill.handler.complete",
                                      {"intent_name": "greet"},
                                      {"skill_id": "some.skill",
                                       "session": {"session_id": "session-a"}})
                dispatcher._on_skill_complete(good_signal)
                self.assertEqual(len(terminals), 1)
                self.assertNotIn("session-a", dispatcher._in_flight)
                self.assertIn("session-b", dispatcher._in_flight,
                             "session B's round is unaffected by A's resolution")


if __name__ == "__main__":
    unittest.main()
