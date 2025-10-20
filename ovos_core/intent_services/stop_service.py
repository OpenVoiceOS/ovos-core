import os
import re
from os.path import dirname
from threading import Event
from typing import Optional, Dict, List, Union

from langcodes import closest_match
from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, UtteranceState

from ovos_config.config import Configuration
from ovos_plugin_manager.templates.pipeline import ConfidenceMatcherPipeline, IntentHandlerMatch
from ovos_utils import flatten_list
from ovos_utils.fakebus import FakeBus
from ovos_utils.bracket_expansion import expand_template
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.log import LOG
from ovos_utils.parse import match_one


class StopService(ConfidenceMatcherPipeline):
    """Intent Service thats handles stopping skills."""

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None):
        config = config or Configuration().get("skills", {}).get("stop") or {}
        super().__init__(config=config, bus=bus)
        self._voc_cache = {}
        self.load_resource_files()
        self.bus.on("stop:global", self.handle_global_stop)
        self.bus.on("stop:skill", self.handle_skill_stop)

    def handle_global_stop(self, message: Message):
        self.bus.emit(message.forward("mycroft.stop"))
        # TODO - this needs a confirmation dialog if nothing was stopped
        self.bus.emit(message.forward("ovos.utterance.handled"))

    def handle_skill_stop(self, message: Message):
        skill_id = message.data["skill_id"]
        self.bus.emit(message.reply(f"{skill_id}.stop"))

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

        Individual skills respond to this request via the `can_stop` method

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

    def handle_stop_confirmation(self, message: Message):
        skill_id = (message.data.get("skill_id") or
                    message.context.get("skill_id") or
                    message.msg_type.split(".stop.response")[0])
        if 'error' in message.data:
            error_msg = message.data['error']
            LOG.error(f"{skill_id}: {error_msg}")
        elif message.data.get('result', False):
            sess = SessionManager.get(message)
            utt_state = sess.utterance_states.get(skill_id, UtteranceState.INTENT)
            if utt_state == UtteranceState.RESPONSE:
                LOG.debug("Forcing get_response timeout")
                # force-kill any ongoing get_response - see @killable_event decorator (ovos-workshop)
                self.bus.emit(message.reply("mycroft.skills.abort_question", {"skill_id": skill_id}))
            if sess.is_active(skill_id):
                LOG.debug("Forcing converse timeout")
                # force-kill any ongoing converse - see @killable_event decorator (ovos-workshop)
                self.bus.emit(message.reply("ovos.skills.converse.force_timeout", {"skill_id": skill_id}))

            # TODO - track if speech is coming from this skill! not currently tracked (ovos-audio)
            if sess.is_speaking:
                # force-kill any ongoing TTS
                self.bus.emit(message.forward("mycroft.audio.speech.stop", {"skill_id": skill_id}))

    def match_high(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
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
            return IntentHandlerMatch(
                match_type="stop:global",
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
                    match_type="stop:skill",
                    match_data={"conf": conf, "skill_id": skill_id},
                    updated_session=sess,
                    utterance=utterance,
                    skill_id="stop.openvoiceos"
                )

        return None

    def match_medium(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
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

        return self.match_low(utterances, lang, message)

    def match_low(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
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
            LOG.debug(f"Telling skill to stop: {skill_id}")
            sess.disable_response_mode(skill_id)
            self.bus.once(f"{skill_id}.stop.response", self.handle_stop_confirmation)
            return IntentHandlerMatch(
                match_type="stop:skill",
                match_data={"conf": conf, "skill_id": skill_id},
                updated_session=sess,
                utterance=utterance,
                skill_id="stop.openvoiceos"
            )

        # emit a global stop, full stop anything OVOS is doing
        LOG.debug(f"Emitting global stop signal, {len(self.get_active_skills(message))} active skills")
        return IntentHandlerMatch(
            match_type="stop:global",
            match_data={"conf": conf},
            updated_session=sess,
            utterance=utterance,
            skill_id="stop.openvoiceos"
        )

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

    def shutdown(self):
        self.bus.remove("stop:global", self.handle_global_stop)
        self.bus.remove("stop:skill", self.handle_skill_stop)