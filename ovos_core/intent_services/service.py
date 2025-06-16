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
from typing import Tuple, Callable, List

import requests
from langcodes import closest_match
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_bus_client.util import get_message_lang
from ovos_config.config import Configuration
from ovos_config.locale import get_valid_languages
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.log import LOG
from ovos_utils.metrics import Stopwatch
from ovos_utils.process_utils import ProcessStatus, StatusCallbackMap
from ovos_utils.thread_utils import create_daemon

from ovos_core.transformers import MetadataTransformersService, UtteranceTransformersService, IntentTransformersService
from ovos_plugin_manager.pipeline import OVOSPipelineFactory
from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch, ConfidenceMatcherPipeline


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
                 error_hook=on_error, stopping_hook=on_stopping):
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
        self.status = ProcessStatus('intents', bus=self.bus, callback_map=callbacks)
        self.status.set_started()
        self.config = config or Configuration().get("intents", {})

        # load and cache the plugins right away so they receive all bus messages
        self.pipeline_plugins = {}

        self.utterance_plugins = UtteranceTransformersService(bus)
        self.metadata_plugins = MetadataTransformersService(bus)
        self.intent_plugins = IntentTransformersService(bus)

        # connection SessionManager to the bus,
        # this will sync default session across all components
        SessionManager.connect_to_bus(self.bus)

        self.bus.on('recognizer_loop:utterance', self.handle_utterance)

        # Context related handlers
        self.bus.on('add_context', self.handle_add_context)
        self.bus.on('remove_context', self.handle_remove_context)
        self.bus.on('clear_context', self.handle_clear_context)

        # Intents API
        self.bus.on('intent.service.intent.get', self.handle_get_intent)

        # internal, track skills that call self.deactivate to avoid reactivating them again
        self._deactivations = defaultdict(list)
        self.bus.on('intent.service.skills.deactivate', self._handle_deactivate)
        self.bus.on('intent.service.pipelines.reload', self.handle_reload_pipelines)

        self.status.set_alive()
        if preload_pipelines:
            self.bus.emit(Message('intent.service.pipelines.reload'))

    def handle_reload_pipelines(self, message: Message):
        pipeline_plugins = OVOSPipelineFactory.get_installed_pipeline_ids()
        LOG.debug(f"Installed pipeline plugins: {pipeline_plugins}")
        for p in pipeline_plugins:
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
        valid_langs = [standardize_lang_tag(l) for l in valid_langs]
        lang_keys = ["stt_lang",
                     "request_lang",
                     "detected_lang"]
        for k in lang_keys:
            if k in message.context:
                try:
                    v = standardize_lang_tag(message.context[k])
                    best_lang, _ = closest_match(v, valid_langs, max_distance=10)
                except:
                    v = message.context[k]
                    best_lang = "und"
                if best_lang == "und":
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
        migration_map = {
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

        matcher_id = migration_map.get(matcher_id, matcher_id)
        pipe_id = re.sub(r'-(high|medium|low)$', '', matcher_id)
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
        matchers = [(p, self.get_pipeline_matcher(p)) for p in session.pipeline]
        matchers = [m for m in matchers if m[1] is not None]  # filter any that failed to load
        final_pipeline = [k[0] for k in matchers]
        if session.pipeline != final_pipeline:
            LOG.warning(f"Requested some invalid pipeline components! "
                        f"filtered: {[k for k in session.pipeline if k not in final_pipeline]}")
        LOG.debug(f"Session final pipeline: {final_pipeline}")
        return matchers

    @staticmethod
    def _validate_session(message, lang):
        # get session
        lang = standardize_lang_tag(lang)
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

    def _emit_match_message(self, match: IntentHandlerMatch, message: Message, lang: str):
        """
        Emit a reply message for a matched intent, updating session and skill activation.

        This method processes matched intents from either a pipeline matcher or an intent handler,
        creating a reply message with matched intent details and managing skill activation.

        Args:
            match (IntentHandlerMatch): The matched intent object containing
                utterance and matching information.
            message (Message): The original messagebus message that triggered the intent match.
            lang (str): The language of the pipeline plugin match

        Details:
            - Handles two types of matches: PipelineMatch and IntentHandlerMatch
            - Creates a reply message with matched intent data
            - Activates the corresponding skill if not previously deactivated
            - Updates session information
            - Emits the reply message on the messagebus

        Side Effects:
            - Modifies session state
            - Emits a messagebus event
            - Can trigger skill activation events

        Returns:
            None
        """
        try:
            match = self.intent_plugins.transform(match)
        except Exception as e:
            LOG.error(f"Error in IntentTransformers: {e}")

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

                # NOTE: do not re-activate if the skill called self.deactivate
                # we could also skip activation if skill is already active,
                # but we still want to update the timestamp
                was_deactivated = match.skill_id in self._deactivations[sess.session_id]
                if not was_deactivated:
                    sess.activate_skill(match.skill_id)
                    # emit event for skills callback -> self.handle_activate
                    self.bus.emit(reply.forward(f"{match.skill_id}.activate"))

            # update Session if modified by pipeline
            reply.context["session"] = sess.serialize()

            # finally emit reply message
            self.bus.emit(reply)

        else:  # upload intent metrics if enabled
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
        LOG.info("utterance canceled, cancel_word:" + message.context.get("cancel_word"))
        # play dedicated cancel sound
        sound = Configuration().get('sounds', {}).get('cancel', "snd/cancel.mp3")
        # NOTE: message.reply to ensure correct message destination
        self.bus.emit(message.reply('mycroft.audio.play_sound', {"uri": sound}))
        self.bus.emit(message.reply("ovos.utterance.cancelled"))
        self.bus.emit(message.reply("ovos.utterance.handled"))

    def handle_utterance(self, message: Message):
        """Main entrypoint for handling user utterances

        Monitor the messagebus for 'recognizer_loop:utterance', typically
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
                    match = match_func(utterances, intent_lang, message)
                    if match:
                        LOG.info(f"{pipeline} match ({intent_lang}): {match}")
                        if match.skill_id and match.skill_id in sess.blacklisted_skills:
                            LOG.debug(
                                f"ignoring match, skill_id '{match.skill_id}' blacklisted by Session '{sess.session_id}'")
                            continue
                        if isinstance(match, IntentHandlerMatch) and match.match_type in sess.blacklisted_intents:
                            LOG.debug(
                                f"ignoring match, intent '{match.match_type}' blacklisted by Session '{sess.session_id}'")
                            continue
                        try:
                            self._emit_match_message(match, message, intent_lang)
                            break
                        except:
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
        """Send a message that no skill could handle the utterance.

        Args:
            message (Message): original message to forward from
        """
        sound = Configuration().get('sounds', {}).get('error', "snd/error.mp3")
        # NOTE: message.reply to ensure correct message destination
        self.bus.emit(message.reply('mycroft.audio.play_sound', {"uri": sound}))
        self.bus.emit(message.reply('complete_intent_failure', message.data))
        self.bus.emit(message.reply("ovos.utterance.handled"))

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
        sess = SessionManager.get(message)
        sess.context.inject_context(entity)

    @staticmethod
    def handle_remove_context(message: Message):
        """Remove specific context

        Args:
            message: data contains the 'context' item to remove
        """
        context = message.data.get('context')
        if context:
            sess = SessionManager.get(message)
            sess.context.remove_context(context)

    @staticmethod
    def handle_clear_context(message: Message):
        """Clears all keywords from context """
        sess = SessionManager.get(message)
        sess.context.clear_context()

    def handle_get_intent(self, message):
        """Get intent from either adapt or padatious.

        Args:
            message (Message): message containing utterance
        """
        utterance = message.data["utterance"]
        lang = get_message_lang(message)
        sess = SessionManager.get(message)
        match = None
        # Loop through the matching functions until a match is found.
        for pipeline, match_func in self.get_pipeline(session=sess):
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

    def shutdown(self):
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

        self.bus.remove('recognizer_loop:utterance', self.handle_utterance)
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