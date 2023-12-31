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
"""Intent service wrapping padatious."""
import concurrent.futures
from functools import lru_cache
from os import path
from os.path import expanduser, isfile
from threading import Event
from time import time as get_time, sleep
from typing import List, Optional

import padatious
from padatious.match_data import MatchData as PadatiousIntent
from ovos_config.config import Configuration
from ovos_config.meta import get_xdg_base
from ovos_utils import flatten_list
from ovos_utils.log import LOG
from ovos_utils.xdg_utils import xdg_data_home

import ovos_core.intent_services
from ovos_bus_client.message import Message


class PadatiousMatcher:
    """Matcher class to avoid redundancy in padatious intent matching."""

    def __init__(self, service):
        self.service = service

    def _match_level(self, utterances, limit, lang=None):
        """Match intent and make sure a certain level of confidence is reached.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
            limit (float): required confidence level.
        """
        LOG.debug(f'Padatious Matching confidence > {limit}')
        # call flatten in case someone is sending the old style list of tuples
        utterances = flatten_list(utterances)
        lang = lang or self.service.lang
        padatious_intent = self.service.calc_intent(utterances, lang)
        if padatious_intent is not None and padatious_intent.conf > limit:
            skill_id = padatious_intent.name.split(':')[0]
            return ovos_core.intent_services.IntentMatch(
                'Padatious', padatious_intent.name,
                padatious_intent.matches, skill_id, padatious_intent.sent)

    def match_high(self, utterances, lang=None, message=None):
        """Intent matcher for high confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        return self._match_level(utterances, self.service.conf_high, lang)

    def match_medium(self, utterances, lang=None, message=None):
        """Intent matcher for medium confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        return self._match_level(utterances, self.service.conf_med, lang)

    def match_low(self, utterances, lang=None, message=None):
        """Intent matcher for low confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        return self._match_level(utterances, self.service.conf_low, lang)


class PadatiousService:
    """Service class for padatious intent matching."""

    def __init__(self, bus, config):
        self.padatious_config = config
        self.bus = bus

        core_config = Configuration()
        self.lang = core_config.get("lang", "en-us")
        langs = core_config.get('secondary_langs') or []
        if self.lang not in langs:
            langs.append(self.lang)

        self.conf_high = self.padatious_config.get("conf_high") or 0.95
        self.conf_med = self.padatious_config.get("conf_med") or 0.8
        self.conf_low = self.padatious_config.get("conf_low") or 0.5

        LOG.debug('Using Padatious intent parser.')
        intent_cache = self.padatious_config.get(
            'intent_cache') or f"{xdg_data_home()}/{get_xdg_base()}/intent_cache"
        self.containers = {
            lang: padatious.IntentContainer(path.join(expanduser(intent_cache), lang))
            for lang in langs}

        self.bus.on('padatious:register_intent', self.register_intent)
        self.bus.on('padatious:register_entity', self.register_entity)
        self.bus.on('detach_intent', self.handle_detach_intent)
        self.bus.on('detach_skill', self.handle_detach_skill)
        self.bus.on('mycroft.skills.initialized', self.train)

        self.finished_training_event = Event()
        self.finished_initial_train = False

        self.train_delay = self.padatious_config.get('train_delay', 4)
        self.train_time = get_time() + self.train_delay

        self.registered_intents = []
        self.registered_entities = []
        self.max_words = 50  # if an utterance contains more words than this, don't attempt to match

    def train(self, message=None):
        """Perform padatious training.

        Args:
            message (Message): optional triggering message
        """
        self.finished_training_event.clear()
        padatious_single_thread = self.padatious_config.get('single_thread', True)
        if message is None:
            single_thread = padatious_single_thread
        else:
            single_thread = message.data.get('single_thread',
                                             padatious_single_thread)
        for lang in self.containers:
            self.containers[lang].train(single_thread=single_thread)

        LOG.info('Training complete.')
        self.finished_training_event.set()
        if not self.finished_initial_train:
            self.bus.emit(Message('mycroft.skills.trained'))
            self.finished_initial_train = True

    def wait_and_train(self):
        """Wait for minimum time between training and start training."""
        if not self.finished_initial_train:
            return
        sleep(self.train_delay)
        if self.train_time < 0.0:
            return

        if self.train_time <= get_time() + 0.01:
            self.train_time = -1.0
            self.train()

    def __detach_intent(self, intent_name):
        """ Remove an intent if it has been registered.

        Args:
            intent_name (str): intent identifier
        """
        if intent_name in self.registered_intents:
            self.registered_intents.remove(intent_name)
            for lang in self.containers:
                self.containers[lang].remove_intent(intent_name)

    def handle_detach_intent(self, message):
        """Messagebus handler for detaching padatious intent.

        Args:
            message (Message): message triggering action
        """
        self.__detach_intent(message.data.get('intent_name'))

    def handle_detach_skill(self, message):
        """Messagebus handler for detaching all intents for skill.

        Args:
            message (Message): message triggering action
        """
        skill_id = message.data['skill_id']
        remove_list = [i for i in self.registered_intents if skill_id in i]
        for i in remove_list:
            self.__detach_intent(i)

    def _register_object(self, message, object_name, register_func):
        """Generic method for registering a padatious object.

        Args:
            message (Message): trigger for action
            object_name (str): type of entry to register
            register_func (callable): function to call for registration
        """
        file_name = message.data.get('file_name')
        samples = message.data.get("samples")
        name = message.data['name']

        LOG.debug('Registering Padatious ' + object_name + ': ' + name)

        if (not file_name or not isfile(file_name)) and not samples:
            LOG.error('Could not find file ' + file_name)
            return

        if not samples and isfile(file_name):
            with open(file_name) as f:
                samples = [l.strip() for l in f.readlines()]

        register_func(name, samples)

        self.train_time = get_time() + self.train_delay
        self.wait_and_train()

    def register_intent(self, message):
        """Messagebus handler for registering intents.

        Args:
            message (Message): message triggering action
        """
        lang = message.data.get('lang', self.lang)
        lang = lang.lower()
        if lang in self.containers:
            self.registered_intents.append(message.data['name'])
            try:
                self._register_object(message, 'intent',
                                      self.containers[lang].add_intent)
            except RuntimeError:
                name = message.data.get('name', "")
                # padacioso fails on reloading a skill, just ignore
                if name not in self.containers[lang].intent_samples:
                    raise

    def register_entity(self, message):
        """Messagebus handler for registering entities.

        Args:
            message (Message): message triggering action
        """
        lang = message.data.get('lang', self.lang)
        lang = lang.lower()
        if lang in self.containers:
            self.registered_entities.append(message.data)
            self._register_object(message, 'entity',
                                  self.containers[lang].add_entity)

    def calc_intent(self, utterances: List[str], lang: str = None) -> Optional[PadatiousIntent]:
        """
        Get the best intent match for the given list of utterances. Utilizes a
        thread pool for overall faster execution. Note that this method is NOT
        compatible with Padatious, but is compatible with Padacioso.
        @param utterances: list of string utterances to get an intent for
        @param lang: language of utterances
        @return:
        """
        if isinstance(utterances, str):
            utterances = [utterances]  # backwards compat when arg was a single string
        utterances = [u for u in utterances if len(u.split()) < self.max_words]
        if not utterances:
            LOG.error(f"utterance exceeds max size of {self.max_words} words, skipping padatious match")
            return None

        lang = lang or self.lang
        lang = lang.lower()
        if lang in self.containers:
            intent_container = self.containers.get(lang)
            intents = [_calc_padatious_intent(utt, intent_container) for utt in utterances]
            intents = [i for i in intents if i is not None]
            # select best
            if intents:
                return max(intents, key=lambda k: k.conf)


@lru_cache(maxsize=3)  # repeat calls under different conf levels wont re-run code
def _calc_padatious_intent(utt, intent_container) -> Optional[PadatiousIntent]:
    """
    Try to match an utterance to an intent in an intent_container
    @param args: tuple of (utterance, IntentContainer)
    @return: matched PadatiousIntent
    """
    try:
        intent = intent_container.calc_intent(utt)
        intent.sent = utt
        return intent
    except Exception as e:
        LOG.error(e)
