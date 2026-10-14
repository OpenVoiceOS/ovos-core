"""Utterances arriving before the service is ready get a "still starting" reply."""
import unittest
from collections import defaultdict
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.dispatcher import IntentDispatcher
from ovos_core.intent_services.manifest import IntentManifest
from ovos_core.intent_services.ready_gate import (PIPELINE_LOADED,
                                                  PIPELINE_LOADING,
                                                  STILL_STARTING_DIALOG,
                                                  LoadTracker,
                                                  still_starting_dialog)
from ovos_core.intent_services.service import IntentService


def _make_service(bus, ready: bool, skills: bool = True) -> IntentService:
    svc = IntentService.__new__(IntentService)
    svc.bus = bus
    svc.config = {}
    svc.pipeline_plugins = {}
    svc._deactivations = defaultdict(list)
    svc.status = MagicMock()
    svc.status.check_ready.return_value = ready
    svc._load_tracker = LoadTracker(bus)
    if skills:
        bus.emit(Message("mycroft.skills.initialized"))

    for attr, transform in (("utterance_plugins", lambda utt, ctx: (utt, ctx)),
                            ("metadata_plugins", lambda ctx: ctx),
                            ("intent_plugins", lambda intent: intent)):
        plugins = MagicMock()
        plugins.transform.side_effect = transform
        setattr(svc, attr, plugins)

    typed_slots = MagicMock()
    typed_slots.transform.return_value = None
    svc.typed_slots_plugins = typed_slots

    svc.disambiguate_lang = lambda m: "en-US"
    svc.intent_manifest = IntentManifest(bus)
    svc.intent_dispatcher = IntentDispatcher(
        bus, timeout=0, on_terminal=svc._emit_utterance_handled)
    svc.get_pipeline = lambda session: []
    return svc


def _utterance(utterance="yes", lang=None, session_id="s1") -> Message:
    data = {"utterances": [utterance]}
    if lang:
        data["lang"] = lang
    return Message("recognizer_loop:utterance", data=data,
                   context={"session": {"session_id": session_id}})


def _loading(bus, pipeline_id: str) -> None:
    bus.emit(Message(PIPELINE_LOADING, {"pipeline_id": pipeline_id}))


def _loaded(bus, pipeline_id: str) -> None:
    bus.emit(Message(PIPELINE_LOADED, {"pipeline_id": pipeline_id}))


class TestReadyGate(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        SessionManager.sessions.clear()
        SessionManager.reset_default_session()
        SessionManager.bus = None

    tearDown = setUp

    def test_process_unready_declines_with_dialog_not_the_pipeline_loop(self):
        svc = _make_service(self.bus, ready=False)
        emitted = []
        with patch.object(svc.bus, "emit", side_effect=emitted.append):
            svc.handle_utterance(_utterance("yes", lang="fr-FR"))

        svc.utterance_plugins.transform.assert_not_called()
        self.assertEqual(svc.intent_dispatcher._in_flight, {},
                         "nothing was dispatched while unready")

        speaks = [m for m in emitted if m.msg_type == "ovos.utterance.speak"]
        handled = [m for m in emitted if m.msg_type == "ovos.utterance.handled"]
        self.assertEqual(len(speaks), 1, "exactly one decline-with-dialog")
        self.assertEqual(speaks[0].data["utterance"],
                         STILL_STARTING_DIALOG["fr"],
                         "localized to the utterance's own language")
        self.assertEqual(speaks[0].context.get("error"), "ovos.ready.not_ready",
                         "OVOS-READY-1 §3.2: a stable identifier so a "
                         "listener knows why this was declined")
        self.assertEqual(len(handled), 1,
                         "the pipeline-loop terminal is still owed even "
                         "though the loop never ran")

    def test_status_ready_but_a_pipeline_still_loading_declines(self):
        svc = _make_service(self.bus, ready=True, skills=False)
        _loading(self.bus, "ovos-padatious-pipeline-plugin")
        self.bus.emit(Message("mycroft.skills.initialized"))
        emitted = []
        with patch.object(svc.bus, "emit", side_effect=emitted.append):
            svc.handle_utterance(_utterance("yes"))

        svc.utterance_plugins.transform.assert_not_called()
        self.assertTrue(any(m.msg_type == "ovos.utterance.speak" for m in emitted))

    def test_ready_and_every_pipeline_loaded_runs_normally(self):
        svc = _make_service(self.bus, ready=True)
        _loading(self.bus, "ovos-padatious-pipeline-plugin")
        _loaded(self.bus, "ovos-padatious-pipeline-plugin")
        emitted = []
        with patch.object(svc.bus, "emit", side_effect=emitted.append):
            svc.handle_utterance(_utterance("yes"))

        svc.utterance_plugins.transform.assert_called_once()
        self.assertFalse(any(m.msg_type == "ovos.utterance.speak" for m in emitted))

    def test_a_pipeline_that_never_reports_does_not_block(self):
        svc = _make_service(self.bus, ready=True)
        svc.handle_utterance(_utterance("yes"))
        svc.utterance_plugins.transform.assert_called_once()

    def test_decline_resolves_a_session_only_language_not_just_english(self):
        """CodeRabbit on an earlier revision of this gate: the dialog must
        go through get_message_lang's full data -> context -> session ->
        configured-default resolution, not `data`/`context` alone -- a
        French session with no explicit `lang` field must not get the
        English dialog."""
        svc = _make_service(self.bus, ready=False)
        session = Session("s2", lang="fr-FR")
        message = Message("recognizer_loop:utterance",
                          data={"utterances": ["yes"]},
                          context={"session": session.serialize()})
        emitted = []
        with patch.object(svc.bus, "emit", side_effect=emitted.append):
            svc.handle_utterance(message)

        speaks = [m for m in emitted if m.msg_type == "ovos.utterance.speak"]
        self.assertEqual(len(speaks), 1)
        self.assertEqual(speaks[0].data["utterance"], STILL_STARTING_DIALOG["fr"],
                         "the session's own language, not the English "
                         "default, when no data/context lang is given")

    def test_pipelines_loaded_but_skills_still_loading_declines(self):
        svc = _make_service(self.bus, ready=True, skills=False)
        _loading(self.bus, "ovos-padatious-pipeline-plugin")
        _loaded(self.bus, "ovos-padatious-pipeline-plugin")
        emitted = []
        with patch.object(svc.bus, "emit", side_effect=emitted.append):
            svc.handle_utterance(_utterance("yes"))
        svc.utterance_plugins.transform.assert_not_called()
        self.assertTrue(any(m.msg_type == "ovos.utterance.speak" for m in emitted))
        handled = [m for m in emitted if m.msg_type == "ovos.utterance.handled"]
        self.assertEqual(handled[0].context.get("error"), "ovos.ready.not_ready")

    def test_skills_initialized_lifts_the_gate(self):
        svc = _make_service(self.bus, ready=True, skills=False)
        self.bus.emit(Message("mycroft.skills.initialized"))
        emitted = []
        with patch.object(svc.bus, "emit", side_effect=emitted.append):
            svc.handle_utterance(_utterance("yes"))
        svc.utterance_plugins.transform.assert_called_once()

    def test_answering_never_closes_after_it_opens(self):
        tracker = LoadTracker(self.bus)
        self.assertFalse(tracker.answering)
        self.bus.emit(Message("mycroft.skills.initialized"))
        self.assertTrue(tracker.answering)
        _loading(self.bus, "a")
        self.bus.emit(Message("mycroft.skills.initialized"))
        self.assertTrue(tracker.answering)
        self.assertTrue(tracker.pipelines_loading)

    def test_answering_waits_for_a_pipeline_loading_at_skills_initialized(self):
        tracker = LoadTracker(self.bus)
        _loading(self.bus, "a")
        self.bus.emit(Message("mycroft.skills.initialized"))
        self.assertFalse(tracker.answering)
        _loaded(self.bus, "a")
        self.assertTrue(tracker.answering)

    def test_ask_skills_picks_up_a_skill_manager_that_finished_first(self):
        """An intent service that starts after the skill manager finished
        never hears mycroft.skills.initialized; the one startup query does."""
        tracker = LoadTracker(self.bus)
        asked = []
        self.bus.on("mycroft.skills.is_ready", lambda m: (
            asked.append(m), self.bus.emit(m.response(data={"status": True}))))
        tracker.ask_skills()
        self.assertEqual(len(asked), 1)
        self.assertTrue(tracker._skills_loaded)

    def test_skills_not_required_waits_for_pipelines_alone(self):
        tracker = LoadTracker(self.bus, skills_required=False)
        self.assertTrue(tracker.answering)
        tracker = LoadTracker(self.bus, skills_required=False)
        _loading(self.bus, "a")
        self.assertFalse(tracker.answering)
        _loaded(self.bus, "a")
        self.assertTrue(tracker.answering)

    def test_ask_skills_not_ready_leaves_the_latch_to_the_event(self):
        tracker = LoadTracker(self.bus)
        self.bus.on("mycroft.skills.is_ready", lambda m: self.bus.emit(
            m.response(data={"status": False})))
        tracker.ask_skills()
        self.assertFalse(tracker._skills_loaded)

    def test_output_lang_wins_over_the_input_language(self):
        """OVOS-SESSION-1 section 3.2.3: a German speaker who set
        output_lang to English hears the English dialog."""
        svc = _make_service(self.bus, ready=False)
        session = Session("s3", lang="de-DE")
        data = session.serialize()
        data["output_lang"] = "en-US"
        message = Message("recognizer_loop:utterance",
                          data={"utterances": ["yes"]},
                          context={"session": data})
        emitted = []
        with patch.object(svc.bus, "emit", side_effect=emitted.append):
            svc.handle_utterance(message)
        speaks = [m for m in emitted if m.msg_type == "ovos.utterance.speak"]
        self.assertEqual(speaks[0].data["utterance"], STILL_STARTING_DIALOG["en"])
        self.assertEqual(speaks[0].data["lang"], "en-US")

    def test_output_lang_without_a_dialog_falls_back_to_the_input_language(self):
        svc = _make_service(self.bus, ready=False)
        session = Session("s4", lang="fr-FR")
        data = session.serialize()
        data["output_lang"] = "zz-ZZ"
        message = Message("recognizer_loop:utterance",
                          data={"utterances": ["yes"]},
                          context={"session": data})
        emitted = []
        with patch.object(svc.bus, "emit", side_effect=emitted.append):
            svc.handle_utterance(message)
        speaks = [m for m in emitted if m.msg_type == "ovos.utterance.speak"]
        self.assertEqual(speaks[0].data["utterance"], STILL_STARTING_DIALOG["fr"])

    def test_no_dialog_for_an_unlisted_language(self):
        self.assertIsNone(still_starting_dialog("zz-ZZ"))
        self.assertIsNone(still_starting_dialog(None))

    def test_unlisted_language_gets_the_error_sound_not_english(self):
        """OVOS-READY-1 section 3: never a dialog in the wrong language."""
        svc = _make_service(self.bus, ready=False)
        message = Message("recognizer_loop:utterance",
                          data={"utterances": ["yes"], "lang": "zz-ZZ"})
        emitted = []
        with patch.object(svc.bus, "emit", side_effect=emitted.append):
            svc.handle_utterance(message)
        self.assertFalse(any(m.msg_type == "ovos.utterance.speak"
                             for m in emitted))
        sounds = [m for m in emitted if m.msg_type == "mycroft.audio.play_sound"]
        self.assertEqual(len(sounds), 1)
        self.assertEqual(sounds[0].data["uri"], "snd/error.mp3")
        self.assertEqual(sounds[0].context.get("error"), "ovos.ready.not_ready")
        handled = [m for m in emitted if m.msg_type == "ovos.utterance.handled"]
        self.assertEqual(len(handled), 1)
        self.assertEqual(handled[0].context.get("error"), "ovos.ready.not_ready")

    def test_status_becomes_ready_only_once_pipelines_are_loaded(self):
        svc = IntentService(self.bus, config={}, preload_pipelines=False)
        _loading(self.bus, "slow")
        svc._plugins_loaded = True
        svc._set_ready_when_loaded()
        self.assertFalse(svc.status.check_ready())
        _loaded(self.bus, "slow")
        self.assertTrue(svc.status.check_ready())

    def test_loaded_callback_fires_once_nothing_is_loading(self):
        calls = []
        LoadTracker(self.bus, on_pipelines_loaded=lambda: calls.append(1))
        _loading(self.bus, "a")
        _loading(self.bus, "b")
        _loaded(self.bus, "a")
        self.assertEqual(calls, [])
        _loaded(self.bus, "b")
        self.assertEqual(calls, [1])


if __name__ == "__main__":
    unittest.main()
