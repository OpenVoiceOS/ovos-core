# Copyright 2017 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import copy
import json
import re
import time
from uuid import uuid4
from collections import defaultdict
from typing import Optional, Tuple, Callable, List

import requests
from ovos_bus_client.message import Message
from ovos_bus_client.session import (SessionManager, Session, MalformedSession,
                                     session_carrier, _CONTEXT_LOCK)
from ovos_bus_client.util import get_message_lang
from ovos_config.config import Configuration
from ovos_config.locale import get_valid_languages
from ovos_spec_tools import closest_lang, standardize_lang, SpecMessage
from ovos_spec_tools.context import resolve_key
from ovos_spec_tools.session import merge_carrier, resolve_session_id
from ovos_utils.log import LOG
from ovos_utils.metrics import Stopwatch
from ovos_utils.process_utils import ProcessStatus, StatusCallbackMap
from ovos_utils.thread_utils import create_daemon

from ovos_core.transformers import MetadataTransformersService, UtteranceTransformersService, IntentTransformersService
from ovos_core.intent_services.dispatcher import IntentDispatcher, DEFAULT_HANDLER_TIMEOUT
from ovos_core.intent_services.manifest import IntentManifest
from ovos_core.intent_services.working_session import (
    close_round, open_round, pruned_entries, record_pruned, round_session, working_session,
)
from ovos_core.version import OVOS_VERSION_STR
from ovos_plugin_manager.pipeline import OVOSPipelineFactory
from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch, ConfidenceMatcherPipeline

from ovos_spec_tools.context import (
    gate_satisfied,
    context_supplied_slots,
    prune as prune_intent_context,
    decrement as decrement_intent_context,
)


# Module-level constants for pipeline matcher migration and optimization
_PIPELINE_MIGRATION_MAP = {
    "converse": "ovos-converse-pipeline-plugin",
    "common_qa": "ovos-common-query-pipeline-plugin",
    "fallback_high": "ovos-fallback-pipeline-plugin-high",
    "fallback_medium": "ovos-fallback-pipeline-plugin-medium",
    "fallback_low": "ovos-fallback-pipeline-plugin-low",
    "stop_high": "ovos-stop-pipeline-plugin-high",
    "stop_medium": "ovos-stop-pipeline-plugin-medium",
    "stop_low": "ovos-stop-pipeline-plugin-low",
    "adapt_high": "ovos-adapt-pipeline-plugin-high",
    "adapt_medium": "ovos-adapt-pipeline-plugin-medium",
    "adapt_low": "ovos-adapt-pipeline-plugin-low",
    "padacioso_high": "ovos-padacioso-pipeline-plugin-high",
    "padacioso_medium": "ovos-padacioso-pipeline-plugin-medium",
    "padacioso_low": "ovos-padacioso-pipeline-plugin-low",
    "padatious_high": "ovos-padatious-pipeline-plugin-high",
    "padatious_medium": "ovos-padatious-pipeline-plugin-medium",
    "padatious_low": "ovos-padatious-pipeline-plugin-low",
    "ocp_high": "ovos-ocp-pipeline-plugin-high",
    "ocp_medium": "ovos-ocp-pipeline-plugin-medium",
    "ocp_low": "ovos-ocp-pipeline-plugin-low",
    "ocp_legacy": "ovos-ocp-pipeline-plugin-legacy"
}

_PIPELINE_RE = re.compile(r'-(high|medium|low)$')

# OVOS-PIPELINE-1 §7.3 reserved intent_names. A Match produced by one of the
# reserving pipeline-plugin roles below is a reserved-name dispatch: §7.1
# requires the ``session.active_handlers`` push to be SUPPRESSED for it, because
# a reserved name represents a continuation/termination of an already-active
# skill's participation, not a fresh activation. Keyed off the producing
# pipeline_id (the role that holds the namespace lease), with the confidence
# suffix (``-high``/``-medium``/``-low``) stripped before lookup.
#
#   converse       -> ovos-converse-pipeline-plugin     (CONVERSE-1 §4/§5: converse, response)
#   fallback       -> ovos-fallback-pipeline-plugin      (FALLBACK-1 §6.3: fallback)
#   common_query   -> ovos-common-query-pipeline-plugin  (COMMON-QUERY-1 §3: common_query)
#
# OVOS-STOP-1 dispatches (``stop``/``global_stop``) also suppress the §7.1 push,
# but express it per-Match via ``IntentHandlerMatch.suppress_activation`` (§6.2)
# rather than through this pipeline_id table.
_RESERVED_NAME_PIPELINES = {
    "ovos-converse-pipeline-plugin",
    "ovos-fallback-pipeline-plugin",
    "ovos-common-query-pipeline-plugin",
}


def _produces_reserved_name(pipeline_id: Optional[str]) -> bool:
    """OVOS-PIPELINE-1 §7.3: True when ``pipeline_id`` is a reserved-name role
    whose dispatches must NOT stamp ``session.active_handlers`` (§7.1)."""
    if not pipeline_id:
        return False
    return _PIPELINE_RE.sub("", pipeline_id) in _RESERVED_NAME_PIPELINES


def _replace_intent_context(sess, new_ctx: dict) -> None:
    """Set a session's ``intent_context`` contents WITHOUT rebinding the dict.

    ``Session.intent_context`` dict identity must be preserved; see the
    ovos-bus-client ``_CONTEXT_LOCK`` contract (every live view — the adapt
    frame-stack projection, a mid-round ``ovos.session.sync`` merge — holds
    the same map object). It also stays a dict, never ``None``: an empty
    context is an empty dict.
    """
    with _CONTEXT_LOCK:
        if sess.intent_context is None:
            sess.intent_context = {}
        sess.intent_context.clear()
        sess.intent_context.update(new_ctx)


def on_started():
    LOG.info('IntentService is starting up.')


def on_alive():
    LOG.info('IntentService is alive.')


def on_ready():
    LOG.info('IntentService is ready.')


def on_error(e='Unknown'):
    LOG.info(f'IntentService failed to launch ({e})')


def on_stopping():
    LOG.info('IntentService is shutting down...')


class IntentService:
    """OVOS intent service. parses utterances using a variety of systems.

    The intent service also provides the internal API for registering and
    querying the intent service.
    """

    def __init__(self, bus, config=None, preload_pipelines=True,
                 alive_hook=on_alive, started_hook=on_started,
                 ready_hook=on_ready,
                 error_hook=on_error, stopping_hook=on_stopping) -> None:
        """Loads the installed pipeline plugins, transformer services, and
        session manager, and registers the bus handlers for utterance
        processing, context mutation, intent queries, and skill deactivation
        tracking."""
        callbacks = StatusCallbackMap(on_started=started_hook,
                                      on_alive=alive_hook,
                                      on_ready=ready_hook,
                                      on_error=error_hook,
                                      on_stopping=stopping_hook)
        self.bus = bus
        self.status: ProcessStatus = ProcessStatus('intents', bus=self.bus, callback_map=callbacks)
        self.status.set_started()
        self.config: dict = config or Configuration().get("intents", {})

        # load and cache the plugins right away so they receive all bus messages
        self.pipeline_plugins: dict = {}

        self.utterance_plugins: UtteranceTransformersService = UtteranceTransformersService(bus)
        self.metadata_plugins: MetadataTransformersService = MetadataTransformersService(bus)
        self.intent_plugins: IntentTransformersService = IntentTransformersService(bus)

        handler_timeout = self.config.get("handler_timeout", DEFAULT_HANDLER_TIMEOUT)
        self.intent_dispatcher: IntentDispatcher = IntentDispatcher(
            bus, timeout=handler_timeout, on_terminal=self._emit_utterance_handled,
            on_done_signal=self._sync_handler_mutations)

        # INTENT-4 §10 manifest — indexes registration broadcasts and serves
        # ovos.intent.list / ovos.intent.describe pull-queries.
        self.intent_manifest: IntentManifest = IntentManifest(bus)

        # connect SessionManager to the bus, this will sync default session
        # across all components. Guarded so the same bus does not get the
        # five SessionManager handlers registered twice: in the monolith,
        # SkillManager.__init__ runs first and connects the bus before this
        # IntentService is constructed; in embedders that construct
        # IntentService directly (without a SkillManager), this call site
        # is the first to connect it.
        if SessionManager.bus is not self.bus:
            SessionManager.connect_to_bus(self.bus)

        self.bus.on(SpecMessage.UTTERANCE, self.handle_utterance)

        # OVOS-SESSION-2 §6.2: honour a synced session snapshot. The §5.3
        # intent_context half of this topic is SessionManager's and is already
        # subscribed there; this handler takes the whole-session snapshot.
        self.bus.on(SpecMessage.SESSION_SYNC, self.handle_session_sync)

        # Context related handlers
        self.bus.on('add_context', self.handle_add_context)
        self.bus.on('remove_context', self.handle_remove_context)
        self.bus.on('clear_context', self.handle_clear_context)

        # Intents API
        self.bus.on('intent.service.intent.get', self.handle_get_intent)

        # internal, track skills that call self.deactivate to avoid reactivating them again
        self._deactivations: defaultdict = defaultdict(list)
        self.bus.on('intent.service.skills.deactivate', self._handle_deactivate)
        self.bus.on('intent.service.pipelines.reload', self.handle_reload_pipelines)

        self.status.set_alive()
        if preload_pipelines:
            self.bus.emit(Message('intent.service.pipelines.reload'))

    def handle_session_sync(self, message: Message):
        """OVOS-SESSION-2 §2.7 — take a synced session snapshot into the
        session it is for.

        §2.7 puts the snapshot in ``Message.data["session"]`` and leaves
        ``Message.context["session"]`` as the ambient carrier saying *which*
        session the sync is about, so the content comes from the data and the
        identity from the context. The merge is §5.1's: a field the snapshot
        carries replaces, a field it omits leaves the current value alone.

        For the default session the merge lands in the store, which
        ``SessionManager`` owns. For a named session there is no store (§2.2)
        and §2.7 directs the update at the session of the utterance in
        progress — so it applies while that round is open, and a sync arriving
        outside one has no session to revise and is dropped.
        """
        payload = message.data.get("session") or {}
        if not payload:
            return
        sess = working_session(message)
        if sess is not None and not sess.is_default:
            sess.update_from(
                Session.deserialize(merge_carrier(sess, payload)))
            return
        SessionManager.handle_sync(message)

    def handle_reload_pipelines(self, message: Message) -> None:
        pipeline_plugins = OVOSPipelineFactory.get_installed_pipeline_ids()
        LOG.debug(f"Installed pipeline plugins: {pipeline_plugins}")

        # `intents.blacklisted_pipelines` lets a deployment opt a plugin out
        # of ovos-core entirely, so it is never imported/instantiated.
        # ovos-core still deliberately loads every OTHER installed plugin
        # regardless of the active `intents.pipeline` selection, because a
        # remote client/session may select a different pipeline at runtime.
        # Matching is by exact installed plugin id (as returned by
        # `OVOSPipelineFactory.get_installed_pipeline_ids`, eg.
        # "ovos-m2v-pipeline"), NOT by confidence-suffixed matcher id (eg.
        # "ovos-m2v-pipeline-high"); blacklisting the plugin id covers all of
        # its matcher variants since they are all produced by the same class.
        blacklist = set(self.config.get("blacklisted_pipelines", []))
        active_pipeline = self.config.get("pipeline", [])

        for p in pipeline_plugins:
            if p in blacklist:
                LOG.info(f"Skipping blacklisted pipeline plugin: '{p}'")
                # `intents.pipeline` may list legacy matcher ids (eg.
                # "adapt_high"); normalize through _PIPELINE_MIGRATION_MAP
                # before comparing against the installed plugin id, or this
                # warning silently fails to fire for legacy configs.
                if any(_PIPELINE_MIGRATION_MAP.get(matcher_id, matcher_id) == p or
                       _PIPELINE_MIGRATION_MAP.get(matcher_id, matcher_id).startswith(f"{p}-")
                       for matcher_id in active_pipeline):
                    LOG.warning(f"Pipeline plugin '{p}' is blacklisted in "
                                f"'intents.blacklisted_pipelines' but also "
                                f"selected in 'intents.pipeline'; the "
                                f"blacklist wins and it will stay disabled")
                continue
            try:
                self.pipeline_plugins[p] = OVOSPipelineFactory.load_plugin(p, bus=self.bus)
                LOG.debug(f"Loaded pipeline plugin: '{p}'")
            except Exception as e:
                LOG.error(f"Failed to load pipeline plugin '{p}': {e}")
        self.status.set_ready()

    def _handle_transformers(self, message: Message) -> Message:
        """
        Pipe utterance through transformer plugins to get more metadata.
        Utterances may be modified by any parser and context overwritten
        """
        lang = get_message_lang(message)  # per query lang or default Configuration lang
        original = utterances = message.data.get('utterances', [])
        message.context["lang"] = lang
        utterances, message.context = self.utterance_plugins.transform(utterances, message.context)
        if original != utterances:
            message.data["utterances"] = utterances
            LOG.debug(f"utterances transformed: {original} -> {utterances}")
        message.context = self.metadata_plugins.transform(message.context)
        return message

    @staticmethod
    def disambiguate_lang(message: Message) -> str:
        """ disambiguate language of the query via pre-defined context keys
        1 - stt_lang -> tagged in stt stage  (STT used this lang to transcribe speech)
        2 - request_lang -> tagged in source message (wake word/request volunteered lang info)
        3 - detected_lang -> tagged by transformers  (text classification, free form chat)
        4 - config lang (or from message.data)
        """
        default_lang = get_message_lang(message)
        valid_langs = message.context.get("valid_langs") or get_valid_languages()
        valid_langs = [standardize_lang(lang) for lang in valid_langs]
        lang_keys = ["stt_lang",
                     "request_lang",
                     "detected_lang"]
        for k in lang_keys:
            if k in message.context:
                v = standardize_lang(message.context[k])
                # closest_lang applies the language-distance threshold and
                # returns None when no candidate is close enough. The bound is
                # inclusive, so a member language still matches its
                # macrolanguage (distance 10, eg. "arz" against "ar")
                best_lang = closest_lang(v, valid_langs)
                if best_lang is None:
                    LOG.warning(f"ignoring {k}, {v} is not in enabled languages: {valid_langs}")
                    continue
                LOG.info(f"replaced {default_lang} with {k}: {v}")
                return v

        return default_lang

    def get_pipeline_matcher(self, matcher_id: str) -> Optional[Callable]:
        """
        Retrieve a matcher function for a given pipeline matcher ID.

        Args:
            matcher_id: The configured matcher ID (e.g. `adapt_high`).

        Returns:
            A callable matcher function.
        """
        matcher_id = _PIPELINE_MIGRATION_MAP.get(matcher_id, matcher_id)
        pipe_id = _PIPELINE_RE.sub('', matcher_id)
        plugin = self.pipeline_plugins.get(pipe_id)
        if not plugin:
            LOG.error(f"Unknown pipeline matcher '{matcher_id}': no installed plugin provides it. A bare ovos-core install ships no matchers - install ovos-core[plugins] or add the specific plugin to your environment.")
            return None

        if isinstance(plugin, ConfidenceMatcherPipeline):
            if matcher_id.endswith("-high"):
                return plugin.match_high
            if matcher_id.endswith("-medium"):
                return plugin.match_medium
            if matcher_id.endswith("-low"):
                return plugin.match_low
        return plugin.match

    def get_pipeline(self, session=None) -> List[Tuple[str, Callable]]:
        """return a list of matcher functions ordered by priority
        utterances will be sent to each matcher in order until one can handle the utterance
        the list can be configured in mycroft.conf under intents.pipeline,
        in the future plugins will be supported for users to define their own pipeline"""
        session = session or SessionManager.get()

        # OVOS-PIPELINE-1 §5.2/§5.5: `session.blacklisted_pipelines` is the
        # policy channel and overrides `session.pipeline` preference - a
        # pipeline_id listed here MUST NOT be invoked for this session even
        # if it is also present in `session.pipeline`. Filtering here is
        # orchestrator-only: no `match` call is made and no bus event is
        # emitted for the skip, it is observable only as a non-invocation.
        # Unknown pipeline_ids in the blacklist are harmless no-ops.
        # a blacklist entry denies the plugin (the actor), never a single
        # confidence tier of it, so entries are normalized to bare plugin ids
        blacklisted = {
            _PIPELINE_RE.sub('', _PIPELINE_MIGRATION_MAP.get(pipeline_id, pipeline_id))
            for pipeline_id in session.blacklisted_pipelines or []
        }

        def is_blacklisted(matcher_id: str) -> bool:
            normalized = _PIPELINE_MIGRATION_MAP.get(matcher_id, matcher_id)
            plugin_id = _PIPELINE_RE.sub('', normalized)
            return plugin_id in blacklisted

        requested = [p for p in session.pipeline if not is_blacklisted(p)]
        if blacklisted:
            skipped = [p for p in session.pipeline if is_blacklisted(p)]
            if skipped:
                LOG.debug(f"Session '{session.session_id}' blacklisted "
                          f"pipelines skipped: {skipped}")

        matchers: List[Tuple[str, Callable]] = [(p, self.get_pipeline_matcher(p)) for p in requested]
        matchers = [m for m in matchers if m[1] is not None]  # filter any that failed to load
        final_pipeline = [k[0] for k in matchers]
        if requested != final_pipeline:
            LOG.warning(f"Requested some invalid pipeline components! "
                        f"filtered: {[k for k in requested if k not in final_pipeline]}")
        LOG.debug(f"Session final pipeline: {final_pipeline}")
        return matchers

    @staticmethod
    def _validate_session(message: Message, lang: str) -> Session:
        """Take the inbound utterance into session state and return the session
        to run it on.

        This is the arrival OVOS-SESSION-2 §5.1 describes, and the only one:
        ``fold_inbound`` merges the raw carrier into the default-session store
        field by field, or builds a named session from its carrier alone since
        the orchestrator holds no state for one (§2.2). Nowhere else in the
        utterance flow may fold a carrier — §2.6 makes an incidental Message
        arriving mid-round unable to revise the working session, and a second
        fold of a stale snapshot is exactly that revision.
        """
        lang = standardize_lang(lang)
        sess = SessionManager.fold_inbound(message)
        if sess.is_default:
            updated = False
            # Default session, check if it needs to be (re)-created
            if sess.expired():
                sess = SessionManager.reset_default_session()
                updated = True
            if lang != sess.lang:
                sess.lang = lang
                updated = True
            if updated:
                SessionManager.update(sess)
                SessionManager.sync(message)
        else:
            sess.lang = lang
        sess.touch()
        return sess

    def _handle_deactivate(self, message: Message) -> None:
        """internal helper, track if a skill asked to be removed from active list during intent match
        in this case we want to avoid reactivating it again
        This only matters in PipelineMatchers, such as fallback and converse
        in those cases the activation is only done AFTER the match, not before unlike intents
        """
        sess = SessionManager.get(message)
        skill_id = message.data.get("skill_id")
        self._deactivations[sess.session_id].append(skill_id)

    def _sync_handler_mutations(self, done_msg: Message, dispatch_msg: Message):
        """OVOS-SESSION-2 §2.6 — sync the round's working session with the
        handler's mutations, at handler completion.

        The handler runs in its own process and mutates its own copy of the
        dispatch session, so the writes come back on the framework done-signal,
        which ovos-workshop forwards from the very Message the handler was
        given. Reading that carrier here is how the orchestrator learns of the
        mutation; §2.6 fixes what happens to it, not how it arrives.

        Only fields the handler owns are taken: ``intent_context``, merged
        entry-by-entry per OVOS-CONTEXT-1 §5.3 through the same
        ``SessionManager`` helper an inbound sync goes through;
        ``response_mode``; and removals from ``active_handlers``, the one
        write OVOS-STOP-1 §4.4 prescribes there. Everything else — ``lang``,
        ``pipeline``, ``site_id``, the rest of the registry — stays as the
        round has it, because a handler writing those is forbidden by §2.6 and
        an orchestrator that applied the write anyway would make the
        prohibition unenforced.

        What is taken is the *difference* against the dispatch snapshot, not
        the carrier wholesale, so a handler that touched nothing changes
        nothing and two handlers on one session cannot clobber each other with
        their stale halves. The round's decay outranks the carrier either way:
        an entry the pre-match prune dropped (see ``handle_utterance``) is
        never put back, however stale the copy the handler answered with. That
        is about the *entry*, not the key — a handler re-arming the same key
        with a fresh entry, which is what a skill asking the same follow-up
        question twice does, is writing, not echoing, and its write lands.

        For the default session the working session *is* the store (§5.1), so
        merging into it here is the store merge §2.6 asks for.
        """
        try:
            carrier = session_carrier(done_msg)
        except MalformedSession:
            LOG.error("done-signal carries a malformed session; skipping the "
                      "OVOS-SESSION-2 §2.6 completion sync")
            return
        if not carrier:
            return

        live = round_session(dispatch_msg)
        carried_id = resolve_session_id(carrier)
        if carried_id != live.resolved_session_id():
            # §2.6 scopes the sync to the round's own session; a done-signal
            # naming another one is a handler or transport fault, and folding
            # it would write one session's state into another.
            LOG.error(f"done-signal for the round on "
                      f"'{live.resolved_session_id()}' carries session "
                      f"'{carried_id}'; not syncing it")
            return

        baseline = dispatch_msg.context.get("session") or {}
        base_ctx = baseline.get("intent_context") or {}
        new_ctx = carrier.get("intent_context") or {}
        # None is CONTEXT-1 §5.3's "remove this key" tombstone, not a value
        changed = {k: v for k, v in new_ctx.items() if base_ctx.get(k) != v}
        removed = {k: None for k in base_ctx if k not in new_ctx}
        payload = {**changed, **removed}
        for key, dropped in pruned_entries(dispatch_msg).items():
            # only the stale carry-over of a pruned entry is beaten by the
            # decay; the same key re-armed with a different entry is a fresh
            # handler write and lands like any other.
            if payload.get(key) == dropped:
                payload.pop(key)
        if payload:
            with _CONTEXT_LOCK:
                ctx = dict(live.intent_context or {})
                SessionManager.merge_intent_context(ctx, payload)
                _replace_intent_context(live, ctx)

        if carrier.get("response_mode") != baseline.get("response_mode"):
            live.response_mode = carrier.get("response_mode")

        baseline_handlers = {h.get("skill_id") for h in baseline.get("active_handlers") or []}
        carrier_handlers = {h.get("skill_id") for h in carrier.get("active_handlers") or []}
        for skill_id in baseline_handlers - carrier_handlers:
            live.remove_active_handler(skill_id)

        SessionManager.update(live)
        # The §8 terminal and the §9.5 end-marker are both forwarded from the
        # dispatch Message, so re-stamping it here is what makes them carry the
        # synced session instead of the snapshot the round has moved past.
        dispatch_msg.context["session"] = live.serialize()

    def _emit_utterance_handled(self, dispatch_msg: Message):
        """OVOS-PIPELINE-1 §9.5 — emit the universal ``ovos.utterance.handled``
        end-marker once a matched handler reaches its §8 terminal.

        Invoked by the dispatcher (``on_terminal``) right after a complete/error/
        timeout terminal is on the bus — non-blocking, and ordered after the terminal
        so consumers never see the end-marker first. The no-match and cancel paths
        emit their own end-marker inline; together they give exactly one per
        utterance."""
        msg = dispatch_msg.forward(SpecMessage.UTTERANCE_HANDLED, {})
        # No fold here (SESSION-2 §2.6): the dispatch message is a snapshot the
        # round has since moved past. Re-apply the tracked deactivations to the
        # working session and stamp that on the end-marker, so the utterance
        # terminates with the state the handler actually requested.
        live = close_round(dispatch_msg)
        if live is not None:
            for skill_id in self._deactivations.pop(live.session_id, None) or []:
                if live.is_active(skill_id):
                    live.deactivate_skill(skill_id)
            msg.context["session"] = live.serialize()
        self.bus.emit(msg)

    def _missing_required_slots(self, match: IntentHandlerMatch,
                                session_id: str, lang: str,
                                intent_context: Optional[dict] = None) -> List[str]:
        """OVOS-PIPELINE-1 §6.2 orchestrator backstop for ``required_slots``.

        After a plugin returns a Match, the orchestrator verifies the match's
        slot map contains every slot the matched intent declares as required
        (OVOS-INTENT-3 §5.3, OVOS-INTENT-4 §6.1). If any is absent, the
        orchestrator treats the match as if the plugin had declined and
        continues iteration — no bus event is emitted; the only observable
        effect is a non-match (§6.2). The primary obligation to enforce
        ``required_slots`` still lies with the engine during ``match()``; this
        is a second line of defense against engine bugs.

        The constraint is the intent's registered ``required_slots``, read from
        the orchestrator's INTENT-4 §10 manifest. The captured slot map is
        ``match.match_data`` (OVOS-INTENT-3 §7; ``Match.slots`` in PIPELINE-1
        §4.3). An intent absent from the manifest yields no required slots, so
        the backstop is a no-op and engine-side enforcement remains authoritative.

        OVOS-CONTEXT-1 §7 interaction: a required slot the live
        ``intent_context`` can fill counts as present. §7 slot fill happens
        inside the dispatch, i.e. AFTER this backstop, so without consulting
        the context here a context-fillable slot would kill an otherwise
        valid match before it ever got the chance to be filled.

        Returns:
            List[str]: required slot names absent from the match's slot map.
        """
        if not match.skill_id or not match.match_type or ":" not in match.match_type:
            return []
        intent_name = match.match_type.split(":", 1)[-1]
        required_slots = self.intent_manifest.get_required_slots(
            session_id, match.skill_id, intent_name, lang)
        if not required_slots:
            return []
        match_data = match.match_data or {}
        from_context = self._context_supplied_slots(
            match, session_id, lang, intent_context)
        return [slot for slot in required_slots
                if not match_data.get(slot) and not from_context.get(slot)]

    def _context_supplied_slots(self, match: IntentHandlerMatch, session_id: str, lang: str,
                                intent_context: Optional[dict]) -> dict:
        """OVOS-CONTEXT-1 §7 — the slots the live ``intent_context`` can fill
        for ``match``. Shared by the §6.2 missing-required backstop and by the
        §7 fill applied during dispatch, so both agree on what "filled" means.
        """
        if not (isinstance(match, IntentHandlerMatch) and match.skill_id
                and match.match_type):
            return {}
        intent_name = match.match_type.split(":", 1)[-1]
        requires, _ = self.intent_manifest.get_context_requirements(
            session_id, match.skill_id, intent_name, lang)
        slot_names = self.intent_manifest.get_slot_names(
            session_id, match.skill_id, intent_name, lang)
        if not requires or not slot_names:
            return {}
        # "filled" is judged against match.match_data, not reply.data, which
        # carries framework/echo fields that could collide with a slot name
        return context_supplied_slots(
            intent_context=intent_context or {},
            requires=requires,
            slot_names=slot_names,
            owner_id=match.skill_id,
            filled_slots=match.match_data or {},
        )

    @staticmethod
    def _apply_post_match_decay(sess: "Session", pre_match_entries: dict) -> Session:
        """OVOS-CONTEXT-1 §4/§4.1: decrement turns_remaining on the session the
        round is running on, skipping keys refreshed since ``pre_match_entries``
        was snapshotted (compared by value, not identity, since reply/forward
        round-trips entries through serialize/deserialize).

        Must run before the dispatch reaches the IntentDispatcher / before
        any §9.3/§9.5 terminal is emitted (see ``_dispatch_match``).

        The caller passes the working session rather than an id to look up:
        OVOS-SESSION-2 §2.2 keeps the orchestrator stateless for named
        sessions, so there is no registry entry to find one by, and a lookup
        that missed would silently stop decaying every session but the
        device's.

        Returns:
            Session: the decayed session.
        """
        post_ctx = dict(sess.intent_context or {})
        unchanged_keys = {k for k in pre_match_entries
                          if k in post_ctx and post_ctx[k] == pre_match_entries[k]}
        decrement_intent_context(post_ctx, only_keys=unchanged_keys)
        _replace_intent_context(sess, post_ctx)
        SessionManager.update(sess)
        return sess

    def _dispatch_match(self, match: IntentHandlerMatch, message: Message, lang: str,
                        pipeline_id: Optional[str] = None,
                        pre_match_entries: Optional[dict] = None) -> None:
        """Orchestrate the OVOS-PIPELINE-1 §6.1 post-match steps, then dispatch.

        Runs the intent-transformer chain, skill activation, session update,
        the OVOS-CONTEXT-1 §4.2 decrement, and ``context['pipeline_id']``
        stamping (§7.1); emits §9.2 ``ovos.intent.matched``; hands the
        dispatch Message to the IntentDispatcher (§7/§8). The §4.2 decrement
        must run before the dispatch is put on the bus, or the pre-decrement
        map would be what the dispatch's consumers see.

        Args:
            match (IntentHandlerMatch): The matched intent (utterance, match_type,
                skill_id, match_data, optional updated_session).
            message (Message): The originating utterance Message to derive from.
            lang (str): The content language of the match.
            pipeline_id (str): The pipeline plugin that produced the match (§3.1).
            pre_match_entries (Optional[dict]): §4.1 pre-match key->entry-value
                snapshot, used to tell a mid-round sync apart from an
                untouched entry when deciding what to decrement.
        """
        try:
            match = self.intent_plugins.transform(match)
        except Exception:
            LOG.exception("_dispatch_match failed")

        reply = None
        # §5.1: a committed ``Match.updated_session`` replaces the working
        # session wholesale; otherwise the round continues on the session it
        # was folded onto at entry. No fold here (§2.6).
        sess = round_session(message)
        if match.updated_session is not None:
            updated = match.updated_session
            if updated.resolved_session_id() != sess.resolved_session_id():
                # §5.1/§4.2: updated_session is defined as the ROUND's session,
                # updated — never a different session. A pipeline plugin
                # returning one for a different id is a plugin bug, and a
                # plugin bug must not kill the utterance: log it and keep
                # dispatching on the round's own working session.
                LOG.error(
                    f"pipeline '{pipeline_id}' returned an updated_session "
                    f"for '{updated.resolved_session_id()}' but the round is "
                    f"running on '{sess.resolved_session_id()}'; ignoring "
                    f"the updated_session and continuing on the round's own "
                    f"session")
            else:
                # ``update`` returns the store for the default session, so the
                # round carries on the one object every co-located view holds.
                sess = SessionManager.update(updated)
                open_round(message, sess)
                SessionManager.bind(message, sess)
        sess.lang = lang  # ensure it is updated

        # Launch intent handler
        if match.match_type:
            # keep all original message.data and update with intent match
            data = dict(message.data)
            data.update(match.match_data)
            reply = message.reply(match.match_type, data)

            # upload intent metrics if enabled
            if self.config.get("open_data", {}).get("intent_urls"):
                create_daemon(self._upload_match_data, (match.utterance,
                                                        match.match_type,
                                                        lang,
                                                        match.match_data,
                                                        sess.pipeline))

        if reply is not None:
            reply.data["utterance"] = match.utterance
            reply.data["lang"] = lang

            # update active skill list
            if match.skill_id:
                # ensure skill_id is present in message.context
                reply.context["skill_id"] = match.skill_id

                was_deactivated = match.skill_id in self._deactivations[sess.session_id]
                # ``suppress_activation`` (OVOS-STOP-1 §6.2/§7.3) marks a dispatch
                # that terminates an already-active skill's participation — a stop —
                # so it must register no activation at all: neither the §7.1
                # ``active_handlers`` push nor the ``{skill_id}.activate`` callback.
                if not was_deactivated and not match.suppress_activation:
                    # OVOS-PIPELINE-1 §7.1 pushes the skill onto the session's
                    # active-handler recency list. §7.3 SUPPRESSES that push for
                    # reserved intent_name dispatches (converse/response/
                    # fallback/common_query): a reserved name is a continuation
                    # or termination of an already-active skill's participation,
                    # not a fresh activation. `activate_skill` is a back-compat
                    # shim over `add_active_handler` (§7.1) in current bus-client.
                    if not _produces_reserved_name(pipeline_id):
                        sess.activate_skill(match.skill_id)
                    # emit event for skills callback -> self.handle_activate
                    self.bus.emit(reply.forward(f"{match.skill_id}.activate"))

            # OVOS-CONTEXT-1 §5.1: matcher-captured entries reach the session
            # via ``match.updated_session`` + the §5.3 ``ovos.session.sync``
            # merge — IntentHandlerMatch carries no ``intent_context`` field.

            # OVOS-CONTEXT-1 §7: fill unfilled slots from live context
            self._apply_context_slots(match, sess, reply)

            # OVOS-CONTEXT-1 §4.2: decrement before dispatch (see docstring)
            sess = self._apply_post_match_decay(sess, pre_match_entries or {})

            # update Session if modified by pipeline
            reply.context["session"] = sess.serialize()

            # stamp the matching plugin's identity on the dispatch (§3.1, §7.1).
            # `pipeline_id` here is whatever entry `session.pipeline` used
            # (e.g. a confidence-tier matcher id like "adapt-high"); §3 requires
            # attribution to name the plugin's single bare `pipeline_id`, never
            # an entry-specific string, so it is normalized the same way
            # `get_pipeline_matcher` resolves it to a plugin.
            if pipeline_id:
                reply.context["pipeline_id"] = _PIPELINE_RE.sub(
                    '', _PIPELINE_MIGRATION_MAP.get(pipeline_id, pipeline_id))

            skill_id = (match.skill_id
                        or (match.match_data or {}).get("skill_id")
                        or reply.msg_type.split(":", 1)[0])
            self.bus.emit(reply.forward(SpecMessage.INTENT_MATCHED, {
                "skill_id": skill_id,
                "intent_name": match.match_type,
                "lang": lang,
                "utterance": match.utterance,
                "slots": dict(match.match_data or {}),
                "pipeline_id": reply.context.get("pipeline_id"),
            }))

            intent_name = reply.msg_type.split(":", 1)[-1]
            self.intent_dispatcher.dispatch(reply, skill_id, intent_name)

        else:  # upload intent metrics if enabled
            if self.config.get("open_data", {}).get("intent_urls"):
                create_daemon(self._upload_match_data, (match.utterance,
                                                        "complete_intent_failure",
                                                        lang,
                                                        match.match_data,
                                                        sess.pipeline))

    @staticmethod
    def _upload_match_data(utterance: str, intent: str, lang: str, match_data: dict, pipeline: List[str]):
        """if enabled upload the intent match data to a server, allowing users and developers
        to collect metrics/datasets to improve the pipeline plugins and skills.

        There isn't a default server to upload things too, users needs to explicitly configure one

        https://github.com/OpenVoiceOS/ovos-opendata-server
        """
        config = Configuration().get("open_data", {})
        endpoints: List[str] = config.get("intent_urls", [])  # eg. "http://localhost:8000/intents"
        if not endpoints:
            return  # user didn't configure any endpoints to upload metrics to
        if isinstance(endpoints, str):
            endpoints = [endpoints]
        headers = {"Content-Type": "application/x-www-form-urlencoded",
                   "User-Agent": config.get("user_agent", "ovos-metrics")}
        data = {
            "utterance": utterance,
            "intent": intent,
            "lang": lang,
            "match_data": json.dumps(match_data, ensure_ascii=False),
            "pipeline": "|".join(pipeline),
            "core_version": OVOS_VERSION_STR
        }
        for url in endpoints:
            try:
                # Add a timeout to prevent hanging
                response = requests.post(url, data=data, headers=headers, timeout=3)
                LOG.info(f"Uploaded intent metrics to '{url}' - Response: {response.status_code}")
            except Exception as e:
                LOG.warning(f"Failed to upload metrics: {e}")

    def send_cancel_event(self, message: Message) -> None:
        """OVOS-PIPELINE-1 §6.4 cancellation terminal path: play the cancel
        sound, emit ``ovos.utterance.cancelled``, then the §9.5 end-marker."""
        LOG.info(f"utterance canceled, cancel_word:{message.context.get('cancel_word')}")
        # play dedicated cancel sound
        sound = Configuration().get('sounds', {}).get('cancel', "snd/cancel.mp3")
        # NOTE: message.reply to ensure correct message destination
        self.bus.emit(message.reply('mycroft.audio.play_sound', {"uri": sound}))
        # OVOS-PIPELINE-1 §6.4 cancellation terminal path: cancelled -> handled
        # OVOS-TRANSFORM-1 §8.2: ovos.utterance.cancelled carries the
        # cancel_reason and the orchestrator-stamped cancel_by from the §8.1
        # signal that triggered the cancellation.
        cancel_data = {}
        if message.context.get("cancel_reason") is not None:
            cancel_data["cancel_reason"] = message.context["cancel_reason"]
        if message.context.get("cancel_by") is not None:
            cancel_data["cancel_by"] = message.context["cancel_by"]
        self.bus.emit(message.reply(SpecMessage.UTTERANCE_CANCELLED, cancel_data))
        self.bus.emit(message.reply(SpecMessage.UTTERANCE_HANDLED))

    @staticmethod
    def _stamp_utterance_id(message: Message) -> str:
        """OVOS-PIPELINE-1 §9.1.1 — name this utterance lifecycle.

        The orchestrator stamps ``context.utterance_id`` once, at lifecycle
        entry. The value is opaque and unique per lifecycle (a UUID here; no
        format is normative). Consumers compare it for equality and do nothing
        else. Every derived Message carries it for free, because
        ``Message.reply``/``Message.forward`` deep-copy ``context``.

        A value already present is kept: a component that opened the lifecycle
        out-of-band already sat at entry and stamped under this same rule.

        Returns:
            str: the lifecycle identifier now on the Message.
        """
        uid = message.context.get("utterance_id")
        if not uid:
            uid = str(uuid4())
            message.context["utterance_id"] = uid
        return uid

    def handle_utterance(self, message: Message):
        """Main entrypoint for handling user utterances, typically generated
        by a spoken interaction but potentially also from a CLI or other
        method of injecting a 'user utterance' into the system.

        Runs the utterance/metadata transformer chain, disambiguates
        language, then tries each configured pipeline matcher in order until
        one produces a Match. If none does, ``send_complete_intent_failure``
        is emitted instead.
        """
        # OVOS-SESSION-1 §2.5: reject a present-but-non-object session carrier
        # before anything downstream (transformers, lang disambiguation, the
        # §5.1 arrival) tries to read it through SessionManager and raises.
        # It is never folded into the default session nor substituted for
        # it — that would process the utterance under a fabricated identity.
        # The Message is dropped before it ever enters the lifecycle (no
        # utterance_id is stamped, no dispatch happens), so no §9.5
        # ovos.utterance.handled end-marker is owed for it either.
        carrier = message.context.get("session")
        if carrier is not None and not isinstance(carrier, dict):
            LOG.error(f"OVOS-SESSION-1 §2.5: malformed session carrier on "
                      f"{message.msg_type} (got {type(carrier).__name__}, "
                      f"expected object); dropping utterance")
            return

        # OVOS-PIPELINE-1 §9.1.1: stamp the lifecycle identifier exactly once,
        # at lifecycle entry, before anything derives from this Message. A value
        # already present is never overwritten — regenerating it downstream would
        # detach every already-derived Message from its lifecycle.
        uid = self._stamp_utterance_id(message)

        # Get utterance utterance_plugins additional context
        message = self._handle_transformers(message)

        # §9.1.1 drop-guard: UtteranceTransformersService/MetadataTransformersService
        # REPLACE message.context wholesale, so a plugin returning a fresh dict
        # silently detaches the lifecycle. Re-assert the entry value (same value,
        # so this is not an overwrite).
        if message.context.get("utterance_id") != uid:
            LOG.debug("transformer chain dropped utterance_id; re-asserting")
            message.context["utterance_id"] = uid

        if message.context.get("canceled"):
            self.send_cancel_event(message)
            return

        # tag language of this utterance
        lang = self.disambiguate_lang(message)

        utterances = message.data.get('utterances', [])
        LOG.info(f"Parsing utterance: {utterances}")

        stopwatch = Stopwatch()

        # get session: the single arrival of the round (SESSION-2 §5.1)
        try:
            sess = self._validate_session(message, lang)
        except MalformedSession:
            # OVOS-SESSION-1 §2.5: a present-but-non-object session carrier is
            # a producer error. It is never folded into the default session
            # nor substituted for it — that would process the utterance under
            # a fabricated identity. The Message is dropped before it ever
            # enters the lifecycle (no utterance_id was bound to a session,
            # no dispatch happened), so no §9.5 ovos.utterance.handled
            # end-marker is owed for it either.
            LOG.error(f"OVOS-SESSION-1 §2.5: malformed session carrier on "
                      f"{message.msg_type} (got "
                      f"{type(message.context.get('session')).__name__}, "
                      f"expected object); dropping utterance")
            return
        # §2.2's utterance-scoped cache. Every Message derived from this round
        # can now reach the session the round is running on, which for a named
        # session is the only place it lives.
        open_round(message, sess)
        # Bind the working session as the message's own session: every
        # ``SessionManager.get(message)`` this round and every derivation's
        # ``stamp_derived`` must see this exact object, mutations included,
        # rather than rebuilding one from the (now stale) carrier.
        SessionManager.bind(message, sess)

        # OVOS-CONTEXT-1 §4 (pre-match): prune dead entries so every matcher
        # this round sees the same gating snapshot
        intent_ctx = dict(sess.intent_context or {})
        prune_intent_context(intent_ctx)
        # SESSION-2 §2.6: what the prune removed here is authoritative for the
        # round, so remember it — the completion sync must not let a handler
        # holding a pre-prune copy of the session put any of it back.
        record_pruned(message, {k: v for k, v in (sess.intent_context or {}).items()
                                if k not in intent_ctx})
        # §4.1: snapshot entry *value* (not identity, which reply/forward
        # round-tripping churns) so a mid-dispatch refresh is exempted below.
        # Deep, so an in-place mutation of a nested entry value later in the
        # round cannot silently defeat the equality-based exemption check.
        pre_match_entries = copy.deepcopy(intent_ctx)
        _replace_intent_context(sess, intent_ctx)
        SessionManager.update(sess)
        message.context["session"] = sess.serialize()

        # match
        match = None
        # no_match_lang defers the §9.3/§9.5 emission until after §4.2 decay
        no_match_lang = None
        with stopwatch:
            self._deactivations[sess.session_id] = []
            # Loop through the matching functions until a match is found.
            for pipeline, match_func in self.get_pipeline(session=sess):
                langs = [lang]
                if self.config.get("multilingual_matching"):
                    # if multilingual matching is enabled, attempt to match all user languages if main fails
                    langs += [l for l in get_valid_languages() if l != lang]
                for intent_lang in langs:
                    try:
                        match = match_func(utterances, intent_lang, message)
                    except Exception:
                        # a misbehaving pipeline matcher (e.g. a malformed .voc
                        # resource) must not abort the whole utterance — log and
                        # treat it as a no-match so iteration continues.
                        LOG.exception(f"{match_func} raised while matching "
                                      f"'{intent_lang}'; treating as no-match")
                        match = None
                    if match:
                        LOG.info(f"{pipeline} match ({intent_lang}): {match}")
                        if match and not match.match_type:
                            LOG.warning(f"Matcher {type(match_func).__name__} returned a match with empty match_type; skipping")
                            continue
                        if match.skill_id and match.skill_id in (sess.blacklisted_skills or []):
                            LOG.debug(
                                f"ignoring match, skill_id '{match.skill_id}' blacklisted by Session '{sess.session_id}'")
                            continue
                        if isinstance(match, IntentHandlerMatch) and match.match_type in (sess.blacklisted_intents or []):
                            LOG.debug(
                                f"ignoring match, intent '{match.match_type}' blacklisted by Session '{sess.session_id}'")
                            continue
                        # OVOS-PIPELINE-1 §6.2: if the matched intent is missing
                        # any required slot, treat it as if the plugin had
                        # declined and continue iteration; no bus event is emitted.
                        missing = self._missing_required_slots(
                            match, sess.session_id, intent_lang,
                            intent_context=sess.intent_context)
                        if missing:
                            LOG.debug(f"ignoring match '{match.match_type}': "
                                      f"missing required slots {missing} (§6.2)")
                            continue
                        # OVOS-CONTEXT-1 §6/§6.1: orchestrator gate backstop
                        # against a misbehaving matcher; gates read from the
                        # manifest, not the Match
                        if isinstance(match, IntentHandlerMatch) and match.skill_id:
                            intent_name = match.match_type.split(":", 1)[-1]
                            requires, excludes = self.intent_manifest.get_context_requirements(
                                sess.session_id, match.skill_id, intent_name, intent_lang)
                            if (requires or excludes) and not gate_satisfied(
                                    sess.intent_context or {}, requires, excludes,
                                    owner_id=match.skill_id):
                                LOG.debug(
                                    f"ignoring match, context gate unsatisfied for '{match.match_type}'")
                                continue
                        try:
                            self._dispatch_match(
                                match, message, intent_lang, pipeline_id=pipeline,
                                pre_match_entries=pre_match_entries)
                            break
                        except Exception:
                            LOG.exception(f"{match_func} returned an invalid match")
                else:
                    LOG.debug(f"no match from {match_func}")
                    continue
                break
            else:
                # Nothing was able to handle the intent. Defer §9.3/§9.5 until
                # after the §4.2 decrement so the end-marker carries it.
                no_match_lang = lang

        LOG.debug(f"intent matching took: {stopwatch.time}")

        # OVOS-CONTEXT-1 §4.2 no-match path (matched path decrements in
        # _dispatch_match)
        if no_match_lang is not None:
            self._apply_post_match_decay(sess, pre_match_entries)
            message.data["lang"] = no_match_lang
            # §9.5 wants the end-marker to carry the round's final session,
            # and the decay just changed it. For a named session this stamp is
            # the only way the decayed context reaches the client (§2.2).
            message.context["session"] = sess.serialize()
            self.send_complete_intent_failure(message)
            close_round(message)

        # sync any changes made to the default session, eg by ConverseService
        if sess.session_id == "default":
            SessionManager.sync(message)
        elif sess.session_id in self._deactivations:
            self._deactivations.pop(sess.session_id)

    def send_complete_intent_failure(self, message):
        """Emit the OVOS-PIPELINE-1 §9.3 no-match terminal.

        The orchestrator owns the no-match branch of the §6.1 lifecycle: it plays
        the error sound, emits ``ovos.intent.unmatched`` (§9.3 — the intent-layer
        failure signal) and then the universal end-marker ``ovos.utterance.handled``
        (§9.5). Exactly one ``ovos.utterance.handled`` terminates the utterance.

        ``ovos.intent.unmatched`` is the spec replacement for the legacy
        ``complete_intent_failure``; the two are bridged by ovos-spec-tools'
        MIGRATION_MAP, so emitting the spec topic re-delivers the legacy one to
        any consumer still subscribed to it.

        Args:
            message (Message): original message to forward from
        """
        sound = Configuration().get('sounds', {}).get('error', "snd/error.mp3")
        # NOTE: message.reply to ensure correct message destination
        self.bus.emit(message.reply('mycroft.audio.play_sound', {"uri": sound}))
        # §9.3: intent-layer failure signal (carries lang from message.data)
        self.bus.emit(message.reply(SpecMessage.INTENT_UNMATCHED, message.data))
        # §9.5: universal end-marker
        self.bus.emit(message.reply(SpecMessage.UTTERANCE_HANDLED))

    def _apply_context_slots(self, match: IntentHandlerMatch, sess: Session, reply: Message) -> None:
        """OVOS-CONTEXT-1 §7 — fill an intent's unfilled slots from live
        context. Fallback for engines that don't implement §7 themselves;
        no-op when the intent declares no context-gated slot.

        @param match: the IntentHandlerMatch being dispatched.
        @param sess: the session whose intent_context is consulted.
        @param reply: the dispatch Message whose ``data`` slots are filled.
        """
        supplied = self._context_supplied_slots(
            match, sess.session_id, sess.lang, sess.intent_context)
        for key, value in supplied.items():
            reply.data[key] = value
        if supplied:
            LOG.debug(f"context-supplied slots (§7): {supplied}")

    @staticmethod
    def handle_add_context(message: Message):
        """Add context.

        LEGACY-COMPAT INPUT (CONTEXT-1 §5.0, architecture#161): the
        `add_context` topic this handles is NOT part of the spec - §5.0
        states there is no context-mutation topic and the session is the
        only context write path. This handler exists only so that
        pre-§5.0 emitters (older ovos-workshop skill processes whose
        `set_context()` wrapper only knew how to emit this message,
        never touching the session directly) keep working against a
        modern core. Modern emitters write `session.intent_context`
        directly and this handler becomes a redundant, idempotent
        write-through for them (see `handle_remove_context` for the
        symmetric case): re-applying the SAME key/value pair through this
        topic after the session already carries the identical entry from
        a direct write is safe - it recomputes and stores the exact same
        `{value, expires_at}` shape, refreshing the decay stamp (by
        design, per OVOS-CONTEXT-1 §5.3: every re-set refreshes
        unconditionally) rather than accumulating duplicate frames or
        entries. Do not build new producers against this topic.

        Args:
            message: data contains the 'context' item to add
                     optionally can include 'word' to be injected as
                     an alias for the context item.
        """
        entity = {'confidence': 1.0}
        context = message.data.get('context')
        word = message.data.get('word') or ''
        origin = message.data.get('origin') or ''
        # if not a string type try creating a string from it
        if not isinstance(word, str):
            word = str(word)
        entity['data'] = [(word, context)]
        entity['match'] = word
        entity['key'] = word
        entity['origin'] = origin
        sess = round_session(message)
        # The read-modify-write below must share the critical section with
        # `inject_context()`'s own fold under `_CONTEXT_LOCK`, or a concurrent
        # skill-side `set_context`/`remove_context` write landing between the
        # read and the reassign is silently clobbered. `_CONTEXT_LOCK` is an
        # RLock because the nested `inject_context()` and
        # `_replace_intent_context()` calls below both reacquire it.
        with _CONTEXT_LOCK:
            sess.context.inject_context(entity)
            # Two dialects meet here: ADAPT's munged `skillidkey` spelling and
            # CONTEXT-1's `skill.id:key` resolved spelling (OVOS-CONTEXT-1 §2/§7)
            # never coincide, so both entries are written to `session.intent_context`
            # below. One decay policy, one computed `expires_at`, applied to both
            # keys (§5): a missing `expires_at` never expires (`is_live()`), so
            # every entry - including the munged one `inject_context()` already
            # wrote above - must carry a fresh stamp. A re-set replaces wholesale
            # and refreshes expiry for both keys; there is no read-back API for a
            # consumer to notice a stale one (§5.3).
            context_cfg = Configuration().get('context', {})
            timeout_s = context_cfg.get('timeout', 2) * 60
            now = time.time()
            ctx = dict(sess.intent_context or {})
            munged_entry = {"value": word or context}
            expires_at = now + timeout_s if timeout_s > 0 else None
            if expires_at is not None:
                munged_entry["expires_at"] = expires_at
            ctx[context] = munged_entry
            # The declarative gate resolves a private declaration via
            # `resolve_key(key, "private", skill_id)` (colon-separated,
            # unsanitized) - a different spelling than the munged key above.
            # Write it too, when the producer (ovos-workshop's set_context) names
            # the original key and a skill_id. Private-scope only: the skill API's
            # stored key is always skill-prefixed; shared-scope writes are
            # session-sync territory, not this handler's.
            key = message.data.get('key')
            skill_id = message.context.get('skill_id') if message.context else None
            if key and skill_id:
                resolved = resolve_key(key, "private", skill_id)
                if resolved:
                    # Value falls back to the ORIGINAL key, never the munged ADAPT
                    # spelling, which must not leak into §7 slot injection here.
                    resolved_entry = {"value": word or key}
                    if expires_at is not None:
                        resolved_entry["expires_at"] = expires_at
                    ctx[resolved] = resolved_entry
            _replace_intent_context(sess, ctx)

    @staticmethod
    def handle_remove_context(message: Message):
        """Remove specific context.

        LEGACY-COMPAT INPUT (CONTEXT-1 §5.0, architecture#161): symmetric
        with `handle_add_context` above - `remove_context` is not a spec
        topic, kept only for pre-§5.0 emitters. A removal already carried
        by a direct session write (tombstoned, per §5.3) and re-applied
        here through the legacy topic is a no-op: popping an already-
        absent key from both spellings' working dicts changes nothing.

        Args:
            message: data contains the 'context' item to remove
        """
        context = message.data.get('context')
        if context:
            sess = round_session(message)
            # Same atomicity requirement as `handle_add_context`: hold
            # `_CONTEXT_LOCK` across the fold and the copy-modify-assign below,
            # or a concurrent skill-side session write is silently clobbered.
            with _CONTEXT_LOCK:
                sess.context.remove_context(context)
                # mirror the removal into the OVOS-CONTEXT-1 map (see
                # `handle_add_context`)
                ctx = dict(sess.intent_context or {})
                ctx.pop(context, None)
                # mirror-remove the resolved private-scope key too, if the
                # producer named the original key (see `handle_add_context`)
                key = message.data.get('key')
                skill_id = message.context.get('skill_id') if message.context else None
                if key and skill_id:
                    resolved = resolve_key(key, "private", skill_id)
                    if resolved:
                        ctx.pop(resolved, None)
                _replace_intent_context(sess, ctx)

    @staticmethod
    def handle_clear_context(message: Message):
        """Clears all keywords from context """
        sess = round_session(message)
        # Same atomicity requirement as `handle_add_context`.
        with _CONTEXT_LOCK:
            sess.context.clear_context()
            # mirror the clear into the OVOS-CONTEXT-1 map (see `handle_add_context`)
            _replace_intent_context(sess, {})

    def handle_get_intent(self, message: Message) -> None:
        """Get intent from either adapt or padatious.

        Args:
            message (Message): message containing utterance

        Optional message.data keys:
            exclude_pipeline (list[str]): drop these stages from the session
                pipeline before matching (substring match, e.g. ["converse"]).
                `intent.service.intent.get` is a read-only probe (it never runs
                a handler), so callers can use this to ask "what would match,
                ignoring these stages?" - e.g. a conversing skill probing the
                pipeline without re-entering the converse stage.
        """
        utterance = message.data["utterance"]
        lang = get_message_lang(message)
        sess = SessionManager.get(message)
        # optional: drop stages from the session pipeline for this probe
        excluded = message.data.get("exclude_pipeline") or []
        if isinstance(excluded, str):
            excluded = [excluded]
        else:
            excluded = [x for x in excluded if isinstance(x, str) and x]
        match = None
        # Loop through the matching functions until a match is found.
        for pipeline, match_func in self.get_pipeline(session=sess):
            if excluded and any(x in pipeline for x in excluded):
                continue
            s = time.monotonic()
            match = match_func([utterance], lang, message)
            LOG.debug(f"matching '{pipeline}' took: {time.monotonic() - s} seconds")
            if match:
                if match.match_type:
                    intent_data = dict(match.match_data)
                    intent_data["intent_name"] = match.match_type
                    intent_data["intent_service"] = pipeline
                    intent_data["skill_id"] = match.skill_id
                    intent_data["handler"] = match_func.__name__
                    LOG.debug(f"final intent match: {intent_data}")
                    m = message.reply("intent.service.intent.reply",
                                      {"intent": intent_data, "utterance": utterance})
                    self.bus.emit(m)
                    return
                LOG.error(f"bad pipeline match! {match}")
        # signal intent failure
        self.bus.emit(message.reply("intent.service.intent.reply",
                                    {"intent": None, "utterance": utterance}))

    def shutdown(self) -> None:
        self.intent_dispatcher.shutdown()
        self.intent_manifest.shutdown()
        self.utterance_plugins.shutdown()
        self.metadata_plugins.shutdown()
        for pipeline in self.pipeline_plugins.values():
            if hasattr(pipeline, "stop"):
                try:
                    pipeline.stop()
                except Exception as e:
                    LOG.warning(f"Failed to stop pipeline {pipeline}: {e}")
                    continue
            if hasattr(pipeline, "shutdown"):
                try:
                    pipeline.shutdown()
                except Exception as e:
                    LOG.warning(f"Failed to shutdown pipeline {pipeline}: {e}")
                    continue

        self.bus.remove(SpecMessage.UTTERANCE, self.handle_utterance)
        self.bus.remove('add_context', self.handle_add_context)
        self.bus.remove('remove_context', self.handle_remove_context)
        self.bus.remove('clear_context', self.handle_clear_context)
        self.bus.remove('intent.service.intent.get', self.handle_get_intent)

        self.status.set_stopping()


def launch_standalone():
    from ovos_bus_client import MessageBusClient
    from ovos_utils import wait_for_exit_signal
    from ovos_config.locale import setup_locale
    from ovos_utils.log import init_service_logger

    LOG.info("Launching IntentService in standalone mode")
    init_service_logger("intents")
    setup_locale()

    bus = MessageBusClient()
    bus.run_in_thread()
    bus.connected_event.wait()

    intents = IntentService(bus)

    wait_for_exit_signal()

    intents.shutdown()

    LOG.info('IntentService shutdown complete!')


if __name__ == "__main__":
    launch_standalone()