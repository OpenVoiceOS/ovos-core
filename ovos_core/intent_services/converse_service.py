import time
from threading import Event, Lock, Timer
from typing import Optional, Dict, List, Union

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.handler import HandlerLifecycle
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ovos_config.config import Configuration
from ovos_utils import flatten_list
from ovos_utils.fakebus import FakeBus
from ovos_spec_tools import standardize_lang
from ovos_utils.log import LOG

from ovos_plugin_manager.templates.pipeline import PipelinePlugin, IntentHandlerMatch
from ovos_workshop.permissions import ConverseMode, ConverseActivationMode

from ovos_core.intent_services.working_session import working_session

#: upper bound, seconds, on how long core waits for a skill's
#: ``skill.converse.response`` before the dispatch lifecycle is declared a
#: timeout (``mycroft.skill.handler.error``). Generous: converse handlers may
#: legitimately run a while, but this must eventually backstop a silent skill so
#: an orchestrator observing the done-signal never hangs on the in-flight
#: dispatch.
CONVERSE_HANDLER_TIMEOUT = 5 * 60


class ConverseService(PipelinePlugin):
    """Intent Service handling conversational skills."""

    @staticmethod
    def _session_for_write(message: Optional[Message]) -> "Session":
        """Resolve the session object a converse write should mutate.

        Converse's write paths are all reached from a bus event a skill emits
        while its round is in flight — an activation request, a get_response
        toggle. OVOS-SESSION-2 §2.6 says such a Message does not revise the
        working session with its own carrier, so the write lands on the
        session the round is already running on, found by ``utterance_id``.

        With no round open the write is out-of-band. The default session is
        the device's store and remains writable at any time (§5); a named
        session resolves to a throwaway built from the carrier, because §2.2
        leaves the orchestrator holding nothing for it between utterances and
        there is no session here for the write to reach.
        """
        return working_session(message) or SessionManager.get(message)

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None) -> None:
        config = config or Configuration().get("skills", {}).get("converse", {})
        super().__init__(bus, config)
        self._consecutive_activations = {}
        self.bus.on('intent.service.skills.deactivate', self.handle_deactivate_skill_request)
        self.bus.on('intent.service.skills.activate', self.handle_activate_skill_request)
        self.bus.on('intent.service.active_skills.get', self.handle_get_active_skills)
        self.bus.on("skill.converse.get_response.enable", self.handle_get_response_enable)
        self.bus.on("skill.converse.get_response.disable", self.handle_get_response_disable)
        self.bus.on("converse:skill", self.handle_converse)

    def handle_converse(self, message: Message):
        """Priority-based skill activation and deactivation. Tracks active skills per session, handles converse requests, and manages lifecycle events."""
        skill_id = message.data["skill_id"]
        # the dispatch belongs to this session; only an ack carrying the same
        # session may resolve it (a concurrent converse dispatch to the same
        # skill in another session must not cross-resolve).
        session_id = SessionManager.get(message).session_id

        lifecycle = HandlerLifecycle(self.bus, message, skill_id=skill_id,
                                     handler_name=f"{skill_id}.converse")

        resolved = Event()
        resolve_lock = Lock()

        def _claim() -> bool:
            with resolve_lock:
                if resolved.is_set():
                    return False
                resolved.set()
                return True

        def _resolve_complete(msg: Message) -> None:
            if msg.data.get("skill_id") and msg.data.get("skill_id") != skill_id:
                return  # ack from a different skill, ignore
            # only peek at the ack's session id; an incidental Message does
            # not revise the working session (SESSION-2 §2.6).
            ack_sess = Session.from_message(msg) if "session" in msg.context else None
            if ack_sess and ack_sess.session_id != session_id:
                return  # ack from a different session, ignore
            if not _claim():
                return
            timer.cancel()
            self.bus.remove("skill.converse.response", _resolve_complete)
            lifecycle.complete()

        def _resolve_timeout() -> None:
            if not _claim():
                return
            self.bus.remove("skill.converse.response", _resolve_complete)
            LOG.warning(f"converse dispatch to {skill_id} timed out after "
                        f"{CONVERSE_HANDLER_TIMEOUT}s; emitting handler error")
            lifecycle.error(TimeoutError(
                f"converse handler timed out after {CONVERSE_HANDLER_TIMEOUT} seconds"))

        timer = Timer(CONVERSE_HANDLER_TIMEOUT, _resolve_timeout)
        timer.daemon = True

        self.bus.on("skill.converse.response", _resolve_complete)
        timer.start()
        # mycroft.skill.handler.start, then the dispatch itself
        lifecycle.start()
        self.bus.emit(message.reply(f"{skill_id}.converse.request", message.data))

    @property
    def active_skills(self):
        session = SessionManager.get()
        return session.active_skills

    @active_skills.setter
    def active_skills(self, val):
        session = SessionManager.get()
        session.active_skills = []
        for skill_id, ts in val:
            session.activate_skill(skill_id)

    @staticmethod
    def get_active_skills(message: Optional[Message] = None,
                          session: Optional[Session] = None) -> List[str]:
        """Active skill ids ordered by converse priority
        this represents the order in which converse will be called

        Args:
            message: bus message to resolve a session from when ``session``
                     is not already known (standalone/incidental callers).
            session: an already-resolved session to read from directly -
                     pass this when the caller is a step in a chain that
                     already resolved it, so every step reads the one object
                     the round is mutating.

        Returns:
            active_skills (list): ordered list of skill_ids
        """
        session = session or SessionManager.get(message)
        return [h["skill_id"] for h in session.active_handlers]

    def deactivate_skill(self, skill_id: str, source_skill: Optional[str] = None,
                         message: Optional[Message] = None) -> Optional[Session]:
        """Remove a skill from being targetable by converse.

        Args:
            skill_id (str): skill to remove
            source_skill (str): skill requesting the removal
            message (Message): the bus message that requested deactivation

        Returns:
            the resolved Session if a deactivation actually happened
            (callers can reuse it instead of re-resolving via
            ``SessionManager.get(message)``), else None (blocked or
            already-inactive no-op - nothing changed, nothing to reuse).
        """
        source_skill = source_skill or skill_id
        if self._deactivate_allowed(skill_id, source_skill):
            message = message or Message("")
            session = self._session_for_write(message)
            if session.is_active(skill_id):
                # update converse session
                session.deactivate_skill(skill_id)

                # keep message.context
                message.context["session"] = session.serialize()  # update session active skills
                # send bus event
                self.bus.emit(
                    message.forward("intent.service.skills.deactivated",
                                    data={"skill_id": skill_id}))
                if skill_id in self._consecutive_activations:
                    self._consecutive_activations[skill_id] = 0
                return session
        return None

    def activate_skill(self, skill_id: str, source_skill: Optional[str] = None,
                       message: Optional[Message] = None) -> Optional[Session]:
        """Add a skill or update the position of an active skill.

        The skill is added to the front of the list, if it's already in the
        list it's removed so there is only a single entry of it.

        Args:
            skill_id (str): identifier of skill to be added.
            source_skill (str): skill requesting the removal
            message (Message): the bus message that requested activation
        """
        source_skill = source_skill or skill_id
        if self._activate_allowed(skill_id, source_skill):
            message = message or Message("")
            session = self._session_for_write(message)
            session.activate_skill(skill_id)

            # keep message.context
            message.context["session"] = session.serialize()  # update session active skills
            message = message.forward("intent.service.skills.activated",
                                      {"skill_id": skill_id})
            # send bus event
            self.bus.emit(message)
            # update activation counter
            self._consecutive_activations[skill_id] += 1
            return session

    def _activate_allowed(self, skill_id: str, source_skill: Optional[str] = None) -> bool:
        """Checks if a skill_id is allowed to jump to the front of active skills list

        - can a skill activate a different skill
        - is the skill blacklisted from conversing
        - is converse configured to only allow specific skills
        - did the skill activate too many times in a row

        Args:
            skill_id (str): identifier of skill to be added.
            source_skill (str): skill requesting the removal

        Returns:
            permitted (bool): True if skill can be activated
        """

        # cross activation control if skills can activate each other
        if not self.config.get("cross_activation"):
            source_skill = source_skill or skill_id
            if skill_id != source_skill:
                # different skill is trying to activate this skill
                return False

        # mode of activation dictates under what conditions a skill is
        # allowed to activate itself
        acmode = self.config.get("converse_activation") or \
                 ConverseActivationMode.ACCEPT_ALL
        if acmode == ConverseActivationMode.PRIORITY:
            prio = self.config.get("converse_priorities") or {}
            # only allowed to activate if no skill with higher priority is
            # active, currently there is no api for skills to
            # define their default priority, this is a user/developer setting
            priority = prio.get(skill_id, 50)
            if any(p > priority for p in
                   [prio.get(s, 50) for s in self.get_active_skills()]):
                return False
        elif acmode == ConverseActivationMode.BLACKLIST:
            if skill_id in self.config.get("converse_blacklist", []):
                return False
        elif acmode == ConverseActivationMode.WHITELIST:
            if skill_id not in self.config.get("converse_whitelist", []):
                return False

        # limit of consecutive activations
        default_max = self.config.get("max_activations", -1)
        # per skill override limit of consecutive activations
        skill_max = self.config.get("skill_activations", {}).get(skill_id)
        max_activations = skill_max if skill_max is not None else default_max
        if skill_id not in self._consecutive_activations:
            self._consecutive_activations[skill_id] = 0
        if max_activations < 0:
            pass  # no limit (mycroft-core default)
        elif max_activations == 0:
            return False  # skill activation disabled
        elif self._consecutive_activations.get(skill_id, 0) > max_activations:
            return False  # skill exceeded authorized consecutive number of activations
        return True

    def _deactivate_allowed(self, skill_id: str, source_skill: Optional[str] = None) -> bool:
        """Checks if a skill_id is allowed to be removed from active skills list

        - can a skill deactivate a different skill

        Args:
            skill_id (str): identifier of skill to be added.
            source_skill (str): skill requesting the removal

        Returns:
            permitted (bool): True if skill can be deactivated
        """
        # cross activation control if skills can deactivate each other
        if not self.config.get("cross_activation"):
            source_skill = source_skill or skill_id
            if skill_id != source_skill:
                # different skill is trying to deactivate this skill
                return False
        return True

    def _converse_allowed(self, skill_id: str) -> bool:
        """Checks if a skill_id is allowed to converse

        - is the skill blacklisted from conversing
        - is converse configured to only allow specific skills

        Args:
            skill_id (str): identifier of skill that wants to converse.

        Returns:
            permitted (bool): True if skill can converse
        """
        opmode = self.config.get("converse_mode",
                                 ConverseMode.ACCEPT_ALL)
        if opmode == ConverseMode.BLACKLIST and skill_id in \
                self.config.get("converse_blacklist", []):
            return False
        elif opmode == ConverseMode.WHITELIST and skill_id not in \
                self.config.get("converse_whitelist", []):
            return False
        return True

    def _collect_converse_skills(self, message: Message,
                                 session: Optional[Session] = None) -> List[str]:
        """use the messagebus api to determine which skills want to converse

        Individual skills respond to this request via the `can_converse` method

        Args:
            message: the bus message driving this converse attempt.
            session: an already-resolved session to use instead of
                     resolving ``message`` again - ``match()`` resolves once
                     and threads the result through this whole call chain, so
                     every step reads and writes the one object the round is
                     running on. Standalone callers may omit it.
        """
        answered = []  # candidates whose first valid pong already landed
        claimed = set()  # candidates whose first valid pong was a claim
        session = session or self._session_for_write(message)

        # note: this is sorted by priority already
        active_skills = [skill_id for skill_id in self.get_active_skills(message, session=session)
                     if not (session.response_mode and session.response_mode.get("skill_id") == skill_id)]
        if not active_skills:
            return []

        event = Event()

        # OVOS-CONVERSE-1 §4.2 round correlation: the round IS the utterance
        # lifecycle, named by context.utterance_id (OVOS-PIPELINE-1 §9.1.1).
        # The ping carries it by `forward` derivation and the pong carries it
        # back by `reply` derivation — no skill-side action.
        round_uid = message.context.get("utterance_id")

        def handle_ack(msg: Message) -> None:
            nonlocal event
            skill_id = msg.data.get("skill_id")
            if not skill_id:
                return  # guard against malformed pong messages

            # A pong that cannot prove which question it answers never decides a
            # round: discard pongs from an earlier (or foreign) lifecycle. When
            # the round itself is unnamed the guard stands down, so a V0 caller
            # that never entered through the orchestrator behaves as before.
            if round_uid is not None and \
                    msg.context.get("utterance_id") != round_uid:
                LOG.debug(f"discarding stale converse pong from '{skill_id}': "
                          f"utterance_id {msg.context.get('utterance_id')!r} "
                          f"does not match round {round_uid!r}")
                return

            # OVOS-CONVERSE-1 §4.2: "the first valid pong per candidate wins".
            # During the dual-emit compat window a current skill answers the
            # round twice — once on the broadcast leg, once on the legacy
            # per-skill leg — so each candidate MUST be counted exactly once.
            if skill_id in answered:
                return
            answered.append(skill_id)

            # the claim boolean is `result` in OVOS-CONVERSE-1 §4.2 and
            # `can_handle` on the legacy per-skill leg. A missing or
            # non-boolean value is a decline: a skill that does not answer
            # clearly must not converse.
            claim = msg.data.get("result", msg.data.get("can_handle"))
            if claim is True:
                claimed.add(skill_id)

            if all(s in answered for s in active_skills):
                # every candidate named by the round has answered — nothing
                # more can arrive that the round would wait for
                event.set()

        self.bus.on("skill.converse.pong", handle_ack)  # legacy leg
        self.bus.on("ovos.converse.pong", handle_ack)  # OVOS-CONVERSE-1 §6.2
        try:
            # OVOS-CONVERSE-1 §4.2: ONE broadcast ping for the round. No
            # candidate identity travels in topic or payload — a skill decides
            # it is a candidate by testing its own skill_id against
            # context.session.converse_handlers, which `reply` carries along.
            #
            # The payload is the inbound data minus skill_id, so a skill that
            # binds BOTH legs decides the round from identical input whichever
            # ping reaches it first. Feeding the two legs different data makes
            # the verdict depend on which leg won the race.
            broadcast_data = {k: v for k, v in message.data.items()
                              if k != "skill_id"}
            self.bus.emit(message.reply("ovos.converse.ping", broadcast_data))

            # V0 compat: skills older than the broadcast binding only listen on
            # the per-skill legacy ping. Dual-emit keeps them in the contest;
            # the collector above counts each skill once whichever leg answers.
            for skill_id in active_skills:
                self.bus.emit(message.forward(f"{skill_id}.converse.ping",
                                              {**message.data, "skill_id": skill_id}))

            # one bounded collection window for the whole round, not n x a
            # per-owner wait (OVOS-CONVERSE-1 §4.2 stage collection ceiling)
            event.wait(timeout=0.5)
        finally:
            self.bus.remove("skill.converse.pong", handle_ack)
            self.bus.remove("ovos.converse.pong", handle_ack)

        # This is also what keeps a foreign pong out of the round
        # (OVOS-CONVERSE-1 §4.2): a skill_id absent from the candidate set
        # cannot appear in the returned list, and it can never satisfy the
        # early-close check above, which is keyed on `active_skills`.
        #
        # OVOS-CONVERSE-1 §4.1 step 3: selection is by recency order — the
        # order of session.converse_handlers — and is NEVER by response-arrival
        # order. Under a parallel broadcast round the arrival order is a race.
        return [skill_id for skill_id in active_skills if skill_id in claimed]

    def _check_converse_timeout(self, message: Message):
        """Drop active handlers whose converse window has expired.

        The filter is a write, so it goes on the round's own session; resolved
        from the message rather than threaded because every caller sits in the
        same round and gets the same object either way.
        """
        timeouts = self.config.get("skill_timeouts") or {}
        def_timeout = self.config.get("timeout", 300)
        session = self._session_for_write(message)
        session.active_handlers = [
            h for h in session.active_handlers
            if time.time() - h["activated_at"] <= timeouts.get(h["skill_id"], def_timeout)]

    def match(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """
        Attempt to converse with active skills for a given set of utterances.

        Iterates through active skills to find one that can handle the utterance. Filters skills based on timeout and blacklist status.

        Args:
            utterances (List[str]): List of utterance strings to process
            lang (str): 4-letter ISO language code for the utterances
            message (Message): Message context for generating a reply

        Returns:
            PipelineMatch: Match details if a skill successfully handles the utterance, otherwise None
            - handled (bool): Whether the utterance was fully handled
            - match_data (dict): Additional match metadata
            - skill_id (str): ID of the skill that handled the utterance
            - updated_session (Session): Current session state after skill interaction
            - utterance (str): The original utterance processed

        Notes:
            - Standardizes language tag
            - Filters out blacklisted skills
            - Checks for skill conversation timeouts
            - Attempts conversation with each eligible skill
        """
        lang = standardize_lang(lang)
        # the round's session, threaded through every sub-call below so
        # each step reads what the previous one wrote. The arrival already
        # happened at the orchestrator's lifecycle entry (SESSION-2 §5.1);
        # this pipeline does not fold again (§2.6).
        session = self._session_for_write(message)

        # we call flatten in case someone is sending the old style list of tuples
        utterances = flatten_list(utterances)

        # note: this is sorted by priority already
        gr_skills = [skill_id for skill_id in self.get_active_skills(message, session=session)
                     if session.response_mode and session.response_mode.get("skill_id") == skill_id]

        # check if any skill wants to capture utterance for self.get_response method
        for skill_id in gr_skills:
            if skill_id in (session.blacklisted_skills or []):
                LOG.debug(f"ignoring match, skill_id '{skill_id}' blacklisted by Session '{session.session_id}'")
                continue
            LOG.debug(f"utterance captured by skill.get_response method: {skill_id}")
            return IntentHandlerMatch(
                match_type=f"{skill_id}.converse.get_response",
                match_data={"utterances": utterances, "lang": lang},
                skill_id=skill_id,
                utterance=utterances[0],
                updated_session=session
            )

        # filter allowed skills
        self._check_converse_timeout(message)

        # check if any skill wants to converse
        for skill_id in self._collect_converse_skills(message, session=session):
            if skill_id in (session.blacklisted_skills or []):
                LOG.debug(f"ignoring match, skill_id '{skill_id}' blacklisted by Session '{session.session_id}'")
                continue
            LOG.debug(f"Attempting to converse with skill: {skill_id}")
            if self._converse_allowed(skill_id):
                return IntentHandlerMatch(
                    match_type="converse:skill",
                    match_data={"utterances": utterances, "lang": lang, "skill_id": skill_id},
                    skill_id=skill_id,
                    utterance=utterances[0],
                    updated_session=session
                )

        return None

    @staticmethod
    def handle_get_response_enable(message: Message):
        skill_id = message.data["skill_id"]
        session = ConverseService._session_for_write(message)
        session.enable_response_mode(skill_id)
        if session.session_id == "default":
            SessionManager.sync(message)

    @staticmethod
    def handle_get_response_disable(message: Message):
        skill_id = message.data["skill_id"]
        session = ConverseService._session_for_write(message)
        session.disable_response_mode(skill_id)
        if session.session_id == "default":
            SessionManager.sync(message)

    def handle_activate_skill_request(self, message: Message):
        # TODO imperfect solution - only a skill can activate itself
        # someone can forge this message and emit it raw, but in OpenVoiceOS all
        # skill messages should have skill_id in context, so let's make sure
        # this doesnt happen accidentally at very least
        skill_id = message.data['skill_id']
        source_skill = message.context.get("skill_id")
        # reuse the already-resolved live session `activate_skill` folded
        # and wrote to - a second `SessionManager.get(message)` here would
        # re-fold the SAME stale message and, on the reject/no-op path
        # (`activate_skill` returns None), there is nothing to sync at all.
        sess = self.activate_skill(skill_id, source_skill, message)
        if sess is not None and sess.session_id == "default":
            SessionManager.sync(message)

    def handle_deactivate_skill_request(self, message: Message):
        # TODO imperfect solution - only a skill can deactivate itself
        # someone can forge this message and emit it raw, but in ovos-core all
        # skill message should have skill_id in context, so let's make sure
        # this doesnt happen accidentally
        skill_id = message.data['skill_id']
        source_skill = message.context.get("skill_id") or skill_id
        # reuse the already-resolved live session `deactivate_skill` folded
        # and wrote to - a second `SessionManager.get(message)` here would
        # re-fold the SAME stale message and, on the reject/no-op path
        # (`deactivate_skill` returns None), there is nothing to sync at all.
        sess = self.deactivate_skill(skill_id, source_skill, message)
        if sess is not None and sess.session_id == "default":
            SessionManager.sync(message)

    def handle_get_active_skills(self, message: Message):
        """Send active skills to caller.

        Argument:
            message: query message to reply to.
        """
        self.bus.emit(message.reply("intent.service.active_skills.reply",
                                    {"skills": self.get_active_skills(message)}))

    def shutdown(self) -> None:
        self.bus.remove("converse:skill", self.handle_converse)
        self.bus.remove('intent.service.skills.deactivate', self.handle_deactivate_skill_request)
        self.bus.remove('intent.service.skills.activate', self.handle_activate_skill_request)
        self.bus.remove('intent.service.active_skills.get', self.handle_get_active_skills)
        self.bus.remove("skill.converse.get_response.enable", self.handle_get_response_enable)
        self.bus.remove("skill.converse.get_response.disable", self.handle_get_response_disable)
