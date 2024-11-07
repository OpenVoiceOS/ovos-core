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
from typing import Tuple, Callable, Union

from ocp_pipeline.opm import OCPPipelineMatcher
from ovos_adapt.opm import AdaptPipeline
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_bus_client.util import get_message_lang
from ovos_commonqa.opm import CommonQAService
from ovos_config.config import Configuration
from ovos_config.locale import setup_locale, get_valid_languages
from ovos_core.intent_services.converse_service import ConverseService
from ovos_core.intent_services.fallback_service import FallbackService
from ovos_core.intent_services.stop_service import StopService
from ovos_core.transformers import MetadataTransformersService, UtteranceTransformersService
from ovos_plugin_manager.templates.pipeline import PipelineMatch, IntentHandlerMatch
from ovos_utils.lang import standardize_lang_tag
from ovos_utils.log import LOG, log_deprecation, deprecated
from ovos_utils.metrics import Stopwatch
from padacioso.opm import PadaciosoPipeline as PadaciosoService


class IntentService:
    """OVOS intent service. parses utterances using a variety of systems.

    The intent service also provides the internal API for registering and
    querying the intent service.
    """

    def __init__(self, bus, config=None):
        self.bus = bus
        self.config = config or Configuration().get("intents", {})

        # Dictionary for translating a skill id to a name
        self.skill_names = {}

        self._adapt_service = None
        self._padatious_service = None
        self._padacioso_service = None
        self._fallback = None
        self._converse = None
        self._common_qa = None
        self._stop = None
        self._ocp = None
        self._load_pipeline_plugins()

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
        self.bus.on('intent.service.skills.get', self.handle_get_skills)
        self.bus.on('mycroft.skills.loaded', self.update_skill_name_dict)

        # internal, track skills that call self.deactivate to avoid reactivating them again
        self._deactivations = defaultdict(list)
        self.bus.on('intent.service.skills.deactivate', self._handle_deactivate)

    def _load_pipeline_plugins(self):
        # TODO - replace with plugin loader from OPM
        self._adapt_service = AdaptPipeline(bus=self.bus, config=self.config.get("adapt", {}))
        if "padatious" not in self.config:
            self.config["padatious"] = Configuration().get("padatious", {})
        try:
            if self.config["padatious"].get("disabled"):
                LOG.info("padatious forcefully disabled in config")
            else:
                from ovos_padatious.opm import PadatiousPipeline
                self._padatious_service = PadatiousPipeline(self.bus, self.config["padatious"])
        except ImportError:
            LOG.error(f'Failed to create padatious intent handlers, padatious not installed')

        self._padacioso_service = PadaciosoService(self.bus, self.config["padatious"])
        self._fallback = FallbackService(self.bus)
        self._converse = ConverseService(self.bus)
        self._common_qa = CommonQAService(self.bus, self.config.get("common_query"))
        self._stop = StopService(self.bus)
        self._ocp = OCPPipelineMatcher(self.bus, config=self.config.get("OCP", {}))

    def update_skill_name_dict(self, message):
        """Messagebus handler, updates dict of id to skill name conversions."""
        self.skill_names[message.data['id']] = message.data['name']

    def get_skill_name(self, skill_id):
        """Get skill name from skill ID.

        Args:
            skill_id: a skill id as encoded in Intent handlers.

        Returns:
            (str) Skill name or the skill id if the skill wasn't found
        """
        return self.skill_names.get(skill_id, skill_id)

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

    def get_pipeline(self, skips=None, session=None) -> Tuple[str, Callable]:
        """return a list of matcher functions ordered by priority
        utterances will be sent to each matcher in order until one can handle the utterance
        the list can be configured in mycroft.conf under intents.pipeline,
        in the future plugins will be supported for users to define their own pipeline"""
        session = session or SessionManager.get()

        # Create matchers
        # TODO - from plugins
        if self._padatious_service is None:
            if any("padatious" in p for p in session.pipeline):
                LOG.warning("padatious is not available! using padacioso in it's place, "
                            "intent matching will be extremely slow in comparison")
            padatious_matcher = self._padacioso_service
        else:
            padatious_matcher = self._padatious_service

        matchers = {
            "converse": self._converse.converse_with_skills,
            "stop_high": self._stop.match_stop_high,
            "stop_medium": self._stop.match_stop_medium,
            "stop_low": self._stop.match_stop_low,
            "padatious_high": padatious_matcher.match_high,
            "padacioso_high": self._padacioso_service.match_high,
            "adapt_high": self._adapt_service.match_high,
            "common_qa": self._common_qa.match,
            "fallback_high": self._fallback.high_prio,
            "padatious_medium": padatious_matcher.match_medium,
            "padacioso_medium": self._padacioso_service.match_medium,
            "adapt_medium": self._adapt_service.match_medium,
            "fallback_medium": self._fallback.medium_prio,
            "padatious_low": padatious_matcher.match_low,
            "padacioso_low": self._padacioso_service.match_low,
            "adapt_low": self._adapt_service.match_low,
            "fallback_low": self._fallback.low_prio
        }
        if self._ocp is not None:
            matchers.update({
                "ocp_high": self._ocp.match_high,
                "ocp_medium": self._ocp.match_medium,
                "ocp_fallback": self._ocp.match_fallback,
                "ocp_legacy": self._ocp.match_legacy})
        skips = skips or []
        pipeline = [k for k in session.pipeline if k not in skips]
        if any(k not in matchers for k in pipeline):
            LOG.warning(f"Requested some invalid pipeline components! "
                        f"filtered {[k for k in pipeline if k not in matchers]}")
            pipeline = [k for k in pipeline if k in matchers]
        LOG.debug(f"Session pipeline: {pipeline}")
        return [(k, matchers[k]) for k in pipeline]

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
        """Update the message data with the matched utterance information and
        activate the corresponding skill if available.

        Args:
            match (IntentHandlerMatch): The matched utterance object.
            message (Message): The messagebus data.
        """
        reply = None
        sess = SessionManager.get(message)

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
                    reply.context["session"] = sess.serialize()
                    # emit event for skills callback -> self.handle_activate
                    self.bus.emit(reply.forward(f"{match.skill_id}.activate"))

            self.bus.emit(reply)

    def send_cancel_event(self, message):
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
        for pipeline, match_func in self.get_pipeline(skips=["converse",
                                                             "fallback_high",
                                                             "fallback_medium",
                                                             "fallback_low"],
                                                      session=sess):
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

    def handle_get_skills(self, message):
        """Send registered skills to caller.

        Argument:
            message: query message to reply to.
        """
        self.bus.emit(message.reply("intent.service.skills.reply",
                                    {"skills": self.skill_names}))

    def shutdown(self):
        self.utterance_plugins.shutdown()
        self.metadata_plugins.shutdown()
        self._adapt_service.shutdown()
        self._padacioso_service.shutdown()
        if self._padatious_service:
            self._padatious_service.shutdown()
        self._common_qa.shutdown()
        self._converse.shutdown()
        self._fallback.shutdown()
        if self._ocp:
            self._ocp.shutdown()

        self.bus.remove('recognizer_loop:utterance', self.handle_utterance)
        self.bus.remove('add_context', self.handle_add_context)
        self.bus.remove('remove_context', self.handle_remove_context)
        self.bus.remove('clear_context', self.handle_clear_context)
        self.bus.remove('mycroft.skills.loaded', self.update_skill_name_dict)
        self.bus.remove('intent.service.intent.get', self.handle_get_intent)
        self.bus.remove('intent.service.skills.get', self.handle_get_skills)

    ###########
    # DEPRECATED STUFF
    @property
    def registered_intents(self):
        log_deprecation("direct access to self.adapt_service is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        lang = get_message_lang()
        return [parser.__dict__
                for parser in self._adapt_service.engines[lang].intent_parsers]

    @property
    def adapt_service(self):
        log_deprecation("direct access to self.adapt_service is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        return self._adapt_service

    @property
    def padatious_service(self):
        log_deprecation("direct access to self.padatious_service is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        return self._padatious_service

    @property
    def padacioso_service(self):
        log_deprecation("direct access to self.padacioso_service is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        return self._padacioso_service

    @property
    def fallback(self):

        log_deprecation("direct access to self.fallback is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        return self._fallback

    @property
    def converse(self):
        log_deprecation("direct access to self.converse is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        return self._converse

    @property
    def common_qa(self):
        log_deprecation("direct access to self.common_qa is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        return self._common_qa

    @property
    def stop(self):
        log_deprecation("direct access to self.stop is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        return self._stop

    @property
    def ocp(self):
        log_deprecation("direct access to self.ocp is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        return self._ocp

    @adapt_service.setter
    def adapt_service(self, value):
        log_deprecation("direct access to self.adapt_service is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        self._adapt_service = value

    @padatious_service.setter
    def padatious_service(self, value):
        log_deprecation("direct access to self.padatious_service is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        self._padatious_service = value

    @padacioso_service.setter
    def padacioso_service(self, value):
        log_deprecation("direct access to self.padacioso_service is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        self._padacioso_service = value

    @fallback.setter
    def fallback(self, value):
        log_deprecation("direct access to self.fallback is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        self._fallback = value

    @converse.setter
    def converse(self, value):
        log_deprecation("direct access to self.converse is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        self._converse = value

    @common_qa.setter
    def common_qa(self, value):
        log_deprecation("direct access to self.common_qa is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        self._common_qa = value

    @stop.setter
    def stop(self, value):
        log_deprecation("direct access to self.stop is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        self._stop = value

    @ocp.setter
    def ocp(self, value):
        log_deprecation("direct access to self.ocp is deprecated, "
                        "pipelines are in the progress of being replaced with plugins", "1.0.0")
        self._ocp = value

    @deprecated("handle_get_adapt moved to adapt service, this method does nothing", "1.0.0")
    def handle_get_adapt(self, message: Message):
        """DEPRECATED"""

    @deprecated("handle_adapt_manifest moved to adapt service, this method does nothing", "1.0.0")
    def handle_adapt_manifest(self, message):
        """DEPRECATED"""

    @deprecated("handle_vocab_manifest moved to adapt service, this method does nothing", "1.0.0")
    def handle_vocab_manifest(self, message):
        """DEPRECATED"""

    @deprecated("handle_get_padatious moved to padatious service, this method does nothing", "1.0.0")
    def handle_get_padatious(self, message):
        """DEPRECATED"""

    @deprecated("handle_padatious_manifest moved to padatious service, this method does nothing", "1.0.0")
    def handle_padatious_manifest(self, message):
        """DEPRECATED"""

    @deprecated("handle_entity_manifest moved to padatious service, this method does nothing", "1.0.0")
    def handle_entity_manifest(self, message):
        """DEPRECATED"""

    @deprecated("handle_register_vocab moved to individual pipeline services, this method does nothing", "1.0.0")
    def handle_register_vocab(self, message):
        """DEPRECATED"""

    @deprecated("handle_register_intent moved to individual pipeline services, this method does nothing", "1.0.0")
    def handle_register_intent(self, message):
        """DEPRECATED"""

    @deprecated("handle_detach_intent moved to individual pipeline services, this method does nothing", "1.0.0")
    def handle_detach_intent(self, message):
        """DEPRECATED"""

    @deprecated("handle_detach_skill moved to individual pipeline services, this method does nothing", "1.0.0")
    def handle_detach_skill(self, message):
        """DEPRECATED"""
