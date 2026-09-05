"""End-to-end check that a targeted stop resolves on its handler's return.

OVOS-PIPELINE-1 §8 gives the handler-lifecycle trio to the orchestrator that
invokes the handler: "`start` before the call, then `complete` on normal return
or `error` on exception. The handler itself does not emit anything."
OVOS-STOP-1 §4.3 applies that to the stop dispatch — "the orchestrator alone
emits `.complete` on normal return or `.error` on exception, and that terminal
event resolves the stop round."

So `<skill_id>:stop` is resolved by the dispatched handler returning, exactly
like every other dispatch, and the §8.3 timeout is the exception path rather
than the normal one. This exercises the whole round trip against a real
ovos-workshop skill on a real MiniCroft bus: the orchestrator's `.complete`
must arrive promptly, and the round must produce exactly one `§9.5`
`ovos.utterance.handled` — "A conformant orchestrator MUST emit exactly one
`ovos.utterance.handled` per entry-topic Message. Multiple emissions for one
utterance are malformed; zero is malformed."

The exactly-once assertion is the load-bearing half. The skill now emits a
genuine framework done-signal for its stop handler, and core's StopService no
longer synthesizes one; if both were to fire, the round would report two
terminals for one dispatch.
"""
import time
from threading import Event
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_spec_tools import SpecMessage
from ovos_utils import create_daemon
from ovos_utils.log import LOG

from ovoscope import get_minicroft

SPEC_UTTERANCE = SpecMessage.UTTERANCE.value

#: Generous next to the PIPELINE-1 §8.3 handler timeout the unresolved path
#: would otherwise wait out (five minutes by default), tight enough that a
#: parked dispatch cannot pass.
RESOLVE_WINDOW = 20.0


class TestTargetedStopResolves(TestCase):
    """A real `<skill_id>:stop` dispatch to a real workshop skill resolves."""

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-count.openvoiceos"
        # the translator bridges the spec `<skill_id>:stop` dispatch onto the
        # `<skill_id>.stop` subscription ovos-workshop registers
        self.minicroft = get_minicroft([self.skill_id],
                                       modernize=True, emit_legacy=True)

    def tearDown(self):
        self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def _start_counting(self, session):
        """Put the skill in `active_handlers` with a long-running intent, so
        the §4 cascade has a real stop target.

        Returns the LIVE session carried on the dispatch — a named session
        never lands in ``SessionManager.sessions``, so the §7.1 push is only
        visible on the round's own messages, not on the snapshot emitted here.
        """
        activated = Event()
        observed = {}

        def on_start(msg):
            if msg.data.get("skill_id") == self.skill_id:
                observed["session"] = Session.from_message(msg)
                activated.set()

        self.minicroft.bus.on(SpecMessage.INTENT_HANDLER_START.value, on_start)
        create_daemon(lambda: self.minicroft.bus.emit(Message(
            SPEC_UTTERANCE,
            {"utterances": ["count to infinity"], "lang": session.lang},
            {"session": session.serialize()})))
        self.assertTrue(activated.wait(RESOLVE_WINDOW),
                        "the count skill never started")
        self.minicroft.bus.remove(SpecMessage.INTENT_HANDLER_START.value, on_start)
        live = observed["session"]
        self.assertIn(self.skill_id,
                      [h["skill_id"] for h in live.active_handlers],
                      "the count skill must be an active handler for the "
                      "§4 cascade to have a targeted stop candidate")
        return live

    def test_stop_dispatch_resolves_with_exactly_one_terminal(self):
        session = Session("stop-resolution")
        session.lang = "en-US"
        session.pipeline = ["ovos-stop-pipeline-plugin-high",
                            "ovos-padatious-pipeline-plugin-high"]
        live = self._start_counting(session)

        stop_dispatched = Event()
        completes, errors, handled = [], [], []
        resolved_at = []
        started_at = []

        def on_dispatch(msg):
            started_at.append(time.monotonic())
            stop_dispatched.set()

        def on_complete(msg):
            if msg.data.get("intent_name") == "stop":
                resolved_at.append(time.monotonic())
                completes.append(msg)

        def on_error(msg):
            if msg.data.get("intent_name") == "stop":
                errors.append(msg)

        bus = self.minicroft.bus
        bus.on(f"{self.skill_id}:stop", on_dispatch)
        bus.on(SpecMessage.INTENT_HANDLER_COMPLETE.value, on_complete)
        bus.on(SpecMessage.INTENT_HANDLER_ERROR.value, on_error)
        bus.on(SpecMessage.UTTERANCE_HANDLED.value, handled.append)

        bus.emit(Message(SPEC_UTTERANCE,
                         {"utterances": ["stop"], "lang": live.lang},
                         {"session": live.serialize()}))

        deadline = time.monotonic() + RESOLVE_WINDOW
        while time.monotonic() < deadline and not completes and not errors:
            time.sleep(0.05)

        self.assertTrue(stop_dispatched.is_set(),
                        f"no {self.skill_id}:stop dispatch was emitted")
        self.assertEqual(errors, [],
                         "the stop handler must resolve as a normal return")
        self.assertEqual(
            len(completes), 1,
            f"§8.1: a dispatch produces exactly one terminal event; got "
            f"{len(completes)} ovos.intent.handler.complete for intent_name "
            f"'stop'. The skill emits the framework done-signal and the "
            f"orchestrator owns the trio — neither StopService nor anything "
            f"else may add a second.")

        elapsed = resolved_at[0] - started_at[0]
        self.assertLess(
            elapsed, RESOLVE_WINDOW,
            f"the stop dispatch took {elapsed:.1f}s to resolve; an unresolved "
            f"dispatch is only closed by the §8.3 timeout")

        # §9.5: exactly one end marker for the stop utterance. The count
        # utterance owns a second one, so wait out both and count the round's.
        time.sleep(2)
        self.assertEqual(
            len(handled), 2,
            f"§9.5: exactly one ovos.utterance.handled per entry-topic "
            f"Message — one for the interrupted count utterance and one for "
            f"the stop; got {[m.msg_type for m in handled]}")
