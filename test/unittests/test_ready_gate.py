"""OVOS-READY-1 — an utterance that arrives before every pipeline that can
report is warm must not enter the pipeline loop at all, and must get a
short, localized "still starting" dialog plus the one terminal event it is
owed instead (OpenVoiceOS/ovos-core#1027, OpenVoiceOS/architecture#285).

"Ready" is NOT ``IntentService.status`` alone: the timeline posted on #1027
showed a misroute landing well after ``ProcessState.READY``, while
padatious was still "compiling in background, serving last compiled
state". ``PipelineWarmTracker`` is the signal that actually covers that
window."""
import unittest
from collections import defaultdict
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.dispatcher import IntentDispatcher
from ovos_core.intent_services.manifest import IntentManifest
from ovos_core.intent_services.ready_gate import (PIPELINE_WARM_STATE,
                                                  STILL_STARTING_DIALOG,
                                                  PipelineWarmTracker,
                                                  is_ready,
                                                  still_starting_dialog)
from ovos_core.intent_services.service import IntentService


def _make_service(bus, ready: bool) -> IntentService:
    svc = IntentService.__new__(IntentService)
    svc.bus = bus
    svc.config = {}
    svc.pipeline_plugins = {}
    svc._deactivations = defaultdict(list)
    svc.status = MagicMock()
    svc.status.check_ready.return_value = ready
    svc._pipeline_warm = PipelineWarmTracker(bus)

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


def _report_warm(bus, pipeline_id: str, warm: bool) -> None:
    bus.emit(Message(PIPELINE_WARM_STATE,
                     {"pipeline_id": pipeline_id, "warm": warm}))


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

    def test_process_ready_but_a_pipeline_still_cold_still_declines(self):
        """The #1027 case: process status alone said ready while padatious
        was still serving a stale compiled state."""
        svc = _make_service(self.bus, ready=True)
        _report_warm(self.bus, "ovos-padatious-pipeline-plugin", False)
        emitted = []
        with patch.object(svc.bus, "emit", side_effect=emitted.append):
            svc.handle_utterance(_utterance("yes"))

        svc.utterance_plugins.transform.assert_not_called()
        self.assertTrue(
            any(m.msg_type == "ovos.utterance.speak" for m in emitted),
            "a cold pipeline must decline even though process status "
            "alone reports ready")

    def test_ready_and_every_reporting_pipeline_warm_runs_normally(self):
        svc = _make_service(self.bus, ready=True)
        _report_warm(self.bus, "ovos-padatious-pipeline-plugin", False)
        _report_warm(self.bus, "ovos-padatious-pipeline-plugin", True)
        emitted = []
        with patch.object(svc.bus, "emit", side_effect=emitted.append):
            svc.handle_utterance(_utterance("yes"))

        svc.utterance_plugins.transform.assert_called_once()
        self.assertFalse(
            any(m.msg_type == "ovos.utterance.speak" for m in emitted),
            "every pipeline that reported is warm; no substitute reply")

    def test_a_pipeline_that_never_reports_does_not_block_readiness(self):
        """A plugin with no warm signal counts as warm -- this must never
        block on a signal that cannot exist."""
        svc = _make_service(self.bus, ready=True)
        emitted = []
        with patch.object(svc.bus, "emit", side_effect=emitted.append):
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

    def test_dialog_falls_back_to_english_for_an_unlisted_language(self):
        self.assertEqual(still_starting_dialog("zz-ZZ"),
                         STILL_STARTING_DIALOG["en"])
        self.assertEqual(still_starting_dialog(None),
                         STILL_STARTING_DIALOG["en"])

    def test_is_ready_reads_through_check_ready_without_emitting(self):
        status = MagicMock()
        status.check_ready.return_value = True
        self.assertTrue(is_ready(status))
        status.check_ready.assert_called_once_with()

    def test_warm_tracker_ignores_a_pipeline_that_never_reports(self):
        tracker = PipelineWarmTracker(self.bus)
        self.assertTrue(tracker.all_warm(), "vacuously warm until told otherwise")
        _report_warm(self.bus, "a", False)
        self.assertFalse(tracker.all_warm())
        _report_warm(self.bus, "b", True)
        self.assertFalse(tracker.all_warm(), "a is still cold")
        _report_warm(self.bus, "a", True)
        self.assertTrue(tracker.all_warm())


if __name__ == "__main__":
    unittest.main()
