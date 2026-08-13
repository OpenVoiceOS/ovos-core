"""End-to-end regression test for the response-mode-holder stop defect.

Live-confirmed chain (round 3 of PR #802's stop rewrite): a user's "stop" was
silently ignored for up to ~35s when the session's only activity was an
outstanding ``get_response`` — ovos-workshop's ``enable_response_mode`` does
NOT push an ``active_handlers`` entry, so the §4.1 candidate-selection path
saw an empty list and fell straight through to a global stop
("Emitting global stop, 0 active skills" — live log). ovos-workshop's
killable-event abort (``killable.py``) listens ONLY on ``<skill_id>.stop`` —
a topic the global broadcast never emits per-skill — so the blocked
``get_response`` thread survived until its own timeout.

This test drives the REAL ``StopService`` against a real ``FakeBus`` (its
namespace translator mirrors the spec ``<skill_id>:stop`` dispatch onto the
legacy ``<skill_id>.stop`` topic exactly as production does — no minicroft/
padatious dependency needed since the behaviour under test lives entirely in
the stop pipeline plugin's candidate selection + dispatch, not in intent
matching). A fake skill registers a killable-style ONCE listener on its own
``<skill_id>.stop`` — the same topic ovos-workshop's ``@killable_event``
decorator binds — standing in for the abort that releases a blocked
``get_response``.
"""
import time
import unittest
from threading import Event
from unittest.mock import MagicMock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.stop_service import StopService

POLL_WINDOW = 2.0  # generous relative to the ~35s get_response timeout this replaces


class TestResponseModeHolderStopE2E(unittest.TestCase):
    """A blocked get_response must be released by a generic 'stop', not
    survive until its own timeout."""

    def setUp(self):
        self.bus = FakeBus()  # translator ON by default (modernize/emit_legacy)
        self.svc = StopService(bus=self.bus, config={})
        self.addCleanup(self.svc.shutdown)

    def _fake_skill_blocked_in_get_response(self, skill_id: str):
        """Registers a killable-style ONCE listener on <skill_id>.stop —
        exactly how ovos-workshop's @killable_event decorator releases a
        blocked get_response wait — and returns the Event it sets plus a
        call counter (lifecycle-terminal-exactly-once check)."""
        released = Event()
        calls = []

        def abort(message: Message) -> None:
            calls.append(message.msg_type)
            released.set()

        self.bus.once(f"{skill_id}.stop", abort)
        return released, calls

    def test_stop_releases_blocked_get_response_with_no_active_handlers(self):
        skill_id = "test-skill.openvoiceos"
        session = Session("resp-mode-only")
        session.enable_response_mode(skill_id)  # the ONLY session activity
        self.assertEqual(session.active_skills, [])  # sanity: no active_handlers

        released, calls = self._fake_skill_blocked_in_get_response(skill_id)

        message = Message(
            "recognizer_loop:utterance",
            {"utterances": ["stop"], "lang": "en-US"},
            {"session": session.serialize()},
        )

        with unittest.mock.patch.object(
                self.svc._locale, "voc_match",
                side_effect=lambda utt, voc, lang, exact: voc == "stop"):
            match = self.svc.match_high(["stop"], "en-US", message)

        # candidate selection: targeted at the holder, NOT a global fallthrough
        self.assertEqual(match.match_type, f"{skill_id}:stop")
        self.assertEqual(match.skill_id, skill_id)

        # simulate the orchestrator's dispatch (service.py _dispatch_match):
        # message.data updated with match_data, replied on match.match_type.
        data = dict(message.data)
        data.update(match.match_data)
        reply = message.reply(match.match_type, data)
        reply.context["skill_id"] = match.skill_id
        self.bus.emit(reply)

        fired = released.wait(timeout=POLL_WINDOW)
        self.assertTrue(fired,
                        "killable-event abort must fire within the poll window "
                        "— a response-mode-only session must not fall through "
                        "to a global stop the abort never observes")
        self.assertEqual(calls, [f"{skill_id}.stop"],
                         "lifecycle terminal (the abort) must fire exactly once")

    def test_stop_releases_blocked_get_response_via_global_stop_path(self):
        """Even when the utterance escalates to an explicit global stop, the
        response-mode holder must still be released (handle_global_stop
        emits the targeted topic before the broadcast)."""
        skill_id = "test-skill.openvoiceos"
        session = Session("resp-mode-only-2")
        session.enable_response_mode(skill_id)

        released, calls = self._fake_skill_blocked_in_get_response(skill_id)

        message = Message(
            "recognizer_loop:utterance",
            {"utterances": ["stop everything"], "lang": "en-US"},
            {"session": session.serialize()},
        )

        with unittest.mock.patch.object(
                self.svc._locale, "voc_match",
                side_effect=lambda utt, voc, lang, exact: voc == "global_stop"):
            match = self.svc.match_high(["stop everything"], "en-US", message)

        self.assertEqual(match.match_type, f"{StopService.pipeline_id}:global_stop")
        self.assertEqual(match.match_data.get("response_mode_holder"), skill_id)

        data = dict(message.data)
        data.update(match.match_data)
        reply = message.reply(match.match_type, data)
        reply.context["skill_id"] = match.skill_id
        self.bus.emit(reply)

        fired = released.wait(timeout=POLL_WINDOW)
        self.assertTrue(fired,
                        "an explicit global stop must still release a "
                        "response-mode holder's blocked get_response")
        self.assertEqual(calls, [f"{skill_id}.stop"])


if __name__ == "__main__":
    unittest.main()
