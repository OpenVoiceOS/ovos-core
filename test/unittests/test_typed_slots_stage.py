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

"""OVOS-TRANSFORM-1 §3.7 typed-slots stage."""

import unittest
from collections import defaultdict
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
from ovos_plugin_manager.templates.pipeline import IntentHandlerMatch
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.dispatcher import IntentDispatcher
from ovos_core.intent_services.manifest import IntentManifest
from ovos_core.intent_services import service as service_module
from ovos_core.intent_services.service import IntentService
from ovos_core import transformers as transformers_module
from ovos_core.transformers import TypedSlotsTransformersService


def _make_plugin(name, priority=50, result=None, supported_types=frozenset(),
                 raises=False):
    """A stub typed-slots transformer recording the arguments it was given."""
    plugin = MagicMock()
    plugin.name = name
    plugin.priority = priority
    plugin.supported_types = supported_types
    if raises:
        plugin.transform.side_effect = RuntimeError("boom")
    else:
        plugin.transform.return_value = {} if result is None else result
    return plugin


def _make_typed_slots_service(plugins=None, config=None) -> TypedSlotsTransformersService:
    """Create TypedSlotsTransformersService without loading real plugins."""
    cfg = config or {}
    with patch("ovos_core.transformers.find_typed_slots_transformer_plugins",
               return_value={}), \
         patch("ovos_core.transformers.Configuration", return_value=cfg):
        svc = TypedSlotsTransformersService(FakeBus(), config=cfg)
    if plugins is not None:
        svc.loaded_plugins = {p.name: p for p in plugins}
        svc._sorted_plugins = None
    return svc


def _make_service(typed_slots=None) -> IntentService:
    """Construct IntentService without loading real pipelines or plugins."""
    bus = FakeBus()
    svc = IntentService.__new__(IntentService)
    svc.bus = bus
    svc.config = {}
    svc.pipeline_plugins = {}
    svc._deactivations = defaultdict(list)
    svc.intent_dispatcher = IntentDispatcher(bus, timeout=0)

    ut = MagicMock()
    ut.transform.side_effect = lambda utt, ctx: (utt, ctx)
    svc.utterance_plugins = ut

    mt = MagicMock()
    mt.transform.side_effect = lambda ctx: ctx
    svc.metadata_plugins = mt

    it = MagicMock()
    it.transform.side_effect = lambda intent: intent
    svc.intent_plugins = it

    svc.typed_slots_plugins = typed_slots or _make_typed_slots_service(plugins=[])
    svc.intent_manifest = IntentManifest(bus)
    svc.status = MagicMock()
    return svc


def _number_entry(surface="two", value=2, start=0):
    return {"span": [start, start + len(surface)], "surface": surface, "value": value}


# ---------------------------------------------------------------------------
# §3.7 / §4 — exactly one transformer runs, and which one
# ---------------------------------------------------------------------------

class TestSelection(unittest.TestCase):

    def test_lowest_priority_number_is_selected(self):
        first = _make_plugin("first", priority=10)
        second = _make_plugin("second", priority=20)
        svc = _make_typed_slots_service(plugins=[second, first])
        self.assertIs(svc.selected, first)

    def test_explicit_order_list_wins_over_priority(self):
        first = _make_plugin("first", priority=10)
        second = _make_plugin("second", priority=20)
        svc = _make_typed_slots_service(plugins=[first, second],
                                        config={"order": ["second", "first"]})
        self.assertIs(svc.selected, second)

    def test_only_the_selected_transformer_runs(self):
        first = _make_plugin("first", priority=10, result={"number": []})
        second = _make_plugin("second", priority=20)
        svc = _make_typed_slots_service(plugins=[first, second])
        svc.transform(["two"], frozenset({"number"}), Session("s"))
        first.transform.assert_called_once()
        second.transform.assert_not_called()

    def test_tied_priority_without_an_order_list_is_logged(self):
        first = _make_plugin("first", priority=10)
        second = _make_plugin("second", priority=10)
        svc = _make_typed_slots_service(plugins=[first, second])
        with patch.object(transformers_module.LOG, "warning") as warn:
            self.assertIsNotNone(svc.selected)
        self.assertIn("share priority", warn.call_args[0][0])

    def test_tied_priority_is_reported_once_not_once_per_utterance(self):
        svc = _make_typed_slots_service(
            plugins=[_make_plugin("first", priority=10, result={}),
                     _make_plugin("second", priority=10)])
        with patch.object(transformers_module.LOG, "warning") as warn:
            for _ in range(5):
                svc.transform(["two"], frozenset(), Session("s"))
        self.assertEqual(warn.call_count, 1)

    def test_no_plugin_loaded_computes_no_map(self):
        svc = _make_typed_slots_service(plugins=[])
        self.assertIsNone(svc.transform(["two"], frozenset(), Session("s")))


# ---------------------------------------------------------------------------
# §3.7 — the transformer's input
# ---------------------------------------------------------------------------

class TestTransformerInput(unittest.TestCase):

    def test_transformer_receives_utterances_types_and_session(self):
        plugin = _make_plugin("p", result={"number": []})
        svc = _make_typed_slots_service(plugins=[plugin])
        sess = Session("s")
        svc.transform(["two apples"], frozenset({"number"}), sess)
        plugin.transform.assert_called_once_with(
            ["two apples"], frozenset({"number"}), sess)

    def test_empty_declared_set_still_calls_the_transformer(self):
        """§3.7 hands the transformer the declared set whatever it holds; what
        to compute from it is the transformer's decision, not the
        orchestrator's."""
        plugin = _make_plugin("p", supported_types=frozenset({"number"}),
                              result={"number": []})
        svc = _make_typed_slots_service(plugins=[plugin])
        svc.transform(["hello"], frozenset(), Session("s"))
        plugin.transform.assert_called_once_with(["hello"], frozenset(), Session("s"))

    def test_a_transformer_computing_every_registered_type_is_not_second_guessed(self):
        """§3.7: a transformer MAY "compute every registered type where the
        deployment asks for that". The orchestrator must not withhold the call
        because the declared set names none of the types the plugin computes —
        that would turn "computed, found nothing" into "not computed", which
        OVOS-INTENT-1 §5.6 reads as a different answer."""
        computed = {"number": [_number_entry()]}
        plugin = _make_plugin("p", supported_types=frozenset({"number"}),
                              result=computed)
        svc = _make_typed_slots_service(plugins=[plugin])
        self.assertEqual(
            svc.transform(["two"], frozenset({"color"}), Session("s")), computed)


# ---------------------------------------------------------------------------
# §7 — a misbehaving transformer never aborts the round
# ---------------------------------------------------------------------------

class TestTransformerErrors(unittest.TestCase):

    def test_raising_transformer_yields_no_map(self):
        plugin = _make_plugin("p", raises=True)
        svc = _make_typed_slots_service(plugins=[plugin])
        self.assertIsNone(svc.transform(["two"], frozenset(), Session("s")))

    def test_wrong_shape_return_yields_no_map(self):
        plugin = _make_plugin("p", result=["not", "a", "map"])
        svc = _make_typed_slots_service(plugins=[plugin])
        self.assertIsNone(svc.transform(["two"], frozenset(), Session("s")))

    def test_a_raising_transformer_lets_the_round_continue(self):
        svc = _make_service(_make_typed_slots_service(
            plugins=[_make_plugin("p", raises=True)]))
        msg = Message("recognizer_loop:utterance", data={"utterances": ["two"]})
        svc._run_typed_slots_stage(msg, Session("s"))
        self.assertNotIn("typed_slots", msg.data)


# ---------------------------------------------------------------------------
# INTENT-4 §6.1 — the declared type set the manifest exposes
# ---------------------------------------------------------------------------

class TestDeclaredSlotTypes(unittest.TestCase):

    def setUp(self):
        self.bus = FakeBus()
        self.manifest = IntentManifest(self.bus)

    def _register(self, intent_name, **payload):
        self.bus.emit(Message("ovos.intent.register.template",
                              {"skill_id": "test.skill",
                               "intent_name": intent_name,
                               "lang": "en-US", **payload},
                              {"session": Session("default").serialize(),
                               "skill_id": "test.skill"}))

    def test_no_registrations_declare_nothing(self):
        self.assertEqual(self.manifest.declared_slot_types("default"), frozenset())

    def test_slot_types_field_is_read(self):
        self._register("timer", samples=["set a timer"],
                       slot_types={"length": "duration"})
        self.assertEqual(self.manifest.declared_slot_types("default"),
                         frozenset({"duration"}))

    def test_sample_prefixes_are_read(self):
        self._register("timer", samples=["set a timer for {duration:length}"])
        self.assertEqual(self.manifest.declared_slot_types("default"),
                         frozenset({"duration"}))

    def test_types_from_several_intents_are_unioned(self):
        self._register("timer", samples=["wait {duration:length}"])
        self._register("paint", samples=["paint it {color:shade}"],
                       slot_types={"count": "number"})
        self.assertEqual(self.manifest.declared_slot_types("default"),
                         frozenset({"duration", "color", "number"}))

    def test_unregistered_type_names_are_not_declarations(self):
        self._register("book", samples=["book a {hotel:place}"],
                       slot_types={"place": "hotel"})
        self.assertEqual(self.manifest.declared_slot_types("default"), frozenset())


# ---------------------------------------------------------------------------
# §3.2 / §3.7 — what happens to a map already on the entry Message
# ---------------------------------------------------------------------------

class TestProducerMap(unittest.TestCase):

    def _transformed(self, svc, msg):
        with patch("ovos_core.intent_services.service.get_message_lang",
                   return_value="en-US"):
            return svc._handle_transformers(msg)

    def test_producer_map_dropped_when_the_utterance_chain_rewrote_the_text(self):
        svc = _make_service()
        svc.utterance_plugins.transform.side_effect = lambda utt, ctx: (["rewritten"], ctx)
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["two apples"],
                            "typed_slots": {"number": [_number_entry()]}})
        self._transformed(svc, msg)
        self.assertNotIn("typed_slots", msg.data)

    def test_producer_map_dropped_when_a_plugin_rewrote_the_text_in_place(self):
        """§3.2 makes in-place mutation of the utterance list conformant, and
        an in-place plugin returns the very list it was handed, so the discard
        must compare against a snapshot of the entry text."""
        svc = _make_service()

        def _rewrite_in_place(utterances, context):
            utterances[:] = ["rewritten"]
            return utterances, context

        svc.utterance_plugins.transform.side_effect = _rewrite_in_place
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["two apples"],
                            "typed_slots": {"number": [_number_entry()]}})
        self._transformed(svc, msg)
        self.assertEqual(msg.data["utterances"], ["rewritten"])
        self.assertNotIn("typed_slots", msg.data)

    def test_producer_map_kept_when_the_utterance_chain_left_the_text_alone(self):
        svc = _make_service()
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["two apples"],
                            "typed_slots": {"number": [_number_entry()]}})
        self._transformed(svc, msg)
        self.assertIn("typed_slots", msg.data)

    def test_the_stage_replaces_a_producer_map(self):
        computed = {"duration": [{"span": [0, 3], "surface": "1 h", "value": 3600}]}
        svc = _make_service(_make_typed_slots_service(
            plugins=[_make_plugin("p", result=computed)]))
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["1 h"],
                            "typed_slots": {"number": [_number_entry()]}})
        svc._run_typed_slots_stage(msg, Session("s"))
        self.assertEqual(msg.data["typed_slots"], computed)

    def test_producer_map_is_filtered_and_carried_with_no_plugin_loaded(self):
        svc = _make_service()
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["two"],
                            "typed_slots": {"number": [_number_entry()],
                                            "hotel": [_number_entry()]}})
        svc._run_typed_slots_stage(msg, Session("s"))
        self.assertEqual(list(msg.data["typed_slots"]), ["number"])


# ---------------------------------------------------------------------------
# §3.7 — the declared set is computed for a transformer, not for its own sake
# ---------------------------------------------------------------------------

class TestDeclaredTypesAreComputedLazily(unittest.TestCase):
    """Reading the declared set walks every registered intent, so it must not
    run on an utterance no transformer will act on — the default deployment
    loads none."""

    def _stage(self, svc):
        with patch.object(svc.intent_manifest, "declared_slot_types",
                          return_value=frozenset({"number"})) as declared:
            svc._run_typed_slots_stage(
                Message("recognizer_loop:utterance", data={"utterances": ["two"]}),
                Session("s"))
        return declared.call_count

    def test_the_manifest_is_not_scanned_when_no_transformer_is_selected(self):
        self.assertEqual(self._stage(_make_service()), 0)

    def test_the_manifest_is_scanned_once_when_a_transformer_is_selected(self):
        svc = _make_service(_make_typed_slots_service(
            plugins=[_make_plugin("p", result={})]))
        self.assertEqual(self._stage(svc), 1)


# ---------------------------------------------------------------------------
# INTENT-1 §5.6 — the closed type set, and the shape of what survives
# ---------------------------------------------------------------------------

class TestClosedTypeSet(unittest.TestCase):

    def test_unregistered_key_is_dropped_and_logged(self):
        from ovos_spec_tools import intent as spec_tools_intent
        svc = _make_service(_make_typed_slots_service(plugins=[_make_plugin(
            "p", result={"number": [_number_entry()],
                         "hotel": [_number_entry()]})]))
        msg = Message("recognizer_loop:utterance", data={"utterances": ["two"]})
        with patch.object(spec_tools_intent._log, "warning") as warn:
            svc._run_typed_slots_stage(msg, Session("s"))
        self.assertEqual(list(msg.data["typed_slots"]), ["number"])
        self.assertIn("hotel", warn.call_args[0][1])

    def test_dropping_an_empty_registered_type_is_not_misreported(self):
        """A registered type with no entries is dropped by
        ``drop_unregistered_typed_slots`` itself, which already logs the
        reason; ovos-core must not additionally claim it "is not a type
        registered" — that reason is simply false for this case."""
        color_entry = {"span": [0, 3], "surface": "red",
                       "value": {"hex": "#ff0000", "name": "red"}}
        svc = _make_service(_make_typed_slots_service(plugins=[_make_plugin(
            "p", result={"number": [], "color": [color_entry]})]))
        msg = Message("recognizer_loop:utterance", data={"utterances": ["red"]})
        with patch.object(service_module.LOG, "warning") as warn:
            svc._run_typed_slots_stage(msg, Session("s"))
        for call in warn.call_args_list:
            self.assertNotIn("not a type registered", call[0][0])

    def test_empty_typed_list_is_dropped(self):
        """OVOS-INTENT-1 §5.6: a type computed with nothing of that kind
        found must be omitted, not carried with an empty list."""
        color_entry = {"span": [0, 3], "surface": "red",
                       "value": {"hex": "#ff0000", "name": "red"}}
        svc = _make_service(_make_typed_slots_service(plugins=[_make_plugin(
            "p", result={"number": [], "color": [color_entry]})]))
        msg = Message("recognizer_loop:utterance", data={"utterances": ["red"]})
        svc._run_typed_slots_stage(msg, Session("s"))
        self.assertEqual(list(msg.data["typed_slots"]), ["color"])

    def test_a_non_conformant_plugins_empty_type_carries_no_entry(self):
        """A plugin returning only an empty-list type violates §5.6's "omit
        rather than list empty" rule, but the stage still filters it: the
        map that reaches the message carries no ``date`` key."""
        svc = _make_service(_make_typed_slots_service(
            plugins=[_make_plugin("p", result={"date": []})]))
        msg = Message("recognizer_loop:utterance", data={"utterances": ["today"]})
        svc._run_typed_slots_stage(msg, Session("s"))
        self.assertNotIn("date", msg.data.get("typed_slots", {}))

    def test_drop_runs_before_validate(self):
        """Reversing the order would let an empty-list type reach
        ``validate_typed_slots`` and reject the whole map instead of just
        that type being dropped."""
        color_entry = {"span": [0, 3], "surface": "red",
                       "value": {"hex": "#ff0000", "name": "red"}}
        svc = _make_service(_make_typed_slots_service(plugins=[_make_plugin(
            "p", result={"number": [], "color": [color_entry]})]))
        msg = Message("recognizer_loop:utterance", data={"utterances": ["red"]})
        svc._run_typed_slots_stage(msg, Session("s"))
        self.assertIn("typed_slots", msg.data)
        self.assertEqual(msg.data["typed_slots"], {"color": [color_entry]})

    def test_a_malformed_map_is_dropped_rather_than_propagated(self):
        svc = _make_service(_make_typed_slots_service(plugins=[_make_plugin(
            "p", result={"number": [{"span": [0, 3], "surface": "two"}]})]))
        msg = Message("recognizer_loop:utterance", data={"utterances": ["two"]})
        svc._run_typed_slots_stage(msg, Session("s"))
        self.assertNotIn("typed_slots", msg.data)

    def test_a_non_map_producer_value_is_dropped(self):
        svc = _make_service()
        msg = Message("recognizer_loop:utterance",
                      data={"utterances": ["two"], "typed_slots": ["nope"]})
        svc._run_typed_slots_stage(msg, Session("s"))
        self.assertNotIn("typed_slots", msg.data)


# ---------------------------------------------------------------------------
# PIPELINE-1 §7.1 — the map reaches dispatch
# ---------------------------------------------------------------------------

class TestCarryToDispatch(unittest.TestCase):

    def setUp(self):
        SessionManager.sessions = {"default": Session("default")}
        SessionManager.bus = None

    tearDown = setUp

    def _round(self, svc, data):
        bus = FakeBus()
        SessionManager.connect_to_bus(bus)
        svc.bus = bus
        svc.intent_dispatcher = IntentDispatcher(bus, timeout=0)
        seen = []
        bus.on("test.skill:test_intent", seen.append)
        matched = []
        bus.on("ovos.intent.matched", matched.append)

        def _match(utts, lang, message):
            return IntentHandlerMatch(match_type="test.skill:test_intent",
                                      match_data={"skill_id": "test.skill"},
                                      skill_id="test.skill",
                                      utterance=utts[0])

        svc.get_pipeline = lambda session: [("fake", _match)]
        svc.handle_utterance(Message("recognizer_loop:utterance", data=data))
        self.assertEqual(len(seen), 1)
        return seen[0], matched[0]

    def test_computed_map_rides_the_dispatch_message(self):
        computed = {"number": [_number_entry()]}
        svc = _make_service(_make_typed_slots_service(
            plugins=[_make_plugin("p", result=computed)]))
        dispatch, _ = self._round(svc, {"utterances": ["two apples"]})
        self.assertEqual(dispatch.data["typed_slots"], computed)

    def test_producer_map_rides_the_dispatch_message_with_no_plugin_loaded(self):
        svc = _make_service()
        dispatch, _ = self._round(
            svc, {"utterances": ["two apples"],
                  "typed_slots": {"number": [_number_entry()],
                                  "hotel": [_number_entry()]}})
        self.assertEqual(dispatch.data["typed_slots"], {"number": [_number_entry()]})

    def test_no_map_means_no_key_on_the_dispatch_message(self):
        svc = _make_service()
        dispatch, _ = self._round(svc, {"utterances": ["two apples"]})
        self.assertNotIn("typed_slots", dispatch.data)

    def test_intent_matched_carries_only_the_fields_9_2_names(self):
        """PIPELINE-1 §9.2 fixes the notification payload and does not list
        ``typed_slots``; the map's home is the dispatch Message (§7.1)."""
        svc = _make_service(_make_typed_slots_service(
            plugins=[_make_plugin("p", result={"number": [_number_entry()]})]))
        _, matched = self._round(svc, {"utterances": ["two apples"]})
        self.assertEqual(set(matched.data),
                         {"skill_id", "intent_name", "lang", "utterance",
                          "slots", "pipeline_id"})


if __name__ == "__main__":
    unittest.main()
