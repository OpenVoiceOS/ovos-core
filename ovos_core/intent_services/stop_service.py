from os.path import dirname, join
from threading import Event
from typing import Optional, Dict, List, NamedTuple, Union

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.handler import HandlerLifecycle
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager, UtteranceState

from ovos_config.config import Configuration
from ovos_plugin_manager.templates.pipeline import ConfidenceMatcherPipeline, IntentHandlerMatch
from ovos_spec_tools import LocaleResources, SpecMessage
from ovos_utils import flatten_list
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG
from ovos_utils.parse import match_one

from ovos_core.intent_services.stop_service_legacy import _LegacyStopBridge


class PreDrainSnapshot(NamedTuple):
    """State a targeted stop observed before match() drained the session copy.

    ``match()`` drains ``active_handlers``/``response_mode`` before dispatch,
    so by the time ``.stop.response`` arrives the live session already lies
    about both fields. Capture them together at drain time, keyed by
    ``(session_id, skill_id)``, and pop them together in
    ``handle_stop_confirmation`` before either result branch runs.
    """
    was_active: bool
    utt_state: UtteranceState


class StopService(ConfidenceMatcherPipeline):
    """Stop pipeline plugin implementing OVOS-STOP-1.

    Matches stop-command utterances and returns Matches under STOP-1 §2:

    - a **targeted** stop dispatched on ``<skill_id>:stop`` (§2, §3.1) when a
      recency-selected active handler declares itself stoppable via the §4
      ping-pong cascade;
    - a **global** stop dispatched on ``<pipeline_id>:global_stop`` (§5)
      otherwise — explicit "stop everything" vocabulary (§3.2), an empty
      ``active_handlers`` (§4.1 step 1), or no positive pong responder
      (§4.1 step 5).

    Both dispatches set ``suppress_activation`` (§6.2/§7.3): a stop terminates
    an already-active skill's participation, so it registers no fresh
    activation. The session drain mandated by §5.2/§6 is committed via
    ``Match.updated_session`` before dispatch.
    """

    #: OVOS-STOP-1 §3.1 shared identity. Every confidence tier reports the same
    #: ``pipeline_id`` so the global-stop handler binds a single topic across
    #: tiers and exactly one ``ovos.stop`` broadcast is emitted per event.
    pipeline_id = "ovos-stop-pipeline-plugin"

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None,
                 suppress_activation: bool = True) -> None:
        config = config if config is not None else Configuration().get("skills", {}).get("stop") or {}
        bus = bus or FakeBus()
        ConfidenceMatcherPipeline.__init__(self, config=config, bus=bus)
        self._locale = LocaleResources(skill_locale=join(dirname(__file__), "locale"))
        #: Stamped onto every Match this plugin returns (§6.2/§7.3).
        self.suppress_activation = suppress_activation
        # §5 global-stop dispatch target; bound once, shared across tiers (§3.1).
        self.bus.on(f"{self.pipeline_id}:global_stop", self.handle_global_stop)
        self._legacy = _LegacyStopBridge(self)
        #: (session_id, skill_id) -> PreDrainSnapshot captured by _targeted_stop
        #: and consumed once by handle_stop_confirmation. Keyed per-session
        #: (not bare skill_id) so two concurrent targeted stops for the same
        #: skill_id in different sessions can't clobber each other's snapshot.
        self._pre_drain: Dict[tuple, PreDrainSnapshot] = {}

    def handle_global_stop(self, message: Message) -> None:
        """OVOS-STOP-1 §5.3 — broadcast the universal ``ovos.stop``.

        Bound on ``<pipeline_id>:global_stop`` and wrapped in HandlerLifecycle
        so the orchestrator observes the §8 terminal for the dispatch.

        A ``response_mode`` holder (OVOS-CONVERSE-1 §2.2 pending get_response
        window) is carried through ``Match.match_data`` (``_global_stop``) as
        ``response_mode_holder`` — the global broadcast alone (``ovos.stop`` /
        legacy ``mycroft.stop``) is never observed by ovos-workshop's
        killable-event abort, which listens ONLY on the per-skill
        ``<skill_id>.stop`` topic. Without this, a skill blocked in
        ``get_response`` survives a global stop until its own timeout. Emit
        the targeted topic first — the session's response_mode has already
        been cleared via ``updated_session`` by dispatch time, so this only
        needs to reach the still-blocked handler.
        """
        with HandlerLifecycle(self.bus, message,
                              skill_id=self.pipeline_id,
                              data={"name": "StopService.handle_global_stop"}):
            holder = message.data.get("response_mode_holder")
            if holder:
                self.bus.emit(message.forward(f"{holder}.stop"))
            self.bus.emit(message.forward(SpecMessage.STOP.value))

    @staticmethod
    def get_active_skills(message: Optional[Message] = None) -> List[str]:
        """Active skill ids ordered by converse priority.

        This is the OVOS-STOP-1 §4.1 recency input (``active_handlers``): the
        order in which stop is attempted.

        Returns:
            active_skills (list): ordered list of skill_ids
        """
        session = SessionManager.get(message)
        return [h["skill_id"] for h in session.active_handlers]

    @staticmethod
    def get_response_mode_holder(message: Optional[Message] = None) -> Optional[str]:
        """The skill_id currently holding the session's response_mode window
        (OVOS-CONVERSE-1 §2.2), if any.

        ovos-workshop's ``enable_response_mode`` (get_response) does NOT push
        an ``active_handlers`` entry — it only sets this field — so a holder
        is otherwise invisible to §4.1 candidate selection even though it is,
        by definition, the most recent interaction in the session.
        """
        session = SessionManager.get(message)
        rm = session.response_mode
        return rm.get("skill_id") if rm else None

    def _stop_candidates(self, message: Message) -> List[str]:
        """OVOS-STOP-1 §4.1 recency-ordered stop candidates.

        A response_mode holder ranks FIRST — it is the most recent
        interaction by definition, even when ``active_handlers`` is empty
        (see ``get_response_mode_holder``) — followed by the recency-ordered
        ``active_handlers`` list, minus blacklisted skills and de-duplicated.
        """
        sess = SessionManager.get(message)
        blacklisted = sess.blacklisted_skills or []
        candidates: List[str] = []
        holder = self.get_response_mode_holder(message)
        if holder and holder not in blacklisted:
            candidates.append(holder)
        for skill_id in self.get_active_skills(message):
            if skill_id not in candidates and skill_id not in blacklisted:
                candidates.append(skill_id)
        return candidates

    def _collect_stop_skills(self, message: Message) -> List[str]:
        """
        Collect skills that can be stopped based on a ping-pong mechanism (§4).

        This method determines which active skills can handle a stop request by sending
        a stop ping to each active skill and waiting for their acknowledgment.

        Individual skills respond to this request via the `can_stop` method.

        Parameters:
            message (Message): The original message triggering the stop request.

        Returns:
            List[str]: A list of skill IDs that can be stopped. If no skills explicitly
                      indicate they can stop, returns all active skills.

        Notes:
            - Excludes skills that are blacklisted in the current session (§6.3)
            - Uses a non-blocking event mechanism to collect skill responses
            - Waits up to 0.5 seconds for skills to respond (§4.1)
            - Falls back to all active skills if no explicit stop confirmation is received
        """
        want_stop = []
        skill_ids = []

        # §4.1 candidates: response_mode holder first (most recent by
        # definition), then recency-ordered active_handlers.
        active_skills = self._stop_candidates(message)

        if not active_skills:
            return want_stop

        event = Event()

        # OVOS-CONVERSE-1 §4.2 round correlation: the round IS the utterance
        # lifecycle, named by context.utterance_id (OVOS-PIPELINE-1 §9.1.1).
        # The ping carries it by `forward` derivation and the pong carries it
        # back by `reply` derivation — no skill-side action.
        round_uid = message.context.get("utterance_id")
        round_session_id = SessionManager.get(message).session_id

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

            # A pong that cannot prove which question it answers never decides a
            # round: discard pongs from an earlier (or foreign) lifecycle, or
            # from a foreign session. When the round itself is unnamed the
            # guard stands down, so a V0 caller that never entered through the
            # orchestrator behaves as before.
            if round_uid is not None and \
                    msg.context.get("utterance_id") != round_uid:
                LOG.debug(f"discarding stale stop pong from '{skill_id}': "
                          f"utterance_id {msg.context.get('utterance_id')!r} "
                          f"does not match round {round_uid!r}")
                return
            ack_sess = Session.from_message(msg) if "session" in msg.context else None
            if ack_sess and ack_sess.session_id != round_session_id:
                LOG.debug(f"discarding cross-session stop pong from '{skill_id}': "
                          f"session {ack_sess.session_id!r} does not match "
                          f"round session {round_session_id!r}")
                return

            # validate the stop pong; default False — a non-responding skill
            # should not be assumed stoppable (§4.2)
            if all((skill_id not in want_stop,
                    msg.data.get("can_handle", False),
                    skill_id in active_skills)):
                want_stop.append(skill_id)

            if skill_id not in skill_ids:  # track which answer we got
                skill_ids.append(skill_id)

            if all(s in skill_ids for s in active_skills):
                # all skills answered the ping!
                event.set()

        # SpecMessage.STOP_PONG.value == "ovos.stop.pong"; the NamespaceTranslator
        # SPEC_TO_LEGACY entry maps it to the literal "skill.stop.pong" every
        # skill (ovos-workshop) actually emits, and mirrors it onto this topic
        # on receipt — so listening on the spec constant still catches the
        # legacy emission (verified against the installed translator).
        self.bus.on(SpecMessage.STOP_PONG.value, handle_ack)
        try:
            # ask skills if they can stop
            for skill_id in active_skills:
                self.bus.emit(message.forward(f"{skill_id}.stop.ping",
                                              {"skill_id": skill_id}))

            # wait for all skills to acknowledge they can stop
            event.wait(timeout=0.5)
        finally:
            self.bus.remove(SpecMessage.STOP_PONG.value, handle_ack)

        if not want_stop:
            return active_skills
        # §4.1 selection must be deterministic: `want_stop` is built in PONG
        # ARRIVAL order (parallel broadcast — the pings all go out together, so
        # whichever skill answers fastest lands first), not recency order. The
        # docstring/contract says the response_mode holder (or more generally
        # the most-recent candidate) ranks first; re-sort by the candidate-list
        # (recency) order that `active_skills` already encodes before picking,
        # so the winner is always the most-recent stoppable candidate
        # regardless of which one's pong happened to arrive first.
        return sorted(want_stop, key=active_skills.index)

    def handle_stop_confirmation(self, message: Message) -> None:
        """Handle a skill's stop.response and force-terminate any in-flight interactions.

        Also resolves the ``IntentDispatcher``'s §8 handler-lifecycle entry for
        this ``<skill_id>:stop`` dispatch: the dispatch goes out on the spec
        colon-topic ``<skill_id>:stop``, which ovos-workshop has no direct
        listener for, so nothing else emits the normal completion signal for
        it. This ``.stop.response`` is the real completion signal — it only
        fires once ``stop()`` has actually finished — so it is the correct
        point to resolve the dispatch, instead of leaving it parked on the
        dispatcher's 5-minute §8.3 timeout. Emitting the framework done-signal
        here, rather than reaching into ``IntentDispatcher`` directly, keeps
        ``StopService`` decoupled from the dispatcher's internals.
        """
        skill_id = (message.data.get("skill_id") or
                    message.context.get("skill_id") or
                    message.msg_type.split(".stop.response")[0])
        sess_id = (message.context.get("session") or {}).get("session_id", "default")
        # Pop both snapshots unconditionally before either branch below: the
        # error/no-dispatch paths must not leak them or hold the
        # _resolve_dispatch_lifecycle gate open for this (session_id, skill_id).
        snapshot = self._pre_drain.pop((sess_id, skill_id), None)
        try:
            if snapshot is not None:
                self._resolve_dispatch_lifecycle(message, skill_id)
        except Exception:
            LOG.exception(f"failed to resolve dispatch lifecycle for {skill_id}:stop")
        if 'error' in message.data:
            error_msg = message.data['error']
            LOG.error(f"{skill_id}: {error_msg}")
        elif message.data.get('result', False):
            sess = SessionManager.get(message)
            # The session on this .stop.response is already post-drain, so
            # live reads of utterance_states/active_handlers lie; consult the
            # pre-drain snapshot popped above, falling back to the live read
            # for direct-invocation callers that bypass _targeted_stop.
            utt_state = snapshot.utt_state if snapshot else (
                UtteranceState.RESPONSE
                if sess.response_mode and sess.response_mode.get("skill_id") == skill_id
                else UtteranceState.INTENT)
            if utt_state == UtteranceState.RESPONSE:
                LOG.debug("Forcing get_response timeout")
                # force-kill any ongoing get_response - see @killable_event decorator (ovos-workshop)
                self.bus.emit(message.reply("mycroft.skills.abort_question", {"skill_id": skill_id}))
            was_active = snapshot.was_active if snapshot else sess.is_active(skill_id)
            if was_active:
                LOG.debug("Forcing converse timeout")
                # force-kill any ongoing converse - see @killable_event decorator (ovos-workshop)
                self.bus.emit(message.reply("ovos.skills.converse.force_timeout", {"skill_id": skill_id}))

            # TODO - track if speech is coming from this skill! not currently tracked (ovos-audio)
            if sess.is_speaking:
                # force-kill any ongoing TTS
                # SpecMessage.AUDIO_STOP.value == "ovos.audio.stop"; the
                # translator's MIGRATION_MAP mirrors it onto the legacy
                # "mycroft.audio.speech.stop" ovos-audio still listens on.
                self.bus.emit(message.forward(SpecMessage.AUDIO_STOP.value, {"skill_id": skill_id}))

    def _resolve_dispatch_lifecycle(self, message: Message, skill_id: str) -> None:
        """Emit the framework done-signal for the ``<skill_id>:stop`` dispatch
        this ``.stop.response`` concludes.

        ``IntentDispatcher._on_skill_complete``/``._on_skill_error`` listen for
        exactly these topics and resolve the matching in-flight entry (by
        session_id + skill_id + ``data["intent_name"]``), cancelling its §8.3
        timeout timer. See ``handle_stop_confirmation``'s docstring for why
        this lives here rather than in ovos-workshop.

        ``data["intent_name"] = "stop"`` is stamped explicitly, since a
        skill can have an ordinary intent handler running concurrently with
        its ``.stop`` — the dispatcher's ``_pop`` needs it to resolve the
        right in-flight entry rather than whichever is on top of the LIFO
        stack. It goes on ``data``, not ``context``: see ``_pop``'s docstring
        in dispatcher.py for why context is client-inherited and unsafe here.

        §8.2: a ``.stop.response`` carrying ``error`` resolves as an
        ``error`` terminal, not ``complete``.
        """
        if 'error' in message.data:
            done = message.forward("mycroft.skill.handler.error",
                                   {"name": f"{skill_id}:stop",
                                    "exception": message.data['error'],
                                    "intent_name": "stop"})
        else:
            done = message.forward("mycroft.skill.handler.complete",
                                   {"name": f"{skill_id}:stop",
                                    "intent_name": "stop"})
        done.context["skill_id"] = skill_id
        self.bus.emit(done)

    def _targeted_stop(self, skill_id: str, conf: float, utterance: str,
                       sess: Session) -> IntentHandlerMatch:
        """Build the OVOS-STOP-1 §2 targeted ``<skill_id>:stop`` Match.

        Drains the dispatch target from ``active_handlers`` and clears its
        ``response_mode`` entry (§6.1/§6.2) via ``Match.updated_session``. The
        §7.1 stamping push is suppressed (``suppress_activation``, §7.3), so the
        removal is the final state.

        CONFIRMED-3: match() must be side-effect-free — the orchestrator may
        still discard this Match (blacklisted intent, missing required slots, a
        dispatch exception) without ever consuming ``updated_session``, so the
        drain is carried on a COPY and only lands on the live SessionManager
        session if/when ``_dispatch_match`` actually commits it. The live
        ``sess`` passed in is read but never mutated here.
        """
        LOG.debug(f"Telling skill to stop: {skill_id}")
        # Captured before the drain: the post-drain session that reaches
        # handle_stop_confirmation via the dispatch round-trip can no longer
        # answer either question truthfully.
        self._pre_drain[(sess.session_id, skill_id)] = PreDrainSnapshot(
            was_active=sess.is_active(skill_id),
            utt_state=(UtteranceState.RESPONSE
                       if sess.response_mode and sess.response_mode.get("skill_id") == skill_id
                       else UtteranceState.INTENT),
        )
        drained = Session.deserialize(sess.serialize())
        drained.disable_response_mode(skill_id)
        drained.deactivate_skill(skill_id)
        self.bus.once(f"{skill_id}.stop.response", self.handle_stop_confirmation)
        return IntentHandlerMatch(
            match_type=f"{skill_id}:stop",
            match_data={"conf": conf, "skill_id": skill_id},
            updated_session=drained,
            utterance=utterance,
            skill_id=skill_id,
            suppress_activation=self.suppress_activation,
        )

    def _global_stop(self, conf: float, utterance: str,
                     sess: Session) -> IntentHandlerMatch:
        """Build the OVOS-STOP-1 §5 global ``<pipeline_id>:global_stop`` Match.

        Carries a fully-cleaned ``updated_session`` (§5.2): ``active_handlers``
        and ``converse_handlers`` emptied and ``response_mode`` removed, all
        committed before dispatch.

        CONFIRMED-3: side-effect-free like ``_targeted_stop`` — the clear is
        carried on a COPY, never the live ``sess``, so a discarded Match
        (blacklist/missing-slots/dispatch-exception) leaves the live session
        untouched.
        """
        LOG.info(f"Emitting global stop, {len(sess.active_handlers)} active skills")
        # read-only: the pre-drain holder, carried through match_data so
        # handle_global_stop (dispatch time, NOT here) can emit the targeted
        # `<skill_id>.stop` a killable-event abort actually listens on —
        # emitting it here would violate the CONFIRMED-3 side-effect-free
        # match() invariant, since this Match can still be discarded.
        holder = sess.response_mode.get("skill_id") if sess.response_mode else None
        drained = Session.deserialize(sess.serialize())
        drained.active_handlers = []
        drained.converse_handlers = []
        drained.clear_response_mode()
        match_data = {"conf": conf}
        if holder:
            match_data["response_mode_holder"] = holder
        return IntentHandlerMatch(
            match_type=f"{self.pipeline_id}:global_stop",
            match_data=match_data,
            updated_session=drained,
            utterance=utterance,
            skill_id=self.pipeline_id,
            suppress_activation=self.suppress_activation,
        )

    def match_high(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """
        Handle high-confidence stop requests by matching exact stop vocabulary (§4/§5).

        - explicit ``global_stop`` vocabulary (or bare ``stop`` with no active
          skills) yields a §5 global stop;
        - a bare ``stop`` with active skills runs the §4 cascade and yields a
          targeted ``<skill_id>:stop`` for the recency-selected stoppable skill.

        Parameters:
            utterances (List[str]): List of user utterances to match against stop vocabulary
            lang (str): Four-letter ISO language code for language-specific matching
            message (Message): Message context for generating appropriate responses

        Returns:
            Optional[IntentHandlerMatch]: the stop Match, or None if no stop
            vocabulary matched.
        """
        sess = SessionManager.get(message)

        # we call flatten in case someone is sending the old style list of tuples
        utterance = flatten_list(utterances)[0]

        is_stop = self._locale.voc_match(utterance, 'stop', lang, exact=True)
        is_global_stop = self._locale.voc_match(utterance, 'global_stop', lang, exact=True) or \
                         (is_stop and not len(self._stop_candidates(message)))

        conf = 1.0

        if is_global_stop:
            return self._global_stop(conf, utterance, sess)

        if is_stop:
            # check if any skill can stop (§4 cascade)
            for skill_id in self._collect_stop_skills(message):
                return self._targeted_stop(skill_id, conf, utterance, sess)

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

        is_stop = self._locale.voc_match(utterance, 'stop', lang, exact=False)
        if not is_stop:
            is_global_stop = self._locale.voc_match(utterance, 'global_stop', lang, exact=False) or \
                             (is_stop and not len(self._stop_candidates(message)))
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

        stop_vocs = self._locale.voc_list('stop', lang)
        if not stop_vocs:
            return None

        conf = match_one(utterance, stop_vocs)[1]
        if len(self.get_active_skills(message)) > 0:
            conf += 0.1
        conf = round(min(conf, 1.0), 3)

        if conf < self.config.get("min_conf", 0.5):
            return None

        # check if any skill can stop (§4 cascade)
        for skill_id in self._collect_stop_skills(message):
            return self._targeted_stop(skill_id, conf, utterance, sess)

        # no positive pong responder -> escalate to a §5 global stop
        return self._global_stop(conf, utterance, sess)

    def shutdown(self) -> None:
        """Remove bus listeners registered by this service."""
        self.bus.remove(f"{self.pipeline_id}:global_stop", self.handle_global_stop)
        self._legacy.shutdown()
