import time
from threading import Event, Lock, Timer
from typing import Optional, Dict, List, Union

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.handler import HandlerLifecycle
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, UtteranceState, Session
from ovos_config.config import Configuration
from ovos_utils import flatten_list
from ovos_utils.fakebus import FakeBus
from ovos_spec_tools import standardize_lang
from ovos_utils.log import LOG

from ovos_plugin_manager.templates.pipeline import PipelinePlugin, IntentHandlerMatch
from ovos_workshop.permissions import ConverseMode, ConverseActivationMode

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
    def _registry_session_for_write(message: Optional[Message]) -> "Session":
        """Resolve the session object to mutate for an INCIDENTAL converse
        write path - one that does NOT echo the resulting session back onto
        the wire (``message.context["session"] = session.serialize()``) and
        is not part of a chain that already resolved the session once for
        this lifecycle-entry call.

        FOLD-ORDER CONTRACT (read this before adding a new call site):

        ``SessionManager.get(message)`` is NEVER a pure read. It always
        folds the incoming message's session snapshot onto the live
        registry entry (``SessionManager._store`` -> ``Session.update_from``,
        full serialize/deserialize replace, for every session id including
        ``"default"``) and returns THAT live object. So every call is a
        write of the message's declared state onto the registry, whether or
        not the caller goes on to mutate anything itself.

        That fold is *correct and required* at two kinds of site:
          1. True lifecycle entry (e.g. ``match()``'s own top-level
             ``SessionManager.get(message)`` call) - SESSION-2 last-writer-
             wins: the client's freshly-declared fields (lang, blacklist,
             client-side (de)activations) must apply here.
          2. Any site that stamps the resolved session back onto the wire
             via ``message.context["session"] = session.serialize()``
             (``activate_skill`` / ``deactivate_skill`` below) - bypassing
             the fold there would silently discard the client's own
             declarations from the outgoing message, e.g. resurrecting a
             skill the client had just blacklisted. These sites MUST use
             plain ``SessionManager.get(message)``, not this helper.

        The fold is *wrong* (and this helper exists to avoid it) only for
        an INCIDENTAL write with no wire echo, where a STALE message (one
        that predates state written to the registry earlier in the same
        session's lifecycle, e.g. by a prior ``get_response.enable`` call)
        would otherwise wipe that state via the full-replace fold before
        this handler's own write lands. ``get_response.enable/disable``
        below are the load-bearing example: they only ``SessionManager.sync``
        for the default session, so a named session's write was being
        wiped on every subsequent fold with no recovery.

        RESIDUAL (not fixed by this helper, tracked as a known gap): a
        case-2 wire-echo site (``activate_skill`` / ``deactivate_skill``)
        still full-replaces the registry entry when it folds. So a
        case-3 write this helper protects (e.g. ``get_response.enable``)
        only survives until the NEXT stale ``activate_skill`` /
        ``deactivate_skill`` call for that same session - executed proof:
        enable get_response for a named session, then drive a stale
        ``activate_skill`` call for the same session id, and
        ``utterance_states`` is wiped back to empty. This is pre-existing
        on ``dev`` (``activate_skill``/``deactivate_skill`` already used
        plain ``SessionManager.get(message)`` before this PR) and is
        unchanged by this PR - this helper narrows the window, it does not
        close it. Fixing it for real needs case-2 sites to fold
        per-field (client wins only on fields it actually declares) rather
        than full-replace; out of scope here.

        A THIRD case - repeated folding within a single synchronous call
        chain sharing one message (``match()`` -> ``_collect_converse_skills``
        / ``get_active_skills``) - is neither of the above: fold once at
        the top (case 1) and THREAD that resolved ``session`` object
        through the rest of the chain via an explicit parameter; do not
        call ``SessionManager.get(message)``/this helper again per
        sub-step, each additional call re-folds the same stale message and
        undoes whatever the previous step in the chain just wrote. Note
        ``_check_converse_timeout`` does NOT need this treatment: verified
        by mutation testing, it sits between two folds of the identical
        message with no intervening write, so re-folding there is
        idempotent - see its own docstring.

        This mirrors ``IntentService._registry_session_for_context_write``
        (#857, ``ovos_core/intent_services/service.py``) exactly for case-3
        incidental writes, but is a deliberately separate copy: the
        intent-context handlers and these converse write paths are
        different call sites landing in different PRs. Do not delete this
        helper assuming #857 covers it - when both PRs are merged, consider
        consolidating the two into one shared helper, but until then each
        pairs with its own call sites.

        Resolution: resolve session_id off the message and, if the registry
        already holds a live entry for it, mutate that object directly - no
        fold. Fall back to ``SessionManager.get(message)`` (today's
        behavior) only when no registry entry exists yet, e.g.
        out-of-registry/test callers or a message with no session context.
        """
        session_data = message.context.get("session") if message and message.context else None
        session_id = session_data.get("session_id") if isinstance(session_data, dict) else None
        if session_id and session_id in SessionManager.sessions:
            return SessionManager.sessions[session_id]
        return SessionManager.get(message)

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
            # peek at the ack's session id WITHOUT folding its snapshot onto
            # the live session — the ack still carries the pre-dispatch
            # snapshot, and folding it would clobber any change the converse
            # handler made to the live session (e.g. deactivating itself)
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
                     pass this when called as part of a chain that already
                     folded once for this lifecycle entry (see
                     ``_registry_session_for_write``'s fold-order contract);
                     re-resolving via ``message`` here would re-fold and can
                     undo a write an earlier step in the same chain made.

        Returns:
            active_skills (list): ordered list of skill_ids
        """
        session = session or SessionManager.get(message)
        return [skill[0] for skill in session.active_skills]

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
            # this session gets stamped back onto the outgoing wire message
            # below, so the fold must apply here (see the fold-order
            # contract on _registry_session_for_write): the client's own
            # declarations must win, not be silently bypassed.
            session = SessionManager.get(message)
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
            # this session gets stamped back onto the outgoing wire message
            # below, so the fold must apply here (see the fold-order
            # contract on _registry_session_for_write): the client's own
            # declarations must win, not be silently bypassed.
            session = SessionManager.get(message)
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
                     re-folding ``message`` (see ``match()``, which folds
                     once and threads the result through this whole call
                     chain - see the fold-order contract on
                     ``_registry_session_for_write``). Falls back to a
                     fresh ``SessionManager.get(message)`` fold for
                     standalone callers.
        """
        skill_ids = []
        want_converse = []
        session = session or SessionManager.get(message)

        # note: this is sorted by priority already
        active_skills = [skill_id for skill_id in self.get_active_skills(message, session=session)
                     if session.utterance_states.get(skill_id, UtteranceState.INTENT) == UtteranceState.INTENT]
        if not active_skills:
            return want_converse

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

            # validate the converse pong; default False — a non-responding skill should not converse
            if all((skill_id not in want_converse,
                    msg.data.get("can_handle", False),
                    skill_id in active_skills)):
                want_converse.append(skill_id)

            if skill_id not in skill_ids:  # track which answer we got
                skill_ids.append(skill_id)

            if all(s in skill_ids for s in active_skills):
                # all skills answered the ping!
                event.set()

        self.bus.on("skill.converse.pong", handle_ack)
        try:
            # ask skills if they want to converse
            for skill_id in active_skills:
                self.bus.emit(message.forward(f"{skill_id}.converse.ping", {**message.data, "skill_id": skill_id}))

            # wait for all skills to acknowledge they want to converse
            event.wait(timeout=0.5)
        finally:
            self.bus.remove("skill.converse.pong", handle_ack)
        return want_converse

    def _check_converse_timeout(self, message: Message):
        """ filter active skill list based on timestamps

        Note: unlike ``_collect_converse_skills``/``get_active_skills``,
        this method does NOT accept a threaded ``session`` param. Verified
        by mutation testing (reverting both the param and a
        registry-first-helper fallback here left the full converse test
        suite green): ``match()``'s own top-level ``SessionManager.get(message)``
        fold and a fresh fold here resolve to the identity-same live
        registry object with no intervening write between the two calls in
        this synchronous frame, so re-folding here is idempotent - unlike
        the fold immediately after this call inside ``_collect_converse_skills``,
        which WOULD wipe the active_skills filter this method just wrote if
        it re-folded instead of using the threaded object. Keep this site
        plain (YAGNI); do not add the param back without a red test proving
        it does something.
        """
        timeouts = self.config.get("skill_timeouts") or {}
        def_timeout = self.config.get("timeout", 300)
        session = SessionManager.get(message)
        session.active_skills = [
            skill for skill in session.active_skills
            if time.time() - skill[1] <= timeouts.get(skill[0], def_timeout)]

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
        # this is the lifecycle-entry fold for this pipeline's turn at the
        # utterance (SESSION-2 last-writer-wins is correct here) - `session`
        # is threaded through every sub-call in this method instead of each
        # one re-resolving via `message`, which would re-fold the same
        # message repeatedly and undo whatever the previous sub-call just
        # wrote (see the fold-order contract on
        # `_registry_session_for_write`).
        session = SessionManager.get(message)

        # we call flatten in case someone is sending the old style list of tuples
        utterances = flatten_list(utterances)

        # note: this is sorted by priority already
        gr_skills = [skill_id for skill_id in self.get_active_skills(message, session=session)
                     if session.utterance_states.get(skill_id, UtteranceState.INTENT) == UtteranceState.RESPONSE]

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
        session = ConverseService._registry_session_for_write(message)
        session.enable_response_mode(skill_id)
        if session.session_id == "default":
            SessionManager.sync(message)

    @staticmethod
    def handle_get_response_disable(message: Message):
        skill_id = message.data["skill_id"]
        session = ConverseService._registry_session_for_write(message)
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
