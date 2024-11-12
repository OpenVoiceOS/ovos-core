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
from collections import defaultdict
from typing import Tuple, Callable, List, Union, Dict

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_bus_client.util import get_message_lang

from ovos_config.config import Configuration
from ovos_config.locale import get_valid_languages
from ovos_core.intent_services.converse_service import ConverseService
from ovos_core.intent_services.fallback_service import FallbackService
from ovos_core.intent_services.stop_service import StopService
from ovos_core.transformers import MetadataTransformersService, UtteranceTransformersService
from ovos_plugin_manager.pipeline import OVOSPipelineFactory
from ovos_plugin_manager.templates.pipeline import PipelineMatch, IntentHandlerMatch
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.log import LOG, log_deprecation, deprecated
from ovos_utils.metrics import Stopwatch
from padacioso.opm import PadaciosoPipeline as PadaciosoService
import warnings


class IntentService:
    """OVOS intent service. parses utterances using a variety of systems.

    The intent service also provides the internal API for registering and
    querying the intent service.
    """

    def __init__(self, bus, config=None):
        self.bus = bus
        self.config = config or Configuration().get("intents", {})

        self.get_pipeline()  # trigger initial load of pipeline plugins (more may be lazy loaded on demand)

        self.utterance_plugins = UtteranceTransformersService(bus)
        self.metadata_plugins = MetadataTransformersService(bus)

        # connection SessionManager to the bus,
        # this will sync default session across all components
        SessionManager.connect_to_bus(self.bus)

        self.bus.on('recognizer_loop:utterance', self.handle_utterance)

        # Context related handlers
        self.bus.on('add_context', self.handle_add_context)
        self.bus.on('remove_context', self.handle_remove_context)
        self.bus.on('clear_context', self.handle_clear_context)

        # Intents API
        self.registered_vocab = []
        self.bus.on('intent.service.intent.get', self.handle_get_intent)

        # internal, track skills that call self.deactivate to avoid reactivating them again
        self._deactivations = defaultdict(list)
        self.bus.on('intent.service.skills.deactivate', self._handle_deactivate)

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

    def get_pipeline(self, skips=None, session=None, skip_stage_matchers=False) -> List[Tuple[str, Callable]]:
        """return a list of matcher functions ordered by priority
        utterances will be sent to each matcher in order until one can handle the utterance
        the list can be configured in mycroft.conf under intents.pipeline,
        in the future plugins will be supported for users to define their own pipeline"""
        skips = skips or []

        session = session or SessionManager.get()

        if skips:
            log_deprecation("'skips' kwarg has been deprecated!", "1.0.0")
            skips = [OVOSPipelineFactory._MAP.get(p, p) for p in skips]

        for p in OVOSPipelineFactory.get_installed_pipelines():
            LOG.info(f"Found pipeline: {p}")

        pipeline: List[str] = [OVOSPipelineFactory._MAP.get(p, p)
                               for p in session.pipeline
                               if p not in skips]
        matchers: List[Tuple[str, Callable]] = OVOSPipelineFactory.create(pipeline, use_cache=True, bus=self.bus,
                                                                          skip_stage_matchers=skip_stage_matchers)
        # Sort matchers to ensure the same order as in `pipeline`
        matcher_dict = dict(matchers)
        matchers = [(p, matcher_dict[p]) for p in pipeline if p in matcher_dict]
        final_pipeline = [k[0] for k in matchers]

        if pipeline != final_pipeline:
            LOG.warning(f"Requested some invalid pipeline components! "
                        f"filtered: {[k for k in pipeline if k not in final_pipeline]}")
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

    def _emit_match_message(self, match: Union[IntentHandlerMatch, PipelineMatch], message: Message):
        """
        Emit a reply message for a matched intent, updating session and skill activation.

        This method processes matched intents from either a pipeline matcher or an intent handler,
        creating a reply message with matched intent details and managing skill activation.

        Args:
            match (Union[IntentHandlerMatch, PipelineMatch]): The matched intent object containing
                utterance and matching information.
            message (Message): The original messagebus message that triggered the intent match.

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
        reply = None
        sess = match.updated_session or SessionManager.get(message)

        # utterance fully handled by pipeline matcher
        if isinstance(match, PipelineMatch):
            if match.handled:
                reply = message.reply("ovos.utterance.handled", {"skill_id": match.skill_id})
        # Launch skill if not handled by the match function
        elif isinstance(match, IntentHandlerMatch) and match.match_type:
            # keep all original message.data and update with intent match
            data = dict(message.data)
            data.update(match.match_data)
            reply = message.reply(match.match_type, data)

        if reply is not None:
            reply.data["utterance"] = match.utterance

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
                match = match_func(utterances, lang, message)
                if match:
                    LOG.info(f"{pipeline} match: {match}")
                    if match.skill_id and match.skill_id in sess.blacklisted_skills:
                        LOG.debug(
                            f"ignoring match, skill_id '{match.skill_id}' blacklisted by Session '{sess.session_id}'")
                        continue
                    if isinstance(match, IntentHandlerMatch) and match.match_type in sess.blacklisted_intents:
                        LOG.debug(
                            f"ignoring match, intent '{match.match_type}' blacklisted by Session '{sess.session_id}'")
                        continue
                    try:
                        self._emit_match_message(match, message)
                        break
                    except:
                        LOG.exception(f"{match_func} returned an invalid match")
                LOG.debug(f"no match from {match_func}")
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
        """Send a message that no skill could handle the utterance.

        Args:
            message (Message): original message to forward from
        """
        sound = Configuration().get('sounds', {}).get('error', "snd/error.mp3")
        # NOTE: message.reply to ensure correct message destination
        self.bus.emit(message.reply('mycroft.audio.play_sound', {"uri": sound}))
        self.bus.emit(message.reply('complete_intent_failure'))
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

        # Loop through the matching functions until a match is found.
        for pipeline, match_func in self.get_pipeline(session=sess, skip_stage_matchers=True):
            match = match_func([utterance], lang, message)
            if match:
                if match.match_type:
                    intent_data = match.match_data
                    intent_data["intent_name"] = match.match_type
                    intent_data["intent_service"] = pipeline
                    intent_data["skill_id"] = match.skill_id
                    intent_data["handler"] = match_func.__name__
                    self.bus.emit(message.reply("intent.service.intent.reply",
                                                {"intent": intent_data}))
                return

        # signal intent failure
        self.bus.emit(message.reply("intent.service.intent.reply",
                                    {"intent": None}))

    def shutdown(self):
        self.utterance_plugins.shutdown()
        self.metadata_plugins.shutdown()
        OVOSPipelineFactory.shutdown()

        self.bus.remove('recognizer_loop:utterance', self.handle_utterance)
        self.bus.remove('add_context', self.handle_add_context)
        self.bus.remove('remove_context', self.handle_remove_context)
        self.bus.remove('clear_context', self.handle_clear_context)
        self.bus.remove('intent.service.intent.get', self.handle_get_intent)

    ###########
    # DEPRECATED STUFF
    @property
    def registered_intents(self):
        log_deprecation("direct access to self.adapt_service is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        warnings.warn(
            "direct access to self.adapt_service is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        return []

    @property
    def skill_names(self) -> Dict:
        """DEPRECATED"""
        log_deprecation("skill names have been replaced by skill_id", "1.0.0")
        return {}

    @skill_names.setter
    def skill_names(self, v):
        log_deprecation("skill names have been replaced by skill_id", "1.0.0")

    @deprecated("skill names have been replaced by skill_id", "1.0.0")
    def update_skill_name_dict(self, message):
        """DEPRECATED"""

    @deprecated("skill names have been replaced by skill_id", "1.0.0")
    def get_skill_name(self, skill_id):
        """DEPRECATED"""
        return skill_id

    @deprecated("skill names have been replaced by skill_id", "1.0.0")
    def handle_get_skills(self, message):
        """DEPRECATED"""
        return []

    @property
    def adapt_service(self):
        warnings.warn(
            "direct access to self.adapt_service is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        log_deprecation("direct access to self.adapt_service is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        return None

    @property
    def padatious_service(self):
        warnings.warn(
            "direct access to self.padatious_service is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        log_deprecation("direct access to self.padatious_service is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        return None

    @property
    def padacioso_service(self):
        warnings.warn(
            "direct access to self.padacioso_service is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        log_deprecation("direct access to self.padacioso_service is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        return None

    @property
    def fallback(self):
        warnings.warn(
            "direct access to self.fallback is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        log_deprecation("direct access to self.fallback is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        return None

    @property
    def converse(self):
        warnings.warn(
            "direct access to self.converse is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        log_deprecation("direct access to self.converse is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        return None

    @property
    def common_qa(self):
        warnings.warn(
            "direct access to self.common_qa is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        log_deprecation("direct access to self.common_qa is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        return None

    @property
    def stop(self):
        warnings.warn(
            "direct access to self.stop is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        log_deprecation("direct access to self.stop is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        return None

    @property
    def ocp(self):
        warnings.warn(
            "direct access to self.ocp is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        log_deprecation("direct access to self.ocp is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        return None

    @adapt_service.setter
    def adapt_service(self, value):
        warnings.warn(
            "direct access to self.adapt_service is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        log_deprecation("direct access to self.adapt_service is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")

    @padatious_service.setter
    def padatious_service(self, value):
        warnings.warn(
            "direct access to self.padatious_service is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        log_deprecation("direct access to self.padatious_service is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")

    @padacioso_service.setter
    def padacioso_service(self, value):
        warnings.warn(
            "direct access to self.padacioso_service is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        log_deprecation("direct access to self.padacioso_service is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")

    @fallback.setter
    def fallback(self, value):
        warnings.warn(
            "direct access to self.fallback is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        log_deprecation("direct access to self.fallback is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")

    @converse.setter
    def converse(self, value):
        warnings.warn(
            "direct access to self.converse is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        log_deprecation("direct access to self.converse is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")

    @common_qa.setter
    def common_qa(self, value):
        warnings.warn(
            "direct access to self.common_qa is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        log_deprecation("direct access to self.common_qa is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")

    @stop.setter
    def stop(self, value):
        warnings.warn(
            "direct access to self.stop is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        log_deprecation("direct access to self.stop is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")

    @ocp.setter
    def ocp(self, value):
        warnings.warn(
            "direct access to self.ocp is deprecated",
            DeprecationWarning,
            stacklevel=2,
        )
        log_deprecation("direct access to self.ocp is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")

    @deprecated("handle_get_adapt moved to adapt service, this method does nothing", "1.0.0")
    def handle_get_adapt(self, message: Message):
        warnings.warn(
            "moved to adapt service, this method does nothing",
            DeprecationWarning,
            stacklevel=2,
        )

    @deprecated("handle_adapt_manifest moved to adapt service, this method does nothing", "1.0.0")
    def handle_adapt_manifest(self, message):
        warnings.warn(
            "moved to adapt service, this method does nothing",
            DeprecationWarning,
            stacklevel=2,
        )

    @deprecated("handle_vocab_manifest moved to adapt service, this method does nothing", "1.0.0")
    def handle_vocab_manifest(self, message):
        warnings.warn(
            "moved to adapt service, this method does nothing",
            DeprecationWarning,
            stacklevel=2,
        )

    @deprecated("handle_get_padatious moved to padatious service, this method does nothing", "1.0.0")
    def handle_get_padatious(self, message):
        warnings.warn(
            "moved to padatious service, this method does nothing",
            DeprecationWarning,
            stacklevel=2,
        )

    @deprecated("handle_padatious_manifest moved to padatious service, this method does nothing", "1.0.0")
    def handle_padatious_manifest(self, message):
        warnings.warn(
            "moved to padatious service, this method does nothing",
            DeprecationWarning,
            stacklevel=2,
        )

    @deprecated("handle_entity_manifest moved to padatious service, this method does nothing", "1.0.0")
    def handle_entity_manifest(self, message):
        warnings.warn(
            "moved to padatious service, this method does nothing",
            DeprecationWarning,
            stacklevel=2,
        )

    @deprecated("handle_register_vocab moved to individual pipeline services, this method does nothing", "1.0.0")
    def handle_register_vocab(self, message):
        warnings.warn(
            "moved to pipeline plugins, this method does nothing",
            DeprecationWarning,
            stacklevel=2,
        )

    @deprecated("handle_register_intent moved to individual pipeline services, this method does nothing", "1.0.0")
    def handle_register_intent(self, message):
        warnings.warn(
            "moved to pipeline plugins, this method does nothing",
            DeprecationWarning,
            stacklevel=2,
        )

    @deprecated("handle_detach_intent moved to individual pipeline services, this method does nothing", "1.0.0")
    def handle_detach_intent(self, message):
        warnings.warn(
            "moved to pipeline plugins, this method does nothing",
            DeprecationWarning,
            stacklevel=2,
        )

    @deprecated("handle_detach_skill moved to individual pipeline services, this method does nothing", "1.0.0")
    def handle_detach_skill(self, message):
        warnings.warn(
            "moved to pipeline plugins, this method does nothing",
            DeprecationWarning,
            stacklevel=2,
        )
