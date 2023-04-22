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
"""Mycroft's intent service, providing intent parsing since forever!"""
import threading

from mycroft.skills.intent_services.fallback_service import HighPrioFallbackService, \
    MediumPrioFallbackService, LowPrioFallbackService
from ovos_config.locale import setup_locale
from ovos_bus_client.message import Message, dig_for_message
from ovos_bus_client.util import get_message_lang
from mycroft.skills.intent_services import (
    AdaptService, FallbackService,
    PadatiousService, PadatiousMatcher,
    ConverseService, CommonQAService,
    IntentBoxService, HighPrioIntentBoxService,\
    MediumPrioIntentBoxService, LowPrioIntentBoxService
)
from ovos_plugin_manager.templates.intents import IntentMatch
from ovos_workshop.permissions import ConverseMode, ConverseActivationMode
from ovos_utils.log import LOG
from ovos_utils.sound import play_error_sound
from mycroft.util.parse import normalize
from ovos_utils.messagebus import get_message_lang


def _normalize_all_utterances(utterances):
    """Create normalized versions and pair them with the original utterance.

    This will create a list of tuples with the original utterance as the
    first item and if normalizing changes the utterance the normalized version
    will be set as the second item in the tuple, if normalization doesn't
    change anything the tuple will only have the "raw" original utterance.

    Args:
        utterances (list): list of utterances to normalize

    Returns:
        list of tuples, [(original utterance, normalized) ... ]
    """
    # normalize() changes "it's a boy" to "it is a boy", etc.
    norm_utterances = [normalize(u.lower(), remove_articles=False)
                       for u in utterances]

    # Create pairs of original and normalized counterparts for each entry
    # in the input list.
    combined = []
    for utt, norm in zip(utterances, norm_utterances):
        if utt == norm:
            combined.append((utt,))
        else:
            combined.append((utt, norm))

    LOG.debug(f"Utterances: {combined}")
    return combined


class IntentService:
    """Mycroft intent service. parses utterances using a variety of systems.

    The intent service also provides the internal API for registering and
    querying the intent service.
    """

    def __init__(self, bus):
        self.bus = bus

        # Dictionary for translating a skill id to a name
        self.skill_names = {}
        self.registered_vocab = []

        self.converse = ConverseService(self.bus)
        self.fallback = FallbackService(self.bus)
        self.intentBox = IntentBoxService(self.bus)
        self.common_qa = CommonQAService(self.bus)
        self.services = []
        self.load_intent_services()

        self.bus.on('recognizer_loop:utterance', self.handle_utterance)
        self.bus.on('mycroft.skills.loaded', self.update_skill_name_dict)
        self.bus.on('mycroft.skills.initialized', self.handle_train)

    def shutdown(self):
        self.bus.remove('recognizer_loop:utterance', self.handle_utterance)
        self.bus.remove('mycroft.skills.loaded', self.update_skill_name_dict)
        self.bus.remove('mycroft.skills.initialized', self.handle_train)

    def load_intent_services(self):
        self.services = [
            self.converse,
            HighPrioIntentBoxService(self.intentBox),
            HighPrioFallbackService(self.bus, self.fallback),
            MediumPrioIntentBoxService(self.intentBox),
            self.common_qa,
            LowPrioIntentBoxService(self.intentBox),
            MediumPrioFallbackService(self.bus, self.fallback),
            LowPrioFallbackService(self.bus, self.fallback)
        ]

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

    # intent matching
    def handle_train(self, message):
        self.intentBox.train()
        self.bus.emit(message.reply('mycroft.skills.trained'))

    def _match_intents(self, utterances, lang, message, converse=False, fallback=False, commonqa=False):
        message.data["utterances"] = utterances
        message.data["lang"] = lang

        # Match the utterance with intent.
        # These are listed in priority order.
        # Loop through the matching functions until a match is found.
        for engine in self.services:
            if not converse and isinstance(engine, ConverseService):
                continue
            if not fallback and (isinstance(engine, HighPrioFallbackService) or
                                 isinstance(engine, MediumPrioFallbackService) or
                                 isinstance(engine, LowPrioFallbackService)):
                continue
            if not commonqa and isinstance(engine, CommonQAService):
                pass
            LOG.info(f"Matching {utterances} with {engine}")
            try:
                for match in engine.handle_utterance_message(message):
                    yield match
            except GeneratorExit:
                return
            except:
                LOG.exception(f"{engine} error!")

    def handle_utterance(self, message):
        """Main entrypoint for handling user utterances with Mycroft skills

        Monitor the messagebus for 'recognizer_loop:utterance', typically
        generated by a spoken interaction but potentially also from a CLI
        or other method of injecting a 'user utterance' into the system.

        Utterances then work through this sequence to be handled:
        1) Active skills attempt to handle using converse()
        2) high match intents (conf > 0.95)
        3) High Priority Fallbacks
        4) near match intents (conf > 0.8)
        5) General Fallbacks
        6) loose match intents (conf > 0.5)
        7) Catch all fallbacks including Unknown intent handler

        If all these fail the complete_intent_failure message will be sent
        and a generic info of the failure will be spoken.

        Args:
            message (Message): The messagebus data
        """
        utterances = message.data.get('utterances', [])
        lang = get_message_lang(message)
        setup_locale(lang)  # set default lang
        combined = _normalize_all_utterances(utterances)

        found_intent = False
        intent_finished = threading.Event()
        skill_id = ""

        def handle_intent_end(message):
            if not skill_id or message.context.get("skill_id", "") == skill_id:
                intent_finished.set()

        self.bus.on('mycroft.skill.handler.complete', handle_intent_end)
        try:
            # iterate over intent engines (ordered by priority)
            # matches is a list or generator with all intents found by a intent engine
            for matches in self._match_intents(combined, lang, message,
                                               converse=True, fallback=True, commonqa=True):
                # iterate over found intents, the utterance may contain more than 1 command
                for match in matches:
                    # If the service didn't report back the skill_id it
                    # takes on the responsibility of making the skill "active"
                    if match.skill_id:
                        self.converse.activate_skill(match.skill_id)
                        skill_id = match.skill_id
                    else:
                        # no skill_id -> no waiting for event
                        # this usually is a fallback skill or
                        # other handler that consumes the utterance
                        intent_finished.set()

                    # Launch skill if not handled by the match function
                    if match.intent_type:
                        # keep all original message.data and update with intent match
                        # NOTE: mycroft-core only keeps "utterances"
                        data = dict(message.data)
                        data.update(match.intent_data)
                        reply = message.reply(match.intent_type, data)
                        # execute intent
                        self.bus.emit(reply)
                        # wait until it finishes before executing next sub-intent
                        intent_finished.wait()

                    found_intent = True

                # dont check the next intent engine
                if found_intent:
                    break
        except Exception as err:
            LOG.exception(err)
        finally:
            self.bus.remove('mycroft.skill.handler.complete', handle_intent_end)

        if not found_intent:
            # Nothing was able to handle the intent
            # Ask politely for forgiveness for failing in this vital task
            self.send_complete_intent_failure(message)

    def send_complete_intent_failure(self, message):
        """Send a message that no skill could handle the utterance.

        Args:
            message (Message): original message to forward from
        """
        play_error_sound()
        self.bus.emit(message.forward('complete_intent_failure'))

    # intent api
    def handle_get_intent(self, message):
        """Get intent from either adapt or padatious.
        Args:
            message (Message): message containing utterance
        """
        utterance = message.data["utterance"]
        lang = get_message_lang(message)
        combined = _normalize_all_utterances([utterance])

        for match in self._match_intents(combined, lang, message):
            intent_data = match.intent_data
            intent_data["intent_name"] = match.intent_type
            intent_data["intent_service"] = match.intent_service
            intent_data["skill_id"] = match.skill_id
            # intent_data["handler"] = match_func.__name__
            self.bus.emit(message.reply("intent.service.intent.reply",
                                        {"intent": intent_data}))
            break
        else:
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

    # TODO Deprecate all below
    @property
    def active_skills(self):
        return self.converse.active_skills  # [skill_id , timestamp]

    @property
    def registered_intents(self):
        return []

    def handle_get_adapt(self, message):
        """DEPRECATED - moved to adapt plugin"""

    def handle_adapt_manifest(self, message):
        """DEPRECATED - moved to adapt plugin"""

    def handle_vocab_manifest(self, message):
        """DEPRECATED - moved to adapt plugin"""

    def handle_get_padatious(self, message):
        """DEPRECATED - moved to padatious plugin"""

    def handle_padatious_manifest(self, message):
        """DEPRECATED - moved to padatious plugin"""

    def handle_entity_manifest(self, message):
        """DEPRECATED - moved to padatious plugin"""

    def send_metrics(self, intent, context, stopwatch):
        """DEPRECATED: does nothing"""
        LOG.warning("send_metrics has been deprecated!\n"
                    "nothing happened (privacy wins!)")

    def handle_register_vocab(self, message):
        """DEPRECATED: does nothing - handler moved to IntentEngine in opm"""

    def handle_register_intent(self, message):
        """DEPRECATED: does nothing - handler moved to IntentEngine in opm"""

    def handle_detach_intent(self, message):
        """DEPRECATED: does nothing - handler moved to IntentEngine in opm"""

    def handle_detach_skill(self, message):
        """DEPRECATED: does nothing - handler moved to IntentEngine in opm"""

    def handle_add_context(self, message):
        """DEPRECATED: does nothing - handler moved to IntentEngine in opm"""

    def handle_remove_context(self, message):
        """DEPRECATED: does nothing - handler moved to IntentEngine in opm"""

    def handle_clear_context(self, message):
        """DEPRECATED: does nothing - handler moved to IntentEngine in opm"""

    def remove_active_skill(self, skill_id):
        """DEPRECATED: do not use, method only for api backwards compatibility

        Logs a warning and calls ConverseService.deactivate_skill

        Args:
            skill_id (str): skill to remove
        """
        # NOTE: can not delete method for backwards compat with upstream
        LOG.warning("self.remove_active_skill has been deprecated!\n"
                    "use self.converse.deactivate_skill instead")
        self.converse.deactivate_skill(skill_id)

    def add_active_skill(self, skill_id):
        """DEPRECATED: do not use, method only for api backwards compatibility

        Logs a warning and calls ConverseService.activate_skill

        Args:
            skill_id (str): identifier of skill to be added.
        """
        # NOTE: can not delete method for backwards compat with upstream
        LOG.warning("self.add_active_skill has been deprecated!\n"
                    "use self.converse.activate_skill instead")
        self.converse.activate_skill(skill_id)

    def handle_get_active_skills(self, message):
        """DEPRECATED: does nothing - handler moved to converse_service"""
        self.bus.emit(message.forward("ovos.intentbox.converse.get_active"))

    def handle_converse_error(self, message):
        """DEPRECATED: does nothing - handler moved to converse_service"""
        LOG.warning("handle_converse_error has been deprecated!\n"
                    "nothing happened")

    def reset_converse(self, message):
        """DEPRECATED: does nothing - handler moved to converse_service"""
        self.bus.emit(message.forward("ovos.intentbox.converse.reset"))

    def do_converse(self, utterances, skill_id, lang, message):
        """DEPRECATED: do not use, method only for api backwards compatibility

        Logs a warning and calls ConverseService.converse

        Args:
            utterances (list of tuples): utterances paired with normalized
                                         versions.
            skill_id: skill to query.
            lang (str): current language
            message (Message): message containing interaction info.
        """
        # NOTE: can not delete method for backwards compat with upstream
        LOG.warning("self.do_converse has been deprecated!\n"
                    "use self.converse.converse instead")
        return self.converse.converse(utterances, skill_id, lang, message)
