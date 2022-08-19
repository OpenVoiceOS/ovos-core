import re
import time
from itertools import chain
from threading import Lock, Event

from mycroft_bus_client.message import Message, dig_for_message

from mycroft.skills.intent_services.base import IntentMatch
from mycroft.skills.skill_data import CoreResources
from ovos_utils.enclosure.api import EnclosureAPI
from ovos_utils.log import LOG
from ovos_utils.messagebus import get_message_lang

EXTENSION_TIME = 10


class CommonQAService:
    """Intent Service handling common query skills.
    All common query skills answer and the best answer is selected
    This is in contrast to triggering best intent directly.
    """

    def __init__(self, bus):
        self.bus = bus
        self.skill_id = "common_query.openvoiceos"  # fake skill
        self.query_replies = {}  # cache of received replies
        self.query_extensions = {}  # maintains query timeout extensions
        self.lock = Lock()
        self.searching = Event()
        self.waiting = True
        self.answered = False
        self.enclosure = EnclosureAPI(self.bus, self.skill_id)
        self._vocabs = {}
        self.bus.on('question:query.response', self.handle_query_response)
        self.bus.on('common_query.question', self.handle_question)

    def voc_match(self, utterance, voc_filename, lang, exact=False):
        """Determine if the given utterance contains the vocabulary provided.

        By default the method checks if the utterance contains the given vocab
        thereby allowing the user to say things like "yes, please" and still
        match against "Yes.voc" containing only "yes". An exact match can be
        requested.

        The method checks the "res/text/{lang}" folder of mycroft-core.
        The result is cached to avoid hitting the disk each time the method is called.

        Args:
            utterance (str): Utterance to be tested
            voc_filename (str): Name of vocabulary file (e.g. 'yes' for
                                'res/text/en-us/yes.voc')
            lang (str): Language code, defaults to self.lang
            exact (bool): Whether the vocab must exactly match the utterance

        Returns:
            bool: True if the utterance has the given vocabulary it
        """
        match = False

        if lang not in self._vocabs:
            resources = CoreResources(language=lang)
            vocab = resources.load_vocabulary_file(voc_filename)
            self._vocabs[lang] = list(chain(*vocab))

        if utterance:
            if exact:
                # Check for exact match
                match = any(i.strip() == utterance
                            for i in self._vocabs[lang])
            else:
                # Check for matches against complete words
                match = any([re.match(r'.*\b' + i + r'\b.*', utterance)
                             for i in self._vocabs[lang]])

        return match

    def is_question_like(self, utterance, lang):
        # skip utterances with less than 3 words
        if len(utterance.split(" ")) < 3:
            return False
        # skip utterances meant for common play
        if self.voc_match(utterance, "common_play", lang):
            return False
        return True

    def match(self, utterances, lang, message):
        """Send common query request and select best response

        Args:
            utterances (list): List of tuples,
                               utterances and normalized version
            lang (str): Language code
            message: Message for session context
        Returns:
            IntentMatch or None
        """
        match = None
        utterance = utterances[0][0]
        if self.is_question_like(utterance, lang):
            message.data["lang"] = lang  # only used for speak
            message.data["utterance"] = utterance
            answered = self.handle_question(message)
            if answered:
                match = IntentMatch('CommonQuery', None, {}, None)
        return match

    def handle_question(self, message):
        """ Send the phrase to the CommonQuerySkills and prepare for handling
            the replies.
        """
        self.searching.set()
        self.waiting = True
        self.answered = False
        utt = message.data.get('utterance')
        self.enclosure.mouth_think()

        self.query_replies[utt] = []
        self.query_extensions[utt] = []
        LOG.info(f'Searching for {utt}')
        # Send the query to anyone listening for them
        msg = message.reply('question:query', data={'phrase': utt})
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id
        self.bus.emit(msg)

        self.timeout_time = time.time() + 1
        while self.searching.is_set():
            if not self.waiting or time.time() > self.timeout_time + 1:
                break
            time.sleep(0.2)

        # forcefully timeout if search is still going
        self._query_timeout(message)
        return self.answered

    def handle_query_response(self, message):
        search_phrase = message.data['phrase']
        skill_id = message.data['skill_id']
        searching = message.data.get('searching')
        answer = message.data.get('answer')

        # Manage requests for time to complete searches
        if searching:
            # extend the timeout by 5 seconds
            self.timeout_time = time.time() + EXTENSION_TIME
            # TODO: Perhaps block multiple extensions?
            if (search_phrase in self.query_extensions and
                    skill_id not in self.query_extensions[search_phrase]):
                self.query_extensions[search_phrase].append(skill_id)
        elif search_phrase in self.query_extensions:
            # Search complete, don't wait on this skill any longer
            if answer and search_phrase in self.query_replies:
                LOG.info(f'Answer from {skill_id}')
                self.query_replies[search_phrase].append(message.data)

            # Remove the skill from list of timeout extensions
            if skill_id in self.query_extensions[search_phrase]:
                self.query_extensions[search_phrase].remove(skill_id)

            # not waiting for any more skills
            if not self.query_extensions[search_phrase]:
                self._query_timeout(message)
        else:
            LOG.warning(f'{skill_id} Answered too slowly, will be ignored.')

    def _query_timeout(self, message):
        if not self.searching.is_set():
            return  # not searching, ignore timeout event
        self.searching.clear()

        # Prevent any late-comers from retriggering this query handler
        with self.lock:
            LOG.info('Timeout occurred check responses')
            search_phrase = message.data.get('phrase', "")
            if search_phrase in self.query_extensions:
                self.query_extensions[search_phrase] = []
            self.enclosure.mouth_reset()

            # Look at any replies that arrived before the timeout
            # Find response(s) with the highest confidence
            best = None
            ties = []
            if search_phrase in self.query_replies:
                for handler in self.query_replies[search_phrase]:
                    if not best or handler['conf'] > best['conf']:
                        best = handler
                        ties = []
                    elif handler['conf'] == best['conf']:
                        ties.append(handler)

            if best:
                if ties:
                    # TODO: Ask user to pick between ties or do it automagically
                    pass

                # invoke best match
                self.speak(best['answer'])
                LOG.info('Handling with: ' + str(best['skill_id']))
                cb = best.get('callback_data') or {}
                self.bus.emit(message.forward('question:action',
                                              data={'skill_id': best['skill_id'],
                                                    'phrase': search_phrase,
                                                    'callback_data': cb}))
                self.answered = True
            else:
                self.answered = False
            self.waiting = False
            if search_phrase in self.query_replies:
                del self.query_replies[search_phrase]
            if search_phrase in self.query_extensions:
                del self.query_extensions[search_phrase]

    def speak(self, utterance, message=None):
        """Speak a sentence.

        Args:
            utterance (str):        sentence mycroft should speak
        """
        # registers the skill as being active
        self.enclosure.register(self.skill_id)

        message = message or dig_for_message()
        lang = get_message_lang(message)
        data = {'utterance': utterance,
                'expect_response': False,
                'meta': {"skill": self.skill_id},
                'lang': lang}

        m = message.forward("speak", data) if message \
            else Message("speak", data)
        m.context["skill_id"] = self.skill_id
        self.bus.emit(m)
