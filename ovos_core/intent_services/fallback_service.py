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
        config = config or Configuration().get("skills", {}).get("fallbacks", {})
        super().__init__(bus, config)
        self.registered_fallbacks = {}  # skill_id: priority
        self.bus.on("ovos.skills.fallback.register", self.handle_register_fallback)
        self.bus.on("ovos.skills.fallback.deregister", self.handle_deregister_fallback)

    def handle_register_fallback(self, message: Message):
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

    def shutdown(self):
        self.bus.remove("ovos.skills.fallback.register", self.handle_register_fallback)
        self.bus.remove("ovos.skills.fallback.deregister", self.handle_deregister_fallback)
