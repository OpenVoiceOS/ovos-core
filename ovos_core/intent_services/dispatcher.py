# Copyright 2017 Mycroft AI Inc.
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
#
"""§7/§8 handler-lifecycle trio — dispatcher.

Emits ``ovos.intent.handler.start`` before each ``<skill_id>:<intent_name>``
dispatch and exactly one terminal (``complete``/``error``/timeout) after. The
framework done-signal (``mycroft.skill.handler.complete``/``.error``) is consumed
as the completion hint. A §8.3 timeout backstops every dispatch. The §9.5
``ovos.utterance.handled`` end-marker is NOT this class's concern — the
orchestrator's ``on_terminal`` callback is invoked after each §8 terminal.
"""
import threading
from typing import Callable, Dict, List, Optional

from ovos_bus_client.message import Message
from ovos_spec_tools import SpecMessage
from ovos_utils.log import LOG

#: default upper bound on handler execution before §8.3 timeout fires, seconds.
#: handlers are long-running by design (§6.5) so this is generous; set to 0 or a
#: negative value (config ``intents.handler_timeout``) to disable the timer.
DEFAULT_HANDLER_TIMEOUT = 5 * 60


class _InFlightDispatch:
    """A dispatch awaiting its §8 terminal."""

    __slots__ = ("skill_id", "intent_name", "dispatch_msg", "timer", "resolved")

    def __init__(self, skill_id: str, intent_name: str, dispatch_msg: Message):
        self.skill_id = skill_id
        self.intent_name = intent_name
        self.dispatch_msg = dispatch_msg
        self.timer: Optional[threading.Timer] = None
        self.resolved = False


class IntentDispatcher:
    """Owns the PIPELINE-1 §7 dispatch + §8 handler-lifecycle trio.

    Emits ``ovos.intent.handler.start`` before the ``<skill_id>:<intent_name>``
    dispatch and exactly one terminal (``complete``/``error``/timeout) after. The
    surrounding §6.1 orchestration — the §9.2 ``ovos.intent.matched`` notification,
    skill activation, session update — lives in
    ``IntentService._dispatch_match``, which hands a built dispatch Message to
    :meth:`dispatch`. This class wires its own bus observers for the framework
    done-signals (``mycroft.skill.handler.complete``/``.error``).
    """

    def __init__(self, bus, timeout: Optional[float] = DEFAULT_HANDLER_TIMEOUT,
                 on_terminal: Optional[Callable[[Message], None]] = None):
        self.bus = bus
        self.timeout = timeout
        # Called synchronously with the dispatch Message immediately AFTER each §8
        # terminal (complete/error/timeout) is emitted, so the orchestrator can emit
        # its §9.5 ovos.utterance.handled end-marker. Doing this in the same step
        # (rather than via a separate bus subscription) guarantees the terminal is
        # observed before the end-marker — otherwise a consumer subscribed to the
        # terminal could emit the end-marker before the terminal is recorded.
        self.on_terminal = on_terminal
        # session_id -> stack of _InFlightDispatch (LIFO for nested lifecycles)
        self._in_flight: Dict[str, List[_InFlightDispatch]] = {}
        self._lock = threading.Lock()
        # framework done-signals (legacy namespace; do NOT bridge to the spec trio)
        self.bus.on("mycroft.skill.handler.complete", self._on_skill_complete)
        self.bus.on("mycroft.skill.handler.error", self._on_skill_error)

    def shutdown(self):
        try:
            self.bus.remove("mycroft.skill.handler.complete", self._on_skill_complete)
            self.bus.remove("mycroft.skill.handler.error", self._on_skill_error)
        except Exception:
            LOG.exception("failed to remove done-signal handlers during shutdown")
        with self._lock:
            for stack in self._in_flight.values():
                for entry in stack:
                    entry.resolved = True
                    if entry.timer is not None:
                        entry.timer.cancel()
            self._in_flight.clear()

    # -- public API ------------------------------------------------------
    def dispatch(self, dispatch_msg: Message,
                 skill_id: Optional[str] = None,
                 intent_name: Optional[str] = None):
        """Dispatch a matched intent and own its §8 handler-lifecycle trio.

        Emits ``ovos.intent.handler.start`` (§8.1), the dispatch on
        ``<skill_id>:<intent_name>`` (§7), then exactly one terminal
        (``complete``/``error``/timeout) once the handler reports. The dispatch goes
        out asynchronously — this call does NOT block. The orchestrator reacts to the
        §8 terminal to emit its §9.5 ``ovos.utterance.handled`` end-marker.

        ``skill_id``/``intent_name`` default to the two halves of the dispatch
        topic; the orchestrator passes them explicitly from its own ``Match`` so
        they never come from the skill.
        """
        topic = dispatch_msg.msg_type
        if skill_id is None:
            skill_id = topic.split(":", 1)[0]
        if intent_name is None:
            intent_name = topic.split(":", 1)[-1]

        entry = _InFlightDispatch(skill_id, intent_name, dispatch_msg)
        sid = self._session_id(dispatch_msg)
        with self._lock:
            self._in_flight.setdefault(sid, []).append(entry)
            if self.timeout and self.timeout > 0:
                entry.timer = threading.Timer(self.timeout, self._on_timeout,
                                              args=(sid, entry))
                entry.timer.daemon = True
                entry.timer.start()

        # §8.1: start immediately before invoking (dispatching) the handler
        self._emit(SpecMessage.INTENT_HANDLER_START, dispatch_msg,
                   {"skill_id": skill_id, "intent_name": intent_name})
        # §7: the dispatch itself
        self.bus.emit(dispatch_msg)

    # -- emission helpers ------------------------------------------------
    @staticmethod
    def _session_id(message: Message) -> str:
        return (message.context.get("session") or {}).get("session_id", "default")

    def _emit(self, topic, dispatch_msg: Message, data: dict):
        """Emit a Message forwarded from the dispatch (§6.1 / §8 — context, incl.
        session, preserved unchanged via MSG-1 §5.1 ``forward``)."""
        self.bus.emit(dispatch_msg.forward(topic, data))

    def _notify_terminal(self, dispatch_msg: Message):
        """Tell the orchestrator a §8 terminal just fired so it can emit its §9.5
        end-marker. Called after the terminal is on the bus, so the terminal is
        always observed before the end-marker."""
        if self.on_terminal is not None:
            self.on_terminal(dispatch_msg)

    # -- terminal resolution ---------------------------------------------
    def _pop(self, sid: str, skill_id: Optional[str]) -> Optional[_InFlightDispatch]:
        """Pop the most-recent unresolved in-flight dispatch for this session
        whose ``skill_id`` matches (when known). LIFO so nested lifecycles
        resolve innermost-first (§6.5)."""
        with self._lock:
            stack = self._in_flight.get(sid)
            if not stack:
                return None
            for i in range(len(stack) - 1, -1, -1):
                entry = stack[i]
                if entry.resolved:
                    continue
                if skill_id and entry.skill_id != skill_id:
                    continue
                entry.resolved = True
                stack.pop(i)
                if not stack:
                    self._in_flight.pop(sid, None)
                if entry.timer is not None:
                    entry.timer.cancel()
                return entry
            return None

    def _on_skill_complete(self, message: Message):
        """Framework done-signal -> ``complete`` (§8.1)."""
        entry = self._pop(self._session_id(message), message.context.get("skill_id"))
        if entry is None:
            return
        try:
            self._emit(SpecMessage.INTENT_HANDLER_COMPLETE, entry.dispatch_msg,
                       {"skill_id": entry.skill_id, "intent_name": entry.intent_name})
        finally:
            self._notify_terminal(entry.dispatch_msg)

    def _on_skill_error(self, message: Message):
        """Framework done-signal -> ``error`` with the exception (§8.2)."""
        entry = self._pop(self._session_id(message), message.context.get("skill_id"))
        if entry is None:
            return
        exception = (message.data.get("exception")
                     or message.data.get("error")
                     or "handler raised an exception")
        try:
            self._emit(SpecMessage.INTENT_HANDLER_ERROR, entry.dispatch_msg,
                       {"skill_id": entry.skill_id,
                        "intent_name": entry.intent_name,
                        "exception": str(exception)})
        finally:
            self._notify_terminal(entry.dispatch_msg)

    def _on_timeout(self, sid: str, entry: _InFlightDispatch):
        """§8.3 — bound handler execution; on timeout emit ``error``."""
        with self._lock:
            if entry.resolved:
                return
            entry.resolved = True
            entry.timer = None
            stack = self._in_flight.get(sid)
            if stack and entry in stack:
                stack.remove(entry)
                if not stack:
                    self._in_flight.pop(sid, None)
        LOG.warning(f"handler timeout for {entry.skill_id}:{entry.intent_name} "
                    f"after {self.timeout}s; emitting ovos.intent.handler.error")
        try:
            self._emit(SpecMessage.INTENT_HANDLER_ERROR, entry.dispatch_msg,
                       {"skill_id": entry.skill_id,
                        "intent_name": entry.intent_name,
                        "exception": f"handler timed out after {self.timeout} seconds"})
        finally:
            self._notify_terminal(entry.dispatch_msg)
