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
"""An intent parsing service using the Adapt parser."""
from threading import Lock
from ovos_plugin_manager.utils.intent_context import ContextManagerFrame, ContextManager

from adapt.intent import IntentBuilder

from mycroft.configuration import Configuration
from ovos_plugin_manager.templates.intents import IntentMatch


def _entity_skill_id(skill_id):
    """Helper converting a skill id to the format used in entities.

    Arguments:
        skill_id (str): skill identifier

    Returns:
        (str) skill id on the format used by skill entities
    """
    skill_id = skill_id[:-1]
    skill_id = skill_id.replace('.', '_')
    skill_id = skill_id.replace('-', '_')
    return skill_id


class AdaptIntent(IntentBuilder):
    """Wrapper for IntentBuilder setting a blank name.

    Args:
        name (str): Optional name of intent
    """

    def __init__(self, name=''):
        super().__init__(name)


class AdaptService:
    """DEPRECATED - use adapt intent plugin directly instead"""

    def __init__(self, config):
        self.config = config
        self.lang = Configuration.get().get("lang", "en-us")
        self.engines = {}
        # Context related initializations
        self.context_keywords = self.config.get('keywords', [])
        self.context_max_frames = self.config.get('max_frames', 3)
        self.context_timeout = self.config.get('timeout', 2)
        self.context_greedy = self.config.get('greedy', False)
        self.context_manager = ContextManager(self.context_timeout)
        self.lock = Lock()
        LOG.error("AdaptService has been deprecated, stop importing this class!!!")

    def update_context(self, intent):
        """DEPRECATED - use adapt intent plugin directly instead"""
        LOG.error("AdaptService has been deprecated, stop importing this class!!!")

    def match_intent(self, utterances, lang=None, __=None):
        """DEPRECATED - use adapt intent plugin directly instead"""
        LOG.error("AdaptService has been deprecated, stop importing this class!!!")

    def register_vocab(self, start_concept, end_concept,
                       alias_of, regex_str, lang):
        """DEPRECATED - use adapt intent plugin directly instead"""
        LOG.error("AdaptService has been deprecated, stop importing this class!!!")

    def register_vocabulary(self, entity_value, entity_type,
                            alias_of, regex_str, lang):
        """DEPRECATED - use adapt intent plugin directly instead"""
        LOG.error("AdaptService has been deprecated, stop importing this class!!!")

    def register_intent(self, intent):
        """DEPRECATED - use adapt intent plugin directly instead"""
        LOG.error("AdaptService has been deprecated, stop importing this class!!!")

    def detach_skill(self, skill_id):
        """DEPRECATED - use adapt intent plugin directly instead"""
        LOG.error("AdaptService has been deprecated, stop importing this class!!!")

    def detach_intent(self, intent_name):
        """DEPRECATED - use adapt intent plugin directly instead"""
        LOG.error("AdaptService has been deprecated, stop importing this class!!!")