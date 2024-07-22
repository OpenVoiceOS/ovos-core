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
from functools import lru_cache
from threading import Lock
from typing import List, Tuple, Optional

from adapt.engine import IntentDeterminationEngine
from ovos_bus_client.message import Message
from ovos_bus_client.session import IntentContextManager as ContextManager, \
    SessionManager
from ovos_config.config import Configuration
from ovos_utils import flatten_list
from ovos_utils.log import LOG

from ovos_plugin_manager.templates.pipeline import IntentMatch


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


class AdaptService:
    """Intent service wrapping the Adapt intent Parser."""

    def __init__(self, config=None):
        core_config = Configuration()
        self.config = config or core_config.get("context", {})
        self.lang = core_config.get("lang", "en-us")
        langs = core_config.get('secondary_langs') or []
        if self.lang not in langs:
            langs.append(self.lang)

        self.engines = {lang: IntentDeterminationEngine()
                        for lang in langs}

        self.lock = Lock()
        self.max_words = 50  # if an utterance contains more words than this, don't attempt to match

        # TODO sanitize config option
        self.conf_high = self.config.get("conf_high") or 0.65
        self.conf_med = self.config.get("conf_med") or 0.45
        self.conf_low = self.config.get("conf_low") or 0.25

    @property
    def context_keywords(self):
        LOG.warning(
            "self.context_keywords has been deprecated and is unused, use self.config.get('keywords', []) instead")
        return self.config.get('keywords', [])

    @context_keywords.setter
    def context_keywords(self, val):
        LOG.warning(
            "self.context_keywords has been deprecated and is unused, edit mycroft.conf instead, setter will be ignored")

    @property
    def context_max_frames(self):
        LOG.warning(
            "self.context_keywords has been deprecated and is unused, use self.config.get('max_frames', 3) instead")
        return self.config.get('max_frames', 3)

    @context_max_frames.setter
    def context_max_frames(self, val):
        LOG.warning(
            "self.context_max_frames has been deprecated and is unused, edit mycroft.conf instead, setter will be ignored")

    @property
    def context_timeout(self):
        LOG.warning("self.context_timeout has been deprecated and is unused, use self.config.get('timeout', 2) instead")
        return self.config.get('timeout', 2)

    @context_timeout.setter
    def context_timeout(self, val):
        LOG.warning(
            "self.context_timeout has been deprecated and is unused, edit mycroft.conf instead, setter will be ignored")

    @property
    def context_greedy(self):
        LOG.warning(
            "self.context_greedy has been deprecated and is unused, use self.config.get('greedy', False) instead")
        return self.config.get('greedy', False)

    @context_greedy.setter
    def context_greedy(self, val):
        LOG.warning(
            "self.context_greedy has been deprecated and is unused, edit mycroft.conf instead, setter will be ignored")

    @property
    def context_manager(self):
        LOG.warning("context_manager has been deprecated, use Session.context instead")
        sess = SessionManager.get()
        return sess.context

    @context_manager.setter
    def context_manager(self, val):
        LOG.warning("context_manager has been deprecated, use Session.context instead")
        assert isinstance(val, ContextManager)
        sess = SessionManager.get()
        sess.context = val

    def update_context(self, intent):
        """Updates context with keyword from the intent.

        NOTE: This method currently won't handle one_of intent keywords
              since it's not using quite the same format as other intent
              keywords. This is under investigation in adapt, PR pending.

        Args:
            intent: Intent to scan for keywords
        """
        LOG.warning("update_context has been deprecated, use Session.context.update_context instead")
        sess = SessionManager.get()
        ents = [tag['entities'][0] for tag in intent['__tags__'] if 'entities' in tag]
        sess.context.update_context(ents)
    
    def match_high(self, utterances: List[str],
                         lang: Optional[str] = None,
                         message: Optional[Message] = None):
        """Intent matcher for high confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        match = self.match_intent(tuple(utterances), lang, message.serialize())
        if match and match.intent_data.get("confidence", 0.0) >= self.conf_high:
            return match
        return None

    def match_medium(self, utterances: List[str],
                           lang: Optional[str] = None,
                           message: Optional[Message] = None):
        """Intent matcher for medium confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        match = self.match_intent(tuple(utterances), lang, message.serialize())
        if match and match.intent_data.get("confidence", 0.0) >= self.conf_med:
            return match
        return None

    def match_low(self, utterances: List[str],
                        lang: Optional[str] = None,
                        message: Optional[Message] = None):
        """Intent matcher for low confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        match = self.match_intent(tuple(utterances), lang, message.serialize())
        if match and match.intent_data.get("confidence", 0.0) >= self.conf_low:
            return match
        return None

    @lru_cache(maxsize=3)  # NOTE - message is a string because of this
    def match_intent(self, utterances: Tuple[str],
                           lang: Optional[str] = None,
                           message: Optional[str] = None):
        """Run the Adapt engine to search for an matching intent.

        Args:
            utterances (iterable): utterances for consideration in intent 
                    matching. As a practical matter, a single utterance will 
                    be passed in most cases. But there are instances, such as
                    streaming STT that could pass multiple. Each utterance is 
                    represented as a tuple containing the raw, normalized, and
                    possibly other variations of the utterance.
            limit (float): confidence threshold for intent matching
            lang (str): language to use for intent matching
            message (Message): message to use for context

        Returns:
            Intent structure, or None if no match was found.
        """

        if message:
            message = Message.deserialize(message)
        sess = SessionManager.get(message)

        # we call flatten in case someone is sending the old style list of tuples
        utterances = flatten_list(utterances)

        utterances = [u for u in utterances if len(u.split()) < self.max_words]
        if not utterances:
            LOG.error(f"utterance exceeds max size of {self.max_words} words, skipping adapt match")
            return None

        lang = lang or self.lang
        if lang not in self.engines:
            return None

        best_intent = {}

        def take_best(intent, utt):
            nonlocal best_intent
            best = best_intent.get('confidence', 0.0) if best_intent else 0.0
            conf = intent.get('confidence', 0.0)
            skill = intent['intent_type'].split(":")[0]
            if best < conf and intent["intent_type"] not in sess.blacklisted_intents \
                    and skill not in sess.blacklisted_skills:
                best_intent = intent
                # TODO - Shouldn't Adapt do this?
                best_intent['utterance'] = utt

        for utt in utterances:
            try:
                intents = [i for i in self.engines[lang].determine_intent(
                    utt, 100,
                    include_tags=True,
                    context_manager=sess.context)]
                if intents:
                    utt_best = max(
                        intents, key=lambda x: x.get('confidence', 0.0)
                    )
                    take_best(utt_best, utt)

            except Exception as err:
                LOG.exception(err)

        if best_intent:
            ents = [tag['entities'][0] for tag in best_intent['__tags__'] if 'entities' in tag]

            sess.context.update_context(ents)

            skill_id = best_intent['intent_type'].split(":")[0]
            ret = IntentMatch(
                'Adapt', best_intent['intent_type'], best_intent, skill_id,
                best_intent['utterance']
            )
        else:
            ret = None
        return ret

    def register_vocab(self, start_concept, end_concept,
                       alias_of, regex_str, lang):
        """Register Vocabulary. DEPRECATED

        This method should not be used, it has been replaced by
        register_vocabulary().
        """
        self.register_vocabulary(start_concept, end_concept, alias_of,
                                 regex_str, lang)

    def register_vocabulary(self, entity_value, entity_type,
                            alias_of, regex_str, lang):
        """Register skill vocabulary as adapt entity.

        This will handle both regex registration and registration of normal
        keywords. if the "regex_str" argument is set all other arguments will
        be ignored.

        Argument:
            entity_value: the natural langauge word
            entity_type: the type/tag of an entity instance
            alias_of: entity this is an alternative for
        """
        if lang in self.engines:
            with self.lock:
                if regex_str:
                    self.engines[lang].register_regex_entity(regex_str)
                else:
                    self.engines[lang].register_entity(
                        entity_value, entity_type, alias_of=alias_of)

    def register_intent(self, intent):
        """Register new intent with adapt engine.

        Args:
            intent (IntentParser): IntentParser to register
        """
        for lang in self.engines:
            with self.lock:
                self.engines[lang].register_intent_parser(intent)

    def detach_skill(self, skill_id):
        """Remove all intents for skill.

        Args:
            skill_id (str): skill to process
        """
        with self.lock:
            for lang in self.engines:
                skill_parsers = [
                    p.name for p in self.engines[lang].intent_parsers if
                    p.name.startswith(skill_id)
                ]
                self.engines[lang].drop_intent_parser(skill_parsers)
            self._detach_skill_keywords(skill_id)
            self._detach_skill_regexes(skill_id)

    def _detach_skill_keywords(self, skill_id):
        """Detach all keywords registered with a particular skill.

        Arguments:
            skill_id (str): skill identifier
        """
        skill_id = _entity_skill_id(skill_id)

        def match_skill_entities(data):
            return data and data[1].startswith(skill_id)

        for lang in self.engines:
            self.engines[lang].drop_entity(match_func=match_skill_entities)

    def _detach_skill_regexes(self, skill_id):
        """Detach all regexes registered with a particular skill.

        Arguments:
            skill_id (str): skill identifier
        """
        skill_id = _entity_skill_id(skill_id)

        def match_skill_regexes(regexp):
            return any([r.startswith(skill_id)
                        for r in regexp.groupindex.keys()])

        for lang in self.engines:
            self.engines[lang].drop_regex_entity(match_func=match_skill_regexes)

    def detach_intent(self, intent_name):
        """Detatch a single intent

        Args:
            intent_name (str): Identifier for intent to remove.
        """
        for lang in self.engines:
            new_parsers = [
                p for p in self.engines[lang].intent_parsers if p.name != intent_name
            ]
            self.engines[lang].intent_parsers = new_parsers

    def shutdown(self):
        for lang in self.engines:
            parsers = self.engines[lang].intent_parsers
            self.engines[lang].drop_intent_parser(parsers)
