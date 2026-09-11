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

import unittest
from unittest.mock import patch

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.manifest import IntentManifest, RESERVED_INTENT_NAMES


def _manifest() -> IntentManifest:
    return IntentManifest(FakeBus())


def _reg(skill_id, intent_name, lang="en-US", method="keyword", session_id="default",
         **definition):
    """A registration broadcast; extra kwargs are the rest of the payload
    (``samples`` for a template intent, ``required`` for a keyword one)."""
    topic = f"ovos.intent.register.{method}"
    return Message(topic,
                   data={"skill_id": skill_id, "intent_name": intent_name, "lang": lang,
                         **definition},
                   context={"session": {"session_id": session_id}, "skill_id": skill_id})


class TestManifestRegister(unittest.TestCase):
    def setUp(self):
        self.m = _manifest()

    def test_register_keyword_adds_entry(self):
        self.m._on_register(_reg("skill.test", "hello", method="keyword"))
        self.assertEqual(len(self.m._index), 1)
        entry = list(self.m._index.values())[0]
        self.assertEqual(entry["intent_name"], "hello")
        self.assertEqual(entry["method"], "keyword")
        self.assertTrue(entry["enabled"])

    def test_register_template_adds_entry(self):
        self.m._on_register(_reg("skill.test", "hello", method="template"))
        entry = list(self.m._index.values())[0]
        self.assertEqual(entry["method"], "template")

    def test_re_registration_replaces_entry(self):
        self.m._on_register(_reg("skill.test", "hello"))
        self.m._on_register(_reg("skill.test", "hello"))
        self.assertEqual(len(self.m._index), 1)

    def test_malformed_registration_ignored(self):
        msg = Message("ovos.intent.register.keyword",
                      data={"skill_id": "s", "intent_name": "x"},  # missing lang
                      context={})
        self.m._on_register(msg)
        self.assertEqual(len(self.m._index), 0)

    def test_session_scoped_registration(self):
        self.m._on_register(_reg("skill.test", "hello", session_id="sat-1"))
        key = list(self.m._index.keys())[0]
        self.assertEqual(key[0], "sat-1")

    def test_reserved_intent_names_warn_and_are_not_indexed(self):
        """OVOS-PIPELINE-1 §7.3 / OVOS-INTENT-4 §5.3/§6.3: a registration
        naming a reserved intent_name is malformed — "log at WARN, do not
        index"."""
        for reserved in RESERVED_INTENT_NAMES:
            with self.subTest(reserved=reserved):
                m = _manifest()
                with patch("ovos_core.intent_services.manifest.LOG") as mock_log:
                    m._on_register(_reg("skill.test", reserved))
                mock_log.warning.assert_called_once()
                self.assertIn("reserved", str(mock_log.warning.call_args))
                self.assertEqual(m._index, {})

    def test_non_reserved_intent_name_does_not_warn(self):
        with patch("ovos_core.intent_services.manifest.LOG") as mock_log:
            self.m._on_register(_reg("skill.test", "hello"))
        mock_log.warning.assert_not_called()

    def test_register_without_context_skill_id_is_indexed(self):
        # OVOS-INTENT-4 §3.2: a §§5-8 message is complete without
        # context["skill_id"] and its absence is not malformed.
        msg = Message("ovos.intent.register.keyword",
                      data={"skill_id": "skill.test", "intent_name": "hello", "lang": "en-US"},
                      context={})
        self.m._on_register(msg)
        self.assertEqual(list(self.m._index),
                         [("default", "skill.test", "hello", "en-US", "keyword")])
        self.assertEqual(list(self.m._index.values())[0]["skill_id"], "skill.test")

    def test_register_is_keyed_by_the_payload_skill_id(self):
        # OVOS-INTENT-4 §3.2: the payload names the target, the context names
        # the source; a provisioning tool registers on another skill's behalf
        # and the entry belongs to the target.
        msg = Message("ovos.intent.register.keyword",
                      data={"skill_id": "a.skill", "intent_name": "hello", "lang": "en-US"},
                      context={"skill_id": "b.skill"})
        self.m._on_register(msg)
        self.assertEqual(list(self.m._index),
                         [("default", "a.skill", "hello", "en-US", "keyword")])
        self.assertEqual(list(self.m._index.values())[0]["skill_id"], "a.skill")

    def test_register_matching_payload_skill_id_still_registers(self):
        msg = Message("ovos.intent.register.keyword",
                      data={"skill_id": "skill.test", "intent_name": "hello", "lang": "en-US"},
                      context={"skill_id": "skill.test"})
        self.m._on_register(msg)
        self.assertEqual(len(self.m._index), 1)

    def test_register_without_payload_skill_id_uses_context(self):
        msg = Message("ovos.intent.register.keyword",
                      data={"intent_name": "hello", "lang": "en-US"},
                      context={"skill_id": "skill.test"})
        self.m._on_register(msg)
        entry = list(self.m._index.values())[0]
        self.assertEqual(entry["skill_id"], "skill.test")


class TestManifestDeregister(unittest.TestCase):
    def setUp(self):
        self.m = _manifest()
        self.m._on_register(_reg("skill.test", "hello", lang="en-US"))
        self.m._on_register(_reg("skill.test", "hello", lang="de-DE"))

    def test_deregister_specific_lang(self):
        msg = Message("ovos.intent.deregister",
                      data={"skill_id": "skill.test", "intent_name": "hello", "lang": "en-US"},
                      context={"skill_id": "skill.test"})
        self.m._on_deregister(msg)
        langs = [e["lang"] for e in self.m._index.values()]
        self.assertNotIn("en-US", langs)
        self.assertIn("de-DE", langs)

    def test_deregister_all_langs(self):
        msg = Message("ovos.intent.deregister",
                      data={"skill_id": "skill.test", "intent_name": "hello"},
                      context={"skill_id": "skill.test"})
        self.m._on_deregister(msg)
        self.assertEqual(len(self.m._index), 0)

    def test_deregister_without_context_skill_id_removes_the_payload_target(self):
        # OVOS-INTENT-4 §3.2: an absent context["skill_id"] is not malformed.
        msg = Message("ovos.intent.deregister",
                      data={"skill_id": "skill.test", "intent_name": "hello"},
                      context={})
        self.m._on_deregister(msg)
        self.assertEqual(list(self.m._index), [])

    def test_deregister_acts_on_the_payload_skill_id(self):
        # a conflict-resolving skill retracts on another skill's behalf; the
        # entry keyed by the payload id goes and the source's stays.
        self.m._on_register(_reg("b.skill", "hello", lang="en-US"))
        self.m._on_register(_reg("a.skill", "hello", lang="en-US"))
        msg = Message("ovos.intent.deregister",
                      data={"skill_id": "a.skill", "intent_name": "hello"},
                      context={"skill_id": "b.skill"})
        self.m._on_deregister(msg)
        self.assertNotIn(("default", "a.skill", "hello", "en-US", "keyword"), self.m._index)
        self.assertIn(("default", "b.skill", "hello", "en-US", "keyword"), self.m._index)

    def test_deregister_reserved_intent_name_warns_and_is_a_noop(self):
        # a reserved name was never indexed (§7.3); deregistering it must
        # not touch the index and must log the ignored mutation.
        msg = Message("ovos.intent.deregister",
                      data={"skill_id": "skill.test", "intent_name": "stop"},
                      context={"skill_id": "skill.test"})
        with patch("ovos_core.intent_services.manifest.LOG") as mock_log:
            self.m._on_deregister(msg)
        mock_log.warning.assert_called_once()
        self.assertIn("reserved", str(mock_log.warning.call_args))
        self.assertEqual(len(self.m._index), 2)


class TestManifestEnableDisable(unittest.TestCase):
    def setUp(self):
        self.m = _manifest()
        self.m._on_register(_reg("skill.test", "hello", lang="en-US"))

    def test_disable_intent(self):
        msg = Message("ovos.intent.disable",
                      data={"skill_id": "skill.test", "intent_name": "hello", "lang": "en-US"})
        self.m._on_enable_disable(msg)
        entry = list(self.m._index.values())[0]
        self.assertFalse(entry["enabled"])

    def test_enable_intent(self):
        msg = Message("ovos.intent.disable",
                      data={"skill_id": "skill.test", "intent_name": "hello", "lang": "en-US"})
        self.m._on_enable_disable(msg)
        msg2 = Message("ovos.intent.enable",
                       data={"skill_id": "skill.test", "intent_name": "hello", "lang": "en-US"})
        self.m._on_enable_disable(msg2)
        entry = list(self.m._index.values())[0]
        self.assertTrue(entry["enabled"])

    def test_bridged_legacy_toggle_resolves_from_context(self):
        # ovos-spec-tools bridges mycroft.skill.disable_intent onto the spec
        # topic, and _toggle_legacy_to_spec has no skill_id field to carry, so
        # the emitter is named only in the context. Resolving payload-only
        # would make every bridged toggle a silent no-op.
        msg = Message("ovos.intent.disable",
                      data={"intent_name": "hello", "lang": "en-US"},
                      context={"skill_id": "skill.test"})
        with patch("ovos_core.intent_services.manifest.LOG.warning") as warn:
            self.m._on_enable_disable(msg)
        entry = list(self.m._index.values())[0]
        self.assertFalse(entry["enabled"])
        warned = " ".join(str(c.args[0]) for c in warn.call_args_list)
        self.assertIn("§3.2", warned)
        self.assertIn("skill.test", warned)

    def test_payload_target_wins_over_a_differing_source(self):
        # §3.2: the payload names the target, the context is provenance. A
        # provisioning tool acting on another skill must not retarget itself.
        self.m._on_register(_reg("skill.other", "hello", lang="en-US"))
        msg = Message("ovos.intent.disable",
                      data={"skill_id": "skill.other", "intent_name": "hello",
                            "lang": "en-US"},
                      context={"skill_id": "provisioner"})
        self.m._on_enable_disable(msg)
        by_skill = {k[1]: v["enabled"] for k, v in self.m._index.items()}
        self.assertEqual(by_skill, {"skill.test": True, "skill.other": False})


class TestDeregisterSessionScope(unittest.TestCase):
    """§11.1/§11.3 — deregistration MUST key off context.session.session_id,
    NEVER Message.data.session_id (security-relevant: a forged data.session_id
    would let one session's producer wipe another session's registrations)."""

    def setUp(self):
        self.m = _manifest()
        self.m._on_register(_reg("skill.test", "hello", session_id="A"))

    def test_forged_data_session_id_does_not_wipe_foreign_session(self):
        # attacker runs under session B (context) but claims data.session_id=A
        msg = Message("ovos.intent.deregister",
                      data={"skill_id": "skill.test", "intent_name": "hello", "session_id": "A"},
                      context={"session": {"session_id": "B"}, "skill_id": "skill.test"})
        self.m._on_deregister(msg)
        # session A's entry MUST survive; only B (which has no entry) was touched
        sessions = {e["session_id"] for e in self.m._index.values()}
        self.assertIn("A", sessions)

    def test_owner_deregister_via_context_removes_entry(self):
        # the true owner of session A deregisters, context-scoped, no data.session_id
        msg = Message("ovos.intent.deregister",
                      data={"skill_id": "skill.test", "intent_name": "hello"},
                      context={"session": {"session_id": "A"}, "skill_id": "skill.test"})
        self.m._on_deregister(msg)
        self.assertEqual(len(self.m._index), 0)


class TestSkillDeregister(unittest.TestCase):
    def setUp(self):
        self.m = _manifest()
        self.m._on_register(_reg("skill.a", "x"))
        self.m._on_register(_reg("skill.a", "y"))
        self.m._on_register(_reg("skill.b", "z"))

    def test_removes_only_target_skill(self):
        msg = Message("ovos.skill.deregister", data={"skill_id": "skill.a"},
                      context={"skill_id": "skill.a"})
        self.m._on_skill_deregister(msg)
        skills = {e["skill_id"] for e in self.m._index.values()}
        self.assertNotIn("skill.a", skills)
        self.assertIn("skill.b", skills)

    def test_without_context_skill_id_removes_the_payload_target(self):
        # OVOS-INTENT-4 §3.2: an absent context["skill_id"] is not malformed.
        msg = Message("ovos.skill.deregister", data={"skill_id": "skill.a"}, context={})
        self.m._on_skill_deregister(msg)
        skills = {e["skill_id"] for e in self.m._index.values()}
        self.assertNotIn("skill.a", skills)
        self.assertIn("skill.b", skills)

    def test_acts_on_the_payload_skill_id(self):
        # a provisioning tool retires skill.a while its own context names
        # skill.b; the payload is the target, the context is provenance.
        msg = Message("ovos.skill.deregister", data={"skill_id": "skill.a"},
                      context={"skill_id": "skill.b"})
        self.m._on_skill_deregister(msg)
        self.assertEqual({e["skill_id"] for e in self.m._index.values()}, {"skill.b"})
        self.assertEqual(sorted(k[2] for k in self.m._index), ["z"])


class TestEffectivePool(unittest.TestCase):
    def setUp(self):
        self.m = _manifest()
        self.m._on_register(_reg("skill.test", "hello", session_id="default"))
        self.m._on_register(_reg("skill.sat", "sat_intent", session_id="sat-1"))

    def test_default_session_excludes_satellite(self):
        pool = self.m._effective_pool("default")
        names = {e["intent_name"] for e in pool}
        self.assertIn("hello", names)
        self.assertNotIn("sat_intent", names)

    def test_satellite_session_inherits_default(self):
        pool = self.m._effective_pool("sat-1")
        names = {e["intent_name"] for e in pool}
        self.assertIn("hello", names)
        self.assertIn("sat_intent", names)


class TestIntentListQuery(unittest.TestCase):
    def setUp(self):
        self.m = _manifest()
        self.m._on_register(_reg("skill.a", "play", lang="en-US"))
        self.m._on_register(_reg("skill.a", "pause", lang="en-US"))
        self.m._on_register(_reg("skill.b", "play", lang="de-DE"))

    def _query(self, **kwargs):
        replies = []
        self.m.bus.on("ovos.intent.list.response", lambda msg: replies.append(msg))
        self.m.bus.emit(Message("ovos.intent.list", data=kwargs))
        return replies[-1].data if replies else None

    def test_no_filters_returns_all(self):
        resp = self._query()
        self.assertTrue(resp["ok"])
        self.assertEqual(len(resp["intents"]), 3)

    def test_filter_by_skill(self):
        resp = self._query(skill_id="skill.a")
        names = {e["intent_name"] for e in resp["intents"]}
        self.assertEqual(names, {"play", "pause"})

    def test_filter_by_lang(self):
        resp = self._query(lang="de-DE")
        self.assertEqual(len(resp["intents"]), 1)
        self.assertEqual(resp["intents"][0]["skill_id"], "skill.b")

    def test_list_non_string_lang_returns_error_reply(self):
        resp = self._query(lang=5)
        self.assertIsNotNone(resp)
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error"], "lang must be a string")

    def test_list_non_string_skill_id_returns_error_reply(self):
        resp = self._query(skill_id=[])
        self.assertIsNotNone(resp)
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error"], "skill_id must be a string")

    def test_list_non_string_session_id_returns_error_reply(self):
        resp = self._query(session_id=7)
        self.assertIsNotNone(resp)
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error"], "session_id must be a string")


class TestIntentDescribeQuery(unittest.TestCase):
    def setUp(self):
        self.m = _manifest()
        self.m._on_register(_reg("skill.a", "play", lang="en-US", method="keyword"))
        self.m._on_register(_reg("skill.a", "play", lang="en-US", method="template"))

    def _query(self, **kwargs):
        replies = []
        self.m.bus.on("ovos.intent.describe.response", lambda msg: replies.append(msg))
        self.m.bus.emit(Message("ovos.intent.describe", data=kwargs))
        return replies[-1].data if replies else None

    def test_describe_both_methods_ordered(self):
        resp = self._query(skill_id="skill.a", intent_name="play", lang="en-US")
        self.assertTrue(resp["ok"])
        methods = [d["method"] for d in resp["definitions"]]
        self.assertEqual(methods, ["keyword", "template"])

    def test_describe_filter_by_method(self):
        resp = self._query(skill_id="skill.a", intent_name="play", lang="en-US", method="template")
        self.assertEqual(len(resp["definitions"]), 1)
        self.assertEqual(resp["definitions"][0]["method"], "template")

    def test_describe_unknown_returns_error(self):
        resp = self._query(skill_id="skill.a", intent_name="nonexistent", lang="en-US")
        self.assertFalse(resp["ok"])

    def test_describe_without_a_skill_id_returns_error(self):
        # skill_id is what bounds the reply, so it stays required.
        resp = self._query(intent_name="play", lang="en-US")
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error"], "skill_id is required")

    def test_describe_non_string_lang_returns_error_reply(self):
        resp = self._query(skill_id="skill.a", lang=5)
        self.assertIsNotNone(resp)
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error"], "lang must be a string")

    def test_describe_none_skill_id_returns_error_reply(self):
        # caught by the pre-existing "skill_id is required" check, not the
        # type-validation guard — None never reaches _invalid_filter's
        # isinstance check because it is treated as "absent".
        resp = self._query(skill_id=None, intent_name="play")
        self.assertIsNotNone(resp)
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error"], "skill_id is required")

    def test_describe_non_string_intent_name_returns_error_reply(self):
        resp = self._query(skill_id="skill.a", intent_name=[])
        self.assertIsNotNone(resp)
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error"], "intent_name must be a string")

    def test_describe_non_string_session_id_returns_error_reply(self):
        resp = self._query(skill_id="skill.a", session_id=7)
        self.assertIsNotNone(resp)
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error"], "session_id must be a string")

    def test_describe_non_string_method_returns_error_reply(self):
        resp = self._query(skill_id="skill.a", method=1)
        self.assertIsNotNone(resp)
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error"], "method must be a string")

    def test_describe_all_valid_fields_still_works(self):
        resp = self._query(skill_id="skill.a", intent_name="play",
                           lang="en-US", method="keyword", session_id="default")
        self.assertIsNotNone(resp)
        self.assertTrue(resp["ok"])


class TestIntentDescribeSkillWide(unittest.TestCase):
    """§10.2 — ``intent_name`` and ``lang`` are optional filters, so one
    describe can cover a whole skill. That is what makes the manifest usable
    for "what can I ask this device": the client walks the skills it got from
    ``ovos.intent.list`` and asks once per skill, instead of once per intent
    per language, and no reply is ever larger than a single skill."""

    ROW_FIELDS = {"skill_id", "intent_name", "lang", "method", "session_id", "definition"}
    EN_WEATHER = ["what is the weather", "what is the weather in {location}"]
    DE_WEATHER = ["wie ist das wetter", "wie ist das wetter in {location}"]
    EN_FORECAST = ["what is the forecast"]

    def setUp(self):
        self.m = _manifest()
        self.m._on_register(_reg("skill.weather", "current.weather", lang="en-US",
                                 method="template", samples=self.EN_WEATHER))
        self.m._on_register(_reg("skill.weather", "current.weather", lang="de-DE",
                                 method="template", samples=self.DE_WEATHER))
        self.m._on_register(_reg("skill.weather", "current.weather", lang="en-US",
                                 method="keyword", required=["WeatherKeyword"]))
        self.m._on_register(_reg("skill.weather", "forecast", lang="en-US",
                                 method="template", samples=self.EN_FORECAST))
        self.m._on_register(_reg("skill.timer", "set.timer", lang="en-US",
                                 method="template", samples=["set a timer"]))

    def _query(self, **kwargs):
        replies = []
        self.m.bus.on("ovos.intent.describe.response", lambda msg: replies.append(msg))
        self.m._on_describe(Message("ovos.intent.describe", data=kwargs))
        return replies[-1].data if replies else None

    @staticmethod
    def _keys(resp):
        return {(d["intent_name"], d["lang"], d["method"]) for d in resp["definitions"]}

    def test_skill_id_alone_returns_every_registration_of_that_skill(self):
        resp = self._query(skill_id="skill.weather")
        self.assertTrue(resp["ok"])
        self.assertEqual(self._keys(resp),
                         {("current.weather", "en-US", "template"),
                          ("current.weather", "de-DE", "template"),
                          ("current.weather", "en-US", "keyword"),
                          ("forecast", "en-US", "template")})

    def test_the_reply_stops_at_the_skill(self):
        # The bound is what keeps a describe small: another skill's intents
        # never ride along.
        resp = self._query(skill_id="skill.weather")
        self.assertNotIn("skill.timer", {d["skill_id"] for d in resp["definitions"]})

    def test_every_row_identifies_its_intent_and_language(self):
        # Without these a multi-intent reply could not be taken apart.
        resp = self._query(skill_id="skill.weather")
        for row in resp["definitions"]:
            self.assertEqual(set(row), self.ROW_FIELDS)
            self.assertEqual(row["skill_id"], "skill.weather")
        by_key = {(d["intent_name"], d["lang"], d["method"]): d["definition"]
                  for d in resp["definitions"]}
        self.assertEqual(by_key[("current.weather", "en-US", "template")]["samples"],
                         self.EN_WEATHER)
        self.assertEqual(by_key[("current.weather", "de-DE", "template")]["samples"],
                         self.DE_WEATHER)
        self.assertEqual(by_key[("current.weather", "en-US", "keyword")]["required"],
                         ["WeatherKeyword"])

    def test_a_language_filter_narrows_and_still_folds(self):
        # "de-de" folds to the stored "de-DE"; the English rows stay out.
        resp = self._query(skill_id="skill.weather", lang="de-de")
        self.assertEqual(self._keys(resp), {("current.weather", "de-DE", "template")})

    def test_an_intent_without_a_language_covers_every_language(self):
        resp = self._query(skill_id="skill.weather", intent_name="current.weather")
        self.assertEqual({d["lang"] for d in resp["definitions"]}, {"en-US", "de-DE"})
        self.assertNotIn("forecast", {d["intent_name"] for d in resp["definitions"]})

    def test_method_and_session_filters_still_compose(self):
        self.m._on_register(_reg("skill.weather", "current.weather", lang="en-US",
                                 method="template", session_id="sat-1",
                                 samples=["how is the weather"]))
        resp = self._query(skill_id="skill.weather", method="template", session_id="sat-1")
        self.assertEqual(len(resp["definitions"]), 1)
        self.assertEqual(resp["definitions"][0]["definition"]["samples"],
                         ["how is the weather"])

    def test_one_skill_wide_query_equals_the_per_intent_queries(self):
        # The claim the change rests on: asking once per skill returns exactly
        # what asking once per intent per language returns.
        wide = self._query(skill_id="skill.weather")
        narrow = []
        for intent_name, lang in (("current.weather", "en-US"), ("current.weather", "de-DE"),
                                  ("forecast", "en-US")):
            narrow += self._query(skill_id="skill.weather", intent_name=intent_name,
                                  lang=lang)["definitions"]
        self.assertEqual(wide["definitions"], sorted(
            narrow, key=lambda d: (d["intent_name"], d["lang"],
                                   0 if d["method"] == "keyword" else 1)))

    def test_ordering_is_deterministic_across_intents_and_languages(self):
        self.m._on_register(_reg("skill.weather", "forecast", lang="en-US",
                                 method="template", session_id="sat-1",
                                 samples=["forecast please"]))
        resp = self._query(skill_id="skill.weather")
        order = [(d["session_id"], d["intent_name"], d["lang"], d["method"])
                 for d in resp["definitions"]]
        self.assertEqual(order, [
            ("default", "current.weather", "de-DE", "template"),
            ("default", "current.weather", "en-US", "keyword"),
            ("default", "current.weather", "en-US", "template"),
            ("default", "forecast", "en-US", "template"),
            ("sat-1", "forecast", "en-US", "template"),
        ])

    def test_an_unknown_skill_names_the_wildcarded_target(self):
        resp = self._query(skill_id="skill.nope")
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error"], "unknown intent skill.nope:*:*")


class TestIntentDescribeSessionScope(unittest.TestCase):
    """§10.2 — session_id is an optional query filter: omitted returns
    definitions from every session_id; each entry self-identifies via
    session_id."""

    def setUp(self):
        self.m = _manifest()
        self.m._on_register(_reg("skill.a", "play", lang="en-US",
                                 method="keyword", session_id="default"))
        self.m._on_register(_reg("skill.a", "play", lang="en-US",
                                 method="keyword", session_id="sat-1"))

    def _query(self, **kwargs):
        replies = []
        self.m.bus.on("ovos.intent.describe.response", lambda msg: replies.append(msg))
        self.m._on_describe(Message("ovos.intent.describe", data=kwargs))
        return replies[-1].data if replies else None

    def test_omitted_session_id_returns_every_session(self):
        resp = self._query(skill_id="skill.a", intent_name="play", lang="en-US")
        self.assertTrue(resp["ok"])
        sessions = {d["session_id"] for d in resp["definitions"]}
        self.assertEqual(sessions, {"default", "sat-1"})

    def test_definitions_carry_session_id(self):
        resp = self._query(skill_id="skill.a", intent_name="play", lang="en-US",
                           session_id="sat-1")
        self.assertEqual(len(resp["definitions"]), 1)
        self.assertEqual(resp["definitions"][0]["session_id"], "sat-1")


def _reg_ctx(skill_id, intent_name, requires=None, excludes=None, slots=None,
             lang="en-US", method="keyword", session_id="default"):
    data = {"skill_id": skill_id, "intent_name": intent_name, "lang": lang}
    if requires is not None:
        data["requires_context"] = requires
    if excludes is not None:
        data["excludes_context"] = excludes
    if slots is not None:
        data["required"] = slots
    return Message(f"ovos.intent.register.{method}", data=data,
                   context={"session": {"session_id": session_id}, "skill_id": skill_id})


class TestManifestContextLookups(unittest.TestCase):
    def setUp(self):
        self.m = _manifest()

    def test_context_requirements(self):
        self.m._on_register(_reg_ctx("s.skill", "on", requires=["kitchen"],
                                     excludes=["modal"]))
        req, exc = self.m.get_context_requirements("default", "s.skill", "on", "en-US")
        self.assertEqual(req, ["kitchen"])
        self.assertEqual(exc, ["modal"])

    def test_context_requirements_empty_when_undeclared(self):
        self.m._on_register(_reg_ctx("s.skill", "on"))
        self.assertEqual(self.m.get_context_requirements("default", "s.skill", "on", "en-US"),
                         ([], []))

    def test_context_requirements_unknown_intent(self):
        self.assertEqual(self.m.get_context_requirements("default", "x", "y", "en-US"),
                         ([], []))

    def test_context_requirements_union_across_methods(self):
        self.m._on_register(_reg_ctx("s.skill", "on", requires=["a"], method="keyword"))
        self.m._on_register(_reg_ctx("s.skill", "on", requires=["b"], method="template"))
        req, _ = self.m.get_context_requirements("default", "s.skill", "on", "en-US")
        self.assertEqual(sorted(req), ["a", "b"])

    def test_slot_names(self):
        self.m._on_register(_reg_ctx("s.skill", "on", slots=["room", "device"]))
        self.assertEqual(self.m.get_slot_names("default", "s.skill", "on", "en-US"),
                         ["room", "device"])

    def test_session_scoped_visible_via_effective_pool(self):
        self.m._on_register(_reg_ctx("s.skill", "on", requires=["k"], session_id="sat-1"))
        req, _ = self.m.get_context_requirements("sat-1", "s.skill", "on", "en-US")
        self.assertEqual(req, ["k"])
        # a different session does not see the satellite-scoped declaration
        self.assertEqual(self.m.get_context_requirements("other", "s.skill", "on", "en-US"),
                         ([], []))


class TestReservedStopIsNotIndexed(unittest.TestCase):
    """OVOS-STOP-1 §2: "Skills and other pipelines MUST NOT register `stop`
    under OVOS-INTENT-4. A registration naming this intent_name is malformed
    per OVOS-INTENT-4 §5.3/§6.3 — consumers log at WARN and do not index."
    PIPELINE-1 §7.3 repeats the rule for every reserved name, and STOP-1 §9
    makes it an orchestrator MUST: "treat OVOS-INTENT-4 registrations naming
    `stop` as malformed — log at WARN and decline to index".

    Warning while indexing anyway is the failure this guards: the entry then
    shows up in `ovos.intent.list`, in `ovos.intent.describe`, and in the
    §6.2 required-slot backstop, where it shadows the stop pipeline's own
    reserved `<skill_id>:stop` dispatch.
    """

    def setUp(self):
        self.m = _manifest()

    def test_stop_registration_is_not_indexed(self):
        with patch("ovos_core.intent_services.manifest.LOG") as mock_log:
            self.m._on_register(_reg("skill.test", "stop"))
        mock_log.warning.assert_called_once()
        self.assertEqual(self.m._index, {})

    def test_stop_registration_absent_from_intent_list(self):
        self.m._on_register(_reg("skill.test", "play"))
        self.m._on_register(_reg("skill.test", "stop"))
        replies = []
        self.m.bus.on("ovos.intent.list.response", lambda msg: replies.append(msg))
        self.m._on_list(Message("ovos.intent.list", data={}))
        names = {e["intent_name"] for e in replies[-1].data["intents"]}
        self.assertEqual(names, {"play"})

    def test_global_stop_is_not_reserved_and_is_indexed(self):
        """STOP-1 §2 leaves `global_stop` unreserved; only `stop` is."""
        self.m._on_register(_reg("skill.test", "global_stop"))
        self.assertEqual(len(self.m._index), 1)

    def test_both_registration_methods_are_declined(self):
        for method in ("keyword", "template"):
            m = _manifest()
            m._on_register(_reg("skill.test", "stop", method=method))
            self.assertEqual(m._index, {}, method)
