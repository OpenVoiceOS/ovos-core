# Copyright 2024 OpenVoiceOS
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

from typing import FrozenSet, List, Optional, Tuple, Union

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_spec_tools import REGISTERED_TYPES, standardize_lang
from ovos_spec_tools import declared_slot_types as template_slot_types
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG

from ovos_core.intent_services.working_session import raw_session_id

# OVOS-PIPELINE-1 §7.3 reserved intent_name registry: skills and pipelines
# MUST NOT register under these names (OVOS-INTENT-4 §5.3/§6.3).
RESERVED_INTENT_NAMES = frozenset({
    "converse", "response", "stop", "fallback", "common_query",
})

# OVOS-INTENT-4 §8.6 capability vocabulary; names outside this set are ignored.
KNOWN_CAPABILITIES = frozenset({"fallback", "common_query", "converse"})


def _target_skill_id(message: Message) -> Optional[str]:
    """OVOS-INTENT-4 §3.2 — the skill a §§5-8 message acts on.

    The payload ``skill_id`` names the target; ``context.skill_id`` names the
    source and is provenance only. They differ legitimately when a
    provisioning tool or a conflict-resolving skill acts on another skill's
    behalf, so a difference is never grounds for rejection and an absent
    context ``skill_id`` never makes the message malformed.

    Substituting the source for an absent target contradicts §3.2 and is kept
    only for the migration window. ``ovos-spec-tools`` bridges the legacy
    ``mycroft.skill.{enable,disable}_intent`` onto the spec topics, and the
    legacy payload has no ``skill_id`` field to carry, so a bridged toggle
    arrives with the emitter named in its context and nothing else. Resolving
    payload-only makes every such toggle a silent no-op. The substitution is
    logged so that a spec-native producer omitting the target is visible rather
    than silently retargeted, and it goes away with the mirror.
    """
    payload_skill_id = message.data.get("skill_id")
    source_skill_id = message.context.get("skill_id")
    if payload_skill_id:
        if source_skill_id and payload_skill_id != source_skill_id:
            LOG.debug(f"{message.msg_type}: source {source_skill_id!r} acting on "
                      f"target {payload_skill_id!r}")
        return payload_skill_id
    if source_skill_id:
        LOG.warning(f"{message.msg_type}: no target skill_id in the payload; "
                    f"acting on the source {source_skill_id!r} instead. "
                    "OVOS-INTENT-4 §3.2 names the target in `data`; this "
                    "substitution serves the pre-spec bridge only.")
    return source_skill_id


class IntentManifest:
    """INTENT-4 §10 orchestrator-owned manifest.

    Indexes every ``ovos.intent.register.*`` broadcast and serves
    ``ovos.intent.list`` / ``ovos.intent.describe`` pull-queries.
    The manifest is keyed by the quintuple
    ``(session_id, skill_id, intent_name, lang, method)`` per §11.1.

    ``ovos.intent.list`` answers what is loaded and stays small. The stored
    registration payloads live behind ``ovos.intent.describe``, which takes
    ``skill_id`` and treats ``intent_name`` and ``lang`` as optional filters,
    so one query covers a whole skill. A client that wants every intent's
    sentences asks once per skill instead of once per intent per language,
    and the reply is still bounded by the skill it named.
    """

    def __init__(self, bus: Union[MessageBusClient, FakeBus]):
        self.bus = bus
        # (session_id, skill_id, intent_name, lang, method) → entry dict
        self._index: dict = {}
        # (session_id, skill_id) → capabilities list, §8.6 announcement index
        self._announcements: dict = {}

        bus.on("ovos.intent.register.keyword", self._on_register)
        bus.on("ovos.intent.register.template", self._on_register)
        bus.on("ovos.intent.deregister", self._on_deregister)
        bus.on("ovos.intent.enable", self._on_enable_disable)
        bus.on("ovos.intent.disable", self._on_enable_disable)
        bus.on("ovos.skill.deregister", self._on_skill_deregister)
        bus.on("ovos.intent.list", self._on_list)
        bus.on("ovos.intent.describe", self._on_describe)
        bus.on("ovos.skill.loaded", self._on_skill_loaded)
        bus.on("ovos.skills.list", self._on_skills_list)

    def shutdown(self):
        self.bus.remove("ovos.intent.register.keyword", self._on_register)
        self.bus.remove("ovos.intent.register.template", self._on_register)
        self.bus.remove("ovos.intent.deregister", self._on_deregister)
        self.bus.remove("ovos.intent.enable", self._on_enable_disable)
        self.bus.remove("ovos.intent.disable", self._on_enable_disable)
        self.bus.remove("ovos.skill.deregister", self._on_skill_deregister)
        self.bus.remove("ovos.intent.list", self._on_list)
        self.bus.remove("ovos.intent.describe", self._on_describe)
        self.bus.remove("ovos.skill.loaded", self._on_skill_loaded)
        self.bus.remove("ovos.skills.list", self._on_skills_list)

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key(session_id: str, skill_id: str, intent_name: str,
              lang: str, method: str) -> Tuple[str, str, str, str, str]:
        return session_id, skill_id, intent_name, standardize_lang(lang), method

    def _effective_pool(self, session_id: str) -> List[dict]:
        """Return entries for *session_id* merged with 'default' (§11.2)."""
        seen = {}
        for key, entry in self._index.items():
            s, skill, name, lang, method = key
            if s not in ("default", session_id):
                continue
            dedup = (skill, name, lang, method)
            if dedup not in seen or s == session_id:
                seen[dedup] = entry
        return list(seen.values())

    @staticmethod
    def _invalid_filter(data: dict, *fields: str) -> Optional[str]:
        """§10.1/§10.2 — every provided filter must be a string.
        Returns the name of the first offending field, or ``None`` if all
        of *fields* are either absent or strings."""
        for field in fields:
            value = data.get(field)
            if value is not None and not isinstance(value, str):
                return field
        return None

    @staticmethod
    def _session_id_of(message: Message) -> Optional[str]:
        """Mutation scope per §11.1/§11.3 — always ``context.session.session_id``,
        NEVER ``Message.data``. A ``data.session_id`` on a mutation is not a
        scope assertion the producer is entitled to make; a producer could
        otherwise deregister/disable another session's intents by forging the
        payload. Any ``data.session_id`` that disagrees with the context is
        logged and ignored.

        ``None`` for a malformed carrier (OVOS-SESSION-1 §2.5) — already
        logged by ``raw_session_id``; matches no real key so the mutation is
        a no-op instead of a crash or a misrouted default-session mutation.
        """
        ctx_session_id = raw_session_id(message)
        data_session_id = message.data.get("session_id")
        if (ctx_session_id is not None and data_session_id is not None
                and data_session_id != ctx_session_id):
            LOG.warning(
                f"{message.msg_type}: ignoring forged data.session_id={data_session_id!r}; "
                f"session scope is context.session.session_id={ctx_session_id!r} (§11.1)")
        return ctx_session_id

    def get_required_slots(self, session_id: str, skill_id: str,
                           intent_name: str, lang: str) -> List[str]:
        """OVOS-INTENT-4 §6.1 / §10 — the ``required_slots`` an intent declares.

        The canonical source for the OVOS-PIPELINE-1 §6.2 orchestrator backstop:
        the required-slot names an intent registered under its
        ``ovos.intent.register.*`` payload. Merges the union across the intent's
        keyword/template registrations in the session's effective pool (§11.2).
        Returns ``[]`` when the intent is not in the manifest (e.g. registered via
        a legacy in-process path), leaving engine-side enforcement authoritative.
        """
        lang = standardize_lang(lang)
        slots: list = []
        for entry in self._effective_pool(session_id):
            if (entry["skill_id"] != skill_id or entry["intent_name"] != intent_name
                    or entry["lang"] != lang):
                continue
            for slot in (entry.get("definition") or {}).get("required_slots") or []:
                if slot not in slots:
                    slots.append(slot)
        return slots

    def declared_slot_types(self, session_id: str) -> FrozenSet[str]:
        """OVOS-TRANSFORM-1 §3.7 — the types registered intents declare.

        The typed-slots stage is handed this set, never the registry, so a
        transformer computes only the types something will read. Both places
        a declaration can appear in an OVOS-INTENT-4 §6.1 registration count:
        the optional ``slot_types`` map, and the ``{type:name}`` placeholders
        of the ``samples`` it is derived from, since a producer may send
        either one alone. Unregistered
        type names are not declarations — they degrade to untyped slots
        (OVOS-INTENT-1 §3.6) — and are left out.
        """
        types = set()
        for entry in self._effective_pool(session_id):
            definition = entry.get("definition") or {}
            for slot_type in (definition.get("slot_types") or {}).values():
                if slot_type in REGISTERED_TYPES:
                    types.add(slot_type)
            types.update(template_slot_types(definition.get("samples") or []).values())
        return frozenset(types)

    # ------------------------------------------------------------------
    # registration broadcasts  §§5–8
    # ------------------------------------------------------------------

    def _on_register(self, message: Message):
        method = "keyword" if message.msg_type == "ovos.intent.register.keyword" else "template"
        skill_id = _target_skill_id(message)
        intent_name = message.data.get("intent_name")
        lang = message.data.get("lang")
        if not (skill_id and intent_name and lang):
            LOG.warning(f"malformed intent registration from {skill_id!r}: missing required fields")
            return
        if intent_name in RESERVED_INTENT_NAMES:
            # OVOS-PIPELINE-1 §7.3 / OVOS-INTENT-4 §5.3/§6.3: a registration
            # naming a reserved intent_name is malformed — log at WARN, do
            # not index.
            LOG.warning(
                f"{message.msg_type}: skill '{skill_id}' registered reserved "
                f"intent_name '{intent_name}' — malformed per OVOS-PIPELINE-1 "
                "§7.3, not indexed.")
            return
        session_id = raw_session_id(message)
        if session_id is None:
            # malformed carrier (OVOS-SESSION-1 §2.5): already logged; drop
            # the registration rather than indexing it under a fabricated
            # session identity.
            return
        key = self._key(session_id, skill_id, intent_name, lang, method)
        self._index[key] = {
            "skill_id": skill_id,
            "intent_name": intent_name,
            "lang": standardize_lang(lang),
            "method": method,
            "enabled": True,
            "session_id": session_id,
            "definition": message.data,
        }

    def _on_deregister(self, message: Message):
        skill_id = _target_skill_id(message)
        intent_name = message.data.get("intent_name")
        lang = message.data.get("lang")
        session_id = self._session_id_of(message)
        if not intent_name:
            return
        if intent_name in RESERVED_INTENT_NAMES:
            # A reserved name was never indexed (§7.3), so deregistering it
            # is a no-op — logged rather than silently ignored.
            LOG.warning(
                f"{message.msg_type}: skill '{skill_id}' deregistered reserved "
                f"intent_name '{intent_name}' — ignored per OVOS-PIPELINE-1 §7.3.")
            return
        for method in ("keyword", "template"):
            if lang:
                self._index.pop(self._key(session_id, skill_id, intent_name, lang, method), None)
            else:
                for key in [k for k in self._index
                            if k[0] == session_id and k[1] == skill_id
                            and k[2] == intent_name and k[4] == method]:
                    del self._index[key]

    def _on_enable_disable(self, message: Message):
        enabled = message.msg_type == "ovos.intent.enable"
        skill_id = _target_skill_id(message)
        intent_name = message.data.get("intent_name")
        lang = message.data.get("lang")
        session_id = self._session_id_of(message)
        for key, entry in self._index.items():
            if key[0] != session_id or key[1] != skill_id or key[2] != intent_name:
                continue
            if lang and key[3] != standardize_lang(lang):
                continue
            entry["enabled"] = enabled

    def _on_skill_deregister(self, message: Message):
        skill_id = _target_skill_id(message)
        session_id = self._session_id_of(message)
        for key in [k for k in self._index if k[0] == session_id and k[1] == skill_id]:
            del self._index[key]
        self._announcements.pop((session_id, skill_id), None)

    def _on_skill_loaded(self, message: Message):
        """OVOS-INTENT-4 §8.6 — ``ovos.skill.loaded`` announcement.

        Re-announcement replaces the ``(session_id, skill_id)`` entry.
        Unknown capability names are ignored rather than rejected.
        """
        skill_id = message.data.get("skill_id")
        session_id = self._session_id_of(message)
        if not (skill_id and session_id):
            return
        capabilities = [c for c in (message.data.get("capabilities") or [])
                        if c in KNOWN_CAPABILITIES]
        self._announcements[(session_id, skill_id)] = capabilities

    def _on_skills_list(self, message: Message):
        """OVOS-INTENT-4 §10.3 — ``ovos.skills.list`` / ``.response``.

        ``session_id`` is an optional filter: present, the effective scope
        is "default" plus the named session (§11.2); absent, every
        announced skill in every session is returned.
        """
        f_session = message.data.get("session_id")
        skills = []
        for (session_id, skill_id), capabilities in self._announcements.items():
            if f_session and session_id not in ("default", f_session):
                continue
            intents = sum(1 for key in self._index
                          if key[0] == session_id and key[1] == skill_id)
            skills.append({
                "skill_id": skill_id,
                "session_id": session_id,
                "capabilities": capabilities,
                "intents": intents,
            })
        skills.sort(key=lambda s: (0 if s["session_id"] == "default" else 1,
                                    s["session_id"], s["skill_id"]))
        self.bus.emit(message.response({"ok": True, "skills": skills}))

    # ------------------------------------------------------------------
    # introspection queries  §10
    # ------------------------------------------------------------------

    def _on_list(self, message: Message):
        bad_field = self._invalid_filter(message.data, "skill_id", "lang", "session_id")
        if bad_field:
            self.bus.emit(message.reply("ovos.intent.list.response",
                                        {"ok": False, "error": f"{bad_field} must be a string"}))
            return
        f_skill = message.data.get("skill_id")
        f_lang = message.data.get("lang")
        f_session = message.data.get("session_id")
        if f_lang:
            f_lang = standardize_lang(f_lang)

        pool = self._effective_pool(f_session) if f_session else list(self._index.values())
        results = []
        for entry in pool:
            if f_skill and entry["skill_id"] != f_skill:
                continue
            if f_lang and entry["lang"] != f_lang:
                continue
            results.append({k: entry[k] for k in
                            ("skill_id", "intent_name", "lang", "method", "enabled", "session_id")})

        self.bus.emit(message.reply("ovos.intent.list.response", {"ok": True, "intents": results}))

    def _on_describe(self, message: Message):
        bad_field = self._invalid_filter(message.data, "skill_id", "intent_name",
                                         "lang", "method", "session_id")
        if bad_field:
            self.bus.emit(message.reply("ovos.intent.describe.response",
                                        {"ok": False, "error": f"{bad_field} must be a string"}))
            return
        skill_id = message.data.get("skill_id")
        intent_name = message.data.get("intent_name")
        lang = message.data.get("lang")
        method_filter = message.data.get("method")
        # NOTE: unlike mutations (§11.1/§11.3), session_id here is a QUERY
        # FILTER, not a scope assertion — reading it from data is legitimate
        # per §10.2. It is an *optional* filter: omitted (None) means every
        # session_id is returned, not just "default" — this is a straight
        # exact-match filter over the raw index, NOT the §11.2 effective
        # pool used by ovos.intent.list (§10.1).
        session_filter = message.data.get("session_id")
        # ``skill_id`` stays REQUIRED: it is what bounds the reply. ``intent_name``
        # and ``lang`` join ``method`` and ``session_id`` as OPTIONAL filters, so
        # one describe can cover a whole skill instead of one intent in one
        # language. A client showing a user what the device understands walks the
        # skills from ``ovos.intent.list`` and asks once per skill, rather than
        # once per intent per language; no reply ever exceeds a single skill.
        if not skill_id:
            self.bus.emit(message.reply("ovos.intent.describe.response",
                                        {"ok": False, "error": "skill_id is required"}))
            return
        if lang:
            lang = standardize_lang(lang)
        definitions = []
        for entry in self._index.values():
            if entry["skill_id"] != skill_id:
                continue
            if intent_name and entry["intent_name"] != intent_name:
                continue
            if lang and entry["lang"] != lang:
                continue
            if method_filter and entry["method"] != method_filter:
                continue
            if session_filter is not None and entry["session_id"] != session_filter:
                continue
            row = {k: entry[k] for k in
                   ("skill_id", "intent_name", "lang", "method", "session_id")}
            row["definition"] = entry["definition"]
            definitions.append(row)
        # §10.2 RECOMMENDED ordering: "default" first, then by session_id, then by
        # method (keyword, template). Intent and language sort between the two, so
        # a single-intent single-language query keeps exactly the old order.
        definitions.sort(key=lambda d: (0 if d["session_id"] == "default" else 1,
                                         d["session_id"],
                                         d["intent_name"],
                                         d["lang"],
                                         0 if d["method"] == "keyword" else 1))
        if definitions:
            self.bus.emit(message.reply("ovos.intent.describe.response",
                                        {"ok": True, "definitions": definitions}))
        else:
            target = f"{skill_id}:{intent_name or '*'}:{lang or '*'}"
            self.bus.emit(message.reply("ovos.intent.describe.response",
                                        {"ok": False, "error": f"unknown intent {target}"}))

    # OVOS-CONTEXT-1: orchestrator lookups for declared context gates / slots

    def _matching_definitions(self, session_id: str, skill_id: str,
                              intent_name: str, lang: Optional[str]) -> List[dict]:
        lang = standardize_lang(lang) if lang else None
        out = []
        for entry in self._effective_pool(session_id):
            if entry["skill_id"] != skill_id or entry["intent_name"] != intent_name:
                continue
            if lang and entry["lang"] != lang:
                continue
            out.append(entry.get("definition") or {})
        return out

    def get_context_requirements(self, session_id: str, skill_id: str,
                                 intent_name: str, lang: Optional[str] = None
                                 ) -> Tuple[List[str], List[str]]:
        """OVOS-CONTEXT-1 §6/§6.1 — declared ``requires_context`` /
        ``excludes_context``, unioned across registration definitions.

        @return: ``(requires, excludes)`` tuple of declaration lists; empty
            when the intent declares no gates or is unknown.
        """
        requires, excludes = [], []
        for d in self._matching_definitions(session_id, skill_id, intent_name, lang):
            for r in (d.get("requires_context") or []):
                if r not in requires:
                    requires.append(r)
            for e in (d.get("excludes_context") or []):
                if e not in excludes:
                    excludes.append(e)
        return requires, excludes

    def get_slot_names(self, session_id: str, skill_id: str,
                       intent_name: str, lang: Optional[str] = None) -> list:
        """The intent's declared slot / keyword names (``required``/
        ``optional``/``one_of``/``slots``), unioned across registration
        definitions. Used by the §7 context-supplied slot rule."""
        names = []
        for d in self._matching_definitions(session_id, skill_id, intent_name, lang):
            for field in ("required", "optional", "one_of", "slots"):
                for name in (d.get(field) or []):
                    if name not in names:
                        names.append(name)
        return names
