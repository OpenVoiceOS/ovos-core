from ovos_bus_client.util import get_message_lang

from mycroft.skills.intent_services.base import IntentService
from ovos_plugin_manager.intents import IntentBox, IntentRange


class IntentBoxService:

    def __init__(self, bus, config=None):
        self.config = config or {}
        self.engine = IntentBox(self.config)
        self.bus = bus
        self.register_bus_handlers()
        self.register_compat_bus_handlers()

    def register_bus_handlers(self):
        self.bus.on('ovos.intentbox.register.entity', self.handle_register_entity)
        self.bus.on('ovos.intentbox.register.intent', self.handle_register_intent)
        self.bus.on('ovos.intentbox.register.keyword_intent', self.handle_register_keyword_intent)
        self.bus.on("ovos.intentbox.register.regex_intent", self.handle_register_regex_intent)
        self.bus.on('ovos.intentbox.detach.entity', self.handle_detach_entity)
        self.bus.on('ovos.intentbox.detach.intent', self.handle_detach_intent)
        self.bus.on('ovos.intentbox.detach.skill', self.handle_detach_skill)

    def register_compat_bus_handlers(self):
        """mycroft compatible namespaces"""
        self.bus.on('detach_intent', self.handle_detach_intent)  # api compatible
        self.bus.on('detach_skill', self.handle_detach_skill)  # api compatible
        # adapt api
        self.bus.on('register_vocab', self.handle_register_adapt_vocab)
        self.bus.on('register_intent', self.handle_register_keyword_intent)  # api compatible
        # padatious api
        self.bus.on('padatious:register_intent', self.handle_register_intent)  # api compatible
        self.bus.on('padatious:register_entity', self.handle_register_entity)  # api compatible

    def train(self):
        self.engine.train()

    def _intent_range(self, utterances, lang, intent_range: IntentRange):
        good_utterance = False
        for utterance in utterances:
            for intent in self.engine.calc(utterance, lang=lang):
                if intent.confidence < intent_range.start or \
                        intent.confidence > intent_range.stop:
                    continue
                yield intent
                good_utterance = True
            if good_utterance:
                break

    def high_prio(self, utterances, lang, message):
        """Pre-padatious fallbacks."""
        return self._intent_range(utterances, lang, IntentRange(0, 5))

    def medium_prio(self, utterances, lang, message):
        """General fallbacks."""
        return self._intent_range(utterances, lang, IntentRange(5, 90))

    def low_prio(self, utterances, lang, message):
        """Low prio fallbacks with general matching such as chat-bot."""
        return self._intent_range(utterances, lang, IntentRange(90, 101))

    # bus handlers
    @staticmethod
    def _parse_message(message):
        name = message.data.get("name") or message.data.get("intent_name")
        lang = get_message_lang(message)
        samples = message.data.get("samples") or []
        if not samples and message.data.get("file_name"):
            with open(message.data["file_name"]) as f:
                samples = [l for l in f.read().split("\n")
                           if l and not l.startswith("#")]
        samples = samples or [name]
        skill_id = message.data.get("skill_id") or message.context.get("skill_id")
        return name, samples, lang, skill_id

    def handle_register_intent(self, message):
        intent_name, samples, lang, skill_id = self._parse_message(message)
        self.engine.register_intent(skill_id, intent_name, samples, lang)

    def handle_register_entity(self, message):
        entity_name, samples, lang, skill_id = self._parse_message(message)
        if not samples and message.data.get("file_name"):
            with open(message.data["file_name"]) as f:
                samples = [l for l in f.read().split("\n")
                           if l and not l.startswith("#")]
        samples = samples or [entity_name]
        self.engine.register_entity(skill_id, entity_name, samples, lang)

    def handle_register_regex_intent(self, message):
        intent_name, samples, lang, skill_id = self._parse_message(message)
        self.engine.register_regex_intent(skill_id, intent_name, samples, lang)

    def handle_register_regex_entity(self, message):
        entity_name, samples, lang, skill_id = self._parse_message(message)
        self.engine.register_regex_entity(skill_id, entity_name, samples, lang)

    def handle_register_keyword_intent(self, message):
        intent_name, samples, lang, skill_id = self._parse_message(message)
        self.engine.register_keyword_intent(skill_id, intent_name,
                                            [_[0] for _ in message.data['requires']],
                                            [_[0] for _ in message.data.get('optional', [])],
                                            [_[0] for _ in message.data.get('at_least_one', [])],
                                            [_[0] for _ in message.data.get('excludes', [])])

    def handle_detach_intent(self, message):
        intent_name, samples, lang, skill_id = self._parse_message(message)
        self.engine.detach_intent(skill_id, intent_name)

    def handle_detach_entity(self, message):
        name, samples, lang, skill_id = self._parse_message(message)
        self.engine.detach_entity(skill_id, name)

    def handle_detach_skill(self, message):
        """Remove all intents registered for a specific skill.
        Args:
            message (Message): message containing intent info
        """
        skill_id = message.data.get('skill_id')
        self.engine.detach_skill(skill_id)

    # backwards compat bus handlers
    def handle_register_adapt_vocab(self, message):
        if 'entity_value' not in message.data and 'start' in message.data:
            message.data['entity_value'] = message.data['start']
            message.data['entity_type'] = message.data['end']
        entity_value = message.data.get('entity_value')
        entity_type = message.data.get('entity_type')
        regex_str = message.data.get('regex')
        alias_of = message.data.get('alias_of') or []

        if regex_str:
            if not entity_type:
                # mycroft does not send an entity_type when registering adapt regex
                # the entity name is in the regex itself, need to extract from string
                # is syntax always (?P<name>someregexhere)  ?
                entity_type = regex_str.split("(?P<")[-1].split(">")[0]
            message.data["name"] = entity_type
            message.data["samples"] = [regex_str]
            self.handle_register_regex_entity(message)
        else:
            for ent in [entity_type] + alias_of:
                message.data["name"] = ent
                message.data["samples"] = [entity_value]
                self.handle_register_entity(message)


class HighPrioIntentBoxService(IntentService):
    """Intent Service handling conversational skills."""

    def __init__(self, intentbox):
        super().__init__(bus=intentbox.bus)
        self.engine = intentbox

    def handle_utterance_message(self, message):
        utterances = message.data["utterances"]
        lang = get_message_lang(message)
        match = self.engine.high_prio(utterances, lang, message)
        return [match] if match else []


class MediumPrioIntentBoxService(IntentService):
    def __init__(self, intentbox):
        super().__init__(bus=intentbox.bus)
        self.engine = intentbox

    def handle_utterance_message(self, message):
        utterances = message.data["utterances"]
        lang = get_message_lang(message)
        match = self.engine.medium_prio(utterances, lang, message)
        return [match] if match else []


class LowPrioIntentBoxService(IntentService):
    def __init__(self, intentbox):
        super().__init__(bus=intentbox.bus)
        self.engine = intentbox

    def handle_utterance_message(self, message):
        utterances = message.data["utterances"]
        lang = get_message_lang(message)
        match = self.engine.low_prio(utterances, lang, message)
        return [match] if match else []
