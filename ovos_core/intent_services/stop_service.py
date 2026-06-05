import re
from os.path import dirname
from threading import Event
from typing import Optional, Dict, List, Union

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, UtteranceState

from ovos_config.config import Configuration
from ovos_plugin_manager.templates.pipeline import ConfidenceMatcherPipeline, IntentHandlerMatch
from ovos_utils import flatten_list
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG
from ovos_utils.parse import match_one
from ovos_workshop.app import OVOSAbstractApplication


class StopService(ConfidenceMatcherPipeline, OVOSAbstractApplication):
    """Intent Service that handles stopping skills."""

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None):
        # OVOSAbstractApplication provides voc_match, voc_list, and locale
        # resource loading — same pattern as CommonQAService and OCPPipelineMatcher
        OVOSAbstractApplication.__init__(self, bus=bus or FakeBus(),
                                         skill_id="stop.openvoiceos",
                                         resources_dir=f"{dirname(__file__)}")
        config = config or Configuration().get("skills", {}).get("stop") or {}
        ConfidenceMatcherPipeline.__init__(self, config=config, bus=bus)
        self.bus.on("stop:global", self.handle_global_stop)
        self.bus.on("stop:skill", self.handle_skill_stop)

    def handle_global_stop(self, message: Message) -> None:
        """Broadcast a global stop and mark the utterance handled."""
        # OVOS-STOP-1 §5.3 universal stop broadcast: legacy 'mycroft.stop' or
        # spec 'ovos.stop', depending on the active namespace.
        stop_topic = "mycroft.stop" if self._legacy_namespace() else "ovos.stop"
        self.bus.emit(message.forward(stop_topic))
        # TODO - this needs a confirmation dialog if nothing was stopped
        self.bus.emit(message.forward("ovos.utterance.handled"))

    def handle_skill_stop(self, message: Message) -> None:
        """Forward a stop request to the specific skill."""
        skill_id = message.data["skill_id"]
        self.bus.emit(message.reply(f"{skill_id}.stop"))

    @staticmethod
    def get_active_skills(message: Optional[Message] = None) -> List[str]:
        """Active skill ids ordered by converse priority.

        This represents the order in which stop will be called.

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

        Individual skills respond to this request via the `can_stop` method.

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

        def handle_ack(msg: Message) -> None:
            """
            Handle acknowledgment from skills during the stop process.

            Parameters:
                msg (Message): Message containing skill acknowledgment details.

            Side Effects:
                - Modifies the `want_stop` list with skills that can handle stopping
                - Updates the `skill_ids` list to track which skills have responded
                - Sets the threading event when all active skills have responded
            """
            nonlocal event, skill_ids
            skill_id = msg.data.get("skill_id")
            if not skill_id:
                return  # guard against malformed pong messages

            # validate the stop pong; default False — a non-responding skill
            # should not be assumed stoppable
            if all((skill_id not in want_stop,
                    msg.data.get("can_handle", False),
                    skill_id in active_skills)):
                want_stop.append(skill_id)

            if skill_id not in skill_ids:  # track which answer we got
                skill_ids.append(skill_id)

            if all(s in skill_ids for s in active_skills):
                # all skills answered the ping!
                event.set()

        # Collect pongs on BOTH namespaces; only one ping namespace is emitted.
        self.bus.on("skill.stop.pong", handle_ack)
        self.bus.on("ovos.stop.pong", handle_ack)  # OVOS-STOP-1 §4.2
        try:
            # ask skills if they can stop (OVOS-STOP-1 §4.2)
            if self._legacy_namespace():
                # legacy: one targeted ping per active skill
                for skill_id in active_skills:
                    self.bus.emit(message.forward(f"{skill_id}.stop.ping",
                                                  {"skill_id": skill_id}))
            else:
                # spec: a single broadcast stoppability query
                self.bus.emit(message.forward("ovos.stop.ping"))

            # wait for all skills to acknowledge they can stop
            event.wait(timeout=0.5)
        finally:
            self.bus.remove("skill.stop.pong", handle_ack)
            self.bus.remove("ovos.stop.pong", handle_ack)
        return want_stop or active_skills

    def handle_stop_confirmation(self, message: Message) -> None:
        """Handle a skill's stop.response and force-terminate any in-flight interactions."""
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
        - Checks for global stop command when no active skills exist
        - Emits a global stop message if applicable
        - Attempts to stop individual skills if a stop command is detected
        - Disables response mode for stopped skills

        Parameters:
            utterances (List[str]): List of user utterances to match against stop vocabulary
            lang (str): Four-letter ISO language code for language-specific matching
            message (Message): Message context for generating appropriate responses

        Returns:
            Optional[IntentHandlerMatch]: Match result indicating whether stop was handled, with optional skill and session information
            - Returns None if no stop action could be performed
            - Returns IntentHandlerMatch with handled=True for successful global or skill-specific stop
        """
        sess = SessionManager.get(message)

        # we call flatten in case someone is sending the old style list of tuples
        utterance = flatten_list(utterances)[0]

        is_stop = self.voc_match(utterance, 'stop', lang=lang, exact=True)
        is_global_stop = self.voc_match(utterance, 'global_stop', lang=lang, exact=True) or \
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
            Optional[IntentHandlerMatch]: A pipeline match if the stop intent is successfully processed,
            otherwise None if no stop intent is detected

        Notes:
            - Attempts to match stop vocabulary with fuzzy matching
            - Falls back to low-confidence matching if medium-confidence match is inconclusive
            - Handles global stop scenarios when no active skills are present
        """
        # we call flatten in case someone is sending the old style list of tuples
        utterance = flatten_list(utterances)[0]

        is_stop = self.voc_match(utterance, 'stop', lang=lang, exact=False)
        if not is_stop:
            is_global_stop = self.voc_match(utterance, 'global_stop', lang=lang, exact=False) or \
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
            Optional[IntentHandlerMatch]: A pipeline match object if a stop action is handled, otherwise None

        Notes:
            - Increases confidence if active skills are present
            - Attempts to stop individual skills before emitting a global stop signal
            - Handles language-specific vocabulary matching
            - Configurable minimum confidence threshold for stop intent
        """
        sess = SessionManager.get(message)
        # we call flatten in case someone is sending the old style list of tuples
        utterance = flatten_list(utterances)[0]

        stop_vocs = self.voc_list('stop', lang)
        if not stop_vocs:
            return None

        conf = match_one(utterance, stop_vocs)[1]
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

    def shutdown(self) -> None:
        """Remove bus listeners registered by this service."""
        self.bus.remove("stop:global", self.handle_global_stop)
        self.bus.remove("stop:skill", self.handle_skill_stop)
