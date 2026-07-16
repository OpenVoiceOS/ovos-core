"""Orchestrator-owned registration registry (OVOS-INTENT-4 §10).

Registration broadcasts are load-time announcements: the bus is async with
no catch-up channel, so a consumer that subscribed after a skill loaded has
missed them (OVOS-INTENT-4 §10). The spec's answer is an orchestrator-owned
passive index of every registration it observes. This module extends that
index to the engine-level registration topics so the orchestrator can
rebuild the compiled state of its pipeline plugins whenever they (re)load —
freshly constructed matchers consult the registry instead of depending on
having observed past broadcasts.

The registry is strictly passive (it does not validate, reject, route, or
gate anything) and the rebuild re-delivers the recorded messages to
in-process listeners only — nothing is put (back) on the wire and no message
outside the existing registration contract is ever produced.
"""
import json
from threading import RLock
from typing import Callable, Dict, List, Optional, Tuple

from ovos_bus_client.message import Message
from ovos_utils.log import LOG

# ordered append-only announcements with no identity of their own; deduped
# by payload so a re-emitted keyword does not accumulate
VOCAB_TOPICS = ("register_vocab",)
# keyed announcements: re-registration with the same key replaces the prior
# record (OVOS-INTENT-4 §8.1)
ENTITY_TOPICS = ("padatious:register_entity", "ovos.entity.register")
INTENT_TOPICS = ("register_intent", "padatious:register_intent",
                 "ovos.intent.register.keyword",
                 "ovos.intent.register.template")
FALLBACK_REGISTER = "ovos.skills.fallback.register"
FALLBACK_DEREGISTER = "ovos.skills.fallback.deregister"
DETACH_INTENT = "detach_intent"
DETACH_SKILL = "detach_skill"
ENTITY_DEREGISTER = "ovos.entity.deregister"


def _skill_id(message: Message) -> str:
    return (message.data.get("skill_id") or
            message.context.get("skill_id") or "anonymous_skill")


def _record_name(message: Message) -> Optional[str]:
    return message.data.get("name") or message.data.get("intent_name") \
        or message.data.get("entity_name")


class RegistrationRegistry:
    """Passive index of engine registration broadcasts, per skill."""

    def __init__(self, bus):
        self.bus = bus
        self._lock = RLock()
        # skill_id -> payload-keyed vocab records (ordered, deduped)
        self._vocab: Dict[str, Dict[str, Message]] = {}
        # skill_id -> (topic, name, lang) -> record  (§8.1 replacement)
        self._entities: Dict[str, Dict[Tuple, Message]] = {}
        self._intents: Dict[str, Dict[Tuple, Message]] = {}
        # skill_id -> latest fallback registration
        self._fallbacks: Dict[str, Message] = {}

        for topic in VOCAB_TOPICS:
            bus.on(topic, self._on_vocab)
        for topic in ENTITY_TOPICS:
            bus.on(topic, self._on_entity)
        for topic in INTENT_TOPICS:
            bus.on(topic, self._on_intent)
        bus.on(FALLBACK_REGISTER, self._on_fallback_register)
        bus.on(FALLBACK_DEREGISTER, self._on_fallback_deregister)
        bus.on(DETACH_INTENT, self._on_detach_intent)
        bus.on(DETACH_SKILL, self._on_detach_skill)
        bus.on(ENTITY_DEREGISTER, self._on_entity_deregister)

    def shutdown(self):
        for topic in VOCAB_TOPICS:
            self.bus.remove(topic, self._on_vocab)
        for topic in ENTITY_TOPICS:
            self.bus.remove(topic, self._on_entity)
        for topic in INTENT_TOPICS:
            self.bus.remove(topic, self._on_intent)
        self.bus.remove(FALLBACK_REGISTER, self._on_fallback_register)
        self.bus.remove(FALLBACK_DEREGISTER, self._on_fallback_deregister)
        self.bus.remove(DETACH_INTENT, self._on_detach_intent)
        self.bus.remove(DETACH_SKILL, self._on_detach_skill)
        self.bus.remove(ENTITY_DEREGISTER, self._on_entity_deregister)

    # ------------------------------------------------------------------
    # recording
    # ------------------------------------------------------------------
    def _on_vocab(self, message: Message):
        key = json.dumps(message.data, sort_keys=True, default=str)
        with self._lock:
            self._vocab.setdefault(_skill_id(message), {})[key] = message

    def _on_entity(self, message: Message):
        key = (message.msg_type, _record_name(message),
               message.data.get("lang"))
        with self._lock:
            self._entities.setdefault(_skill_id(message), {})[key] = message

    def _on_intent(self, message: Message):
        key = (message.msg_type, _record_name(message),
               message.data.get("lang"))
        with self._lock:
            self._intents.setdefault(_skill_id(message), {})[key] = message

    def _on_fallback_register(self, message: Message):
        with self._lock:
            self._fallbacks[_skill_id(message)] = message

    def _on_fallback_deregister(self, message: Message):
        with self._lock:
            self._fallbacks.pop(_skill_id(message), None)

    def _on_detach_intent(self, message: Message):
        name = message.data.get("intent_name")
        if not name:
            return
        with self._lock:
            for records in self._intents.values():
                for key in [k for k in records if k[1] == name]:
                    del records[key]

    def _on_detach_skill(self, message: Message):
        skill_id = _skill_id(message)
        with self._lock:
            self._vocab.pop(skill_id, None)
            self._entities.pop(skill_id, None)
            self._intents.pop(skill_id, None)
            self._fallbacks.pop(skill_id, None)

    def _on_entity_deregister(self, message: Message):
        skill_id = _skill_id(message)
        name = message.data.get("entity_name")
        with self._lock:
            records = self._entities.get(skill_id) or {}
            for key in [k for k in records
                        if name is None or k[1] == name]:
                del records[key]

    # ------------------------------------------------------------------
    # rebuild
    # ------------------------------------------------------------------
    def replay(self, dispatch: Callable[[Message], None]):
        """Re-deliver every recorded registration through ``dispatch``.

        Each skill's records are preceded by a ``detach_skill`` so matchers
        that never lost their compiled state (legacy consumers append
        instead of replacing) come out without duplicates, and vocabulary is
        delivered before intents so no intent references a keyword the
        matcher has not (re)learned yet.
        """
        with self._lock:
            skills = list(dict.fromkeys(list(self._vocab) +
                                        list(self._entities) +
                                        list(self._intents)))
            batches: List[Message] = []
            for skill_id in skills:
                batches.append(Message(DETACH_SKILL, {"skill_id": skill_id},
                                       {"skill_id": skill_id}))
            for skill_id in skills:
                batches.extend(self._vocab.get(skill_id, {}).values())
                batches.extend(self._entities.get(skill_id, {}).values())
                batches.extend(self._intents.get(skill_id, {}).values())
            batches.extend(self._fallbacks.values())
        for message in batches:
            try:
                dispatch(message)
            except Exception:
                LOG.exception(f"failed to re-deliver {message.msg_type} "
                              "while rebuilding matcher state")
