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
from collections import namedtuple

from ovos_bus_client.util import get_message_lang
from ovos_config import Configuration

from mycroft.skills.intent_services.base import IntentService
from ovos_plugin_manager.templates.intents import IntentMatch

FallbackRange = namedtuple('FallbackRange', ['start', 'stop'])


class FallbackService(IntentService):
    """Intent Service handling fallback skills."""

    def __init__(self, bus):
        config = Configuration.get().get("skills", {}).get("fallback") or {}
        super().__init__(bus=bus, config=config)

    def _fallback_range(self, utterances, lang, message, fb_range):
        """Send fallback request for a specified priority range.

        Args:
            utterances (list): List of tuples,
                               utterances and normalized version
            lang (str): Language code
            message: Message for session context
            fb_range (FallbackRange): fallback order start and stop.

        Returns:
            IntentMatch or None
        """
        if not utterances:
            return None
        msg = message.reply(
            'mycroft.skills.fallback',
            data={'utterance': utterances[0][0],
                  'lang': lang,
                  'fallback_range': (fb_range.start, fb_range.stop)}
        )
        response = self.bus.wait_for_response(msg, timeout=10)
        if response and response.data['handled']:
            skill_id = response.data.get("skill_id") or response.context.get("skill_id")

            ret = IntentMatch(intent_service='Fallback',
                              intent_type="fallback",
                              intent_data={},
                              confidence=(100 - fb_range.stop) / 100,
                              utterance=utterances[0],
                              utterance_remainder="",
                              skill_id=skill_id)
        else:
            ret = None
        return ret

    def high_prio(self, utterances, lang, message):
        """Pre-padatious fallbacks."""
        return self._fallback_range(utterances, lang, message,
                                    FallbackRange(0, 5))

    def medium_prio(self, utterances, lang, message):
        """General fallbacks."""
        return self._fallback_range(utterances, lang, message,
                                    FallbackRange(5, 90))

    def low_prio(self, utterances, lang, message):
        """Low prio fallbacks with general matching such as chat-bot."""
        return self._fallback_range(utterances, lang, message,
                                    FallbackRange(90, 101))


class HighPrioFallbackService(IntentService):
    """Intent Service handling conversational skills."""

    def __init__(self, bus, engine=None):
        super().__init__(bus=bus)
        self.config = Configuration.get()["skills"].get("fallbacks", {})
        self.engine = engine or FallbackService(self.bus)

    def handle_utterance_message(self, message):
        utterances = message.data["utterances"]
        lang = get_message_lang(message)
        match = self.engine.high_prio(utterances, lang, message)
        return [match] if match else []


class MediumPrioFallbackService(IntentService):
    def __init__(self, bus, engine=None):
        super().__init__(bus=bus)
        self.config = Configuration.get()["skills"].get("fallbacks", {})
        self.engine = engine or FallbackService(self.bus)

    def handle_utterance_message(self, message):
        utterances = message.data["utterances"]
        lang = get_message_lang(message)
        match = self.engine.medium_prio(utterances, lang, message)
        return [match] if match else []


class LowPrioFallbackService(IntentService):
    def __init__(self, bus, engine=None):
        super().__init__(bus=bus)
        self.config = Configuration.get()["skills"].get("fallbacks", {})
        self.engine = engine or FallbackService(self.bus)

    def handle_utterance_message(self, message):
        utterances = message.data["utterances"]
        lang = get_message_lang(message)
        match = self.engine.low_prio(utterances, lang, message)
        return [match] if match else []
