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
    """
    Logs that the IntentService is starting up.
    """
    LOG.info('IntentService is starting up.')


def on_alive():
    """
    Logs that the IntentService process is alive.
    """
    LOG.info('IntentService is alive.')


def on_ready():
    """
    Logs that the IntentService is ready for operation.
    """
    LOG.info('IntentService is ready.')


def on_error(e='Unknown'):
    """
    Logs an informational message indicating that the IntentService failed to launch.
    
    Args:
        e: The error message or exception that caused the failure. Defaults to 'Unknown'.
    """
    LOG.info(f'IntentService failed to launch ({e})')


def on_stopping():
    """
    Logs a message indicating that the IntentService is shutting down.
    """
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
                 Initializes the IntentService with intent parsing pipelines, transformer services, and event handlers.
                 
                 Sets up the process status callbacks, loads configuration, initializes utterance, metadata, and intent transformer services, connects the session manager to the message bus, and registers all relevant messagebus event handlers for utterance processing, context management, intent queries, and skill deactivation tracking. Optionally preloads all supported intent matching pipelines.
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
        """
        Reloads all installed intent pipeline plugins and updates the internal plugin cache.
        
        Iterates through available pipeline plugin IDs, attempts to load each plugin, and stores successfully loaded plugins in the internal cache. Logs the outcome for each plugin. Marks the service as ready after reloading.
        """
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
        Processes the utterance and context through transformer plugins to update utterances and enrich context metadata.
        
        The function applies utterance transformers, which may modify the utterances, and metadata transformers, which may update the context. The message is updated in place and returned.
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
        """
        Determines the most appropriate language for a query based on prioritized context keys.
        
        Checks for language indicators in the message context in the following order: 'stt_lang', 'request_lang', and 'detected_lang'. Returns the first valid language found that matches the enabled languages; otherwise, falls back to the default language from the message.
        """
        default_lang = get_message_lang(message)
        valid_langs = get_valid_languages()
        valid_langs = [standardize_lang_tag(l) for l in valid_langs]
        lang_keys = ["stt_lang",
                     "request_lang",
                     "detected_lang"]
        for k in lang_keys:
            if k in message.context:
                v = standardize_lang_tag(message.context[k])
                if v in valid_langs:  # TODO - use lang distance instead to choose best dialect
                    if v != default_lang:
                        LOG.info(f"replaced {default_lang} with {k}: {v}")
                    return v
                else:
                    LOG.warning(f"ignoring {k}, {v} is not in enabled languages: {valid_langs}")

        return default_lang

    def get_pipeline_matcher(self, matcher_id: str):
        """
        Returns the matcher function corresponding to the specified pipeline matcher ID.
        
        If the matcher ID is recognized, returns the appropriate callable matcher function from the loaded pipeline plugins. Returns None and logs an error if the matcher ID is unknown.
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
        """
        Returns an ordered list of intent matcher functions for the current session's pipeline.
        
        Each matcher is paired with its identifier and filtered to exclude any invalid or missing components. The pipeline order is determined by the session configuration, and a warning is logged if any requested matchers are unavailable.
        
        Returns:
            A list of tuples containing matcher IDs and their corresponding callable functions, ordered by priority.
        """
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
        """
        Validates and updates the session associated with a message for the specified language.
        
        If the session is the default and expired, it is reset. The session language is updated if necessary, and the session's timestamp is refreshed. The session state is synchronized with the message when changes occur.
        
        Args:
            message: The message containing session context.
            lang: The language code to set for the session.
        
        Returns:
            The validated and updated session object.
        """
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
        """
        Tracks skills that request deactivation during intent matching to prevent their reactivation within the same session.
        
        This is relevant for pipeline matchers where skill activation occurs after a match, such as fallback and converse pipelines.
        """
        sess = SessionManager.get(message)
        skill_id = message.data.get("skill_id")
        self._deactivations[sess.session_id].append(skill_id)

    def _emit_match_message(self, match: IntentHandlerMatch, message: Message, lang: str):
        """
        Emits a reply message for a matched intent, updating session state and managing skill activation.
        
        Transforms the matched intent, constructs a reply message with intent details, updates the session language and context, and emits the reply on the message bus. Activates the matched skill unless it was previously deactivated in the session. Asynchronously uploads intent match metrics. If no reply is generated, uploads failure metrics instead.
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
        """
        Uploads intent match data to configured remote endpoints for metrics collection.
        
        If one or more upload URLs are specified in the configuration, sends the utterance,
        intent, language, and match data as a POST request to each endpoint. Skips upload
        if no endpoints are configured.
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
        Handles utterance cancellation by playing a cancel sound and emitting cancellation events.
        
        Logs the cancellation, plays a configured cancel sound, and emits events to indicate that the utterance was canceled and processing is complete.
        """
        LOG.info("utterance canceled, cancel_word:" + message.context.get("cancel_word"))
        # play dedicated cancel sound
        sound = Configuration().get('sounds', {}).get('cancel', "snd/cancel.mp3")
        # NOTE: message.reply to ensure correct message destination
        self.bus.emit(message.reply('mycroft.audio.play_sound', {"uri": sound}))
        self.bus.emit(message.reply("ovos.utterance.cancelled"))
        self.bus.emit(message.reply("ovos.utterance.handled"))

    def handle_utterance(self, message: Message):
        """
        Processes a user utterance message, applies transformers, matches intents using configured pipelines, and emits the appropriate response.
        
        The function handles utterance transformation, language disambiguation, session validation, and sequentially attempts intent matching across multiple pipelines and languages. If a match is found and not blacklisted, it emits a match message; otherwise, it signals a complete intent failure. Session state is synchronized after processing.
        
        Args:
            message (Message): The incoming message containing user utterances and context.
        
        Returns:
            A tuple containing the matched intent (or None), the updated message context, and a stopwatch object with timing information.
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
                self.send_complete_intent_failure(message)

        LOG.debug(f"intent matching took: {stopwatch.time}")

        # sync any changes made to the default session, eg by ConverseService
        if sess.session_id == "default":
            SessionManager.sync(message)
        elif sess.session_id in self._deactivations:
            self._deactivations.pop(sess.session_id)
        return match, message.context, stopwatch

    def send_complete_intent_failure(self, message):
        """
        Emits events indicating that no skill could handle the given utterance.
        
        Plays an error sound and notifies listeners of the intent failure and utterance handling completion.
        """
        sound = Configuration().get('sounds', {}).get('error', "snd/error.mp3")
        # NOTE: message.reply to ensure correct message destination
        self.bus.emit(message.reply('mycroft.audio.play_sound', {"uri": sound}))
        self.bus.emit(message.reply('complete_intent_failure'))
        self.bus.emit(message.reply("ovos.utterance.handled"))

    @staticmethod
    def handle_add_context(message: Message):
        """
        Adds a context entity to the current session for intent recognition.
        
        The context entity is defined by the provided context value and an optional alias word and origin. This enables subsequent utterances to be matched with additional contextual information.
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
        """
        Removes a specific context item from the current session.
        
        The context item to remove is specified in the message data under the 'context' key.
        """
        context = message.data.get('context')
        if context:
            sess = SessionManager.get(message)
            sess.context.remove_context(context)

    @staticmethod
    def handle_clear_context(message: Message):
        """
        Removes all context keywords from the current session.
        
        This clears any stored context entities, resetting the session's context state.
        """
        sess = SessionManager.get(message)
        sess.context.clear_context()

    def handle_get_intent(self, message):
        """
        Processes an intent query for a given utterance and emits a reply with the matched intent or failure.
        
        Attempts to match the provided utterance against all configured intent pipelines in order. If a match is found, emits a reply message containing intent details; otherwise, emits a reply indicating no intent was matched.
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
        """
        Shuts down the IntentService and its components.
        
        Stops all transformer services and pipeline plugins, unregisters message bus event handlers, and updates the service status to indicate it is stopping.
        """
        self.utterance_plugins.shutdown()
        self.metadata_plugins.shutdown()
        for pipeline in self.pipeline_plugins.values():
            if hasattr(pipeline, "stop"):
                try:
                    pipeline.stop()
                except:
                    continue
            if hasattr(pipeline, "shutdown"):
                try:
                    pipeline.shutdown()
                except:
                    continue

        self.bus.remove('recognizer_loop:utterance', self.handle_utterance)
        self.bus.remove('add_context', self.handle_add_context)
        self.bus.remove('remove_context', self.handle_remove_context)
        self.bus.remove('clear_context', self.handle_clear_context)
        self.bus.remove('intent.service.intent.get', self.handle_get_intent)

        self.status.set_stopping()


def launch_standalone():
    """
    Runs the IntentService as a standalone process.
    
    Initializes logging and locale, connects to the message bus, starts the IntentService, waits for an exit signal, and then shuts down the service cleanly.
    """
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