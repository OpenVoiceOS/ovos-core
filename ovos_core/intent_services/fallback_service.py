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
"""Intent service for Mycroft's fallback system."""
import operator
from collections import namedtuple
from typing import Optional

import time
from ovos_bus_client.session import SessionManager
from ovos_config import Configuration
from ovos_utils import flatten_list
from ovos_utils.log import LOG
from ovos_workshop.skills.fallback import FallbackMode

from ovos_plugin_manager.templates.pipeline import IntentMatch

FallbackRange = namedtuple('FallbackRange', ['start', 'stop'])


class FallbackService:
    """Intent Service handling fallback skills."""

    def __init__(self, bus):
        self.bus = bus
        self.fallback_config = Configuration()["skills"].get("fallbacks", {})
        self.registered_fallbacks = {}  # skill_id: priority
        self.bus.on("ovos.skills.fallback.register", self.handle_register_fallback)
        self.bus.on("ovos.skills.fallback.deregister", self.handle_deregister_fallback)

    def handle_register_fallback(self, message):
        skill_id = message.data.get("skill_id")
        priority = message.data.get("priority") or 101

        # check if .conf is overriding the priority for this skill
        priority_overrides = self.fallback_config.get("fallback_priorities", {})
        if skill_id in priority_overrides:
            new_priority = priority_overrides.get(skill_id)
            LOG.info(f"forcing {skill_id} fallback priority from {priority} to {new_priority}")
            self.registered_fallbacks[skill_id] = new_priority
        else:
            self.registered_fallbacks[skill_id] = priority

    def handle_deregister_fallback(self, message):
        skill_id = message.data.get("skill_id")
        if skill_id in self.registered_fallbacks:
            self.registered_fallbacks.pop(skill_id)

    def _fallback_allowed(self, skill_id):
        """Checks if a skill_id is allowed to fallback

        - is the skill blacklisted from fallback
        - is fallback configured to only allow specific skills

        Args:
            skill_id (str): identifier of skill that wants to fallback.

        Returns:
            permitted (bool): True if skill can fallback
        """
        opmode = self.fallback_config.get("fallback_mode", FallbackMode.ACCEPT_ALL)
        if opmode == FallbackMode.BLACKLIST and skill_id in \
                self.fallback_config.get("fallback_blacklist", []):
            return False
        elif opmode == FallbackMode.WHITELIST and skill_id not in \
                self.fallback_config.get("fallback_whitelist", []):
            return False
        return True

    def _collect_fallback_skills(self, message, fb_range=FallbackRange(0, 100)):
        """use the messagebus api to determine which skills have registered fallback handlers
        This includes all skills and external applications"""
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
                if skill_id in self.registered_fallbacks:
                    fallback_skills.append(skill_id)
                LOG.info(f"{skill_id} will try to handle fallback")
            else:
                LOG.info(f"{skill_id} will NOT try to handle fallback")
            skill_ids.append(skill_id)

        if in_range:  # no need to search if no skills available
            self.bus.on("ovos.skills.fallback.pong", handle_ack)

            LOG.info("checking for FallbackSkillsV2 candidates")
            # wait for all skills to acknowledge they want to answer fallback queries
            self.bus.emit(message.forward("ovos.skills.fallback.ping",
                                          message.data))
            start = time.time()
            while not all(s in skill_ids for s in self.registered_fallbacks) \
                    and time.time() - start <= 0.5:
                time.sleep(0.02)

            self.bus.remove("ovos.skills.fallback.pong", handle_ack)
        return fallback_skills

    def attempt_fallback(self, utterances, skill_id, lang, message):
        """Call skill and ask if they want to process the utterance.

        Args:
            utterances (list of tuples): utterances paired with normalized
                                         versions.
            skill_id: skill to query.
            lang (str): current language
            message (Message): message containing interaction info.

        Returns:
            handled (bool): True if handled otherwise False.
        """
        sess = SessionManager.get(message)
        if skill_id in sess.blacklisted_skills:
            LOG.debug(f"ignoring match, skill_id '{skill_id}' blacklisted by Session '{sess.session_id}'")
            return False
        if self._fallback_allowed(skill_id):
            fb_msg = message.reply(f"ovos.skills.fallback.{skill_id}.request",
                                   {"skill_id": skill_id,
                                    "utterances": utterances,
                                    "utterance": utterances[0],  # backwards compat, we send all transcripts now
                                    "lang": lang})
            result = self.bus.wait_for_response(fb_msg,
                                                f"ovos.skills.fallback.{skill_id}.response",
                                                timeout=self.fallback_config.get("max_skill_runtime", 10))
            if result and 'error' in result.data:
                error_msg = result.data['error']
                LOG.error(f"{skill_id}: {error_msg}")
                return False
            elif result is not None:
                return result.data.get('result', False)
            else:
                # abort any ongoing fallback
                # if skill crashed or returns False, all good
                # if it is just taking a long time, more than 1 fallback would end up answering
                self.bus.emit(message.forward("ovos.skills.fallback.force_timeout",
                                              {"skill_id": skill_id}))
                LOG.warning(f"{skill_id} took too long to answer, "
                            f'increasing "max_skill_runtime" in mycroft.conf might help alleviate this issue')
        return False

    def _fallback_range(self, utterances, lang, message, fb_range) -> Optional[IntentMatch]:
        """Send fallback request for a specified priority range.

        Args:
            utterances (list): List of tuples,
                               utterances and normalized version
            lang (str): Langauge code
            message: Message for session context
            fb_range (FallbackRange): fallback order start and stop.

        Returns:
            IntentMatch or None
        """
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
            result = self.attempt_fallback(utterances, skill_id, lang, message)
            if result:
                return IntentMatch(intent_service='Fallback',
                                   intent_type=None,
                                   intent_data={},
                                   skill_id=skill_id,
                                   utterance=utterances[0])
        return None

    def high_prio(self, utterances, lang, message) -> Optional[IntentMatch]:
        """Pre-padatious fallbacks."""
        return self._fallback_range(utterances, lang, message,
                                    FallbackRange(0, 5))

    def medium_prio(self, utterances, lang, message) -> Optional[IntentMatch]:
        """General fallbacks."""
        return self._fallback_range(utterances, lang, message,
                                    FallbackRange(5, 90))

    def low_prio(self, utterances, lang, message) -> Optional[IntentMatch]:
        """Low prio fallbacks with general matching such as chat-bot."""
        return self._fallback_range(utterances, lang, message,
                                    FallbackRange(90, 101))

    def shutdown(self):
        self.bus.remove("ovos.skills.fallback.register", self.handle_register_fallback)
        self.bus.remove("ovos.skills.fallback.deregister", self.handle_deregister_fallback)
