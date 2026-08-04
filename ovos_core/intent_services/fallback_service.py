# Copyright 2020 Mycroft AI Inc.
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
import operator
import threading
import time
from _thread import LockType
from collections import namedtuple
from typing import Callable, Dict, List, Optional, Tuple, Union

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.handler import HandlerLifecycle
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_config import Configuration
from ovos_plugin_manager.templates.pipeline import ConfidenceMatcherPipeline, IntentHandlerMatch
from ovos_utils import flatten_list
from ovos_utils.fakebus import FakeBus
from ovos_spec_tools import standardize_lang
from ovos_utils.log import LOG
from ovos_workshop.permissions import FallbackMode

FallbackRange = namedtuple('FallbackRange', ['start', 'stop'])


class FallbackService(ConfidenceMatcherPipeline):
    """Intent Service handling fallback skills."""

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None) -> None:
        config = config if config is not None else Configuration().get("skills", {}).get("fallbacks", {})
        super().__init__(bus, config)
        self.registered_fallbacks: Dict[str, int] = {}  # skill_id: priority
        self._registered_fallbacks_lock = threading.RLock()
        self._fallback_session_locks: Dict[str, Tuple[LockType, int]] = {}
        self._fallback_session_locks_lock = threading.Lock()
        # skill_id -> (start_handler, response_handler) wired for the
        # done-signal translation, so they can be removed on deregister
        self._lifecycle_handlers: Dict[str, Tuple[Callable, Callable]] = {}
        self.bus.on("ovos.skills.fallback.register", self.handle_register_fallback)
        self.bus.on("ovos.skills.fallback.deregister", self.handle_deregister_fallback)

    def _wire_lifecycle(self, skill_id: str) -> None:
        """Translate lifecycle done-signal for a fallback skill."""
        def _on_start(message: Message) -> None:
            HandlerLifecycle(self.bus, message, skill_id=skill_id,
                             handler_name=f"{skill_id}.fallback").start()

        def _on_response(message: Message) -> None:
            # .response is emitted whether or not a handler matched; the dispatch
            # itself completed either way (the result bool is orthogonal to the
            # handler lifecycle), so this is always ``complete``.
            HandlerLifecycle(self.bus, message, skill_id=skill_id,
                             handler_name=f"{skill_id}.fallback").complete()

        with self._registered_fallbacks_lock:
            if skill_id in self._lifecycle_handlers:
                return
            self.bus.on(f"ovos.skills.fallback.{skill_id}.start", _on_start)
            self.bus.on(f"ovos.skills.fallback.{skill_id}.response", _on_response)
            self._lifecycle_handlers[skill_id] = (_on_start, _on_response)

    def _unwire_lifecycle(self, skill_id: str) -> None:
        with self._registered_fallbacks_lock:
            handlers = self._lifecycle_handlers.pop(skill_id, None)
            if not handlers:
                return
            start_handler, response_handler = handlers
            self.bus.remove(f"ovos.skills.fallback.{skill_id}.start", start_handler)
            self.bus.remove(f"ovos.skills.fallback.{skill_id}.response", response_handler)

    def handle_register_fallback(self, message: Message) -> None:
        skill_id = message.data.get("skill_id")
        priority = message.data.get("priority")
        if priority is None:
            priority = 101

        # check if .conf is overriding the priority for this skill
        priority_overrides = self.config.get("fallback_priorities", {})
        with self._registered_fallbacks_lock:
            if skill_id in priority_overrides:
                new_priority = priority_overrides.get(skill_id)
                LOG.info(f"forcing {skill_id} fallback priority from {priority} to {new_priority}")
                self.registered_fallbacks[skill_id] = new_priority
            else:
                self.registered_fallbacks[skill_id] = priority

        # report this skill's fallback dispatch lifecycle as the framework
        # done-signal so an orchestrator can resolve it (no skill_id -> skip)
        if skill_id:
            self._wire_lifecycle(skill_id)

    def handle_deregister_fallback(self, message: Message) -> None:
        skill_id = message.data.get("skill_id")
        with self._registered_fallbacks_lock:
            if skill_id in self.registered_fallbacks:
                self.registered_fallbacks.pop(skill_id)
        self._unwire_lifecycle(skill_id)

    def _fallback_registry_snapshot(self) -> Dict[str, int]:
        """Return a stable fallback registry view for one match operation."""
        with self._registered_fallbacks_lock:
            return dict(self.registered_fallbacks)

    def _acquire_fallback_session_lock(self, session_id: str) -> LockType:
        """Serialize overlapping fallback polls for the same bus session."""
        with self._fallback_session_locks_lock:
            lock, users = self._fallback_session_locks.get(
                session_id, (threading.Lock(), 0))
            self._fallback_session_locks[session_id] = (lock, users + 1)
        lock.acquire()
        return lock

    def _release_fallback_session_lock(self, session_id: str,
                                       lock: LockType) -> None:
        lock.release()
        with self._fallback_session_locks_lock:
            current_lock, users = self._fallback_session_locks[session_id]
            if users == 1:
                self._fallback_session_locks.pop(session_id)
            else:
                self._fallback_session_locks[session_id] = (
                    current_lock, users - 1)

    def _fallback_allowed(self, skill_id: str) -> bool:
        """Checks if a skill_id is allowed to fallback

        - is the skill blacklisted from fallback
        - is fallback configured to only allow specific skills

        Args:
            skill_id (str): identifier of skill that wants to fallback.

        Returns:
            permitted (bool): True if skill can fallback
        """
        opmode = self.config.get("fallback_mode", FallbackMode.ACCEPT_ALL)
        if opmode == FallbackMode.BLACKLIST and skill_id in \
                self.config.get("fallback_blacklist", []):
            return False
        elif opmode == FallbackMode.WHITELIST and skill_id not in \
                self.config.get("fallback_whitelist", []):
            return False
        return True

    def _collect_fallback_skills(self, message: Message,
                                 fb_range: Optional[FallbackRange] = None) -> List[str]:
        """use the messagebus api to determine which skills have registered fallback handlers

        Individual skills respond to this request via the `can_answer` method
        """
        if fb_range is None:
            fb_range = FallbackRange(0, 100)
        sess = SessionManager.get(message)
        if sess is None:
            return []

        registered_fallbacks = self._fallback_registry_snapshot()
        pool = [
            skill_id for skill_id, priority in sorted(
                registered_fallbacks.items(), key=operator.itemgetter(1))
            if fb_range.start < priority <= fb_range.stop
            and skill_id not in (sess.blacklisted_skills or [])
            and self._fallback_allowed(skill_id)
        ]
        if not pool:
            return []

        session_id = sess.session_id
        session_lock = self._acquire_fallback_session_lock(session_id)
        responses: Dict[str, Optional[bool]] = {
            skill_id: None for skill_id in pool
        }
        response_event = threading.Event()
        response_lock = threading.Lock()
        handlers: Dict[str, Callable] = {}

        def make_handler(expected_skill_id: str) -> Callable:
            def handle_ack(msg: Message) -> None:
                response_session = SessionManager.get(msg)
                if response_session is None or \
                        response_session.session_id != session_id:
                    return
                skill_id = msg.data.get("skill_id")
                can_handle = msg.data.get("can_handle")
                valid = skill_id == expected_skill_id and \
                    isinstance(can_handle, bool)
                with response_lock:
                    if responses[expected_skill_id] is not None:
                        return
                    responses[expected_skill_id] = can_handle if valid else False
                response_event.set()

            return handle_ack

        try:
            LOG.info("checking for FallbackSkill candidates")
            for skill_id in pool:
                pong_type = f"{skill_id}.fallback.pong"
                handler = make_handler(skill_id)
                handlers[pong_type] = handler
                self.bus.on(pong_type, handler)

            query_data = {
                "utterances": list(message.data.get("utterances", [])),
                "lang": message.data.get("lang")
            }
            for skill_id in pool:
                # FALLBACK-1 section 6.1 defines this as a dotted-addressed
                # reply derived from the inbound utterance envelope.
                self.bus.emit(message.reply(
                    f"{skill_id}.fallback.ping", query_data))

            try:
                timeout = max(0.0, float(self.config.get(
                    "fallback_query_timeout", 0.5)))
            except (TypeError, ValueError):
                LOG.warning("Invalid fallback_query_timeout; using 0.5 seconds")
                timeout = 0.5
            deadline = time.monotonic() + timeout
            while True:
                response_event.clear()
                with response_lock:
                    ordered_responses = [responses[skill_id]
                                         for skill_id in pool]
                for index, response in enumerate(ordered_responses):
                    if response is None:
                        break
                    if response:
                        selected = pool[index]
                        LOG.info(f"{selected} will try to handle fallback")
                        return [selected]
                else:
                    return []

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    with response_lock:
                        final_responses = [responses[skill_id]
                                           for skill_id in pool]
                    for index, response in enumerate(final_responses):
                        if response:
                            return [pool[index]]
                    return []
                response_event.wait(remaining)
        finally:
            for pong_type, handler in handlers.items():
                self.bus.remove(pong_type, handler)
            self._release_fallback_session_lock(session_id, session_lock)

    def _fallback_range(self, utterances: List[str], lang: str,
                        message: Message, fb_range: FallbackRange) -> Optional[IntentHandlerMatch]:
        """Send fallback request for a specified priority range.

        Args:
            utterances (list): List of tuples,
                               utterances and normalized version
            lang (str): Langauge code
            message: Message for session context
            fb_range (FallbackRange): fallback order start and stop.

        Returns:
            PipelineMatch or None
        """
        lang = standardize_lang(lang)
        # we call flatten in case someone is sending the old style list of tuples
        utterances = flatten_list(utterances)
        message.data["utterances"] = utterances  # all transcripts
        message.data["lang"] = lang

        sess = SessionManager.get(message)
        if sess is None:
            return None
        # new style bus api
        available_skills = self._collect_fallback_skills(message, fb_range)
        registered_fallbacks = self._fallback_registry_snapshot()
        fallbacks = [(k, v) for k, v in registered_fallbacks.items()
                     if k in available_skills]
        sorted_handlers = sorted(fallbacks, key=operator.itemgetter(1))

        for skill_id, _priority in sorted_handlers:
            if skill_id in (sess.blacklisted_skills or []):
                LOG.debug(f"ignoring match, skill_id '{skill_id}' blacklisted by Session '{sess.session_id}'")
                continue

            if self._fallback_allowed(skill_id):
                return IntentHandlerMatch(
                    match_type=f"ovos.skills.fallback.{skill_id}.request",
                    match_data={"skill_id": skill_id,
                                "utterances": utterances,
                                "lang": lang},
                    utterance=utterances[0],
                    updated_session=sess
                )

        return None

    def match_high(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """High confidence/quality matchers."""
        return self._fallback_range(utterances, lang, message,
                                    FallbackRange(0, 5))

    def match_medium(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """General fallbacks."""
        return self._fallback_range(utterances, lang, message,
                                    FallbackRange(5, 90))

    def match_low(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """Low prio fallbacks with general matching such as chat-bot."""
        return self._fallback_range(utterances, lang, message,
                                    FallbackRange(90, 101))

    def shutdown(self) -> None:
        for skill_id in list(self._lifecycle_handlers):
            self._unwire_lifecycle(skill_id)
        self.bus.remove("ovos.skills.fallback.register", self.handle_register_fallback)
        self.bus.remove("ovos.skills.fallback.deregister", self.handle_deregister_fallback)
