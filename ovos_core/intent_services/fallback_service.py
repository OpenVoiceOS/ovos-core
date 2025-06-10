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
import time
from collections import namedtuple
from typing import Optional, Dict, List, Union

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_config import Configuration
from ovos_plugin_manager.templates.pipeline import ConfidenceMatcherPipeline, IntentHandlerMatch
from ovos_utils import flatten_list
from ovos_utils.fakebus import FakeBus
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.log import LOG
from ovos_workshop.permissions import FallbackMode

FallbackRange = namedtuple('FallbackRange', ['start', 'stop'])


class FallbackService(ConfidenceMatcherPipeline):
    """Intent Service handling fallback skills."""

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None):
        """
                 Initializes the FallbackService with an optional message bus and configuration.
                 
                 Registers event handlers for fallback skill registration and deregistration, and sets up internal tracking for registered fallback skills and their priorities.
                 """
                 config = config or Configuration().get("skills", {}).get("fallbacks", {})
        super().__init__(bus, config)
        self.registered_fallbacks = {}  # skill_id: priority
        self.bus.on("ovos.skills.fallback.register", self.handle_register_fallback)
        self.bus.on("ovos.skills.fallback.deregister", self.handle_deregister_fallback)

    def handle_register_fallback(self, message: Message):
        """
        Handles the registration of a fallback skill by storing its priority.
        
        If a priority override for the skill exists in the configuration, it is applied; otherwise, the provided or default priority is used.
        """
        skill_id = message.data.get("skill_id")
        priority = message.data.get("priority") or 101

        # check if .conf is overriding the priority for this skill
        priority_overrides = self.config.get("fallback_priorities", {})
        if skill_id in priority_overrides:
            new_priority = priority_overrides.get(skill_id)
            LOG.info(f"forcing {skill_id} fallback priority from {priority} to {new_priority}")
            self.registered_fallbacks[skill_id] = new_priority
        else:
            self.registered_fallbacks[skill_id] = priority

    def handle_deregister_fallback(self, message: Message):
        skill_id = message.data.get("skill_id")
        if skill_id in self.registered_fallbacks:
            self.registered_fallbacks.pop(skill_id)

    def _fallback_allowed(self, skill_id: str) -> bool:
        """
        Determines whether a skill is permitted to handle fallback requests.
        
        A skill is allowed if it is not blacklisted when in blacklist mode, or if it is present in the whitelist when in whitelist mode. In accept-all mode, all skills are permitted.
        
        Args:
            skill_id: The identifier of the skill to check.
        
        Returns:
            True if the skill is allowed to handle fallback; otherwise, False.
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
                                 fb_range: FallbackRange = FallbackRange(0, 100)) -> List[str]:
        """
                                 Queries registered fallback skills via the message bus to identify those willing to handle a fallback request within a specified priority range.
                                 
                                 Args:
                                     message: The message triggering the fallback query, used for context and session information.
                                     fb_range: The priority range to filter fallback skills (default is 0 to 100).
                                 
                                 Returns:
                                     A list of skill IDs that have indicated willingness to handle the fallback request.
                                 """
        skill_ids = []  # skill_ids that already answered to ping
        fallback_skills = []  # skill_ids that want to handle fallback

        sess = SessionManager.get(message)
        # filter skills outside the fallback_range
        in_range = [s for s, p in self.registered_fallbacks.items()
                    if fb_range.start < p <= fb_range.stop
                    and s not in sess.blacklisted_skills]
        skill_ids += [s for s in self.registered_fallbacks if s not in in_range]

        def handle_ack(msg):
            skill_id = msg.data["skill_id"]
            if msg.data.get("can_handle", True):
                if skill_id in in_range:
                    fallback_skills.append(skill_id)
                    LOG.info(f"{skill_id} will try to handle fallback")
                else:
                    LOG.debug(f"{skill_id} is out of range, skipping")
            else:
                LOG.debug(f"{skill_id} does NOT WANT to try to handle fallback")
            skill_ids.append(skill_id)

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
                time.sleep(0.02)

            self.bus.remove("ovos.skills.fallback.pong", handle_ack)
        return fallback_skills

    def _fallback_range(self, utterances: List[str], lang: str,
                        message: Message, fb_range: FallbackRange) -> Optional[IntentHandlerMatch]:
        """
                        Attempts to find a fallback skill match within a specified priority range.
                        
                        Sends a fallback request for the given utterances and language, filtering available fallback skills by priority and session context. Returns an `IntentHandlerMatch` for the first eligible fallback skill, or `None` if no suitable skill is found.
                        
                        Args:
                            utterances: List of utterances to process.
                            lang: Language code for the utterances.
                            message: Message object containing session context.
                            fb_range: Priority range to consider for fallback skills.
                        
                        Returns:
                            An `IntentHandlerMatch` if a suitable fallback skill is found; otherwise, `None`.
                        """
        lang = standardize_lang_tag(lang)
        # we call flatten in case someone is sending the old style list of tuples
        utterances = flatten_list(utterances)
        message.data["utterances"] = utterances  # all transcripts
        message.data["lang"] = lang

        sess = SessionManager.get(message)
        # new style bus api
        available_skills = self._collect_fallback_skills(message, fb_range)
        fallbacks = [(k, v) for k, v in self.registered_fallbacks.items()
                     if k in available_skills]
        sorted_handlers = sorted(fallbacks, key=operator.itemgetter(1))

        for skill_id, prio in sorted_handlers:
            if skill_id in sess.blacklisted_skills:
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
        """
        Attempts to find a high-priority fallback skill match for the given utterances.
        
        Searches for a fallback skill within the highest priority range (0 to 5) that is eligible to handle the provided utterances and language, based on current configuration and session context.
        
        Args:
            utterances: List of user utterances to match.
            lang: Language code for the utterances.
            message: Message object containing context and session data.
        
        Returns:
            An IntentHandlerMatch if a suitable high-priority fallback skill is found; otherwise, None.
        """
        return self._fallback_range(utterances, lang, message,
                                    FallbackRange(0, 5))

    def match_medium(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """
        Attempts to find a fallback skill match within the medium-priority range.
        
        Returns an IntentHandlerMatch if a suitable fallback skill is found for the given utterances and language; otherwise, returns None.
        """
        return self._fallback_range(utterances, lang, message,
                                    FallbackRange(5, 90))

    def match_low(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """
        Attempts to find a low-priority fallback skill match for the given utterances.
        
        Searches for fallback skills within the lowest priority range (90–101), typically used for general-purpose or chat-bot style responses. Returns an `IntentHandlerMatch` if a suitable fallback skill is found, or `None` if no match is available.
        """
        return self._fallback_range(utterances, lang, message,
                                    FallbackRange(90, 101))

    def shutdown(self):
        self.bus.remove("ovos.skills.fallback.register", self.handle_register_fallback)
        self.bus.remove("ovos.skills.fallback.deregister", self.handle_deregister_fallback)
