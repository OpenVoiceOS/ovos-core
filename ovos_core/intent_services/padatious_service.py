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
from multiprocessing import Pool
from os import path
from os.path import expanduser, isfile
from subprocess import call
from threading import Event
from typing import List, Optional, Tuple

from ovos_bus_client.message import Message
from ovos_config.config import Configuration
from ovos_utils.xdg_utils import xdg_data_home
from ovos_config.meta import get_xdg_base
from padacioso import IntentContainer as FallbackIntentContainer
from time import time as get_time, sleep

import ovos_core.intent_services
from ovos_utils import flatten_list
from ovos_utils.log import LOG

try:
    import padatious as _pd
    from padatious.match_data import MatchData as PadatiousIntent
except ImportError:
    _pd = None
    # padatious is optional, this class is just for compat

    class PadatiousIntent:
        """
        A set of data describing how a query fits into an intent
        Attributes:
            name (str): Name of matched intent
            sent (str): The input utterance associated with the intent
            conf (float): Confidence (from 0.0 to 1.0)
            matches (dict of str -> str): Key is the name of the entity and
                value is the extracted part of the sentence
        """

        def __init__(self, name, sent, matches=None, conf=0.0):
            self.name = name
            self.sent = sent
            self.matches = matches or {}
            self.conf = conf

        def __getitem__(self, item):
            return self.matches.__getitem__(item)

        def __contains__(self, item):
            return self.matches.__contains__(item)

        def get(self, key, default=None):
            return self.matches.get(key, default)

        def __repr__(self):
            return repr(self.__dict__)


class PadatiousMatcher:
    """Matcher class to avoid redundancy in padatious intent matching."""

    def __init__(self, service):
        self.service = service

        self.has_result = False
        self.ret = None
        self.conf = None

    def _match_level(self, utterances, limit, lang=None):
        """Match intent and make sure a certain level of confidence is reached.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
            limit (float): required confidence level.
        """
        # call flatten in case someone is sending the old style list of tuples
        utterances = flatten_list(utterances)
        if not self.has_result:
            lang = lang or self.service.lang
            LOG.debug(f'Padatious Matching confidence > {limit}')
            if _pd:
                LOG.info(f"Using legacy Padatious module")
                padatious_intent = self._legacy_padatious_match(utterances,
                                                                lang)
            else:
                padatious_intent = self.service.threaded_calc_intent(utterances,
                                                                     lang)
            if padatious_intent:
                skill_id = padatious_intent.name.split(':')[0]
                self.ret = ovos_core.intent_services.IntentMatch(
                    'Padatious', padatious_intent.name,
                    padatious_intent.matches, skill_id)
                self.conf = padatious_intent.conf
            self.has_result = True
        if self.conf and self.conf > limit:
            return self.ret

    def match_high(self, utterances, lang=None, __=None):
        """Intent matcher for high confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        return self._match_level(utterances, self.service.conf_high, lang)

    def match_medium(self, utterances, lang=None, __=None):
        """Intent matcher for medium confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        return self._match_level(utterances, self.service.conf_med, lang)

    def match_low(self, utterances, lang=None, __=None):
        """Intent matcher for low confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        return self._match_level(utterances, self.service.conf_low, lang)

    def _legacy_padatious_match(self, utterances: List[str],
                                lang: str) -> Optional[PadatiousIntent]:
        """
        Handle intent match with the Padatious intent parser.
        @param utterances: List of string utterances to evaluate
        @param lang: BCP-47 language of utterances
        @return: PadatiousIntent if matched, else None
        """
        padatious_intent = None
        for utt in utterances:
            intent = self.service.calc_intent(utt, lang)
            if intent:
                best = padatious_intent.conf if padatious_intent else 0.0
                if best < intent.conf:
                    padatious_intent = intent
                    padatious_intent.matches['utterance'] = utt
        return padatious_intent


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

        if self.is_regex_only:
            if not _pd:
                LOG.info('Padatious not installed. '
                         'Falling back to Padacioso')
                try:
                    call(['notify-send', 'Padatious not installed',
                          'Falling back to Padacioso'])
                except OSError:
                    pass
            LOG.debug('Using Padacioso intent parser.')
            self.containers = {lang: FallbackIntentContainer(
                self.padatious_config.get("fuzz"))
                               for lang in langs}
        else:
            intent_cache = self.padatious_config.get('intent_cache') or f"{xdg_data_home()}/{get_xdg_base()}/intent_cache"
            self.containers = {
                lang: _pd.IntentContainer(path.join(expanduser(intent_cache), lang))
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

    @property
    def is_regex_only(self):
        if not _pd:
            return True
        return self.padatious_config.get("regex_only") or False

    @property
    def threaded_inference(self):
        if not self.is_regex_only:
            # Padatious isn't thread-safe, so don't even try
            return False
        return self.padatious_config.get("threaded_inference", False)

    def train(self, message=None):
        """Perform padatious training.

        Args:
            message (Message): optional triggering message
        """
        self.finished_training_event.clear()
        if not self.is_regex_only:
            padatious_single_thread = self.padatious_config['single_thread']
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

        if not self.is_regex_only:
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
            self._register_object(message, 'intent',
                                  self.containers[lang].add_intent)

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

    def calc_intent(self, utt, lang=None):
        """Cached version of container calc_intent.

        This improves speed when called multiple times for different confidence
        levels.

        Args:
            utt (str): utterance to calculate best intent for
        """
        lang = lang or self.lang
        lang = lang.lower()
        if lang in self.containers:
            return _calc_padatious_intent((utt, self.containers[lang]))

    def threaded_calc_intent(self, utterances: List[str],
                             lang: str = None) -> Optional[PadatiousIntent]:
        """
        Get the best intent match for the given list of utterances. Utilizes a
        thread pool for overall faster execution. Note that this method is NOT
        compatible with Padatious, but is compatible with Padacioso.
        @param utterances: list of string utterances to get an intent for
        @param lang: language of utterances
        @return:
        """
        lang = lang or self.lang
        lang = lang.lower()
        if lang in self.containers:
            intent_container = self.containers.get(lang)
            if self.threaded_inference:
                with Pool() as pool:
                    intents = (intent for intent in
                               pool.imap_unordered(_calc_padatious_intent,
                                                   ((utt, intent_container)
                                                    for utt in utterances)))
                    pool.close()
                    pool.join()
            else:
                intents = (self.calc_intent(utt, lang) for utt in utterances)
            padatious_intent = None
            for intent in intents:
                if intent:
                    best = \
                        padatious_intent.conf if padatious_intent else 0.0
                    if intent.conf > best:  # this intent is the best so far
                        padatious_intent = intent
                        # TODO: This is for backwards-compat. but means that an
                        #   entity "utterance" will be overridden
                        padatious_intent.matches['utterance'] = \
                            padatious_intent.sent
                        if intent.conf == 1.0:
                            LOG.debug(f"Returning perfect match")
                            return intent
            return padatious_intent


def _calc_padatious_intent(*args) -> \
        Optional[PadatiousIntent]:
    """
    Try to match an utterance to an intent in an intent_container
    @param args: tuple of (utterance, IntentContainer)
    @return: matched PadatiousIntent
    """
    try:
        LOG.info(args)
        if len(args) == 1:
            args = args[0]
        utt = args[0]
        intent_container = args[1]
        intent = intent_container.calc_intent(utt)
        if isinstance(intent, dict):
            if "entities" in intent:
                intent["matches"] = intent.pop("entities")
            intent["sent"] = utt
            intent = PadatiousIntent(**intent)
        else:
            LOG.info(f"Overriding `intent.sent` with matched utterance")
            intent.sent = utt
        return intent
    except Exception as e:
        LOG.error(e)
