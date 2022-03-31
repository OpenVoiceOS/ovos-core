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
from mycroft.configuration import Configuration
from ovos_plugin_manager.intents import IntentMatch, IntentPriority, IntentEngine
from mycroft.messagebus.message import get_message_lang
from ovos_plugin_manager.intents import IntentMatch, IntentPriority, IntentEngine

FallbackRange = namedtuple('FallbackRange', ['start', 'stop'])


class FallbackService(IntentEngine):
    """Intent Service handling fallback skills."""

    def __init__(self, bus):
        config = Configuration.get().get("skills", {}).get("fallback") or {}
        super().__init__("ovos.intentbox.fallback", bus=bus, config=config)
        self.bus = bus

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
        msg = message.reply(
            'mycroft.skills.fallback',
            data={'utterance': utterances[0][0],
                  'lang': lang,
                  'fallback_range': (fb_range.start, fb_range.stop)}
        )
        response = self.bus.wait_for_response(msg, timeout=10)
        if response and response.data['handled']:
            skill_id = response.data.get("skill_id") or response.context.get("skill_id")
            ret = IntentMatch('Fallback', None, {}, skill_id)
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


class HighPrioFallbackService(IntentEngine):
    """Intent Service handling conversational skills."""

    def __init__(self, bus, service=None):
        super().__init__("ovos.intentbox.fallback.high", bus=bus, engine=service)
        self.config = Configuration.get()["skills"].get("fallbacks", {})

    def bind(self, bus, engine=None):
        self.bus = bus
        engine = engine or FallbackService(self.bus)
        self.engine = engine

    @property
    def priority(self):
        return IntentPriority.FALLBACK_HIGH

    def handle_utterance_message(self, message):
        utterances = message.data["utterances"]
        lang = get_message_lang(message)
        match = self.engine.high_prio(utterances, lang, message)
        return [match] if match else []


class MediumPrioFallbackService(IntentEngine):
    def __init__(self, bus, service=None):
        super().__init__("ovos.intentbox.fallback.medium", bus=bus, engine=service)
        self.config = Configuration.get()["skills"].get("fallbacks", {})

    def bind(self, bus, engine=None):
        self.bus = bus
        engine = engine or FallbackService(self.bus)
        self.engine = engine

    @property
    def priority(self):
        return IntentPriority.FALLBACK_MEDIUM

    def handle_utterance_message(self, message):
        utterances = message.data["utterances"]
        lang = get_message_lang(message)
        match = self.engine.medium_prio(utterances, lang, message)
        return [match] if match else []


class LowPrioFallbackService(IntentEngine):
    def __init__(self, bus, service=None):
        super().__init__("ovos.intentbox.fallback.low", bus=bus, engine=service)
        self.config = Configuration.get()["skills"].get("fallbacks", {})

    def bind(self, bus, engine=None):
        self.bus = bus
        engine = engine or FallbackService(self.bus)
        self.engine = engine

    @property
    def priority(self):
        return IntentPriority.FALLBACK_LOW

    def handle_utterance_message(self, message):
        utterances = message.data["utterances"]
        lang = get_message_lang(message)
        match = self.engine.low_prio(utterances, lang, message)
        return [match] if match else []

