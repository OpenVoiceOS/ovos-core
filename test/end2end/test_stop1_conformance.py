"""OVOS-STOP-1 conformance suite.

Encodes the normative *Conformance* clauses (§9) and the bus surface (§8) of
OVOS-STOP-1 (``ovos/org/architecture/ovos-stop-1.md``) as ovoscope end-to-end
assertions against ovos-core's in-process stop pipeline
(``ovos_core.intent_services.stop_service``).

The stop pipeline is in-core and deterministic on a ``FakeBus`` — no external
matcher is needed. Drivers and the xfail discipline are described in
``_conformance.py``.

During the transition both the legacy and the spec topic names are emitted.

Coverage map (clause -> status against current ovos-core):
- §5.1 empty ``active_handlers`` triggers a global stop ......... green (terminates)
- §5.3 global stop broadcasts on ``ovos.stop`` .................. green (alongside legacy)
- §4.2 stoppability query broadcast ``ovos.stop.ping`` .......... green (alongside legacy)
- §4.2 a stoppable skill answers ``ovos.stop.pong`` ............. green
- §4.3 per-skill stop dispatched on ``<skill_id>.stop`` ......... green
- §4   stop with an active skill vs none chooses skill/global ... green
- §3.1 global-stop self-dispatch ``<id>:global_stop`` ........... xfail (stop:global)
- §2   a registration naming ``stop`` is malformed (reserved) ... xfail
"""
import time
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG

from ovoscope import get_minicroft, register_padatious_intent

from ._conformance import (ENTRY_TOPIC, STOP_HIGH, capture, reset_namespace,
                           types, use_spec_namespace, utterance)

_MC = None


def setUpModule():
    global _MC
    LOG.set_level("CRITICAL")
    use_spec_namespace()  # assert the ovos.* spec topics
    _MC = get_minicroft([])
    time.sleep(1)


def tearDownModule():
    if _MC is not None:
        _MC.stop()
    reset_namespace()


def _stop_with_active(session_id: str, active_skill: str) -> Message:
    """Entry message for ``stop`` carrying one active handler in the session."""
    sess = Session(session_id)
    sess.lang = "en-US"
    sess.pipeline = [STOP_HIGH]
    sess.activate_skill(active_skill)
    return Message(ENTRY_TOPIC,
                   {"utterances": ["stop"], "lang": "en-US"},
                   {"session": sess.serialize(), "source": "A", "destination": "B"})


# ─────────────────────────────────────────────────────────────────────────────
# §4.1 / §5.1 — Generic stop with no active handlers escalates to global stop
# ─────────────────────────────────────────────────────────────────────────────

class TestSec5GlobalStop(TestCase):
    """§4.1 step 1 / §5.1: a generic ``stop`` with empty ``active_handlers``
    returns a ``global_stop`` Match, whose handler broadcasts the universal
    stop and terminates the utterance."""

    def test_global_stop_terminates(self):
        """The global-stop path terminates with exactly one end-marker
        (§5.1; end-marker per PIPELINE-1 §9.5)."""
        recs = capture(_MC, utterance("stop", "stop-global-eof", [STOP_HIGH]), 4.0)
        self.assertEqual(types(recs).count("ovos.utterance.handled"), 1)

    def test_global_stop_broadcast_topic(self):
        """The global-stop handler MUST emit ``ovos.stop`` (§5.3)."""
        recs = capture(_MC, utterance("stop", "stop-global-bcast", [STOP_HIGH]), 4.0)
        self.assertIn("ovos.stop", types(recs))

    @pytest.mark.xfail(strict=False,
                       reason="ovos-core self-dispatches the legacy 'stop:global'; "
                              "STOP-1 §3.1/§5.2 use '<stop_plugin_id>:global_stop'")
    def test_global_stop_dispatch_topic(self):
        """Global stop is dispatched on ``<stop_plugin_id>:global_stop`` (§3.1, §5.2)."""
        recs = capture(_MC, utterance("stop", "stop-global-disp", [STOP_HIGH]), 4.0)
        self.assertTrue(any(t.endswith(":global_stop") for t in types(recs)))


# ─────────────────────────────────────────────────────────────────────────────
# §4.2 — Stoppability discovery (ping/pong)
# ─────────────────────────────────────────────────────────────────────────────

class TestSec42PingPong(TestCase):
    """§4.1 step 2 / §4.2: with active handlers present, the stop plugin emits a
    broadcast ``ovos.stop.ping`` and collects ``ovos.stop.pong`` responses."""

    def test_ping_broadcast_topic(self):
        """The stoppability query is the broadcast topic ``ovos.stop.ping`` (§4.2)."""
        recs = capture(_MC, _stop_with_active("stop-ping", "fake.skill"), 4.0)
        self.assertIn("ovos.stop.ping", types(recs))

    def test_pong_reply_from_active_skill(self):
        """An active, stoppable skill answers the ping with ``ovos.stop.pong``
        carrying ``{skill_id, can_handle: True}``; that pong is collected and the
        skill is told to stop (§4.2)."""
        skill_id = "stoppable.test"

        def _responder(msg):
            # mimic a ConversationalSkill/stoppable skill answering the broadcast
            _MC.bus.emit(msg.reply("ovos.stop.pong",
                                   {"skill_id": skill_id, "can_handle": True}))

        _MC.bus.on("ovos.stop.ping", _responder)
        try:
            recs = capture(_MC, _stop_with_active("stop-pong", skill_id), 4.0)
        finally:
            _MC.bus.remove("ovos.stop.ping", _responder)
        seq = types(recs)
        self.assertIn("ovos.stop.pong", seq)
        # the collected, stoppable skill is dispatched its per-skill stop (§4.3)
        self.assertIn(f"{skill_id}.stop", seq)


# ─────────────────────────────────────────────────────────────────────────────
# §4.3 / §4 — Per-skill stop dispatch and active-vs-none selection
# ─────────────────────────────────────────────────────────────────────────────

class TestSec43PerSkillStop(TestCase):
    """§4.1 step 3 / §4.3: once a stoppable skill is selected, the stop plugin
    dispatches a targeted stop on ``<skill_id>.stop`` (not the universal
    broadcast). With at least one active skill, a generic ``stop`` is per-skill,
    not global."""

    def test_per_skill_stop_topic(self):
        """With an active skill, ``stop`` dispatches ``<skill_id>.stop`` (§4.3)."""
        recs = capture(_MC, _stop_with_active("stop-perskill", "fake.skill"), 4.0)
        self.assertIn("fake.skill.stop", types(recs))

    def test_active_skill_does_not_global_stop(self):
        """A generic ``stop`` with an active skill targets that skill — the
        universal ``ovos.stop`` broadcast is NOT emitted (§4 step ordering)."""
        recs = capture(_MC, _stop_with_active("stop-noglobal", "fake.skill"), 4.0)
        seq = types(recs)
        self.assertIn("fake.skill.stop", seq)
        self.assertNotIn("ovos.stop", seq)

    def test_no_active_skill_goes_global(self):
        """A generic ``stop`` with no active skill escalates to the global stop
        broadcast ``ovos.stop`` (§4.1 step 1 / §5.1)."""
        recs = capture(_MC, utterance("stop", "stop-none-global", [STOP_HIGH]), 4.0)
        seq = types(recs)
        self.assertIn("ovos.stop", seq)
        self.assertFalse(any(t.endswith(".stop") and t != "ovos.stop"
                             and t != "mycroft.stop" for t in seq),
                         "no per-skill stop should fire when no skill is active")


# ─────────────────────────────────────────────────────────────────────────────
# §2 — Reserved intent_name `stop`
# ─────────────────────────────────────────────────────────────────────────────

class TestSec2ReservedName(TestCase):
    """§2 (with INTENT-4 §5.3 / PIPELINE-1 §7.3): skills and pipelines MUST NOT
    register the reserved intent_name ``stop``; such a registration is malformed
    and must not be indexed, so it never dispatches."""

    @pytest.mark.xfail(strict=False,
                       reason="ovos-core does not reject registrations naming the "
                              "reserved 'stop'; STOP-1 §2 / INTENT-4 §5.3 MUST")
    def test_reserved_stop_registration_not_dispatched(self):
        """A registered intent named ``stop`` must not become matchable (§2)."""
        register_padatious_intent(_MC.bus, "rogue.skill:stop",
                                  ["please halt everything now"])
        time.sleep(1)
        from ._conformance import PADACIOSO_HIGH
        recs = capture(_MC,
                       utterance("please halt everything now", "stop-reserved",
                                 [PADACIOSO_HIGH]),
                       3.0)
        self.assertNotIn("rogue.skill:stop", types(recs))
