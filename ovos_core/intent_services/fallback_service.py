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
from collections import namedtuple
from typing import Callable, Dict, List, Optional, Tuple, Union

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.handler import HandlerLifecycle
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ovos_core.intent_services._session_fold import registry_session_for_write
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
        # skill_id -> (start_handler, response_handler) wired for the
        # done-signal translation, so they can be removed on deregister
        self._lifecycle_handlers: Dict[str, Tuple[Callable, Callable]] = {}
        self._fallback_response_event = threading.Event()
        self.bus.on("ovos.skills.fallback.register", self.handle_register_fallback)
        self.bus.on("ovos.skills.fallback.deregister", self.handle_deregister_fallback)

    def _wire_lifecycle(self, skill_id: str) -> None:
        """Translate lifecycle done-signal for a fallback skill."""
        if skill_id in self._lifecycle_handlers:
            return

        def _on_start(message: Message) -> None:
            HandlerLifecycle(self.bus, message, skill_id=skill_id,
                             handler_name=f"{skill_id}.fallback").start()

        def _on_response(message: Message) -> None:
            # .response is emitted whether or not a handler matched; the dispatch
            # itself completed either way (the result bool is orthogonal to the
            # handler lifecycle), so this is always ``complete``.
            HandlerLifecycle(self.bus, message, skill_id=skill_id,
                             handler_name=f"{skill_id}.fallback").complete()

        self.bus.on(f"ovos.skills.fallback.{skill_id}.start", _on_start)
        self.bus.on(f"ovos.skills.fallback.{skill_id}.response", _on_response)
        self._lifecycle_handlers[skill_id] = (_on_start, _on_response)

    def _unwire_lifecycle(self, skill_id: str) -> None:
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
        if skill_id in self.registered_fallbacks:
            self.registered_fallbacks.pop(skill_id)
        self._unwire_lifecycle(skill_id)

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
        skill_ids = []  # skill_ids that already answered to ping
        fallback_skills = []  # skill_ids that want to handle fallback

        # incidental read of registry state (blacklist/active skills), no
        # wire echo from this method and not a lifecycle entry - resolve via
        # `registry_session_for_write` so an earlier registry-first write
        # this same turn (e.g. stop_service's disable_response_mode) isn't
        # clobbered by this call's fold (see ``_session_fold.py``).
        sess = registry_session_for_write(message)
        if sess is None:
            return fallback_skills
        # filter skills outside the fallback_range
        in_range = [s for s, p in self.registered_fallbacks.items()
                    if fb_range.start < p <= fb_range.stop
                    and s not in (sess.blacklisted_skills or [])]
        skill_ids += [s for s in self.registered_fallbacks if s not in in_range]

        # OVOS-CONVERSE-1 §4.2 round correlation: the round IS the utterance
        # lifecycle, named by context.utterance_id (OVOS-PIPELINE-1 §9.1.1).
        # The ping carries it by `forward` derivation and the pong carries it
        # back by `reply` derivation — no skill-side action.
        round_uid = message.context.get("utterance_id")
        round_session_id = sess.session_id

        def handle_ack(msg):
            skill_id = msg.data["skill_id"]

            # A pong that cannot prove which question it answers never decides a
            # round: discard pongs from an earlier (or foreign) lifecycle, or
            # from a foreign session. When the round itself is unnamed the
            # guard stands down, so a V0 caller that never entered through the
            # orchestrator behaves as before.
            if round_uid is not None and \
                    msg.context.get("utterance_id") != round_uid:
                LOG.debug(f"discarding stale fallback pong from '{skill_id}': "
                          f"utterance_id {msg.context.get('utterance_id')!r} "
                          f"does not match round {round_uid!r}")
                return
            ack_sess = Session.from_message(msg) if "session" in msg.context else None
            if ack_sess and ack_sess.session_id != round_session_id:
                LOG.debug(f"discarding cross-session fallback pong from '{skill_id}': "
                          f"session {ack_sess.session_id!r} does not match "
                          f"round session {round_session_id!r}")
                return

            if msg.data.get("can_handle", True):
                if skill_id in in_range:
                    fallback_skills.append(skill_id)
                    LOG.info(f"{skill_id} will try to handle fallback")
                else:
                    LOG.debug(f"{skill_id} is out of range, skipping")
            else:
                LOG.debug(f"{skill_id} does NOT WANT to try to handle fallback")
            skill_ids.append(skill_id)
            self._fallback_response_event.set()

        if in_range:  # no need to search if no skills available
            self.bus.on("ovos.skills.fallback.pong", handle_ack)

            LOG.info("checking for FallbackSkill candidates")
            message.data["range"] = (fb_range.start, fb_range.stop)
            # wait for all skills to acknowledge they want to answer fallback queries
            self.bus.emit(message.forward("ovos.skills.fallback.ping",
                                          message.data))
            start = time.time()
            while not all(s in skill_ids for s in self.registered_fallbacks) \
                    and time.time() - start <= 0.5:
                self._fallback_response_event.clear()
                self._fallback_response_event.wait(0.02)

            self.bus.remove("ovos.skills.fallback.pong", handle_ack)
        return fallback_skills

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

        # KEEP the plain fold here: this is a genuine wire-echo site (case
        # 2 of the fold-order contract) - the returned IntentHandlerMatch's
        # `updated_session=sess` is consumed by
        # ``IntentService._dispatch_match`` (service.py) and stamped back
        # onto the outgoing message, so this call must apply the message's
        # own declared session state, not bypass it.
        sess = SessionManager.get(message)
        if sess is None:
            return None
        # new style bus api
        available_skills = self._collect_fallback_skills(message, fb_range)
        fallbacks = [(k, v) for k, v in self.registered_fallbacks.items()
                     if k in available_skills]
        sorted_handlers = sorted(fallbacks, key=operator.itemgetter(1))

        for skill_id, prio in sorted_handlers:
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
