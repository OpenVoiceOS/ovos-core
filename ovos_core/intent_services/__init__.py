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
from typing import Tuple, Callable
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_bus_client.util import get_message_lang
from ovos_config.config import Configuration
from ovos_config.locale import setup_locale, get_valid_languages, get_full_lang_code

from ovos_core.intent_services.adapt_service import AdaptService
from ovos_core.intent_services.commonqa_service import CommonQAService
from ovos_core.intent_services.converse_service import ConverseService
from ovos_core.intent_services.fallback_service import FallbackService
from ovos_core.intent_services.ocp_service import OCPPipelineMatcher
from ovos_core.intent_services.padacioso_service import PadaciosoService
from ovos_core.intent_services.stop_service import StopService
from ovos_core.transformers import MetadataTransformersService, UtteranceTransformersService
from ovos_utils.log import LOG, deprecated, log_deprecation
from ovos_utils.metrics import Stopwatch
from ovos_workshop.intents import open_intent_envelope
from ovos_plugin_manager.templates.pipeline import IntentMatch


class IntentService:
    """OVOS intent service. parses utterances using a variety of systems.

    The intent service also provides the internal API for registering and
    querying the intent service.
    """

    def __init__(self, bus, config=None):
        self.bus = bus
        self.config = config or Configuration().get("intents", {})
        if "padatious" not in self.config:
            self.config["padatious"] = Configuration().get("padatious", {})

        # Dictionary for translating a skill id to a name
        self.skill_names = {}

        # TODO - replace with plugins
        self.adapt_service = AdaptService(config=self.config.get("adapt", {}))
        self.padatious_service = None
        try:
            if self.config["padatious"].get("disabled"):
                LOG.info("padatious forcefully disabled in config")
            else:
                from ovos_core.intent_services.padatious_service import PadatiousService
                self.padatious_service = PadatiousService(bus, self.config["padatious"])
        except ImportError:
            LOG.error(f'Failed to create padatious intent handlers, padatious not installed')

        self.padacioso_service = PadaciosoService(bus, self.config["padatious"])
        self.fallback = FallbackService(bus)
        self.converse = ConverseService(bus)
        self.common_qa = CommonQAService(bus, self.config.get("common_query"))
        self.stop = StopService(bus)
        self.ocp = OCPPipelineMatcher(self.bus, config=self.config.get("OCP", {}))
        self.utterance_plugins = UtteranceTransformersService(bus)
        self.metadata_plugins = MetadataTransformersService(bus)

        # connection SessionManager to the bus,
        # this will sync default session across all components
        SessionManager.connect_to_bus(self.bus)

        self.bus.on('register_vocab', self.handle_register_vocab)
        self.bus.on('register_intent', self.handle_register_intent)
        self.bus.on('recognizer_loop:utterance', self.handle_utterance)
        self.bus.on('detach_intent', self.handle_detach_intent)
        self.bus.on('detach_skill', self.handle_detach_skill)
        # Context related handlers
        self.bus.on('add_context', self.handle_add_context)
        self.bus.on('remove_context', self.handle_remove_context)
        self.bus.on('clear_context', self.handle_clear_context)

        # Converse method
        self.bus.on('mycroft.skills.loaded', self.update_skill_name_dict)

        # Intents API
        self.registered_vocab = []
        self.bus.on('intent.service.intent.get', self.handle_get_intent)
        self.bus.on('intent.service.skills.get', self.handle_get_skills)
        self.bus.on('intent.service.adapt.get', self.handle_get_adapt)
        self.bus.on('intent.service.adapt.manifest.get', self.handle_adapt_manifest)
        self.bus.on('intent.service.adapt.vocab.manifest.get', self.handle_vocab_manifest)
        self.bus.on('intent.service.padatious.get', self.handle_get_padatious)
        self.bus.on('intent.service.padatious.manifest.get', self.handle_padatious_manifest)
        self.bus.on('intent.service.padatious.entities.manifest.get', self.handle_entity_manifest)

    @property
    def registered_intents(self):
        lang = get_message_lang()
        return [parser.__dict__
                for parser in self.adapt_service.engines[lang].intent_parsers]

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

    # converse handling
    @property
    def active_skills(self):
        log_deprecation("self.active_skills is deprecated! use Session instead", "0.0.9")
        session = SessionManager.get()
        return session.active_skills

    @active_skills.setter
    def active_skills(self, val):
        log_deprecation("self.active_skills is deprecated! use Session instead", "0.0.9")
        session = SessionManager.get()
        session.active_skills = []
        for skill_id, ts in val:
            session.activate_skill(skill_id)

    @deprecated("handle_activate_skill_request moved to ConverseService, overriding this method has no effect, "
                "it has been disconnected from the bus event", "0.0.8")
    def handle_activate_skill_request(self, message):
        self.converse.handle_activate_skill_request(message)

    @deprecated("handle_deactivate_skill_request moved to ConverseService, overriding this method has no effect, "
                "it has been disconnected from the bus event", "0.0.8")
    def handle_deactivate_skill_request(self, message):
        self.converse.handle_deactivate_skill_request(message)

    @deprecated("reset_converse moved to ConverseService, overriding this method has no effect, "
                "it has been disconnected from the bus event", "0.0.8")
    def reset_converse(self, message):
        self.converse.reset_converse(message)

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
        lang_keys = ["stt_lang",
                     "request_lang",
                     "detected_lang"]
        for k in lang_keys:
            if k in message.context:
                v = get_full_lang_code(message.context[k])
                if v in valid_langs:
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
        if self.padatious_service is None:
            if any("padatious" in p for p in session.pipeline):
                LOG.warning("padatious is not available! using padacioso in it's place, "
                            "intent matching will be extremely slow in comparison")
            padatious_matcher = self.padacioso_service
        else:
            from ovos_core.intent_services.padatious_service import PadatiousMatcher
            padatious_matcher = PadatiousMatcher(self.padatious_service)

        matchers = {
            "converse": self.converse.converse_with_skills,
            "stop_high": self.stop.match_stop_high,
            "stop_medium": self.stop.match_stop_medium,
            "stop_low": self.stop.match_stop_low,
            "padatious_high": padatious_matcher.match_high,
            "padacioso_high": self.padacioso_service.match_high,
            "adapt_high": self.adapt_service.match_high,
            "common_qa": self.common_qa.match,
            "fallback_high": self.fallback.high_prio,
            "padatious_medium": padatious_matcher.match_medium,
            "padacioso_medium": self.padacioso_service.match_medium,
            "adapt_medium": self.adapt_service.match_medium,
            "fallback_medium": self.fallback.medium_prio,
            "padatious_low": padatious_matcher.match_low,
            "padacioso_low": self.padacioso_service.match_low,
            "adapt_low": self.adapt_service.match_low,
            "fallback_low": self.fallback.low_prio
        }
        if self.ocp is not None:
            matchers.update({
                "ocp_high": self.ocp.match_high,
                "ocp_medium": self.ocp.match_medium,
                "ocp_fallback": self.ocp.match_fallback,
                "ocp_legacy": self.ocp.match_legacy})
        skips = skips or []
        pipeline = [k for k in session.pipeline if k not in skips]
        if any(k not in matchers for k in pipeline):
            LOG.warning(f"Requested some invalid pipeline components! "
                        f"filtered {[k for k in pipeline if k not in matchers]}")
            pipeline = [k for k in pipeline if k in matchers]
        LOG.debug(f"Session pipeline: {pipeline}")
        return [(k, matchers[k]) for k in pipeline]

    def _validate_session(self, message, lang):
        # get session
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

    def _emit_match_message(self, match: IntentMatch, message: Message):
        """Update the message data with the matched utterance information and
        activate the corresponding skill if available.

        Args:
            match (IntentMatch): The matched utterance object.
            message (Message): The messagebus data.
        """
        message.data["utterance"] = match.utterance

        if match.skill_id:
            # ensure skill_id is present in message.context
            message.context["skill_id"] = match.skill_id

        if match.intent_type is True:
            # utterance fully handled
            reply = message.reply("ovos.utterance.handled",
                                  {"skill_id": match.skill_id})
            self.bus.emit(reply)
        # Launch skill if not handled by the match function
        elif match.intent_type:
            # keep all original message.data and update with intent match
            data = dict(message.data)
            data.update(match.intent_data)

            # NOTE: message.reply to ensure correct message destination
            reply = message.reply(match.intent_type, data)

            # let's activate the skill BEFORE the intent is triggered
            # to ensure an accurate Session
            # NOTE: this was previously done async by the skill,
            #   but then the skill was missing from Session.active_skills
            sess = self.converse.activate_skill(message=reply,
                                                skill_id=match.skill_id)
            if sess:
                reply.context["session"] = sess.serialize()

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

        try:
            setup_locale(lang)
        except Exception as e:
            LOG.exception(f"Failed to set lingua_franca default lang to {lang}")

        utterances = message.data.get('utterances', [])

        stopwatch = Stopwatch()

        # get session
        sess = self._validate_session(message, lang)
        message.context["session"] = sess.serialize()

        # match
        match = None
        with stopwatch:
            # Loop through the matching functions until a match is found.
            for pipeline, match_func in self.get_pipeline(session=sess):
                match = match_func(utterances, lang, message)
                if match:
                    LOG.info(f"{pipeline} match: {match}")
                    if match.skill_id and match.skill_id in sess.blacklisted_skills:
                        LOG.debug(f"ignoring match, skill_id '{match.skill_id}' blacklisted by Session '{sess.session_id}'")
                        continue
                    if match.intent_type and match.intent_type in sess.blacklisted_intents:
                        LOG.debug(f"ignoring match, intent '{match.intent_type}' blacklisted by Session '{sess.session_id}'")
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

    def handle_register_vocab(self, message):
        """Register adapt vocabulary.

        Args:
            message (Message): message containing vocab info
        """
        # TODO: 22.02 Remove backwards compatibility
        if _is_old_style_keyword_message(message):
            LOG.warning('Deprecated: Registering keywords with old message. '
                        'This will be removed in v22.02.')
            _update_keyword_message(message)

        entity_value = message.data.get('entity_value')
        entity_type = message.data.get('entity_type')
        regex_str = message.data.get('regex')
        alias_of = message.data.get('alias_of')
        lang = get_message_lang(message)
        self.adapt_service.register_vocabulary(entity_value, entity_type,
                                               alias_of, regex_str, lang)
        self.registered_vocab.append(message.data)

    def handle_register_intent(self, message):
        """Register adapt intent.

        Args:
            message (Message): message containing intent info
        """
        intent = open_intent_envelope(message)
        self.adapt_service.register_intent(intent)

    def handle_detach_intent(self, message):
        """Remover adapt intent.

        Args:
            message (Message): message containing intent info
        """
        intent_name = message.data.get('intent_name')
        self.adapt_service.detach_intent(intent_name)

    def handle_detach_skill(self, message):
        """Remove all intents registered for a specific skill.

        Args:
            message (Message): message containing intent info
        """
        skill_id = message.data.get('skill_id')
        self.adapt_service.detach_skill(skill_id)

    def handle_add_context(self, message):
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

    def handle_remove_context(self, message):
        """Remove specific context

        Args:
            message: data contains the 'context' item to remove
        """
        context = message.data.get('context')
        if context:
            sess = SessionManager.get(message)
            sess.context.remove_context(context)

    def handle_clear_context(self, message):
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
                if match.intent_type:
                    intent_data = match.intent_data
                    intent_data["intent_name"] = match.intent_type
                    intent_data["intent_service"] = match.intent_service
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

    @deprecated("handle_get_active_skills moved to ConverseService, overriding this method has no effect, "
                "it has been disconnected from the bus event", "0.0.8")
    def handle_get_active_skills(self, message):
        """Send active skills to caller.

        Argument:
            message: query message to reply to.
        """
        self.converse.handle_get_active_skills(message)

    def handle_get_adapt(self, message: Message):
        """handler getting the adapt response for an utterance.

        Args:
            message (Message): message containing utterance
        """
        utterance = message.data["utterance"]
        lang = get_message_lang(message)
        intent = self.adapt_service.match_intent((utterance,), lang, message.serialize())
        intent_data = intent.intent_data if intent else None
        self.bus.emit(message.reply("intent.service.adapt.reply",
                                    {"intent": intent_data}))

    def handle_adapt_manifest(self, message):
        """Send adapt intent manifest to caller.

        Argument:
            message: query message to reply to.
        """
        self.bus.emit(message.reply("intent.service.adapt.manifest",
                                    {"intents": self.registered_intents}))

    def handle_vocab_manifest(self, message):
        """Send adapt vocabulary manifest to caller.

        Argument:
            message: query message to reply to.
        """
        self.bus.emit(message.reply("intent.service.adapt.vocab.manifest",
                                    {"vocab": self.registered_vocab}))

    def handle_get_padatious(self, message):
        """messagebus handler for perfoming padatious parsing.

        Args:
            message (Message): message triggering the method
        """
        utterance = message.data["utterance"]
        norm = message.data.get('norm_utt', utterance)
        intent = self.padacioso_service.calc_intent(utterance)
        if not intent and norm != utterance:
            intent = self.padacioso_service.calc_intent(norm)
        if intent:
            intent = intent.__dict__
        self.bus.emit(message.reply("intent.service.padatious.reply",
                                    {"intent": intent}))

    def handle_padatious_manifest(self, message):
        """Messagebus handler returning the registered padatious intents.

        Args:
            message (Message): message triggering the method
        """
        self.bus.emit(message.reply(
            "intent.service.padatious.manifest",
            {"intents": self.padacioso_service.registered_intents}))

    def handle_entity_manifest(self, message):
        """Messagebus handler returning the registered padatious entities.

        Args:
            message (Message): message triggering the method
        """
        self.bus.emit(message.reply(
            "intent.service.padatious.entities.manifest",
            {"entities": self.padacioso_service.registered_entities}))

    def shutdown(self):
        self.utterance_plugins.shutdown()
        self.metadata_plugins.shutdown()
        self.adapt_service.shutdown()
        self.padacioso_service.shutdown()
        if self.padatious_service:
            self.padatious_service.shutdown()
        self.common_qa.shutdown()
        self.converse.shutdown()
        self.fallback.shutdown()
        if self.ocp:
            self.ocp.shutdown()

        self.bus.remove('register_vocab', self.handle_register_vocab)
        self.bus.remove('register_intent', self.handle_register_intent)
        self.bus.remove('recognizer_loop:utterance', self.handle_utterance)
        self.bus.remove('detach_intent', self.handle_detach_intent)
        self.bus.remove('detach_skill', self.handle_detach_skill)
        self.bus.remove('add_context', self.handle_add_context)
        self.bus.remove('remove_context', self.handle_remove_context)
        self.bus.remove('clear_context', self.handle_clear_context)
        self.bus.remove('mycroft.skills.loaded', self.update_skill_name_dict)
        self.bus.remove('intent.service.intent.get', self.handle_get_intent)
        self.bus.remove('intent.service.skills.get', self.handle_get_skills)
        self.bus.remove('intent.service.adapt.get', self.handle_get_adapt)
        self.bus.remove('intent.service.adapt.manifest.get', self.handle_adapt_manifest)
        self.bus.remove('intent.service.adapt.vocab.manifest.get', self.handle_vocab_manifest)
        self.bus.remove('intent.service.padatious.get', self.handle_get_padatious)
        self.bus.remove('intent.service.padatious.manifest.get', self.handle_padatious_manifest)
        self.bus.remove('intent.service.padatious.entities.manifest.get', self.handle_entity_manifest)


def _is_old_style_keyword_message(message):
    """Simple check that the message is not using the updated format.

    TODO: Remove in v22.02

    Args:
        message (Message): Message object to check

    Returns:
        (bool) True if this is an old messagem, else False
    """
    return ('entity_value' not in message.data and 'start' in message.data)


def _update_keyword_message(message):
    """Make old style keyword registration message compatible.

    Copies old keys in message data to new names.

    Args:
        message (Message): Message to update
    """
    message.data['entity_value'] = message.data['start']
    message.data['entity_type'] = message.data['end']
