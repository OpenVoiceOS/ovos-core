"""OVOS-SESSION-1 §2.5 — a malformed session carrier (a present ``session``
that is not a JSON object) must never crash a consumer, and must never be
substituted for the default session.

These drive the real entry points a forged/corrupted carrier can reach:
utterance intake (``IntentService.handle_utterance``) and the
``IntentDispatcher`` framework done-signal path.
"""
import unittest
from collections import defaultdict
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from ovos_bus_client.session import DEFAULT_SESSION_ID, SessionManager
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

    def test_malformed_carrier_never_crashes_and_is_dropped(self):
        for carrier in MALFORMED_CARRIERS:
            with self.subTest(carrier=carrier):
                svc = _make_service(self.bus)
                default_before = SessionManager.get_default_session().serialize()

                handled = []
                self.bus.on("ovos.utterance.handled", handled.append)
                try:
                    svc.handle_utterance(_utterance(carrier))  # must not raise
                finally:
                    self.bus.remove("ovos.utterance.handled", handled.append)

                self.assertEqual(len(handled), 0,
                                 "a dropped utterance owes no end-marker")
                self.assertEqual(
                    SessionManager.get_default_session().serialize(),
                    default_before,
                    "malformed carrier must not touch the default session")

    def test_service_keeps_working_after_a_malformed_carrier(self):
        svc = _make_service(self.bus)
        svc.handle_utterance(_utterance("notanobject"))  # dropped

        handled = []
        self.bus.on("ovos.utterance.handled", handled.append)
        svc.handle_utterance(_utterance(None))  # a normal follow-up
        self.bus.remove("ovos.utterance.handled", handled.append)
        self.assertEqual(len(handled), 1,
                         "a normal utterance after a malformed one must still "
                         "be handled")


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
