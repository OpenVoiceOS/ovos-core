import time
from dataclasses import dataclass
from os.path import dirname
from threading import Event
from typing import Dict, Optional

from ovos_config.config import Configuration

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_plugin_manager.solvers import find_multiple_choice_solver_plugins
from ovos_plugin_manager.templates.pipeline import IntentMatch
from ovos_utils import flatten_list
from ovos_utils.log import LOG
from ovos_workshop.app import OVOSAbstractApplication


@dataclass
class Query:
    session_id: str
    query: str
    lang: str
    replies: list = None
    extensions: list = None
    queried_skills: list = None
    query_time: float = 0
    timeout_time: float = 0
    responses_gathered: Event = Event()
    completed: Event = Event()
    answered: bool = False
    selected_skill: str = ""


class CommonQAService(OVOSAbstractApplication):
    def __init__(self, bus, config: Optional[Dict] = None):
        super().__init__(bus=bus,
                         skill_id="common_query.openvoiceos",
                         resources_dir=f"{dirname(__file__)}")
        self.active_queries: Dict[str, Query] = dict()

        self.common_query_skills = None
        config = config or Configuration().get('intents', {}).get("common_query") or dict()
        self._extension_time = config.get('extension_time') or 3
        CommonQAService._EXTENSION_TIME = self._extension_time
        self._min_wait = config.get('min_response_wait') or 2
        self._max_time = config.get('max_response_wait') or 6  # regardless of extensions
        reranker_module = config.get("reranker", "ovos-choice-solver-bm25")  # default to BM25 from ovos-classifiers
        self.reranker = None
        try:
            for name, plug in find_multiple_choice_solver_plugins().items():
                if name == reranker_module:
                    self.reranker = plug(config=config.get(name, {}))
                    LOG.info(f"CommonQuery ReRanker: {name}")
                    break
            else:
                LOG.info("No CommonQuery ReRanker loaded!")
        except Exception as e:
            LOG.error(f"Failed to load ReRanker plugin: {e}")
        self.ignore_scores = config.get("ignore_skill_scores", False) and self.reranker is not None
        self.add_event('question:query.response', self.handle_query_response)
        self.add_event('common_query.question', self.handle_question)
        self.add_event('ovos.common_query.pong', self.handle_skill_pong)
        self.bus.emit(Message("ovos.common_query.ping"))  # gather any skills that already loaded

    def handle_skill_pong(self, message: Message):
        """ track running common query skills """
        if self.common_query_skills is None:
            self.common_query_skills = []
        if message.data["skill_id"] not in self.common_query_skills:
            self.common_query_skills.append(message.data["skill_id"])
            LOG.debug("Detected CommonQuery skill: " + message.data["skill_id"])

    def is_question_like(self, utterance: str, lang: str):
        """
        Check if the input utterance looks like a question for CommonQuery
        @param utterance: user input to evaluate
        @param lang: language of input
        @return: True if input might be a question to handle here
        """
        # skip utterances with less than 3 words
        if len(utterance.split(" ")) < 3:
            LOG.debug("utterance has less than 3 words, doesnt look like a question")
            return False
        # skip utterances meant for common play
        if self.voc_match(utterance, "Play", lang):
            LOG.debug("utterance has 'playback' keywords, doesnt look like a question")
            return False
        # require a "question word"
        return self.voc_match(utterance, "QuestionWord", lang)

    def match(self, utterances: str, lang: str, message: Message) -> Optional[IntentMatch]:
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
        if not self.common_query_skills:
            from ovos_workshop.version import VERSION_BUILD, VERSION_ALPHA
            # TODO - standalone skills can be any version >=0.0.12a16
            # common query skills should ensure ovos-workshop >= 0.0.16a7 in requirements.txt
            # ovos-core currently only requires ovos-workshop 0.0.15
            if VERSION_BUILD < 16 or (VERSION_BUILD == 16 and 0 < VERSION_ALPHA < 7):
                LOG.warning("you seem to be running ovos-workshop < 0.0.16a7 , "
                            f"CommonQuery will wait minimum {self._min_wait} seconds for skills."
                            f" upgrade ovos-workshop for an extra speedup")
            else:
                LOG.info("No CommonQuery skills to search")
                return None
        else:
            LOG.info(f"Gathering answers from skills: {self.common_query_skills}")

        for utterance in utterances:
            if self.is_question_like(utterance, lang):
                message.data["lang"] = lang  # only used for speak method
                message.data["utterance"] = utterance
                answered, skill_id = self.handle_question(message)
                if answered:
                    match = IntentMatch(intent_service='CommonQuery',
                                        intent_type=True,
                                        intent_data={},
                                        skill_id=skill_id,
                                        utterance=utterance)
                break
        return match

    def handle_question(self, message: Message):
        """
        Send the phrase to CommonQuerySkills and prepare for handling replies.
        """
        utt = message.data.get('utterance')
        sess = SessionManager.get(message)
        query = Query(session_id=sess.session_id, query=utt, lang=sess.lang,
                      replies=[], extensions=[],
                      query_time=time.time(), timeout_time=time.time() + self._max_time,
                      responses_gathered=Event(), completed=Event(),
                      answered=False,
                      queried_skills=[s for s in sess.blacklisted_skills
                                      if s in self.common_query_skills])  # dont wait for these
        assert query.responses_gathered.is_set() is False
        assert query.completed.is_set() is False
        self.active_queries[sess.session_id] = query
        self.enclosure.mouth_think()

        LOG.info(f'Searching for {utt}')
        # Send the query to anyone listening for them
        msg = message.reply('question:query', data={'phrase': utt})
        if "skill_id" not in msg.context:
            msg.context["skill_id"] = self.skill_id
        # Define the timeout_msg here before any responses modify context
        timeout_msg = msg.response(msg.data)
        self.bus.emit(msg)

        while not query.responses_gathered.wait(0.1):
            # forcefully timeout if search is still going
            if time.time() > query.timeout_time:
                if not query.completed.is_set():
                    LOG.debug(f"Session Timeout gathering responses ({query.session_id})")
                    LOG.warning(f"Timed out getting responses for: {query.query}")
                    timeout = True
                break

        self._query_timeout(timeout_msg)
        if not query.completed.wait(5):
            raise TimeoutError("Timed out processing responses")
        answered = bool(query.answered)
        self.active_queries.pop(sess.session_id)
        LOG.debug(f"answered={answered}|"
                  f"remaining active_queries={len(self.active_queries)}")
        return answered, query.selected_skill

    def handle_query_response(self, message: Message):
        search_phrase = message.data['phrase']
        skill_id = message.data['skill_id']
        searching = message.data.get('searching')
        answer = message.data.get('answer')

        sess = SessionManager.get(message)
        if skill_id in sess.blacklisted_skills:
            LOG.debug(f"ignoring match, skill_id '{skill_id}' blacklisted by Session '{sess.session_id}'")
            return

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

            query.queried_skills.append(skill_id)

            # Remove the skill from list of timeout extensions
            if skill_id in query.extensions:
                LOG.debug(f"Done waiting for {skill_id}")
                query.extensions.remove(skill_id)

            # if all skills answered, stop searching
            if self.common_query_skills is not None and set(query.queried_skills) == set(self.common_query_skills):
                LOG.debug("All skills answered")
                query.responses_gathered.set()
            else:
                time_to_wait = (query.timeout_time - time.time())
                if time_to_wait > 0:
                    LOG.debug(f"Waiting up to {time_to_wait}s for other skills")
                    query.responses_gathered.wait(time_to_wait)

                # not waiting for any more skills
                if not query.extensions and not query.responses_gathered.is_set():
                    LOG.debug(f"Exiting early, no more skills to wait for session ({query.session_id})")
                    query.responses_gathered.set()

    def _query_timeout(self, message: Message):
        """
        All accepted responses have been provided, either because all skills
        replied or a timeout condition was met. The best response is selected,
        spoken, and `question:action` is emitted so the associated skill's
        handler can perform any additional actions.
        @param message: question:query.response Message with `phrase` data
        """
        sess = SessionManager.get(message)
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
            if response["skill_id"] in sess.blacklisted_skills:
                continue
            if not self.ignore_scores:
                if not best or response['conf'] > best['conf']:
                    best = response
                    ties = [response]
                elif response['conf'] == best['conf']:
                    ties.append(response)
            else:
                best = response
                # let's rerank all answers and ignore skill self-reported confidence
                ties.append(response)

        if best:
            if len(ties) > 1:
                tied_ids = [m["skill_id"] for m in ties]
                LOG.debug(f"Tied skills: {tied_ids}")
                answers = {m["answer"]: m for m in ties}
                if self.reranker is None:
                    LOG.debug("No ReRanker available, selecting randomly")
                    # random pick, no re-ranker available
                    best_ans = list(answers.keys())[0]
                else:
                    reranked = self.reranker.rerank(query.query,
                                                    list(answers.keys()),
                                                    lang=query.lang)
                    for score, ans in reranked:
                        LOG.info(f"ReRanked score: {score} - {answers[ans]}")
                    best_ans = reranked[0][1]

                best = answers[best_ans]

            LOG.info('Handling with: ' + str(best['skill_id']))
            query.selected_skill = best["skill_id"]
            response_data = {**best, "phrase": search_phrase}
            self.bus.emit(message.reply('question:action', data=response_data))
            query.answered = True
        else:
            query.answered = False
        query.completed.set()

    def shutdown(self):
        self.default_shutdown()  # remove events registered via self.add_event
