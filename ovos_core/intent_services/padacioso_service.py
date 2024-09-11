"""Intent service wrapping padacioso."""
from functools import lru_cache
from os.path import isfile
from typing import List, Optional

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ovos_config.config import Configuration
from ovos_utils import flatten_list
from ovos_utils.log import LOG
from padacioso import IntentContainer as FallbackIntentContainer

from ovos_plugin_manager.templates.pipeline import IntentMatch


class PadaciosoIntent:
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


class PadaciosoService:
    """Service class for padacioso intent matching."""

    def __init__(self, bus, config):
        self.padacioso_config = config
        self.bus = bus

        core_config = Configuration()
        self.lang = core_config.get("lang", "en-us")
        langs = core_config.get('secondary_langs') or []
        if self.lang not in langs:
            langs.append(self.lang)

        self.conf_high = self.padacioso_config.get("conf_high") or 0.95
        self.conf_med = self.padacioso_config.get("conf_med") or 0.8
        self.conf_low = self.padacioso_config.get("conf_low") or 0.5
        self.workers = self.padacioso_config.get("workers") or 4

        try:
            self.containers = {
                lang: FallbackIntentContainer(self.padacioso_config.get("fuzz"),
                                              n_workers=self.workers)
                for lang in langs}
        except TypeError: # old padacioso version without n_workers kwarg
            self.containers = {
                lang: FallbackIntentContainer(self.padacioso_config.get("fuzz"))
                for lang in langs}

        self.bus.on('padatious:register_intent', self.register_intent)
        self.bus.on('padatious:register_entity', self.register_entity)
        self.bus.on('detach_intent', self.handle_detach_intent)
        self.bus.on('detach_skill', self.handle_detach_skill)

        self.registered_intents = []
        self.registered_entities = []
        self.max_words = 50  # if an utterance contains more words than this, don't attempt to match
        LOG.debug('Loaded Padacioso intent parser.')

    def _match_level(self, utterances, limit, lang=None,
                    message: Optional[Message] = None):
        """Match intent and make sure a certain level of confidence is reached.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
            limit (float): required confidence level.
        """
        LOG.debug(f'Padacioso Matching confidence > {limit}')
        # call flatten in case someone is sending the old style list of tuples
        utterances = flatten_list(utterances)
        lang = lang or self.lang
        padacioso_intent = self.calc_intent(utterances, lang, message)
        if padacioso_intent is not None and padacioso_intent.conf > limit:
            skill_id = padacioso_intent.name.split(':')[0]
            return IntentMatch(
                'Padacioso', padacioso_intent.name,
                padacioso_intent.matches, skill_id, padacioso_intent.sent)

    def match_high(self, utterances, lang=None, message=None):
        """Intent matcher for high confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        return self._match_level(utterances, self.conf_high, lang, message)

    def match_medium(self, utterances, lang=None, message=None):
        """Intent matcher for medium confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        return self._match_level(utterances, self.conf_med, lang, message)

    def match_low(self, utterances, lang=None, message=None):
        """Intent matcher for low confidence.

        Args:
            utterances (list of tuples): Utterances to parse, originals paired
                                         with optional normalized version.
        """
        return self._match_level(utterances, self.conf_low, lang, message)

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
        """Messagebus handler for detaching padacioso intent.

        Args:
            message (Message): message triggering action
        """
        self.__detach_intent(message.data.get('intent_name'))

    def __detach_entity(self, name, lang):
        """ Remove an entity.

        Args:
            entity name
            entity lang
        """
        if lang in self.containers:
            self.containers[lang].remove_entity(name)

    def handle_detach_skill(self, message):
        """Messagebus handler for detaching all intents for skill.

        Args:
            message (Message): message triggering action
        """
        skill_id = message.data['skill_id']
        remove_list = [i for i in self.registered_intents if skill_id in i]
        for i in remove_list:
            self.__detach_intent(i)
        skill_id_colon = skill_id + ":"
        for en in self.registered_entities:
            if en["name"].startswith(skill_id_colon):
                self.__detach_entity(en["name"], en["lang"])

    def _register_object(self, message, object_name, register_func):
        """Generic method for registering a padacioso object.

        Args:
            message (Message): trigger for action
            object_name (str): type of entry to register
            register_func (callable): function to call for registration
        """
        file_name = message.data.get('file_name')
        samples = message.data.get("samples")
        name = message.data['name']

        LOG.debug('Registering Padacioso ' + object_name + ': ' + name)

        if (not file_name or not isfile(file_name)) and not samples:
            LOG.error('Could not find file ' + file_name)
            return

        if not samples and isfile(file_name):
            with open(file_name) as f:
                samples = [l.strip() for l in f.readlines()]

        register_func(name, samples)

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

    def calc_intent(self, utterances: List[str], lang: str = None,
                    message: Optional[Message] = None) -> Optional[PadaciosoIntent]:
        """
        Get the best intent match for the given list of utterances. Utilizes a
        thread pool for overall faster execution. Note that this method is NOT
        compatible with Padacioso, but is compatible with Padacioso.
        @param utterances: list of string utterances to get an intent for
        @param lang: language of utterances
        @return:
        """
        if isinstance(utterances, str):
            utterances = [utterances]  # backwards compat when arg was a single string
        utterances = [u for u in utterances if len(u.split()) < self.max_words]
        if not utterances:
            LOG.error(f"utterance exceeds max size of {self.max_words} words, skipping padacioso match")
            return None

        lang = lang or self.lang
        lang = lang.lower()
        sess = SessionManager.get(message)
        if lang in self.containers:
            intent_container = self.containers.get(lang)
            intents = [_calc_padacioso_intent(utt, intent_container, sess)
                       for utt in utterances]
            intents = [i for i in intents if i is not None]
            # select best
            if intents:
                return max(intents, key=lambda k: k.conf)

    def shutdown(self):
        self.bus.remove('padatious:register_intent', self.register_intent)
        self.bus.remove('padatious:register_entity', self.register_entity)
        self.bus.remove('detach_intent', self.handle_detach_intent)
        self.bus.remove('detach_skill', self.handle_detach_skill)


@lru_cache(maxsize=3)  # repeat calls under different conf levels wont re-run code
def _calc_padacioso_intent(utt: str,
                           intent_container: FallbackIntentContainer,
                           sess: Session) -> \
        Optional[PadaciosoIntent]:
    """
    Try to match an utterance to an intent in an intent_container
    @param args: tuple of (utterance, IntentContainer)
    @return: matched PadaciosoIntent
    """
    try:
        intents = [i for i in intent_container.calc_intents(utt)
                   if i is not None
                   and i["name"] not in sess.blacklisted_intents
                   and i["name"].split(":")[0] not in sess.blacklisted_skills]
        if len(intents) == 0:
            return None
        best_conf = max(x.get("conf", 0) for x in intents if x.get("name"))
        ties = [i for i in intents if i.get("conf", 0) == best_conf]
        if not ties:
            return None
        # TODO - how to disambiguate ?
        intent = ties[0]
        if "entities" in intent:
            intent["matches"] = intent.pop("entities")
        intent["sent"] = utt
        intent = PadaciosoIntent(**intent)
        intent.sent = utt
        return intent
    except Exception as e:
        LOG.error(e)
