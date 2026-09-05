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

from ovos_core.intent_services.manifest import IntentManifest


def _manifest() -> IntentManifest:
    return IntentManifest(FakeBus())


def _reg(skill_id, intent_name, lang="en-US", method="keyword", session_id="default"):
    topic = f"ovos.intent.register.{method}"
    return Message(topic,
                   data={"skill_id": skill_id, "intent_name": intent_name, "lang": lang},
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

    def test_reserved_stop_intent_name_warns(self):
        """STOP-1 §2/§9 and PIPELINE-1 §7.3: a registration naming the
        reserved `stop` is malformed — "log at WARN, do not index"."""
        with patch("ovos_core.intent_services.manifest.LOG") as mock_log:
            self.m._on_register(_reg("skill.test", "stop"))
        mock_log.warning.assert_called_once()
        self.assertIn("reserved", str(mock_log.warning.call_args))
        self.assertEqual(self.m._index, {})

    def test_non_reserved_intent_name_does_not_warn(self):
        with patch("ovos_core.intent_services.manifest.LOG") as mock_log:
            self.m._on_register(_reg("skill.test", "hello"))
        mock_log.warning.assert_not_called()


class TestManifestDeregister(unittest.TestCase):
    def setUp(self):
        self.m = _manifest()
        self.m._on_register(_reg("skill.test", "hello", lang="en-US"))
        self.m._on_register(_reg("skill.test", "hello", lang="de-DE"))

    def test_deregister_specific_lang(self):
        msg = Message("ovos.intent.deregister",
                      data={"skill_id": "skill.test", "intent_name": "hello", "lang": "en-US"})
        self.m._on_deregister(msg)
        langs = [e["lang"] for e in self.m._index.values()]
        self.assertNotIn("en-US", langs)
        self.assertIn("de-DE", langs)

    def test_deregister_all_langs(self):
        msg = Message("ovos.intent.deregister",
                      data={"skill_id": "skill.test", "intent_name": "hello"})
        self.m._on_deregister(msg)
        self.assertEqual(len(self.m._index), 0)


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
                      context={"session": {"session_id": "B"}})
        self.m._on_deregister(msg)
        # session A's entry MUST survive; only B (which has no entry) was touched
        sessions = {e["session_id"] for e in self.m._index.values()}
        self.assertIn("A", sessions)

    def test_owner_deregister_via_context_removes_entry(self):
        # the true owner of session A deregisters, context-scoped, no data.session_id
        msg = Message("ovos.intent.deregister",
                      data={"skill_id": "skill.test", "intent_name": "hello"},
                      context={"session": {"session_id": "A"}})
        self.m._on_deregister(msg)
        self.assertEqual(len(self.m._index), 0)


class TestSkillDeregister(unittest.TestCase):
    def setUp(self):
        self.m = _manifest()
        self.m._on_register(_reg("skill.a", "x"))
        self.m._on_register(_reg("skill.a", "y"))
        self.m._on_register(_reg("skill.b", "z"))

    def test_removes_only_target_skill(self):
        msg = Message("ovos.skill.deregister", data={"skill_id": "skill.a"})
        self.m._on_skill_deregister(msg)
        skills = {e["skill_id"] for e in self.m._index.values()}
        self.assertNotIn("skill.a", skills)
        self.assertIn("skill.b", skills)


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
        self.m._on_list(Message("ovos.intent.list", data=kwargs))
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


class TestIntentDescribeQuery(unittest.TestCase):
    def setUp(self):
        self.m = _manifest()
        self.m._on_register(_reg("skill.a", "play", lang="en-US", method="keyword"))
        self.m._on_register(_reg("skill.a", "play", lang="en-US", method="template"))

    def _query(self, **kwargs):
        replies = []
        self.m.bus.on("ovos.intent.describe.response", lambda msg: replies.append(msg))
        self.m._on_describe(Message("ovos.intent.describe", data=kwargs))
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

    def test_describe_missing_fields_returns_error(self):
        resp = self._query(skill_id="skill.a")
        self.assertFalse(resp["ok"])


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
