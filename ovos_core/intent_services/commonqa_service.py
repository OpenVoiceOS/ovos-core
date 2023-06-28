import re
import time
from dataclasses import dataclass
from itertools import chain
from threading import Event
from typing import Dict

from ovos_bus_client.apis.enclosure import EnclosureAPI
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_bus_client.util import get_message_lang
from ovos_config.config import Configuration
from ovos_utils import flatten_list
from ovos_utils.log import LOG, log_deprecation

import ovos_core.intent_services
from ovos_workshop.resource_files import CoreResources


@dataclass
class Query:
    session_id: str
    query: str
    replies: list = None
    extensions: list = None
    queried_skills: list = None
    query_time: float = time.time()
    timeout_time: float = time.time() + 1
    responses_gathered: Event = Event()
    completed: Event = Event()
    answered: bool = False
    selected_skill: str = ""


class CommonQAService:
    def __init__(self, bus):
        self.bus = bus
        self.skill_id = "common_query.openvoiceos"  # fake skill
        self.active_queries: Dict[str, Query] = dict()
        self.enclosure = EnclosureAPI(self.bus, self.skill_id)
        self._vocabs = {}
        self.common_query_skills = None
        config = Configuration().get('skills', {}).get("common_query") or dict()
        self._extension_time = config.get('extension_time') or 3
        CommonQAService._EXTENSION_TIME = self._extension_time
        self._min_response_wait = config.get('min_response_wait') or 2
        self._max_time = config.get('max_response_wait') or 6  # regardless of extensions
        self.bus.on('question:query.response', self.handle_query_response)
        self.bus.on('common_query.question', self.handle_question)
        self.bus.on('ovos.common_query.pong', self.handle_skill_pong)
        self.bus.emit(Message("ovos.common_query.ping"))  # gather any skills that already loaded

    def handle_skill_pong(self, message: Message):
        """ track running common query skills """
        if self.common_query_skills is None:
            self.common_query_skills = []
        if message.data["skill_id"] not in self.common_query_skills:
            self.common_query_skills.append(message.data["skill_id"])

    def voc_match(self, utterance: str, voc_filename: str, lang: str,
                  exact: bool = False) -> bool:
        """
        Determine if the given utterance contains the vocabulary provided.

        By default, the method checks if the utterance contains the given vocab
        thereby allowing the user to say things like "yes, please" and still
        match against "Yes.voc" containing only "yes". An exact match can be
        requested.

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

    def is_question_like(self, utterance: str, lang: str):
        """
        Check if the input utterance looks like a question for CommonQuery
        @param utterance: user input to evaluate
        @param lang: language of input
        @return: True if input might be a question to handle here
        """
        # skip utterances with less than 3 words
        if len(utterance.split(" ")) < 3:
            return False
        # skip utterances meant for common play
        if self.voc_match(utterance, "common_play", lang):
            return False
        return True

    def match(self, utterances: str, lang: str, message: Message):
        """
        Send common query request and select best response

        Args:
            utterances (list): List of tuples,
                               utterances and normalized version
            lang (str): Language code
            message: Message for session context
        Returns:
            IntentMatch or None
        """
        # we call flatten in case someone is sending the old style list of tuples
        utterances = flatten_list(utterances)
        match = None

        # exit early if no common query skills are installed
        if self.common_query_skills is None:
            # when None means a older ovos-workshop is in use
            LOG.warning(
                "you seem to be running an old ovos-workshop version, CommonQuery will wait minimum 2 seconds for skill responses")
        elif not self.common_query_skills:
            LOG.info("No Commonquery skills to search")
            return None

        for utterance in utterances:
            if self.is_question_like(utterance, lang):
                message.data["lang"] = lang  # only used for speak
                message.data["utterance"] = utterance
                answered, skill_id = self.handle_question(message)
                if answered:
                    match = ovos_core.intent_services.IntentMatch('CommonQuery',
                                                                  None, {},
                                                                  skill_id,
                                                                  utterance)
                break
        return match

    def handle_question(self, message: Message):
        """
        Send the phrase to CommonQuerySkills and prepare for handling replies.
        """
        utt = message.data.get('utterance')
        sid = SessionManager.get(message).session_id
        # TODO: Why are defaults not creating new objects on init?
        query = Query(session_id=sid, query=utt, replies=[], extensions=[],
                      query_time=time.time(), timeout_time=time.time() + 1,
                      responses_gathered=Event(), completed=Event(),
                      answered=False, queried_skills=self.common_query_skills)
        assert query.responses_gathered.is_set() is False
        assert query.completed.is_set() is False
        self.active_queries[sid] = query
        self.enclosure.mouth_think()

        LOG.info(f'Searching for {utt}')
        # Send the query to anyone listening for them
        msg = message.reply('question:query', data={'phrase': utt})
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id
        # Define the timeout_msg here before any responses modify context
        timeout_msg = msg.response(msg.data)
        self.bus.emit(msg)

        query.timeout_time = time.time() + self._max_time
        timeout = False
        while not query.responses_gathered.wait(0.5):
            # forcefully timeout if search is still going
            if time.time() > query.timeout_time:
                if not query.completed.is_set():
                    LOG.debug(f"Session Timeout gathering responses ({query.session_id})")
                    timeout = True
                break

        if timeout:
            LOG.warning(f"Timed out getting responses for: {query.query}")
        self._query_timeout(timeout_msg)
        if not query.completed.wait(5):
            raise TimeoutError("Timed out processing responses")
        answered = bool(query.answered)
        self.active_queries.pop(sid)
        LOG.debug(f"answered={answered}|"
                  f"remaining active_queries={len(self.active_queries)}")
        return answered, query.selected_skill

    def handle_query_response(self, message: Message):
        search_phrase = message.data['phrase']
        skill_id = message.data['skill_id']
        searching = message.data.get('searching')
        answer = message.data.get('answer')

        query = self.active_queries.get(SessionManager.get(message).session_id)
        if not query:
            LOG.warning(f"Late answer received from {skill_id}, no active query for: {search_phrase}")
            return

        # Manage requests for time to complete searches
        if searching:
            LOG.debug(f"{skill_id} is searching")
            # request extending the timeout by EXTENSION_TIME
            query.timeout_time = time.time() + self._extension_time
            # TODO: Perhaps block multiple extensions?
            if skill_id not in query.extensions:
                query.extensions.append(skill_id)
        else:
            # Search complete, don't wait on this skill any longer
            if answer:
                LOG.info(f'Answer from {skill_id}')
                query.replies.append(message.data)

            # Remove the skill from list of timeout extensions
            if skill_id in query.extensions:
                LOG.debug(f"Done waiting for {skill_id}")
                query.extensions.remove(skill_id)

            time_to_wait = (query.query_time + self._min_response_wait -
                            time.time())
            if time_to_wait > 0:
                LOG.debug(f"Waiting {time_to_wait}s before checking extensions")
                query.responses_gathered.wait(time_to_wait)
            # not waiting for any more skills
            if not query.extensions:
                LOG.debug(f"No more skills to wait for ({query.session_id})")
                query.responses_gathered.set()

            # if all skills answered, stop searching
            if self.common_query_skills is not None and query.queried_skills == self.common_query_skills:
                query.responses_gathered.set()

    def _query_timeout(self, message: Message):
        """
        All accepted responses have been provided, either because all skills
        replied or a timeout condition was met. The best response is selected,
        spoken, and `question:action` is emitted so the associated skill's
        handler can perform any additional actions.
        @param message: question:query.response Message with `phrase` data
        """
        query = self.active_queries.get(SessionManager.get(message).session_id)
        LOG.info(f'Check responses with {len(query.replies)} replies')
        search_phrase = message.data.get('phrase', "")
        if query.extensions:
            query.extensions = []
        self.enclosure.mouth_reset()

        # Look at any replies that arrived before the timeout
        # Find response(s) with the highest confidence
        best = None
        ties = []
        for response in query.replies:
            if not best or response['conf'] > best['conf']:
                best = response
                ties = []
            elif response['conf'] == best['conf']:
                ties.append(response)

        if best:
            if ties:
                # TODO: Ask user to pick between ties or do it automagically
                pass

            if not best.get('handles_speech'):
                self.speak(best['answer'], message.reply("", best))
            LOG.info('Handling with: ' + str(best['skill_id']))
            query.selected_skill = best["skill_id"]
            response_data = {**best, "phrase": search_phrase}
            self.bus.emit(message.forward('question:action',
                                          data=response_data))
            query.answered = True
        else:
            query.answered = False
        query.completed.set()

    def speak(self, utterance: str, message: Message):
        """Speak a sentence.

        Args:
            utterance (str): response to be spoken
            message (Message): Message associated with selected response
        """
        log_deprecation("Skills should handle `speak` calls.", "0.1.0")
        selected_skill = message.data['skill_id']
        # registers the skill as being active
        self.enclosure.register(selected_skill)

        lang = get_message_lang(message)
        data = {'utterance': utterance,
                'expect_response': False,
                'meta': {"skill": selected_skill},
                'lang': lang}

        m = message.forward("speak", data)
        m.context["skill_id"] = selected_skill
        self.bus.emit(m)
