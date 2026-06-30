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
"""OVOS-PIPELINE-1 §7 / §8 — orchestrator-owned handler-lifecycle trio.

Validates that the orchestrator's ``IntentDispatcher`` drives the §6.1 matched
path:

- ``ovos.intent.handler.start`` (§8.1) before the dispatch Message goes out;
- exactly one terminal — ``complete`` on the framework done-signal, ``error`` on
  the framework error signal or on the §8.3 timeout;
- the ``exception`` field is populated on the error path (§8.2);
- ``context`` (incl. ``session``) preserved unchanged via ``forward``;
- the §8.3 timeout terminal (error) releases the waiting orchestrator;
- reserved-name dispatches (§7.0/§7.3) get the trio identically.

The dispatcher does NOT emit the §9.5 ``ovos.utterance.handled`` end-marker — it
only sets each in-flight entry's ``done`` event on its §8 terminal. The orchestrator
(``IntentService``) blocks on that and emits the single end-marker itself, uniformly
with the no-match and cancel paths (see ``TestDispatchFromMatch``).
"""
# ruff: noqa: RUF023
import time
import unittest
from collections import defaultdict
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch
from ovos_spec_tools import SpecMessage
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.service import IntentService
from ovos_core.intent_services.dispatcher import IntentDispatcher

START = SpecMessage.INTENT_HANDLER_START.value
COMPLETE = SpecMessage.INTENT_HANDLER_COMPLETE.value
ERROR = SpecMessage.INTENT_HANDLER_ERROR.value
HANDLED = SpecMessage.UTTERANCE_HANDLED.value
# the framework done-signal the orchestrator observes (legacy namespace)
SKILL_COMPLETE = "mycroft.skill.handler.complete"
SKILL_ERROR = "mycroft.skill.handler.error"


def _skill_complete(dispatch_msg):
    """The framework's normal-completion signal (forwarded from the dispatch)."""
    return dispatch_msg.forward(SKILL_COMPLETE, {"name": "handler"})


class _Recorder:
    """Capture the orchestrator-emitted topics (+ dispatch) in bus order.

    Subscribes to the ``"message"`` aggregate (as the real bus / ovoscope harness
    do) rather than to specific topics: the FakeBus namespace bridge mirrors a
    counterpart onto specific-topic subscribers but NOT onto the ``"message"``
    aggregate, so a single emission is recorded once — matching what a
    spec-namespace consumer observing the wire actually sees."""

    _TRACKED = (START, COMPLETE, ERROR, HANDLED)

    def __init__(self, bus, dispatch_topic=None):
        self.msgs = []
        self._tracked = set(self._TRACKED)
        if dispatch_topic:
            self._tracked.add(dispatch_topic)
        bus.on("message", self._on_message)

    def _on_message(self, serialized):
        msg = Message.deserialize(serialized)
        if msg.msg_type in self._tracked:
            self.msgs.append((msg.msg_type, msg))

    def topics(self):
        return [t for t, _ in self.msgs]

    def by_topic(self, topic):
        return [m for t, m in self.msgs if t == topic]


def _dispatch_msg(skill_id="test.skill", intent_name="do", session_id="s1"):
    sess = Session(session_id)
    return Message(f"{skill_id}:{intent_name}",
                   {"utterance": "hello", "lang": "en-US"},
                   {"skill_id": skill_id, "session": sess.serialize(),
                    "source": "B", "destination": "A"})


class TestIntentDispatcher(unittest.TestCase):

    def setUp(self):
        self.bus = FakeBus()
        self.rec = _Recorder(self.bus, dispatch_topic="test.skill:do")
        self.disp = IntentDispatcher(self.bus, timeout=0)  # timer off by default

    def tearDown(self):
        self.disp.shutdown()

    def test_start_before_dispatch(self):
        self.disp.dispatch(_dispatch_msg(), "test.skill", "do")
        # §8.1 start, then the §7 dispatch — in that order
        self.assertEqual(self.rec.topics()[:2], [START, "test.skill:do"])

    def test_start_payload(self):
        self.disp.dispatch(_dispatch_msg(), "test.skill", "do")
        self.assertEqual(self.rec.by_topic(START)[0].data,
                         {"skill_id": "test.skill", "intent_name": "do"})

    def test_intent_name_defaults_from_topic(self):
        self.disp.dispatch(_dispatch_msg())
        self.assertEqual(self.rec.by_topic(START)[0].data,
                         {"skill_id": "test.skill", "intent_name": "do"})

    def test_reserved_name_dispatch_gets_trio(self):
        # §7.0/§7.3 polymorphism: a reserved-name dispatch (e.g. <skill>:stop) is
        # a dispatch like any other -> it gets the trio, no special-casing.
        rec = _Recorder(self.bus, dispatch_topic="stop.openvoiceos:stop")
        msg = _dispatch_msg(skill_id="stop.openvoiceos", intent_name="stop")
        self.disp.dispatch(msg, "stop.openvoiceos", "stop")
        self.assertEqual(rec.topics()[:2], [START, "stop.openvoiceos:stop"])
        self.bus.emit(msg.forward(SKILL_COMPLETE, {"name": "h"}))
        self.assertEqual(len(rec.by_topic(COMPLETE)), 1)

    def test_complete_on_done_signal(self):
        msg = _dispatch_msg()
        self.disp.dispatch(msg, "test.skill", "do")
        self.bus.emit(_skill_complete(msg))
        comps = self.rec.by_topic(COMPLETE)
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0].data,
                         {"skill_id": "test.skill", "intent_name": "do"})
        self.assertEqual(self.rec.by_topic(ERROR), [])
        # the dispatcher does NOT emit ovos.utterance.handled -- the §9.5 end-marker
        # is the orchestrator's (emitted in reaction to this terminal).
        self.assertEqual(self.rec.by_topic(HANDLED), [])

    def test_exactly_one_terminal_on_repeated_done_signal(self):
        msg = _dispatch_msg()
        self.disp.dispatch(msg, "test.skill", "do")
        self.bus.emit(_skill_complete(msg))
        self.bus.emit(_skill_complete(msg))  # duplicate / nested signal
        self.assertEqual(len(self.rec.by_topic(COMPLETE)), 1)  # exactly one terminal
        self.assertEqual(self.rec.by_topic(HANDLED), [])  # dispatcher emits no end-marker

    def test_no_echo_loop_from_bridged_spec_complete(self):
        # if the bus bridges the orchestrator's spec complete back to the legacy
        # done-signal, the resolved-guard must keep the terminal count at one.
        msg = _dispatch_msg()
        self.disp.dispatch(msg, "test.skill", "do")
        self.bus.emit(_skill_complete(msg))
        # simulate the bridged echo arriving as another legacy done-signal
        self.disp._on_skill_complete(_skill_complete(msg))
        self.assertEqual(len(self.rec.by_topic(COMPLETE)), 1)

    def test_error_on_done_signal_with_exception(self):
        msg = _dispatch_msg()
        self.disp.dispatch(msg, "test.skill", "do")
        self.bus.emit(msg.forward(SKILL_ERROR, {"exception": "RuntimeError: boom"}))
        errs = self.rec.by_topic(ERROR)
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0].data["skill_id"], "test.skill")
        self.assertEqual(errs[0].data["intent_name"], "do")
        self.assertEqual(errs[0].data["exception"], "RuntimeError: boom")
        self.assertEqual(self.rec.by_topic(COMPLETE), [])

    def test_trio_terminal_ordering(self):
        msg = _dispatch_msg()
        self.disp.dispatch(msg, "test.skill", "do")
        self.bus.emit(_skill_complete(msg))
        trio = [t for t in self.rec.topics() if t in (START, COMPLETE, ERROR)]
        self.assertEqual(trio, [START, COMPLETE])

    def test_context_session_preserved(self):
        msg = _dispatch_msg(session_id="abc123")
        self.disp.dispatch(msg, "test.skill", "do")
        self.bus.emit(_skill_complete(msg))
        for topic in (START, COMPLETE):
            m = self.rec.by_topic(topic)[0]
            self.assertEqual(m.context["session"]["session_id"], "abc123")
            self.assertEqual(m.context.get("skill_id"), "test.skill")

    def test_nested_lifecycles_lifo(self):
        msg_outer = _dispatch_msg(intent_name="outer")
        msg_inner = _dispatch_msg(intent_name="inner")
        self.disp.dispatch(msg_outer, "test.skill", "outer")
        self.disp.dispatch(msg_inner, "test.skill", "inner")
        self.bus.emit(_skill_complete(msg_inner))  # inner completes first
        self.bus.emit(_skill_complete(msg_outer))  # outer second
        comps = [m.data["intent_name"] for m in self.rec.by_topic(COMPLETE)]
        self.assertEqual(comps, ["inner", "outer"])

    def test_timeout_emits_error(self):
        disp = IntentDispatcher(self.bus, timeout=0.2)
        try:
            disp.dispatch(_dispatch_msg(), "test.skill", "do")
            # deterministic: poll for the §8.3 terminal rather than a fixed sleep
            deadline = time.time() + 5
            while not self.rec.by_topic(ERROR) and time.time() < deadline:
                time.sleep(0.02)
            errs = self.rec.by_topic(ERROR)
            self.assertEqual(len(errs), 1)
            self.assertIn("timed out", errs[0].data["exception"])
            # the dispatcher itself emits no §9.5 ovos.utterance.handled end-marker
            self.assertEqual(self.rec.by_topic(HANDLED), [])
        finally:
            disp.shutdown()

    def test_timeout_does_not_double_fire_if_skill_reports(self):
        disp = IntentDispatcher(self.bus, timeout=0.3)
        try:
            msg = _dispatch_msg()
            disp.dispatch(msg, "test.skill", "do")
            self.bus.emit(_skill_complete(msg))  # reports before timeout
            time.sleep(0.5)
            self.assertEqual(len(self.rec.by_topic(COMPLETE)), 1)
            self.assertEqual(self.rec.by_topic(ERROR), [])
        finally:
            disp.shutdown()


class TestDispatchFromMatch(unittest.TestCase):
    """The dispatch + trio must fire from the orchestrator's match path."""

    def _make_service(self):
        bus = FakeBus()
        svc = IntentService.__new__(IntentService)
        svc.bus = bus
        svc.config = {}
        svc.pipeline_plugins = {}
        svc._deactivations = defaultdict(list)
        ut = MagicMock(); ut.transform.side_effect = lambda u, c: (u, c)
        svc.utterance_plugins = ut
        mt = MagicMock(); mt.transform.side_effect = lambda c: c
        svc.metadata_plugins = mt
        it = MagicMock(); it.transform.side_effect = lambda i: i
        svc.intent_plugins = it
        svc.status = MagicMock()
        # mirror IntentService.__init__: the dispatcher notifies the orchestrator on
        # each §8 terminal, which emits the §9.5 end-marker
        svc.intent_dispatcher = IntentDispatcher(
            bus, timeout=0, on_terminal=svc._emit_utterance_handled)
        return svc, bus

    @staticmethod
    def _report_complete(bus):
        """Make the dispatched handler report its framework done-signal so the
        dispatcher emits its §8 terminal (which drives the orchestrator's §9.5
        end-marker). FakeBus is in-thread, so this all resolves synchronously."""
        bus.on("test.skill:do",
               lambda m: bus.emit(m.forward(SKILL_COMPLETE, {"name": "h"})))

    def test_start_before_dispatch(self):
        svc, bus = self._make_service()
        order = []
        bus.on(START, lambda m: order.append("start"))
        bus.on("test.skill:do", lambda m: order.append("dispatch"))
        self._report_complete(bus)

        match = IntentHandlerMatch(match_type="test.skill:do",
                                   match_data={}, skill_id="test.skill",
                                   utterance="hello")
        msg = Message(SpecMessage.UTTERANCE,
                      {"utterances": ["hello"]},
                      {"session": Session("s1").serialize()})
        svc._dispatch_match(match, msg, "en-US", pipeline_id="p1")
        self.assertEqual(order[:2], ["start", "dispatch"])
        svc.intent_dispatcher.shutdown()

    def test_orchestrator_emits_handled_on_terminal(self):
        # §9.5: the orchestrator (not the dispatcher) owns ovos.utterance.handled;
        # it reacts to the §8 handler-complete terminal and emits exactly one marker.
        svc, bus = self._make_service()
        handled = []
        bus.on(HANDLED, lambda m: handled.append(m))
        self._report_complete(bus)

        match = IntentHandlerMatch(match_type="test.skill:do",
                                   match_data={}, skill_id="test.skill",
                                   utterance="hello")
        msg = Message(SpecMessage.UTTERANCE,
                      {"utterances": ["hello"]},
                      {"session": Session("s1").serialize()})
        svc._dispatch_match(match, msg, "en-US", pipeline_id="p1")
        self.assertEqual(len(handled), 1)
        self.assertEqual(handled[0].data, {})
        svc.intent_dispatcher.shutdown()


if __name__ == "__main__":
    unittest.main()
