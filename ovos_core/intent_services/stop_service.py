from os.path import dirname, join
from threading import Event
from typing import Optional, Dict, List, NamedTuple, Set, Tuple, Union

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
from ovos_core.version import VERSION_MAJOR

#: Removal is scheduled for the next major release; derived from version.py so
#: the deprecation notice never goes stale.
_LEGACY_PING_REMOVAL_VERSION = f"{VERSION_MAJOR + 1}.0.0"


class PreDrainSnapshot(NamedTuple):
    """State a targeted stop observed before match() drained the session copy.

    ``match()`` drains ``active_handlers``/``response_mode`` before dispatch,
    so by the time ``.stop.response`` arrives the live session already lies
    about both fields. OVOS-PIPELINE-1 §4.2 permits a plugin's own bus side
    effects and internal bookkeeping inside ``match()`` — this is recorded
    there, keyed by ``(utterance_id, skill_id)``, and popped in
    ``handle_stop_confirmation`` before either result branch runs. Keying by
    the round rather than the session means a barge-in for a NEW utterance in
    the same session can never evict a still-running dispatched stop's
    snapshot — only that round's own §9.5 ``ovos.utterance.handled`` end
    marker does (see ``_on_utterance_handled``), and a dispatched stop is
    always consumed before its own round's end marker fires.
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

    The reserved ``stop`` intent_name suppresses the OVOS-PIPELINE-1 §7.1
    activation push by the §7.3 registry; ``global_stop`` is not reserved and
    pushes (STOP-1 §5.2). Neither is a property of the Match — the
    orchestrator reads the registry. The session drain mandated by §5.2/§6 is
    committed via ``Match.updated_session`` before dispatch.
    """

    #: OVOS-STOP-1 §3.1 shared identity. Every confidence tier reports the same
    #: ``pipeline_id`` so the global-stop handler binds a single topic across
    #: tiers and exactly one ``ovos.stop`` broadcast is emitted per event.
    pipeline_id = "ovos-stop-pipeline-plugin"

    #: one-shot guard for the legacy per-skill ping deprecation notice
    _warned_legacy_ping = False

    def __init__(self, bus: Optional[Union[MessageBusClient, FakeBus]] = None,
                 config: Optional[Dict] = None) -> None:
        config = config if config is not None else Configuration().get("skills", {}).get("stop") or {}
        bus = bus or FakeBus()
        ConfidenceMatcherPipeline.__init__(self, config=config, bus=bus)
        self._locale = LocaleResources(skill_locale=join(dirname(__file__), "locale"))
        # §5 global-stop dispatch target; bound once, shared across tiers (§3.1).
        self.bus.on(f"{self.pipeline_id}:global_stop", self.handle_global_stop)
        # The ONLY `_pre_drain` eviction: §9.5's universal, exactly-once-per-
        # round end marker.
        self.bus.on(SpecMessage.UTTERANCE_HANDLED.value, self._on_utterance_handled)
        self._legacy = _LegacyStopBridge(self)
        #: (utterance_id, skill_id) -> PreDrainSnapshot recorded by
        #: `_targeted_stop` and consumed once by `handle_stop_confirmation`.
        #: Keyed per-round (not bare skill_id) so two concurrent targeted
        #: stops for the same skill_id can't clobber each other's snapshot.
        self._pre_drain: Dict[Tuple[str, str], PreDrainSnapshot] = {}
        #: skill_ids with a permanent `<skill_id>.stop.response` listener
        #: already bound (see `_targeted_stop`).
        self._stop_listeners: Set[str] = set()

    def handle_global_stop(self, message: Message) -> None:
        """OVOS-STOP-1 §5.3 — broadcast the universal ``ovos.stop``.

        Bound on ``<pipeline_id>:global_stop`` and wrapped in HandlerLifecycle
        so the orchestrator observes the §8 terminal for the dispatch.

        §5.3 names exactly one emission: "The handler dispatched by
        ``<pipeline_id>:global_stop`` MUST emit ``ovos.stop``". No per-skill
        topic is emitted alongside it — a component with user-visible activity
        subscribes to ``ovos.stop`` and ceases activity for the session_id in
        Message context.
        """
        with HandlerLifecycle(self.bus, message,
                              skill_id=self.pipeline_id,
                              data={"name": "StopService.handle_global_stop"}):
            self.bus.emit(message.forward(SpecMessage.STOP.value))

    @staticmethod
    def get_active_skills(message: Optional[Message] = None) -> List[str]:
        """Active skill ids ordered by converse priority.

        This is the OVOS-STOP-1 §4.1 recency input (``active_handlers``): the
        order in which stop is attempted.

        OVOS-PIPELINE-1 §7.1 defines the recency order once, normatively, and
        forbids consumers from defining their own: ``activated_at`` is
        authoritative, and entries sharing an ``activated_at`` are ordered by
        proximity to the head of the list. Sorting is stable, so listing the
        entries head-first and sorting by descending ``activated_at`` applies
        both rules.

        Returns:
            active_skills (list): ordered list of skill_ids
        """
        session = SessionManager.get(message)
        handlers = sorted(session.active_handlers,
                          key=lambda h: h.get("activated_at") or 0,
                          reverse=True)
        return [h["skill_id"] for h in handlers]

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

        §4.1's candidate set "additionally includes, as its first member, the
        ``skill_id`` named by ``session.response_mode``" — CONVERSE-1 §2.2
        sets that field with no ``active_handlers`` push, so its holder would
        otherwise be invisible despite being the most recent interaction by
        construction. The recency-ordered ``active_handlers`` entries follow.

        The §4.1 candidate filter then drops, before any recency comparison,
        an entry whose ``skill_id`` is blacklisted (§6.3) or equals this
        plugin's own ``pipeline_id`` — the entry §7.1 stamps for a preceding
        ``global_stop`` dispatch. "The stop plugin is never its own stop
        target."
        """
        sess = SessionManager.get(message)
        blacklisted = sess.blacklisted_skills or []
        candidates: List[str] = []
        holder = self.get_response_mode_holder(message)
        for skill_id in [holder] + self.get_active_skills(message):
            if skill_id and skill_id not in candidates \
                    and skill_id not in blacklisted \
                    and skill_id != self.pipeline_id:
                candidates.append(skill_id)
        return candidates

    def _collect_stop_skills(self, message: Message) -> List[str]:
        """OVOS-STOP-1 §4 ping-pong: ask each active skill whether it can
        stop, wait up to 0.5s (§4.1), and return the stoppable ones in
        recency order. Falls back to all active skills if none confirm."""
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
            """Record a skill's stop-ping pong, and signal ``event`` once
            every active skill has answered."""
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

            # §4.2: a pong is valid only when it carries a `skill_id` string
            # and a `can_handle` BOOLEAN — "a truthy non-boolean value MUST
            # NOT be coerced to true". A missing or non-boolean `can_handle`
            # leaves the responder not stoppable for this round.
            if all((skill_id not in want_stop,
                    msg.data.get("can_handle") is True,
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
            # §4.1 step 2 / §4.2: one `ovos.stop.ping` BROADCAST, derived via
            # `reply` from the inbound utterance Message so it carries the
            # inbound session_id and the utterance emitter's routing metadata.
            self.bus.emit(message.reply(SpecMessage.STOP_PING.value))
            # Pre-spec compatibility: skills that predate the broadcast only
            # answer their own `<skill_id>.stop.ping`. Dropped in ovos-core
            # `_LEGACY_PING_REMOVAL_VERSION`.
            if not StopService._warned_legacy_ping:
                StopService._warned_legacy_ping = True
                LOG.warning(
                    "Emitting the pre-STOP-1 per-skill '<skill_id>.stop.ping' "
                    "alongside the 'ovos.stop.ping' broadcast for backward "
                    f"compatibility; removed in ovos-core "
                    f"{_LEGACY_PING_REMOVAL_VERSION}. Migrate skills to "
                    "subscribe to 'ovos.stop.ping'.")
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
        """Force-terminate the in-flight interactions a targeted stop killed.

        PIPELINE-1 §8 gives the handler-lifecycle trio to the orchestrator
        alone — "the orchestrator alone emits ``.complete`` on normal return
        or ``.error`` on exception, and that terminal event resolves the stop
        round. The stop handler does not emit either event itself" (STOP-1
        §4.3). This listener therefore only fires the kill signals the
        pre-drain snapshot says are owed.

        The ``.stop.response`` listener is bound permanently per skill_id
        (``_targeted_stop``), so this fires for every round's response for
        that skill, not just the one that just dispatched it. A response with
        no matching ``(utterance_id, skill_id)`` snapshot is therefore a
        no-op: either this skill_id was never targeted by a stop for this
        round, or its snapshot was already consumed/evicted.
        """
        skill_id = (message.data.get("skill_id") or
                    message.context.get("skill_id") or
                    message.msg_type.split(".stop.response")[0])
        utt_id = message.context.get("utterance_id")
        if not utt_id:
            # no round to correlate against (a V0/direct-invocation caller
            # that never entered through the orchestrator's §9.1.1 stamping)
            # -- `_targeted_stop` never records a snapshot for this case
            # either, so there is nothing to resolve.
            return
        snapshot = self._pre_drain.pop((utt_id, skill_id), None)
        if snapshot is None:
            return  # no pending targeted stop for this (round, skill) pair
        if 'error' in message.data:
            LOG.error(f"{skill_id}: {message.data['error']}")
        elif message.data.get('result', False):
            if snapshot.utt_state == UtteranceState.RESPONSE:
                LOG.debug("Forcing get_response timeout")
                # force-kill any ongoing get_response - see @killable_event decorator (ovos-workshop)
                self.bus.emit(message.reply("mycroft.skills.abort_question", {"skill_id": skill_id}))
            if snapshot.was_active:
                LOG.debug("Forcing converse timeout")
                # force-kill any ongoing converse - see @killable_event decorator (ovos-workshop)
                self.bus.emit(message.reply("ovos.skills.converse.force_timeout", {"skill_id": skill_id}))

            # TODO - track if speech is coming from this skill! not currently tracked (ovos-audio)
            if SessionManager.get(message).is_speaking:
                # force-kill any ongoing TTS
                # SpecMessage.AUDIO_STOP.value == "ovos.audio.stop"; the
                # translator's MIGRATION_MAP mirrors it onto the legacy
                # "mycroft.audio.speech.stop" ovos-audio still listens on.
                self.bus.emit(message.forward(SpecMessage.AUDIO_STOP.value, {"skill_id": skill_id}))

    def _on_utterance_handled(self, message: Message) -> None:
        """Evict every pending ``_pre_drain`` snapshot for a finished round.

        ``ovos.utterance.handled`` (§9.5) is the universal end marker: exactly
        one is emitted per utterance lifecycle, on every exit path (a
        dispatched Match's §8 terminal, a discarded/blacklisted Match, no
        Match at all). A snapshot still pending when its own round's end
        marker fires can only belong to a Match that was never dispatched, or
        was dispatched but never got a ``.stop.response`` back — either way
        the round is over and the snapshot is stale. A dispatched, genuinely
        answered stop is always popped by `handle_stop_confirmation` before
        this fires, so this is a no-op for it.
        """
        utt_id = message.context.get("utterance_id")
        if not utt_id:
            return
        for key in [k for k in self._pre_drain if k[0] == utt_id]:
            self._pre_drain.pop(key, None)

    def _targeted_stop(self, skill_id: str, utterance: str,
                       sess: Session, message: Message) -> IntentHandlerMatch:
        """Build the OVOS-STOP-1 §2 targeted ``<skill_id>:stop`` Match.

        Drains the dispatch target from ``active_handlers`` and clears its
        ``response_mode`` entry (§6.1/§6.2) via ``Match.updated_session``. The
        §7.1 stamping push is suppressed for the reserved ``stop``
        intent_name by the §7.3 registry, so the removal is the final state.

        match() must not touch the live session: the orchestrator may still
        discard this Match (blacklisted intent, missing required slots, a
        dispatch exception) without ever consuming ``updated_session``, so the
        drain is carried on a COPY and only lands on the live SessionManager
        session if/when ``_dispatch_match`` actually commits it. The live
        ``sess`` passed in is read but never mutated.

        Recording the ``_pre_drain`` snapshot and binding the (permanent,
        per-skill_id) ``.stop.response`` listener here, in ``match()``, is
        allowed by OVOS-PIPELINE-1 §4.2: a plugin's own bus registrations and
        internal bookkeeping are not dispatch actions. If this Match is later
        discarded, the snapshot is stale but not permanently leaked — it is
        keyed by ``message.context["utterance_id"]`` (§9.1.1, stamped by the
        orchestrator at lifecycle entry and carried by every derived Message),
        so it dies with that round's own §9.5 end marker (see
        ``_on_utterance_handled``) regardless of what happens to this Match.
        """
        LOG.debug(f"Telling skill to stop: {skill_id}")
        utt_id = message.context.get("utterance_id")
        if not utt_id:
            # No round to key the snapshot by (a V0/direct-invocation caller
            # that never entered through the orchestrator's §9.1.1 stamping).
            # The stop still dispatches; it just loses the automatic
            # get_response/converse kill signals.
            LOG.debug(f"no utterance_id on the stop Match for '{skill_id}'; "
                      f"skipping the pre-drain snapshot")
        else:
            # Captured before the drain: the post-drain session that reaches
            # handle_stop_confirmation via the dispatch round-trip can no
            # longer answer either question truthfully.
            self._pre_drain[(utt_id, skill_id)] = PreDrainSnapshot(
                was_active=sess.is_active(skill_id),
                utt_state=(UtteranceState.RESPONSE
                           if sess.response_mode and sess.response_mode.get("skill_id") == skill_id
                           else UtteranceState.INTENT),
            )
        if skill_id not in self._stop_listeners:
            self._stop_listeners.add(skill_id)
            self.bus.on(f"{skill_id}.stop.response", self.handle_stop_confirmation)
        drained = Session.deserialize(sess.serialize())
        drained.disable_response_mode(skill_id)
        drained.deactivate_skill(skill_id)
        return IntentHandlerMatch(
            match_type=f"{skill_id}:stop",
            match_data={"skill_id": skill_id},
            updated_session=drained,
            utterance=utterance,
            skill_id=skill_id,
        )

    def _global_stop(self, utterance: str, sess: Session) -> IntentHandlerMatch:
        """Build the OVOS-STOP-1 §5 global ``<pipeline_id>:global_stop`` Match.

        Carries a fully-cleaned ``updated_session`` (§5.2): ``active_handlers``
        and ``converse_handlers`` emptied and ``response_mode`` removed, all
        committed before dispatch.

        Like ``_targeted_stop``, match() must not touch the live session: the
        clear is carried on a COPY, never the live ``sess``, so a discarded
        Match (blacklist/missing-slots/dispatch-exception) leaves the live
        session untouched.
        """
        LOG.info(f"Emitting global stop, {len(sess.active_handlers)} active skills")
        drained = Session.deserialize(sess.serialize())
        drained.active_handlers = []
        drained.converse_handlers = []
        drained.clear_response_mode()
        return IntentHandlerMatch(
            match_type=f"{self.pipeline_id}:global_stop",
            match_data={},
            updated_session=drained,
            utterance=utterance,
            skill_id=self.pipeline_id,
        )

    def match_high(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """High-confidence stop match: exact stop vocabulary only (§4/§5).

        Explicit ``global_stop`` vocabulary (or bare ``stop`` with no active
        skills) yields a §5 global stop; a bare ``stop`` with active skills
        runs the §4 cascade and yields a targeted ``<skill_id>:stop`` for the
        recency-selected stoppable skill.
        """
        sess = SessionManager.get(message)

        # we call flatten in case someone is sending the old style list of tuples
        utterance = flatten_list(utterances)[0]

        is_stop = self._locale.voc_match(utterance, 'stop', lang, exact=True)
        is_global_stop = self._locale.voc_match(utterance, 'global_stop', lang, exact=True) or \
                         (is_stop and not self._stop_candidates(message))

        if is_global_stop:
            return self._global_stop(utterance, sess)

        if is_stop:
            # check if any skill can stop (§4 cascade)
            candidates = self._collect_stop_skills(message)
            if candidates:
                return self._targeted_stop(candidates[0], utterance, sess, message)

        return None

    def match_medium(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """Medium-confidence stop match: fuzzy ``stop``/``global_stop``
        vocabulary, delegated to ``match_low`` for the actual dispatch."""
        # we call flatten in case someone is sending the old style list of tuples
        utterance = flatten_list(utterances)[0]

        if not (self._locale.voc_match(utterance, 'stop', lang, exact=False) or
                self._locale.voc_match(utterance, 'global_stop', lang, exact=False)):
            return None
        return self.match_low(utterances, lang, message)

    def match_low(self, utterances: List[str], lang: str, message: Message) -> Optional[IntentHandlerMatch]:
        """Low-confidence fuzzy stop match, tried last before fallback.

        Confidence is boosted when active skills are present. Below
        ``min_conf`` (default 0.5), no match. Otherwise runs the §4 cascade
        and falls back to a §5 global stop when no skill responds.
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
        candidates = self._collect_stop_skills(message)
        if candidates:
            return self._targeted_stop(candidates[0], utterance, sess, message)

        # no positive pong responder -> escalate to a §5 global stop
        return self._global_stop(utterance, sess)

    def shutdown(self) -> None:
        """Remove bus listeners registered by this service."""
        self.bus.remove(f"{self.pipeline_id}:global_stop", self.handle_global_stop)
        self.bus.remove(SpecMessage.UTTERANCE_HANDLED.value, self._on_utterance_handled)
        for skill_id in self._stop_listeners:
            self.bus.remove(f"{skill_id}.stop.response", self.handle_stop_confirmation)
        self._stop_listeners.clear()
        self._legacy.shutdown()
