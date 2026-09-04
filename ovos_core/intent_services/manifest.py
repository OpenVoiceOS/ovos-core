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

from typing import Optional

from ovos_bus_client.message import Message
from ovos_spec_tools import standardize_lang
from ovos_utils.log import LOG

from ovos_core.intent_services.working_session import raw_session_id


class IntentManifest:
    """INTENT-4 §10 orchestrator-owned manifest.

    Indexes every ``ovos.intent.register.*`` broadcast and serves
    ``ovos.intent.list`` / ``ovos.intent.describe`` pull-queries.
    The manifest is keyed by the quintuple
    ``(session_id, skill_id, intent_name, lang, method)`` per §11.1.
    """

    def __init__(self, bus):
        self.bus = bus
        # (session_id, skill_id, intent_name, lang, method) → entry dict
        self._index: dict = {}

        bus.on("ovos.intent.register.keyword", self._on_register)
        bus.on("ovos.intent.register.template", self._on_register)
        bus.on("ovos.intent.deregister", self._on_deregister)
        bus.on("ovos.intent.enable", self._on_enable_disable)
        bus.on("ovos.intent.disable", self._on_enable_disable)
        bus.on("ovos.skill.deregister", self._on_skill_deregister)
        bus.on("ovos.intent.list", self._on_list)
        bus.on("ovos.intent.describe", self._on_describe)

    def shutdown(self):
        self.bus.remove("ovos.intent.register.keyword", self._on_register)
        self.bus.remove("ovos.intent.register.template", self._on_register)
        self.bus.remove("ovos.intent.deregister", self._on_deregister)
        self.bus.remove("ovos.intent.enable", self._on_enable_disable)
        self.bus.remove("ovos.intent.disable", self._on_enable_disable)
        self.bus.remove("ovos.skill.deregister", self._on_skill_deregister)
        self.bus.remove("ovos.intent.list", self._on_list)
        self.bus.remove("ovos.intent.describe", self._on_describe)

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key(session_id: str, skill_id: str, intent_name: str,
              lang: str, method: str) -> tuple:
        return session_id, skill_id, intent_name, standardize_lang(lang), method

    def _effective_pool(self, session_id: str) -> list:
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
                           intent_name: str, lang: str) -> list:
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

    # ------------------------------------------------------------------
    # registration broadcasts  §§5–8
    # ------------------------------------------------------------------

    def _on_register(self, message: Message):
        method = "keyword" if message.msg_type == "ovos.intent.register.keyword" else "template"
        skill_id = message.data.get("skill_id") or message.context.get("skill_id")
        intent_name = message.data.get("intent_name")
        lang = message.data.get("lang")
        if not (skill_id and intent_name and lang):
            LOG.warning(f"malformed intent registration from {skill_id!r}: missing required fields")
            return
        if intent_name == "stop":
            # OVOS-STOP-1 reserves "<skill_id>:stop" for the pipeline's own
            # targeted-stop dispatch (stop_service.py _targeted_stop); a real
            # intent registered under the same name binds the identical topic
            # and is shadowed by / collides with the reserved dispatch.
            LOG.warning(
                f"skill '{skill_id}' registered an intent literally named 'stop' — "
                f"this collides with the OVOS-STOP-1 reserved '{skill_id}:stop' "
                "targeted-dispatch topic, so both the registered intent handler "
                "and the stop machinery will react to messages on that topic.")
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
        skill_id = message.data.get("skill_id") or message.context.get("skill_id")
        intent_name = message.data.get("intent_name")
        lang = message.data.get("lang")
        session_id = self._session_id_of(message)
        if not (skill_id and intent_name):
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
        skill_id = message.data.get("skill_id") or message.context.get("skill_id")
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
        skill_id = message.data.get("skill_id") or message.context.get("skill_id")
        session_id = self._session_id_of(message)
        if not skill_id:
            return
        for key in [k for k in self._index if k[0] == session_id and k[1] == skill_id]:
            del self._index[key]

    # ------------------------------------------------------------------
    # introspection queries  §10
    # ------------------------------------------------------------------

    def _on_list(self, message: Message):
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
        if not (skill_id and intent_name and lang):
            self.bus.emit(message.reply("ovos.intent.describe.response",
                                        {"ok": False,
                                         "error": "skill_id, intent_name and lang are required"}))
            return
        lang = standardize_lang(lang)
        definitions = []
        for entry in self._index.values():
            if entry["skill_id"] != skill_id or entry["intent_name"] != intent_name or entry["lang"] != lang:
                continue
            if method_filter and entry["method"] != method_filter:
                continue
            if session_filter is not None and entry["session_id"] != session_filter:
                continue
            definitions.append({"method": entry["method"],
                                 "session_id": entry["session_id"],
                                 "definition": entry["definition"]})
        # §10.2 RECOMMENDED ordering: "default" first, then by session_id,
        # then by method (keyword, template).
        definitions.sort(key=lambda d: (0 if d["session_id"] == "default" else 1,
                                         d["session_id"],
                                         0 if d["method"] == "keyword" else 1))
        if definitions:
            self.bus.emit(message.reply("ovos.intent.describe.response",
                                        {"ok": True, "definitions": definitions}))
        else:
            self.bus.emit(message.reply("ovos.intent.describe.response",
                                        {"ok": False,
                                         "error": f"unknown intent {skill_id}:{intent_name}:{lang}"}))

    # OVOS-CONTEXT-1: orchestrator lookups for declared context gates / slots

    def _matching_definitions(self, session_id: str, skill_id: str,
                              intent_name: str, lang: Optional[str]) -> list:
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
                                 intent_name: str, lang: Optional[str] = None):
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
