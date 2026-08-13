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

import json
import re
import time
from collections import defaultdict
from typing import Optional, Tuple, Callable, List

import requests
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_bus_client.util import get_message_lang
from ovos_config.config import Configuration
from ovos_config.locale import get_valid_languages
from ovos_spec_tools import closest_lang, standardize_lang, SpecMessage
from ovos_spec_tools.context import resolve_key
from ovos_utils.log import LOG
from ovos_utils.metrics import Stopwatch
from ovos_utils.process_utils import ProcessStatus, StatusCallbackMap
from ovos_utils.thread_utils import create_daemon

from ovos_core.transformers import MetadataTransformersService, UtteranceTransformersService, IntentTransformersService
from ovos_core.intent_services.dispatcher import IntentDispatcher, DEFAULT_HANDLER_TIMEOUT
from ovos_core.intent_services.manifest import IntentManifest
from ovos_plugin_manager.pipeline import OVOSPipelineFactory
from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch, ConfidenceMatcherPipeline


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
#   stop           -> ovos-stop-pipeline-plugin          (STOP-1 §4: stop)
#   fallback       -> ovos-fallback-pipeline-plugin      (FALLBACK-1 §6.3: fallback)
#   common_query   -> ovos-common-query-pipeline-plugin  (COMMON-QUERY-1 §3: common_query)
_RESERVED_NAME_PIPELINES = {
    "ovos-converse-pipeline-plugin",
    "ovos-stop-pipeline-plugin",
    "ovos-fallback-pipeline-plugin",
    "ovos-common-query-pipeline-plugin",
}


def _produces_reserved_name(pipeline_id: Optional[str]) -> bool:
    """OVOS-PIPELINE-1 §7.3: True when ``pipeline_id`` is a reserved-name role
    whose dispatches must NOT stamp ``session.active_handlers`` (§7.1)."""
    if not pipeline_id:
        return False
    return _PIPELINE_RE.sub("", pipeline_id) in _RESERVED_NAME_PIPELINES


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
        """
        Initializes the IntentService with all intent parsing pipelines, transformer services, and messagebus event handlers.

        Args:
            bus: The messagebus connection used for event-driven communication.
            config: Optional configuration dictionary for intent services.

        Sets up skill name mapping, loads all supported intent matching pipelines (including Adapt, Padatious, Padacioso, Fallback, Converse, CommonQA, Stop, OCP, Persona, and optionally LLM and Model2Vec pipelines), initializes utterance and metadata transformer services, connects the session manager, and registers all relevant messagebus event handlers for utterance processing, context management, intent queries, and skill deactivation tracking.
        """
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
            bus, timeout=handler_timeout, on_terminal=self._emit_utterance_handled)

        # INTENT-4 §10 manifest — indexes registration broadcasts and serves
        # ovos.intent.list / ovos.intent.describe pull-queries.
        self.intent_manifest: IntentManifest = IntentManifest(bus)

        # connection SessionManager to the bus,
        # this will sync default session across all components
        SessionManager.connect_to_bus(self.bus)

        self.bus.on(SpecMessage.UTTERANCE, self.handle_utterance)

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

    def handle_reload_pipelines(self, message: Message):
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

    def _handle_transformers(self, message):
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
    def disambiguate_lang(message):
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

    def get_pipeline_matcher(self, matcher_id: str):
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
            LOG.error(f"Unknown pipeline matcher: {matcher_id}")
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
        blacklisted = set(session.blacklisted_pipelines or [])
        requested = [p for p in session.pipeline if p not in blacklisted]
        if blacklisted:
            skipped = [p for p in session.pipeline if p in blacklisted]
            if skipped:
                LOG.debug(f"Session '{session.session_id}' blacklisted "
                          f"pipelines skipped: {skipped}")

        matchers = [(p, self.get_pipeline_matcher(p)) for p in requested]
        matchers = [m for m in matchers if m[1] is not None]  # filter any that failed to load
        final_pipeline = [k[0] for k in matchers]
        if requested != final_pipeline:
            LOG.warning(f"Requested some invalid pipeline components! "
                        f"filtered: {[k for k in requested if k not in final_pipeline]}")
        LOG.debug(f"Session final pipeline: {final_pipeline}")
        return matchers

    @staticmethod
    def _validate_session(message, lang):
        # get session
        lang = standardize_lang(lang)
        sess = SessionManager.get(message)
        if sess.session_id == "default":
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
            SessionManager.update(sess)
        sess.touch()
        return sess

    def _handle_deactivate(self, message):
        """internal helper, track if a skill asked to be removed from active list during intent match
        in this case we want to avoid reactivating it again
        This only matters in PipelineMatchers, such as fallback and converse
        in those cases the activation is only done AFTER the match, not before unlike intents
        """
        sess = SessionManager.get(message)
        skill_id = message.data.get("skill_id")
        self._deactivations[sess.session_id].append(skill_id)

    def _emit_utterance_handled(self, dispatch_msg: Message):
        """OVOS-PIPELINE-1 §9.5 — emit the universal ``ovos.utterance.handled``
        end-marker once a matched handler reaches its §8 terminal.

        Invoked by the dispatcher (``on_terminal``) right after a complete/error/
        timeout terminal is on the bus — non-blocking, and ordered after the terminal
        so consumers never see the end-marker first. The no-match and cancel paths
        emit their own end-marker inline; together they give exactly one per
        utterance."""
        msg = dispatch_msg.forward(SpecMessage.UTTERANCE_HANDLED, {})
        # the dispatch message's session snapshot predates the handler run, and
        # messages the handler itself emitted (e.g. the framework done-signal)
        # carry that same stale snapshot — each inbound fold is last-writer-wins,
        # so a skill that deactivated itself mid-handler gets re-activated by
        # its own ack. Re-apply the tracked deactivations to the live session
        # and stamp it on the end-marker so the utterance terminates with the
        # session state the handler actually requested.
        sid = (dispatch_msg.context.get("session") or {}).get("session_id")
        live = SessionManager.sessions.get(sid) if sid else None
        if live is not None:
            for skill_id in self._deactivations.get(sid) or []:
                if live.is_active(skill_id):
                    live.deactivate_skill(skill_id)
            msg.context["session"] = live.serialize()
        self.bus.emit(msg)

    def _missing_required_slots(self, match: IntentHandlerMatch,
                                session_id: str, lang: str) -> List[str]:
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
        return [slot for slot in required_slots if not match_data.get(slot)]

    def _dispatch_match(self, match: IntentHandlerMatch, message: Message, lang: str,
                        pipeline_id: str = None) -> None:
        """Orchestrate the OVOS-PIPELINE-1 §6.1 post-match steps, then dispatch.

        Runs the service-state-dependent post-match orchestration — the
        intent-transformer chain (TRANSFORM-1 §3.4), skill activation +
        ``{skill_id}.activate``, session update, and ``context['pipeline_id']``
        stamping (§7.1) — builds the dispatch Message, emits the §9.2
        ``ovos.intent.matched`` notification, and hands the dispatch Message to
        the IntentDispatcher, which owns the §7 dispatch + §8 handler-lifecycle
        trio.

        Args:
            match (IntentHandlerMatch): The matched intent (utterance, match_type,
                skill_id, match_data, optional updated_session).
            message (Message): The originating utterance Message to derive from.
            lang (str): The content language of the match.
            pipeline_id (str): The pipeline plugin that produced the match (§3.1).

        Returns:
            None
        """
        try:
            match = self.intent_plugins.transform(match)
        except Exception:
            LOG.exception("_dispatch_match failed")

        reply = None
        sess = match.updated_session or SessionManager.get(message)
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
                                                        match.match_data))

        if reply is not None:
            reply.data["utterance"] = match.utterance
            reply.data["lang"] = lang

            # update active skill list
            if match.skill_id:
                # ensure skill_id is present in message.context
                reply.context["skill_id"] = match.skill_id

                was_deactivated = match.skill_id in self._deactivations[sess.session_id]
                if not was_deactivated:
                    # OVOS-PIPELINE-1 §7.1 pushes the skill onto the session's
                    # active-handler recency list. §7.3 SUPPRESSES that push for
                    # reserved intent_name dispatches (converse/response/stop/
                    # fallback/common_query): a reserved name is a continuation
                    # or termination of an already-active skill's participation,
                    # not a fresh activation. `activate_skill` is a back-compat
                    # shim over `add_active_handler` (§7.1) in current bus-client.
                    if not _produces_reserved_name(pipeline_id):
                        sess.activate_skill(match.skill_id)
                    # emit event for skills callback -> self.handle_activate
                    self.bus.emit(reply.forward(f"{match.skill_id}.activate"))

            # update Session if modified by pipeline
            reply.context["session"] = sess.serialize()

            # stamp the matching plugin's identity on the dispatch (§3.1, §7.1)
            if pipeline_id:
                reply.context["pipeline_id"] = pipeline_id

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
                                                        match.match_data))

    @staticmethod
    def _upload_match_data(utterance: str, intent: str, lang: str, match_data: dict):
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
            "match_data": json.dumps(match_data, ensure_ascii=False)
        }
        for url in endpoints:
            try:
                # Add a timeout to prevent hanging
                response = requests.post(url, data=data, headers=headers, timeout=3)
                LOG.info(f"Uploaded intent metrics to '{url}' - Response: {response.status_code}")
            except Exception as e:
                LOG.warning(f"Failed to upload metrics: {e}")

    def send_cancel_event(self, message):
        """
        Emit events and play a sound when an utterance is canceled.

        Logs the cancellation with the specific cancel word, plays a predefined cancel sound,
        and emits multiple events to signal the utterance cancellation.

        Parameters:
            message (Message): The original message that triggered the cancellation.

        Events Emitted:
            - 'mycroft.audio.play_sound': Plays a cancel sound from configuration
            - 'ovos.utterance.cancelled': Signals that the utterance was canceled
            - 'ovos.utterance.handled': Indicates the utterance processing is complete

        Notes:
            - Uses the default cancel sound path 'snd/cancel.mp3' if not specified in configuration
            - Ensures events are sent as replies to the original message
        """
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

    def handle_utterance(self, message: Message):
        """Main entrypoint for handling user utterances

        Monitor the messagebus for 'ovos.utterance.handle', typically
        generated by a spoken interaction but potentially also from a CLI
        or other method of injecting a 'user utterance' into the system.

        Utterances then work through this sequence to be handled:
        1) UtteranceTransformers can modify the utterance and metadata in message.context
        2) MetadataTransformers can modify the metadata in message.context
        3) Language is extracted from message
        4) Active skills attempt to handle using converse()
        5) Padatious high match intents (conf > 0.95)
        6) Adapt intent handlers
        7) CommonQuery Skills
        8) High Priority Fallbacks
        9) Padatious near match intents (conf > 0.8)
        10) General Fallbacks
        11) Padatious loose match intents (conf > 0.5)
        12) Catch all fallbacks including Unknown intent handler

        If all these fail the complete_intent_failure message will be sent
        and a generic error sound played.

        Args:
            message (Message): The messagebus data
        """
        # Get utterance utterance_plugins additional context
        message = self._handle_transformers(message)

        if message.context.get("canceled"):
            self.send_cancel_event(message)
            return

        # tag language of this utterance
        lang = self.disambiguate_lang(message)

        utterances = message.data.get('utterances', [])
        LOG.info(f"Parsing utterance: {utterances}")

        stopwatch = Stopwatch()

        # get session
        sess = self._validate_session(message, lang)
        message.context["session"] = sess.serialize()

        # match
        match = None
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
                            match, sess.session_id, intent_lang)
                        if missing:
                            LOG.debug(f"ignoring match '{match.match_type}': "
                                      f"missing required slots {missing} (§6.2)")
                            continue
                        try:
                            self._dispatch_match(match, message, intent_lang,
                                                     pipeline_id=pipeline)
                            break
                        except Exception:
                            LOG.exception(f"{match_func} returned an invalid match")
                else:
                    LOG.debug(f"no match from {match_func}")
                    continue
                break
            else:
                # Nothing was able to handle the intent
                # Ask politely for forgiveness for failing in this vital task
                message.data["lang"] = lang
                self.send_complete_intent_failure(message)

        LOG.debug(f"intent matching took: {stopwatch.time}")

        # sync any changes made to the default session, eg by ConverseService
        if sess.session_id == "default":
            SessionManager.sync(message)
        elif sess.session_id in self._deactivations:
            self._deactivations.pop(sess.session_id)
        return match, message.context, stopwatch

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

    @staticmethod
    def _registry_session_for_context_write(message: Message) -> "Session":
        """Resolve the session object to mutate for an in-lifecycle context write.

        Wave-3 CONFIRMED (round 4): ``SessionManager.get(message)`` always folds
        the incoming message's session onto the live registry entry
        (``SessionManager._store``), and for NAMED sessions that fold is
        full-replace (``update_from``). Calling it from a context handler means
        the fold first wipes the registry entry's ``intent_context`` with the
        message's stale snapshot, then every subsequent mid-lifecycle frame
        (skill replies, follow-up handler frames) re-wipes it again - a named
        session's context can never survive to the terminal event. SESSION-2
        §2.6 is unambiguous: folding a message's session onto the working
        session belongs at lifecycle entry only; incidental messages must never
        mutate it. This is not a named-session-only defect: ``update_from``
        round-trips through full serialize/deserialize for every session id,
        including ``"default"`` - a stale default-session snapshot arriving
        on an incidental message wipes the device-local default session's
        context exactly the same way. The registry-first fix below is load-
        bearing for the default session too, not only named ones.

        Fix (this handler's scope only - the general fold-discipline at every
        ``get(message)`` call site is a tracked follow-up): resolve the
        session_id off the message and, if the registry already holds a live
        entry for it, mutate that object directly - no fold. Fall back to
        ``SessionManager.get(message)`` (today's behavior) only when no
        registry entry exists yet, e.g. out-of-registry/test callers.
        """
        session_data = message.context.get("session") if message and message.context else None
        session_id = session_data.get("session_id") if isinstance(session_data, dict) else None
        if session_id and session_id in SessionManager.sessions:
            return SessionManager.sessions[session_id]
        return SessionManager.get(message)

    @staticmethod
    def handle_add_context(message: Message):
        """Add context

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
        sess = IntentService._registry_session_for_context_write(message)
        sess.context.inject_context(entity)
        # OVOS-CONTEXT-1 §2/§7: pipelines gate and inject from the canonical
        # `session.intent_context` map, so a keyword added via `set_context`
        # must land there too or it never reaches matching. Entries are
        # keyed by the context token and carry its injected value.
        #
        # Round 3 (wave-3 live lead): `sess.context.inject_context()` above
        # (the legacy `_IntentContextView`, ovos-bus-client) already folded
        # its own write into `session.intent_context[context]`, stamping
        # `expires_at = now + timeout` using the adapt `context.timeout`
        # config convention (`Configuration()["context"]["timeout"]`,
        # minutes, default 2 -> 120s). The plain-dict overwrite that used to
        # follow here (`ctx[context] = {"value": ...}`) clobbered that stamp
        # two lines later - the pre-existing dev "immortal context entries"
        # bug: `ovos_spec_tools.context.is_live()` treats a missing
        # `expires_at` as never-expiring, so `prune()` could never reap
        # these entries. OVOS-CONTEXT-1 sides against that: legacy-sourced
        # entries carry decay; immortality is reserved for deliberate
        # writers, which the skill API is not.
        #
        # Round 5 (C1): a re-set of the same context key is a wholesale
        # replace, not a merge (OVOS-CONTEXT-1 §5) - there is no read-back
        # API for consumers to notice a stale expiry (§5.3). Every re-set
        # must refresh `expires_at` unconditionally, same as
        # `inject_context()` above does for the munged key. Preserving a
        # prior stamp here (reading it back off `ctx`) let this key and the
        # resolved private key below drift out of sync: a skill re-calling
        # `set_context` kept the adapt entry alive while the resolved entry
        # kept dying at its original expiry. One decay policy, computed
        # once, applied to both keys.
        context_cfg = Configuration().get('context', {})
        timeout_s = context_cfg.get('timeout', 2) * 60
        now = time.time()
        ctx = dict(sess.intent_context or {})
        munged_entry = {"value": word or context}
        expires_at = now + timeout_s if timeout_s > 0 else None
        if expires_at is not None:
            munged_entry["expires_at"] = expires_at
        ctx[context] = munged_entry
        # Two dialects meet here: legacy ADAPT context is stored under the
        # producer's munged `alphanumeric_skill_id + key` spelling (above),
        # while the declarative OVOS-CONTEXT-1 gate resolves a private
        # declaration to `resolve_key(key, "private", skill_id)` (colon
        # separated, unsanitized) - the two never coincide. When the
        # producer (ovos-workshop's set_context) names the original,
        # unmunged key via `data["key"]` and the message carries a
        # skill_id, also write the resolved private-scope entry so the
        # gate becomes reachable. The skill API is private-scope by
        # construction (its stored key is always skill-prefixed); shared-
        # scope writes are session-sync territory, not this handler's.
        key = message.data.get('key')
        skill_id = message.context.get('skill_id') if message.context else None
        if key and skill_id:
            resolved = resolve_key(key, "private", skill_id)
            if resolved:
                # Round 2 (C3): the fallback value must be the ORIGINAL key,
                # not the munged legacy context string - the munged spelling
                # is an internal wire detail of the ADAPT dialect and must
                # never leak into OVOS-CONTEXT-1 §7 slot injection via this
                # (declarative-gate) entry.
                # Round 5 (C1): stamp the SAME `expires_at` computed above
                # for the munged key, unconditionally, on every re-set - no
                # setdefault-style preservation of a prior write's expiry.
                # Preserving it here was the bug: it let this resolved key
                # keep dying at the FIRST write's expiry while the munged
                # key above kept getting refreshed by `inject_context()`,
                # so the declarative gate could close while the legacy
                # adapt context was still alive (or vice versa). One decay
                # policy, one computed `expires_at`, both keys.
                resolved_entry = {"value": word or key}
                if expires_at is not None:
                    resolved_entry["expires_at"] = expires_at
                ctx[resolved] = resolved_entry
        sess.intent_context = ctx

    @staticmethod
    def handle_remove_context(message: Message):
        """Remove specific context

        Args:
            message: data contains the 'context' item to remove
        """
        context = message.data.get('context')
        if context:
            sess = IntentService._registry_session_for_context_write(message)
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
            sess.intent_context = ctx or None

    @staticmethod
    def handle_clear_context(message: Message):
        """Clears all keywords from context """
        sess = IntentService._registry_session_for_context_write(message)
        sess.context.clear_context()
        # mirror the clear into the OVOS-CONTEXT-1 map (see `handle_add_context`)
        sess.intent_context = None

    def handle_get_intent(self, message):
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