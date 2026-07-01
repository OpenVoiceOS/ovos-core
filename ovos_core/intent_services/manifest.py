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

from ovos_bus_client.message import Message
from ovos_spec_tools import standardize_lang
from ovos_utils.log import LOG


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
        session_id = (message.context.get("session") or {}).get("session_id", "default")
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
        session_id = message.data.get("session_id", "default")
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
        session_id = message.data.get("session_id", "default")
        for key, entry in self._index.items():
            if key[0] != session_id or key[1] != skill_id or key[2] != intent_name:
                continue
            if lang and key[3] != standardize_lang(lang):
                continue
            entry["enabled"] = enabled

    def _on_skill_deregister(self, message: Message):
        skill_id = message.data.get("skill_id") or message.context.get("skill_id")
        session_id = message.data.get("session_id", "default")
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
        session_id = message.data.get("session_id", "default")
        if not (skill_id and intent_name and lang):
            self.bus.emit(message.reply("ovos.intent.describe.response",
                                        {"ok": False,
                                         "error": "skill_id, intent_name and lang are required"}))
            return
        lang = standardize_lang(lang)
        pool = self._effective_pool(session_id)
        definitions = []
        for entry in pool:
            if entry["skill_id"] != skill_id or entry["intent_name"] != intent_name or entry["lang"] != lang:
                continue
            if method_filter and entry["method"] != method_filter:
                continue
            definitions.append({"method": entry["method"], "definition": entry["definition"]})
        definitions.sort(key=lambda d: 0 if d["method"] == "keyword" else 1)
        if definitions:
            self.bus.emit(message.reply("ovos.intent.describe.response",
                                        {"ok": True, "definitions": definitions}))
        else:
            self.bus.emit(message.reply("ovos.intent.describe.response",
                                        {"ok": False,
                                         "error": f"unknown intent {skill_id}:{intent_name}:{lang}"}))
