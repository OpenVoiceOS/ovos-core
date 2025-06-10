import os
import re
from os.path import dirname
from threading import Event
from typing import Optional, Dict, List, Union

from langcodes import closest_match
from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager

from ovos_config.config import Configuration
from ovos_plugin_manager.templates.pipeline import ConfidenceMatcherPipeline, IntentHandlerMatch
from ovos_utils import flatten_list
from ovos_utils.fakebus import FakeBus
from ovos_utils.bracket_expansion import expand_template
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.log import LOG, deprecated
from ovos_utils.parse import match_one


class StopService(ConfidenceMatcherPipeline):
    """Intent Service thats handles stopping skills."""

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None):
        """
                 Initializes the StopService with optional message bus and configuration.
                 
                 Loads stop-related vocabulary resources for multiple languages into a cache for intent matching.
                 """
                 config = config or Configuration().get("skills", {}).get("stop") or {}
        super().__init__(config=config, bus=bus)
        self._voc_cache = {}
        self.load_resource_files()

    def load_resource_files(self):
        """
        Loads and caches stop-related vocabulary files for all supported languages.
        
        Scans the locale directory for language folders, reads vocabulary files within each,
        expands templates, and flattens the resulting lists. The processed vocabulary is
        stored in an internal cache, organized by standardized language tags and vocabulary names.
        """
        base = f"{dirname(__file__)}/locale"
        for lang in os.listdir(base):
            lang2 = standardize_lang_tag(lang)
            self._voc_cache[lang2] = {}
            for f in os.listdir(f"{base}/{lang}"):
                with open(f"{base}/{lang}/{f}", encoding="utf-8") as fi:
                    lines = [expand_template(l) for l in fi.read().split("\n")
                             if l.strip() and not l.startswith("#")]
                    n = f.split(".", 1)[0]
                    self._voc_cache[lang2][n] = flatten_list(lines)

    @staticmethod
    def get_active_skills(message: Optional[Message] = None) -> List[str]:
        """Active skill ids ordered by converse priority
        this represents the order in which stop will be called

        Returns:
            active_skills (list): ordered list of skill_ids
        """
        session = SessionManager.get(message)
        return [skill[0] for skill in session.active_skills]

    def _collect_stop_skills(self, message: Message) -> List[str]:
        """
        Identifies which active skills can be stopped by sending a stop ping and collecting acknowledgments.
        
        Sends a stop request to each active, non-blacklisted skill and waits up to 0.5 seconds for responses indicating their ability to stop. Returns a list of skill IDs that confirm they can handle a stop request; if none explicitly confirm, returns all active skills.
        """
        sess = SessionManager.get(message)

        want_stop = []
        skill_ids = []

        active_skills = [s for s in self.get_active_skills(message)
                         if s not in sess.blacklisted_skills]

        if not active_skills:
            return want_stop

        event = Event()

        def handle_ack(msg):
            """
            Processes acknowledgment messages from skills during the stop negotiation process.
            
            Adds skills that confirm their ability to handle a stop request to the tracking list, records which skills have responded, and signals completion when all active skills have replied.
            """
            nonlocal event, skill_ids
            skill_id = msg.data["skill_id"]

            # validate the stop pong
            if all((skill_id not in want_stop,
                    msg.data.get("can_handle", True),
                    skill_id in active_skills)):
                want_stop.append(skill_id)

            if skill_id not in skill_ids:  # track which answer we got
                skill_ids.append(skill_id)

            if all(s in skill_ids for s in active_skills):
                # all skills answered the ping!
                event.set()

        self.bus.on("skill.stop.pong", handle_ack)

        # ask skills if they can stop
        for skill_id in active_skills:
            self.bus.emit(message.forward(f"{skill_id}.stop.ping",
                                          {"skill_id": skill_id}))

        # wait for all skills to acknowledge they can stop
        event.wait(timeout=0.5)

        self.bus.remove("skill.stop.pong", handle_ack)
        return want_stop or active_skills

    def handle_stop_confirmation(self, message: Message):
        """
        Handles confirmation responses from skills after a stop request.
        
        If the response contains an error, logs the error message. If the stop was successful, emits events to abort any ongoing question, conversation, or speech synthesis associated with the skill.
        """
        skill_id = (message.data.get("skill_id") or
                    message.context.get("skill_id") or
                    message.msg_type.split(".stop.response")[0])
        if 'error' in message.data:
            error_msg = message.data['error']
            LOG.error(f"{skill_id}: {error_msg}")
        elif message.data.get('result', False):
            # force-kill any ongoing get_response/converse/TTS - see @killable_event decorator
            self.bus.emit(message.forward("mycroft.skills.abort_question", {"skill_id": skill_id}))
            self.bus.emit(message.forward("ovos.skills.converse.force_timeout", {"skill_id": skill_id}))
            # TODO - track if speech is coming from this skill! not currently tracked
            self.bus.emit(message.reply("mycroft.audio.speech.stop", {"skill_id": skill_id}))

    def match_high(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """
        Performs high-confidence matching for stop commands and initiates stopping of active skills.
        
        Checks user utterances for exact matches to stop or global stop vocabulary in the closest supported language. If a global stop is detected and no active skills are present, emits a global stop intent. If a stop command is detected and active skills exist, attempts to stop each skill by disabling its response mode and registering a one-time listener for its stop confirmation. Returns an `IntentHandlerMatch` indicating the stop action, or None if no match is found.
        
        Args:
            utterances: User utterances to evaluate for stop intent.
            lang: Language code used for vocabulary matching.
            message: Contextual message for the stop request.
        
        Returns:
            An `IntentHandlerMatch` if a stop or global stop intent is detected and handled; otherwise, None.
        """
        lang = self._get_closest_lang(lang)
        if lang is None:  # no vocs registered for this lang
            return None

        sess = SessionManager.get(message)

        # we call flatten in case someone is sending the old style list of tuples
        utterance = flatten_list(utterances)[0]

        is_stop = self.voc_match(utterance, 'stop', exact=True, lang=lang)
        is_global_stop = self.voc_match(utterance, 'global_stop', exact=True, lang=lang) or \
                         (is_stop and not len(self.get_active_skills(message)))

        conf = 1.0

        if is_global_stop:
            LOG.info(f"Emitting global stop, {len(self.get_active_skills(message))} active skills")
            # emit a global stop, full stop anything OVOS is doing
            return IntentHandlerMatch(
                match_type="mycroft.stop",
                match_data={"conf": conf},
                updated_session=sess,
                utterance=utterance,
                skill_id="stop.openvoiceos"
            )

        if is_stop:
            # check if any skill can stop
            for skill_id in self._collect_stop_skills(message):
                LOG.debug(f"Telling skill to stop: {skill_id}")
                sess.disable_response_mode(skill_id)
                self.bus.once(f"{skill_id}.stop.response", self.handle_stop_confirmation)
                return IntentHandlerMatch(
                    match_type=f"{skill_id}.stop",
                    match_data={"conf": conf},
                    updated_session=sess,
                    utterance=utterance,
                    skill_id="stop.openvoiceos"
                )

        return None

    def match_medium(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """
        Performs medium-confidence matching for stop intents with fuzzy vocabulary analysis.
        
        Analyzes utterances for stop or global stop commands using fuzzy matching, allowing for additional context or words beyond exact stop phrases. If a medium-confidence match is not found, falls back to low-confidence matching. Returns an intent match if a stop intent is detected, or None otherwise.
        """
        lang = self._get_closest_lang(lang)
        if lang is None:  # no vocs registered for this lang
            return None

        # we call flatten in case someone is sending the old style list of tuples
        utterance = flatten_list(utterances)[0]

        is_stop = self.voc_match(utterance, 'stop', exact=False, lang=lang)
        if not is_stop:
            is_global_stop = self.voc_match(utterance, 'global_stop', exact=False, lang=lang) or \
                             (is_stop and not len(self.get_active_skills(message)))
            if not is_global_stop:
                return None

        return self.match_low(utterances, lang, message)

    def match_low(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """
        Performs a low-confidence fuzzy match for stop intent and initiates stopping of active skills.
        
        Attempts to match user utterances against stop-related vocabulary with low confidence. If the confidence threshold is met, disables response mode for stoppable skills and registers for their stop confirmation. If no skills respond, emits a global stop intent. Returns an intent handler match if a stop action is handled, otherwise None.
        
        Args:
            utterances: List of user utterances to evaluate for stop intent.
            lang: ISO language code for vocabulary matching.
            message: Message context for session and reply management.
        
        Returns:
            An IntentHandlerMatch if a stop action is handled; otherwise, None.
        """
        lang = self._get_closest_lang(lang)
        if lang is None:  # no vocs registered for this lang
            return None
        sess = SessionManager.get(message)
        # we call flatten in case someone is sending the old style list of tuples
        utterance = flatten_list(utterances)[0]

        conf = match_one(utterance, self._voc_cache[lang]['stop'])[1]
        if len(self.get_active_skills(message)) > 0:
            conf += 0.1
        conf = round(min(conf, 1.0), 3)

        if conf < self.config.get("min_conf", 0.5):
            return None

        # check if any skill can stop
        for skill_id in self._collect_stop_skills(message):
            LOG.debug(f"Telling skill to stop: {skill_id}")
            sess.disable_response_mode(skill_id)
            self.bus.once(f"{skill_id}.stop.response", self.handle_stop_confirmation)
            return IntentHandlerMatch(
                match_type=f"{skill_id}.stop",
                match_data={"conf": conf},
                updated_session=sess,
                utterance=utterance,
                skill_id="stop.openvoiceos"
            )

        # emit a global stop, full stop anything OVOS is doing
        LOG.debug(f"Emitting global stop signal, {len(self.get_active_skills(message))} active skills")
        return IntentHandlerMatch(
            match_type="mycroft.stop",
            match_data={"conf": conf},
            updated_session=sess,
            utterance=utterance,
            skill_id="stop.openvoiceos"
        )

    def _get_closest_lang(self, lang: str) -> Optional[str]:
        """
        Finds the closest matching language tag from the vocabulary cache.
        
        Returns the closest language tag if the match score is less than 10, indicating a significant but acceptable regional difference; otherwise, returns None.
        """
        if self._voc_cache:
            lang = standardize_lang_tag(lang)
            closest, score = closest_match(lang, list(self._voc_cache.keys()))
            # https://langcodes-hickford.readthedocs.io/en/sphinx/index.html#distance-values
            # 0 -> These codes represent the same language, possibly after filling in values and normalizing.
            # 1- 3 -> These codes indicate a minor regional difference.
            # 4 - 10 -> These codes indicate a significant but unproblematic regional difference.
            if score < 10:
                return closest
        return None

    def voc_match(self, utt: str, voc_filename: str, lang: str,
                  exact: bool = False):
        """
                  Checks if an utterance matches vocabulary from cached files for a given language.
                  
                  Searches the cached vocabulary for the specified language and file, supporting exact or partial word boundary matching. Returns True if the utterance matches any vocabulary entry; otherwise, returns False.
                  
                  Args:
                      utt: The utterance to test.
                      voc_filename: The base name of the vocabulary file (without extension).
                      lang: The language code to use for matching.
                      exact: If True, requires an exact match; otherwise, matches on word boundaries.
                  
                  Returns:
                      True if the utterance matches the vocabulary; False otherwise.
                  """
        lang = self._get_closest_lang(lang)
        if lang is None:  # no vocs registered for this lang
            return False

        _vocs = self._voc_cache[lang].get(voc_filename) or []

        if utt and _vocs:
            if exact:
                # Check for exact match
                return any(i.strip().lower() == utt.lower()
                           for i in _vocs)
            else:
                # Check for matches against complete words
                return any([re.match(r'.*\b' + i + r'\b.*', utt, re.IGNORECASE)
                            for i in _vocs])
        return False

