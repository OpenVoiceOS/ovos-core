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
from unittest.mock import MagicMock, patch

from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch
from ovos_utils.fakebus import FakeBus

from ovos_core.transformers import (
    UtteranceTransformersService,
    MetadataTransformersService,
    IntentTransformersService,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_mock_plugin(name: str = "mock_plugin", priority: int = 50) -> MagicMock:
    """Return a mock transformer plugin with the required interface."""
    plugin = MagicMock()
    plugin.name = name
    plugin.priority = priority
    return plugin


def _make_utterance_service(plugins=None, config=None) -> UtteranceTransformersService:
    """Create UtteranceTransformersService without loading real plugins."""
    bus = FakeBus()
    cfg = config or {}
    with patch("ovos_core.transformers.find_utterance_transformer_plugins",
               return_value={}), \
         patch("ovos_core.transformers.Configuration", return_value=cfg):
        svc = UtteranceTransformersService(bus, config=cfg)
    if plugins is not None:
        svc.loaded_plugins = {p.name: p for p in plugins}
        svc._sorted_plugins = None
    return svc


def _make_metadata_service(plugins=None, config=None) -> MetadataTransformersService:
    """Create MetadataTransformersService without loading real plugins."""
    bus = FakeBus()
    cfg = config or {}
    with patch("ovos_core.transformers.find_metadata_transformer_plugins",
               return_value={}), \
         patch("ovos_core.transformers.Configuration", return_value=cfg):
        svc = MetadataTransformersService(bus, config=cfg)
    if plugins is not None:
        svc.loaded_plugins = {p.name: p for p in plugins}
        svc._sorted_plugins = None
    return svc


def _make_intent_service(plugins=None, config=None) -> IntentTransformersService:
    """Create IntentTransformersService without loading real plugins."""
    bus = FakeBus()
    cfg = config or {}
    with patch("ovos_core.transformers.find_intent_transformer_plugins",
               return_value={}), \
         patch("ovos_core.transformers.Configuration", return_value=cfg):
        svc = IntentTransformersService(bus, config=cfg)
    if plugins is not None:
        svc.loaded_plugins = {p.name: p for p in plugins}
        svc._sorted_plugins = None
    return svc


# ---------------------------------------------------------------------------
# UtteranceTransformersService
# ---------------------------------------------------------------------------

class TestUtteranceTransformersServiceInit(unittest.TestCase):
    """Tests for UtteranceTransformersService initialisation."""

    def test_no_plugins_loaded_when_config_empty(self):
        """With an empty config, no plugins are loaded."""
        svc = _make_utterance_service()
        self.assertEqual(svc.loaded_plugins, {})

    def test_plugin_loaded_when_active_in_config(self):
        """A plugin listed in config with active=True is instantiated."""
        mock_cls = MagicMock(return_value=_make_mock_plugin("plug"))
        # The service reads self.config which is config_core.get("utterance_transformers")
        # Pass a config_core that returns the plugin config when .get() is called
        config_core = {"utterance_transformers": {"plug": {"active": True}}}
        with patch("ovos_core.transformers.find_utterance_transformer_plugins",
                   return_value={"plug": mock_cls}), \
             patch("ovos_core.transformers.Configuration", return_value=config_core):
            svc = UtteranceTransformersService(FakeBus())
        self.assertIn("plug", svc.loaded_plugins)
        mock_cls.assert_called_once()

    def test_plugin_skipped_when_active_false(self):
        """A plugin with active=False is not loaded."""
        mock_cls = MagicMock()
        cfg = {"plug": {"active": False}}
        with patch("ovos_core.transformers.find_utterance_transformer_plugins",
                   return_value={"plug": mock_cls}), \
             patch("ovos_core.transformers.Configuration", return_value=cfg):
            svc = UtteranceTransformersService(FakeBus(), config=cfg)
        self.assertNotIn("plug", svc.loaded_plugins)
        mock_cls.assert_not_called()

    def test_plugin_load_exception_is_swallowed(self):
        """An exception during plugin init is logged and not re-raised."""
        def bad_init():
            raise RuntimeError("boom")

        cfg = {"bad_plug": {"active": True}}
        with patch("ovos_core.transformers.find_utterance_transformer_plugins",
                   return_value={"bad_plug": bad_init}), \
             patch("ovos_core.transformers.Configuration", return_value=cfg):
            # Should not raise
            svc = UtteranceTransformersService(FakeBus(), config=cfg)
        self.assertNotIn("bad_plug", svc.loaded_plugins)


class TestUtteranceTransformersServicePluginsProperty(unittest.TestCase):
    """Tests for the plugins property (priority ordering)."""

    def test_plugins_sorted_by_priority_ascending(self):
        """OVOS-TRANSFORM §4: lower priority number runs first."""
        low = _make_mock_plugin("low", priority=10)
        high = _make_mock_plugin("high", priority=90)
        svc = _make_utterance_service(plugins=[low, high])
        self.assertEqual(svc.plugins[0].name, "low")
        self.assertEqual(svc.plugins[1].name, "high")

    def test_plugins_sorted_result_is_cached(self):
        """The sorted list is computed once and cached in _sorted_plugins."""
        p = _make_mock_plugin("p", priority=50)
        svc = _make_utterance_service(plugins=[p])
        first = svc.plugins
        second = svc.plugins
        self.assertIs(first, second)

    def test_load_plugins_invalidates_cache(self):
        """Calling load_plugins sets _sorted_plugins to None."""
        svc = _make_utterance_service()
        svc._sorted_plugins = ["cached"]
        with patch("ovos_core.transformers.find_utterance_transformer_plugins",
                   return_value={}):
            svc.load_plugins()
        self.assertIsNone(svc._sorted_plugins)


class TestUtteranceTransformersServiceTransform(unittest.TestCase):
    """Tests for UtteranceTransformersService.transform."""

    def test_transform_calls_each_plugin(self):
        """Each loaded plugin's transform method is called once."""
        p1 = _make_mock_plugin("p1", priority=50)
        p1.transform.return_value = (["hello"], {})
        p2 = _make_mock_plugin("p2", priority=40)
        p2.transform.return_value = (["hello"], {})
        svc = _make_utterance_service(plugins=[p1, p2])
        svc.transform(["hello"])
        p1.transform.assert_called_once()
        p2.transform.assert_called_once()

    def test_transform_merges_context(self):
        """Context returned by a plugin is merged into the running context."""
        p = _make_mock_plugin("p", priority=50)
        p.transform.return_value = (["hello"], {"extra_key": "value"})
        svc = _make_utterance_service(plugins=[p])
        _, ctx = svc.transform(["hello"], {})
        self.assertEqual(ctx.get("extra_key"), "value")

    def test_transform_passes_modified_utterances_forward(self):
        """Utterances modified by a plugin are passed to the next plugin."""
        p1 = _make_mock_plugin("p1", priority=10)
        p1.transform.return_value = (["modified"], {})
        p2 = _make_mock_plugin("p2", priority=90)
        p2.transform.return_value = (["modified"], {})
        svc = _make_utterance_service(plugins=[p1, p2])
        svc.transform(["original"])
        # p2 runs after p1 and should see ["modified"]
        call_args = p2.transform.call_args[0]
        self.assertEqual(call_args[0], ["modified"])

    def test_transform_plugin_exception_is_swallowed(self):
        """An exception in a plugin transform is caught and does not propagate."""
        p = _make_mock_plugin("bad", priority=50)
        p.transform.side_effect = RuntimeError("oops")
        svc = _make_utterance_service(plugins=[p])
        # Should not raise
        result_utt, result_ctx = svc.transform(["hello"], {"k": "v"})
        self.assertEqual(result_utt, ["hello"])

    def test_transform_returns_original_when_no_plugins(self):
        """With no plugins the utterances and context pass through unchanged."""
        svc = _make_utterance_service(plugins=[])
        utt, ctx = svc.transform(["hello world"], {"lang": "en-US"})
        self.assertEqual(utt, ["hello world"])
        self.assertEqual(ctx, {"lang": "en-US"})

    def test_transform_default_context_is_empty_dict(self):
        """context defaults to an empty dict when not provided."""
        svc = _make_utterance_service(plugins=[])
        utt, ctx = svc.transform(["hi"])
        self.assertEqual(ctx, {})

    def test_session_key_excluded_from_log(self):
        """The 'session' key is stripped before logging (no exception raised)."""
        p = _make_mock_plugin("p", priority=50)
        p.transform.return_value = (["hello"], {"session": {"secret": "creds"}, "other": 1})
        svc = _make_utterance_service(plugins=[p])
        # Just ensuring it doesn't raise (the _safe dict excludes session)
        svc.transform(["hello"])


class TestUtteranceTransformersServiceShutdown(unittest.TestCase):
    """Tests for UtteranceTransformersService.shutdown."""

    def test_shutdown_calls_plugin_shutdown(self):
        """shutdown() calls shutdown on each loaded plugin."""
        p = _make_mock_plugin("p")
        svc = _make_utterance_service(plugins=[p])
        svc.shutdown()
        p.shutdown.assert_called_once()

    def test_shutdown_ignores_plugin_exception(self):
        """An exception in plugin shutdown does not propagate."""
        p = _make_mock_plugin("p")
        p.shutdown.side_effect = RuntimeError("bad")
        svc = _make_utterance_service(plugins=[p])
        svc.shutdown()  # should not raise


# ---------------------------------------------------------------------------
# MetadataTransformersService
# ---------------------------------------------------------------------------

class TestMetadataTransformersServiceTransform(unittest.TestCase):
    """Tests for MetadataTransformersService.transform."""

    def test_transform_calls_each_plugin(self):
        """Each plugin's transform method is called once."""
        p1 = _make_mock_plugin("p1", priority=50)
        p1.transform.return_value = {}
        p2 = _make_mock_plugin("p2", priority=40)
        p2.transform.return_value = {}
        svc = _make_metadata_service(plugins=[p1, p2])
        svc.transform({})
        p1.transform.assert_called_once()
        p2.transform.assert_called_once()

    def test_transform_merges_returned_data(self):
        """Data returned by a plugin is merged into context."""
        p = _make_mock_plugin("p", priority=50)
        p.transform.return_value = {"new_key": 42}
        svc = _make_metadata_service(plugins=[p])
        result = svc.transform({})
        self.assertEqual(result.get("new_key"), 42)

    def test_transform_exception_is_swallowed(self):
        """A plugin exception is caught and does not propagate."""
        p = _make_mock_plugin("bad", priority=50)
        p.transform.side_effect = ValueError("fail")
        svc = _make_metadata_service(plugins=[p])
        result = svc.transform({"x": 1})
        self.assertEqual(result, {"x": 1})

    def test_transform_returns_unchanged_context_when_no_plugins(self):
        """With no plugins the context passes through unchanged."""
        svc = _make_metadata_service(plugins=[])
        ctx = {"lang": "en-US"}
        result = svc.transform(ctx)
        self.assertEqual(result, {"lang": "en-US"})

    def test_transform_default_context_is_empty_dict(self):
        """context defaults to an empty dict when not provided."""
        svc = _make_metadata_service(plugins=[])
        result = svc.transform()
        self.assertEqual(result, {})

    def test_session_key_excluded_from_log(self):
        """'session' key is stripped from log data (no exception raised)."""
        p = _make_mock_plugin("p", priority=50)
        p.transform.return_value = {"session": {"token": "secret"}, "foo": "bar"}
        svc = _make_metadata_service(plugins=[p])
        svc.transform({})

    def test_plugins_sorted_by_priority_ascending(self):
        """OVOS-TRANSFORM §4: lower priority number runs first."""
        call_order = []
        low = _make_mock_plugin("low", priority=10)
        low.transform.side_effect = lambda ctx: call_order.append("low") or {}
        high = _make_mock_plugin("high", priority=90)
        high.transform.side_effect = lambda ctx: call_order.append("high") or {}
        svc = _make_metadata_service(plugins=[low, high])
        svc.transform({})
        self.assertEqual(call_order[0], "low")

    def test_shutdown_calls_plugin_shutdown(self):
        """shutdown() calls shutdown on each loaded plugin."""
        p = _make_mock_plugin("p")
        svc = _make_metadata_service(plugins=[p])
        svc.shutdown()
        p.shutdown.assert_called_once()

    def test_plugin_skipped_when_active_false(self):
        """A plugin with active=False is not loaded."""
        mock_cls = MagicMock()
        cfg = {"plug": {"active": False}}
        with patch("ovos_core.transformers.find_metadata_transformer_plugins",
                   return_value={"plug": mock_cls}), \
             patch("ovos_core.transformers.Configuration", return_value=cfg):
            svc = MetadataTransformersService(FakeBus(), config=cfg)
        self.assertNotIn("plug", svc.loaded_plugins)

    def test_plugin_loaded_when_active_true(self):
        """A plugin listed in config with active=True is instantiated."""
        mock_instance = _make_mock_plugin("plug")
        mock_cls = MagicMock(return_value=mock_instance)
        config_core = {"metadata_transformers": {"plug": {"active": True}}}
        with patch("ovos_core.transformers.find_metadata_transformer_plugins",
                   return_value={"plug": mock_cls}), \
             patch("ovos_core.transformers.Configuration", return_value=config_core):
            svc = MetadataTransformersService(FakeBus())
        self.assertIn("plug", svc.loaded_plugins)


# ---------------------------------------------------------------------------
# IntentTransformersService
# ---------------------------------------------------------------------------

def _make_intent_match(match_type: str = "test:intent") -> IntentHandlerMatch:
    """Create a minimal IntentHandlerMatch for testing."""
    return IntentHandlerMatch(
        match_type=match_type,
        match_data={},
        skill_id=None,
        utterance="hello",
    )


class TestIntentTransformersServiceTransform(unittest.TestCase):
    """Tests for IntentTransformersService.transform."""

    def test_transform_calls_each_plugin(self):
        """Each plugin's transform is called once with the intent object."""
        intent = _make_intent_match()
        p = _make_mock_plugin("p", priority=50)
        p.transform.return_value = intent
        svc = _make_intent_service(plugins=[p])
        svc.transform(intent)
        p.transform.assert_called_once_with(intent)

    def test_transform_returns_modified_intent(self):
        """A legitimate capture enrichment (same identity) is passed along.

        OVOS-TRANSFORM-1 §3.4 permits enriching ``Match.captures`` /
        ``match_data`` while keeping the dispatch identity (match_type/skill_id)
        unchanged.
        """
        original = IntentHandlerMatch(match_type="test:intent", match_data={},
                                      skill_id="skillA", utterance="hello")
        enriched = IntentHandlerMatch(match_type="test:intent",
                                      match_data={"slot": "value"},
                                      skill_id="skillA", utterance="hello")
        p = _make_mock_plugin("p", priority=50)
        p.transform.return_value = enriched
        svc = _make_intent_service(plugins=[p])
        result = svc.transform(original)
        self.assertEqual(result.match_data.get("slot"), "value")

    def test_transform_identity_change_rejected(self):
        """OVOS-TRANSFORM-1 §3.4: a transformer changing match_type or
        skill_id is rejected; the prior Match is kept."""
        original = IntentHandlerMatch(match_type="original:intent",
                                      match_data={}, skill_id="skillA",
                                      utterance="hello")
        modified = IntentHandlerMatch(match_type="modified:intent",
                                      match_data={}, skill_id="skillA",
                                      utterance="hello")
        p = _make_mock_plugin("p", priority=50)
        p.transform.return_value = modified
        svc = _make_intent_service(plugins=[p])
        result = svc.transform(original)
        self.assertEqual(result.match_type, "original:intent")

    def test_transform_exception_is_swallowed(self):
        """A plugin exception is caught and processing continues."""
        intent = _make_intent_match()
        p = _make_mock_plugin("bad", priority=50)
        p.transform.side_effect = RuntimeError("fail")
        svc = _make_intent_service(plugins=[p])
        # Should not raise; returns last known intent
        result = svc.transform(intent)
        self.assertIsNotNone(result)

    def test_transform_returns_unchanged_when_no_plugins(self):
        """With no plugins the original intent is returned."""
        svc = _make_intent_service(plugins=[])
        intent = _make_intent_match("test:intent")
        result = svc.transform(intent)
        self.assertEqual(result.match_type, "test:intent")

    def test_plugins_sorted_by_priority_ascending(self):
        """OVOS-TRANSFORM §4: lower priority number runs first."""
        call_order = []
        intent = _make_intent_match()

        low = _make_mock_plugin("low", priority=10)
        low.transform.side_effect = lambda i: call_order.append("low") or i
        high = _make_mock_plugin("high", priority=90)
        high.transform.side_effect = lambda i: call_order.append("high") or i

        svc = _make_intent_service(plugins=[low, high])
        svc.transform(intent)
        self.assertEqual(call_order[0], "low")

    def test_shutdown_calls_plugin_shutdown(self):
        """shutdown() calls shutdown on each loaded plugin."""
        p = _make_mock_plugin("p")
        svc = _make_intent_service(plugins=[p])
        svc.shutdown()
        p.shutdown.assert_called_once()

    def test_shutdown_ignores_plugin_exception(self):
        """An exception during plugin shutdown does not propagate."""
        p = _make_mock_plugin("p")
        p.shutdown.side_effect = Exception("bad")
        svc = _make_intent_service(plugins=[p])
        svc.shutdown()  # should not raise

    def test_plugin_loaded_and_bound_to_bus(self):
        """A loaded intent plugin has bind() called with the bus."""
        mock_instance = _make_mock_plugin("plug")
        mock_cls = MagicMock(return_value=mock_instance)
        config_core = {"intent_transformers": {"plug": {"active": True}}}
        bus = FakeBus()
        with patch("ovos_core.transformers.find_intent_transformer_plugins",
                   return_value={"plug": mock_cls}), \
             patch("ovos_core.transformers.Configuration", return_value=config_core):
            svc = IntentTransformersService(bus)
        mock_instance.bind.assert_called_once_with(bus)

    def test_plugin_skipped_when_active_false(self):
        """A plugin with active=False is not loaded."""
        mock_cls = MagicMock()
        cfg = {"plug": {"active": False}}
        with patch("ovos_core.transformers.find_intent_transformer_plugins",
                   return_value={"plug": mock_cls}), \
             patch("ovos_core.transformers.Configuration", return_value=cfg):
            svc = IntentTransformersService(FakeBus(), config=cfg)
        self.assertNotIn("plug", svc.loaded_plugins)

    def test_plugin_load_exception_is_swallowed(self):
        """An exception during plugin init is logged and not re-raised."""
        def bad_init():
            raise RuntimeError("boom")

        cfg = {"bad_plug": {"active": True}}
        with patch("ovos_core.transformers.find_intent_transformer_plugins",
                   return_value={"bad_plug": bad_init}), \
             patch("ovos_core.transformers.Configuration", return_value=cfg):
            svc = IntentTransformersService(FakeBus(), config=cfg)
        self.assertNotIn("bad_plug", svc.loaded_plugins)

    def test_find_plugins_returns_items(self):
        """find_plugins delegates to find_intent_transformer_plugins().items()."""
        with patch("ovos_core.transformers.find_intent_transformer_plugins",
                   return_value={"a": MagicMock()}) as mock_find:
            result = list(IntentTransformersService.find_plugins())
        self.assertEqual(len(result), 1)


if __name__ == "__main__":
    unittest.main()
