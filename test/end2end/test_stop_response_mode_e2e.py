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
from ovos_spec_tools import SpecMessage
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

    def test_global_stop_releases_the_holder_via_the_ovos_stop_broadcast(self):
        """An explicit global stop releases the holder through `ovos.stop`.

        STOP-1 §5.3 gives the global-stop handler exactly one emission — "The
        handler dispatched by `<pipeline_id>:global_stop` MUST emit
        `ovos.stop`" — and makes the broadcast the universal channel: "Every
        component performing user-visible activity MUST subscribe to
        `ovos.stop` and cease activity for the `session_id` carried in Message
        context." §9 restates it as a skill MUST: subscribe to both
        `<own_skill_id>:stop` and `ovos.stop`.

        So the release path for a blocked `get_response` under a global stop
        is the skill's own `ovos.stop` subscription, not a per-skill topic
        synthesized by the stop plugin.
        """
        skill_id = "test-skill.openvoiceos"
        session = Session("resp-mode-only-2")
        session.enable_response_mode(skill_id)

        released = Event()
        seen = []
        # a §9-conformant skill: subscribed to the broadcast
        self.bus.once(SpecMessage.STOP.value,
                      lambda m: (seen.append(m.msg_type), released.set()))
        # ...and to its own targeted topic, which a global stop must NOT use
        targeted = []
        self.bus.once(f"{skill_id}.stop", lambda m: targeted.append(m.msg_type))

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
        # PIPELINE-1 §4.3: slots are string->string, so no plugin-internal
        # holder rides out on the dispatch.
        self.assertEqual(match.match_data, {})
        # §5.2: response_mode removed entirely by the Match's updated_session.
        self.assertFalse(match.updated_session.response_mode)

        data = dict(message.data)
        data.update(match.match_data)
        reply = message.reply(match.match_type, data)
        reply.context["skill_id"] = match.skill_id
        self.bus.emit(reply)

        self.assertTrue(released.wait(timeout=POLL_WINDOW),
                        "an explicit global stop must reach a blocked "
                        "get_response through the ovos.stop broadcast")
        self.assertEqual(seen, [SpecMessage.STOP.value])
        self.assertEqual(targeted, [],
                         "§5.3 permits no per-skill emission from the "
                         "global-stop handler")


if __name__ == "__main__":
    unittest.main()
