import os
import re
from os.path import dirname
from threading import Event
from typing import Optional, List

from langcodes import closest_match

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_config.config import Configuration
from ovos_plugin_manager.templates.pipeline import PipelineMatch, PipelinePlugin
from ovos_utils import flatten_list
from ovos_utils.bracket_expansion import expand_template
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.log import LOG
from ovos_utils.parse import match_one


class StopService(PipelinePlugin):
    """Intent Service thats handles stopping skills."""

    def __init__(self, bus):
        self.bus = bus
        self._voc_cache = {}
        self.load_resource_files()
        super().__init__(config=Configuration().get("skills", {}).get("stop") or {})

    def load_resource_files(self):
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
        Collect skills that can be stopped based on a ping-pong mechanism.
        
        This method determines which active skills can handle a stop request by sending
        a stop ping to each active skill and waiting for their acknowledgment.
        
        Parameters:
            message (Message): The original message triggering the stop request.
        
        Returns:
            List[str]: A list of skill IDs that can be stopped. If no skills explicitly
                      indicate they can stop, returns all active skills.
        
        Notes:
            - Excludes skills that are blacklisted in the current session
            - Uses a non-blocking event mechanism to collect skill responses
            - Waits up to 0.5 seconds for skills to respond
            - Falls back to all active skills if no explicit stop confirmation is received
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
            Handle acknowledgment from skills during the stop process.
            
            This method is a nested function used in skill stopping negotiation. It validates and tracks skill responses to a stop request.
            
            Parameters:
                msg (Message): Message containing skill acknowledgment details.
            
            Side Effects:
                - Modifies the `want_stop` list with skills that can handle stopping
                - Updates the `skill_ids` list to track which skills have responded
                - Sets the threading event when all active skills have responded
            
            Notes:
                - Checks if a skill can handle stopping based on multiple conditions
                - Ensures all active skills provide a response before proceeding
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

    def stop_skill(self, skill_id: str, message: Message) -> bool:
        """
        Stop a skill's ongoing activities and manage its session state.
        
        Sends a stop command to a specific skill and handles its response, ensuring
        that any active interactions or processes are terminated. The method checks
        for errors, verifies the skill's stopped status, and emits additional signals
        to forcibly abort ongoing actions like conversations, questions, or speech.
        
        Args:
            skill_id (str): Unique identifier of the skill to be stopped.
            message (Message): The original message context containing interaction details.
        
        Returns:
            bool: True if the skill was successfully stopped, False otherwise.
        
        Raises:
            Logs error if skill stop request encounters an issue.
        
        Notes:
            - Emits multiple bus messages to ensure complete skill termination
            - Checks and handles different skill interaction states
            - Supports force-stopping of conversations, questions, and speech
        """
        stop_msg = message.reply(f"{skill_id}.stop")
        result = self.bus.wait_for_response(stop_msg, f"{skill_id}.stop.response")
        if result and 'error' in result.data:
            error_msg = result.data['error']
            LOG.error(f"{skill_id}: {error_msg}")
            return False
        elif result is not None:
            stopped = result.data.get('result', False)
        else:
            stopped = False

        if stopped:
            sess = SessionManager.get(message)
            state = sess.utterance_states.get(skill_id, "intent")
            LOG.debug(f"skill response status: {state}")
            if state == "response":  # TODO this is never happening and it should...
                LOG.debug(f"stopping {skill_id} in middle of get_response!")

            # force-kill any ongoing get_response/converse/TTS - see @killable_event decorator
            self.bus.emit(message.forward("mycroft.skills.abort_question", {"skill_id": skill_id}))
            self.bus.emit(message.forward("ovos.skills.converse.force_timeout", {"skill_id": skill_id}))
            # TODO - track if speech is coming from this skill! not currently tracked
            self.bus.emit(message.reply("mycroft.audio.speech.stop",{"skill_id": skill_id}))

        return stopped

    def match_stop_high(self, utterances: List[str], lang: str, message: Message) -> Optional[PipelineMatch]:
        """
        Handles high-confidence stop requests by matching exact stop vocabulary and managing skill stopping.
        
        Attempts to stop skills when an exact "stop" or "global_stop" command is detected. Performs the following actions:
        - Identifies the closest language match for vocabulary
        - Checks for global stop command when no active skills exist
        - Emits a global stop message if applicable
        - Attempts to stop individual skills if a stop command is detected
        - Disables response mode for stopped skills
        
        Parameters:
            utterances (List[str]): List of user utterances to match against stop vocabulary
            lang (str): Four-letter ISO language code for language-specific matching
            message (Message): Message context for generating appropriate responses
        
        Returns:
            Optional[PipelineMatch]: Match result indicating whether stop was handled, with optional skill and session information
            - Returns None if no stop action could be performed
            - Returns PipelineMatch with handled=True for successful global or skill-specific stop
        
        Raises:
            No explicit exceptions raised, but may log debug/info messages during processing
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
            self.bus.emit(message.reply("mycroft.stop", {}))
            return PipelineMatch(handled=True,
                                 match_data={"conf": conf},
                                 skill_id=None,
                                 utterance=utterance)

        if is_stop:
            # check if any skill can stop
            for skill_id in self._collect_stop_skills(message):
                LOG.debug(f"Checking if skill wants to stop: {skill_id}")
                if self.stop_skill(skill_id, message):
                    LOG.info(f"Skill stopped: {skill_id}")
                    sess.disable_response_mode(skill_id)
                    return PipelineMatch(handled=True,
                                         match_data={"conf": conf},
                                         skill_id=skill_id,
                                         utterance=utterance,
                                         updated_session=sess)
        return None

    def match_stop_medium(self, utterances: List[str], lang: str, message: Message) -> Optional[PipelineMatch]:
        """
        Handle stop intent with additional context beyond simple stop commands.
        
        This method processes utterances that contain "stop" or global stop vocabulary but may include
        additional words not explicitly defined in intent files. It performs a medium-confidence
        intent matching for stop requests.
        
        Parameters:
            utterances (List[str]): List of input utterances to analyze
            lang (str): Four-letter ISO language code for localization
            message (Message): Message context for generating appropriate responses
        
        Returns:
            Optional[PipelineMatch]: A pipeline match if the stop intent is successfully processed,
            otherwise None if no stop intent is detected
        
        Notes:
            - Attempts to match stop vocabulary with fuzzy matching
            - Falls back to low-confidence matching if medium-confidence match is inconclusive
            - Handles global stop scenarios when no active skills are present
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

        return self.match_stop_low(utterances, lang, message)

    def _get_closest_lang(self, lang: str) -> Optional[str]:
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

    def match_stop_low(self, utterances: List[str], lang: str, message: Message) -> Optional[PipelineMatch]:
        """
        Perform a low-confidence fuzzy match for stop intent before fallback processing.
        
        This method attempts to match stop-related vocabulary with low confidence and handle stopping of active skills.
        
        Parameters:
            utterances (List[str]): List of input utterances to match against stop vocabulary
            lang (str): Four-letter ISO language code for vocabulary matching
            message (Message): Message context used for generating replies and managing session
        
        Returns:
            Optional[PipelineMatch]: A pipeline match object if a stop action is handled, otherwise None
        
        Notes:
            - Increases confidence if active skills are present
            - Attempts to stop individual skills before emitting a global stop signal
            - Handles language-specific vocabulary matching
            - Configurable minimum confidence threshold for stop intent
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
            LOG.debug(f"Checking if skill wants to stop: {skill_id}")
            if self.stop_skill(skill_id, message):
                sess.disable_response_mode(skill_id)
                return PipelineMatch(handled=True,
                                     match_data={"conf": conf},
                                     skill_id=skill_id,
                                     utterance=utterance,
                                     updated_session=sess)

        # emit a global stop, full stop anything OVOS is doing
        LOG.debug(f"Emitting global stop signal, {len(self.get_active_skills(message))} active skills")
        self.bus.emit(message.reply("mycroft.stop", {}))
        return PipelineMatch(handled=True,
                             # emit instead of intent message {"conf": conf},
                             match_data={"conf": conf},
                             skill_id=None,
                             utterance=utterance)

    def voc_match(self, utt: str, voc_filename: str, lang: str,
                  exact: bool = False):
        """
        TODO - should use ovos_workshop method instead of reimplementing here
               look into subclassing from OVOSAbstractApp

        Determine if the given utterance contains the vocabulary provided.

        By default the method checks if the utterance contains the given vocab
        thereby allowing the user to say things like "yes, please" and still
        match against "Yes.voc" containing only "yes". An exact match can be
        requested.

        The method first checks in the current Skill's .voc files and secondly
        in the "res/text" folder of mycroft-core. The result is cached to
        avoid hitting the disk each time the method is called.

        Args:
            utt (str): Utterance to be tested
            voc_filename (str): Name of vocabulary file (e.g. 'yes' for
                                'res/text/en-us/yes.voc')
            lang (str): Language code, defaults to self.lang
            exact (bool): Whether the vocab must exactly match the utterance

        Returns:
            bool: True if the utterance has the given vocabulary it
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
