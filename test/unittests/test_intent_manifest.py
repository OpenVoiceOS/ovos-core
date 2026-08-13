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
        """CONFIRMED-5: a skill registering a real intent literally named
        'stop' binds the same '<skill_id>:stop' topic OVOS-STOP-1 reserves for
        the targeted-stop dispatch — the manifest must warn about the
        collision, the natural point where core observes registration."""
        with patch("ovos_core.intent_services.manifest.LOG") as mock_log:
            self.m._on_register(_reg("skill.test", "stop"))
        mock_log.warning.assert_called_once()
        self.assertIn("reserved", str(mock_log.warning.call_args))
        # registration itself still proceeds (warn, don't reject)
        self.assertEqual(len(self.m._index), 1)

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
        self.m._on_register(_reg("skill.a", "stop", lang="en-US"))
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
        self.assertEqual(names, {"play", "stop"})

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
