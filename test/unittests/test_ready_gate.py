"""OVOS-READY-1 — an utterance that arrives before the orchestrator is
ready must not enter the pipeline loop at all, and must get a short,
localized "still starting" dialog plus the one terminal event it is owed
instead (OpenVoiceOS/ovos-core#1027, OpenVoiceOS/architecture#285)."""
import unittest
from collections import defaultdict
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.dispatcher import IntentDispatcher
from ovos_core.intent_services.manifest import IntentManifest
from ovos_core.intent_services.ready_gate import (STILL_STARTING_DIALOG,
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


def _utterance(utterance="yes", lang=None) -> Message:
    data = {"utterances": [utterance]}
    if lang:
        data["lang"] = lang
    return Message("recognizer_loop:utterance", data=data,
                   context={"session": {"session_id": "s1"}})


class TestReadyGate(unittest.TestCase):
    def setUp(self):
        self.bus = FakeBus()
        SessionManager.sessions.clear()
        SessionManager.reset_default_session()
        SessionManager.bus = None

    tearDown = setUp

    def test_unready_declines_with_dialog_not_the_pipeline_loop(self):
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
        self.assertEqual(len(handled), 1,
                         "the pipeline-loop terminal is still owed even "
                         "though the loop never ran")

    def test_ready_runs_the_pipeline_loop_normally(self):
        svc = _make_service(self.bus, ready=True)
        emitted = []
        with patch.object(svc.bus, "emit", side_effect=emitted.append):
            svc.handle_utterance(_utterance("yes"))

        svc.utterance_plugins.transform.assert_called_once()
        self.assertFalse(
            any(m.msg_type == "ovos.utterance.speak" for m in emitted),
            "a ready orchestrator never substitutes the decline-with-dialog")

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


if __name__ == "__main__":
    unittest.main()
