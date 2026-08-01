"""Loud guard for the intent-topic legacy RE-EMIT contract (send side).

Relocated from ``ovoscope#127`` at the maintainer's request: ovoscope is the
test-harness library, not the stack, and a stack contract has to be pinned
where the stack lives. ``test_intent_alias_backcompat.py`` in this same
directory already pins the *registration* half of the migration (a legacy
``.intent``-suffixed id still resolves at match/blacklist time, and — per
ovos-workshop#497 — a legacy-registered handler still fires). This module
pins the other half: the bus-level RE-EMIT of the suffixed twin when a
CANONICAL intent is dispatched, for an old containerized skill that only
ever subscribed on the bus (never registered through this core), so it
never appears in any alias registry.

That re-emit is NOT implemented yet anywhere in the stack. It needs, in
order:

* ``ovos-spec-tools#88`` — ``legacy_reemit_targets`` / ``IntentAliasRegistry``
  (see ``ovos_spec_tools.intent_topics``, already vendored unreleased) wired
  into the bus/core dispatch path, gated by an ``emit_legacy`` config knob;
* ``bus-client#271`` — the client-side hook the wiring above needs;
* ``ovos-utils#411`` — ``FakeBus`` support for the same hook, so this test
  can exercise it at all without a live MQ.

Every assertion that needs that train is marked
``@pytest.mark.xfail(strict=True, ...)`` so:

* the suite is green right now (the missing behavior is an *expected*
  failure), and
* the moment the train lands, the assertion starts passing, ``strict=True``
  turns that XPASS into a hard failure, and that loud failure is the signal
  to drop the xfail marker and promote the test into a permanent compat
  guard for the contract it pins.

The positive/negative pair uses a real ``MiniCroft`` boot (matching the
``End2EndTest`` style of the sibling module) so the guard exercises the
actual bus dispatch path, not a mock of it.
"""
import time
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus
from ovos_utils.log import LOG
from ovos_workshop.skills.ovos import OVOSSkill

from ovoscope import get_minicroft

_XFAIL_REASON = ("pending intent-topic compat train: spec-tools#88 + "
                 "bus-client#271 + ovos-utils#411")

SKILL_ID = "ovos-core-intent-legacy-reemit-guard.test"
INTENT_NAME = "LegacyReemit"
CANONICAL_TOPIC = f"{SKILL_ID}:{INTENT_NAME}"
LEGACY_TOPIC = f"{CANONICAL_TOPIC}.intent"


class _LegacyBusOnlySkill(OVOSSkill):
    """Stand-in for an old, un-migrated containerized skill: it never
    registers through this core at all, it just subscribes directly to the
    legacy suffixed bus topic the way a pre-INTENT-4 workshop dispatched.
    Wired with ``add_event`` (skipping the padatious resource file) so the
    fixture stays a MiniCroft boot, not a full skill-resource fixture."""

    def initialize(self):
        self.add_event(LEGACY_TOPIC, self.handle_legacy,
                       'mycroft.skill.handler', activation=True,
                       is_intent=True)

    def handle_legacy(self, message: Message):
        pass


def _enable_emit_legacy():
    """Best-effort toggle for the (not-yet-existing) ``emit_legacy`` compat
    knob. Until the compat train ships this is a no-op — the re-emitted twin
    below simply never appears, which is exactly what the xfail below pins."""
    try:
        from ovos_config.config import Configuration
        Configuration().setdefault("intent_topic_compat", {})["emit_legacy"] = True
    except Exception:
        pass


def _disable_emit_legacy():
    try:
        from ovos_config.config import Configuration
        Configuration().setdefault("intent_topic_compat", {})["emit_legacy"] = False
    except Exception:
        pass


class TestIntentLegacyReemitGuard(TestCase):
    """One MiniCroft boot, shared by all methods — a legacy bus-only
    consumer skill is loaded once and each test observes the bus around a
    canonical dispatch."""

    @classmethod
    def setUpClass(cls):
        LOG.set_level("ERROR")
        cls.mc = get_minicroft([SKILL_ID],
                               extra_skills={SKILL_ID: _LegacyBusOnlySkill})

    @classmethod
    def tearDownClass(cls):
        cls.mc.stop()
        LOG.set_level("CRITICAL")

    def test_direct_legacy_dispatch_still_fires_the_handler(self):
        """Positive control: today's plumbing already delivers a message
        emitted straight onto the suffixed topic to a legacy consumer
        listening on it — no compat train needed for this, it is the plain
        current bus wiring, unrelated to re-emission."""
        hits = []
        self.mc.bus.on(LEGACY_TOPIC, hits.append)
        try:
            self.mc.bus.emit(Message(LEGACY_TOPIC, {"food": "tacos"}))
            time.sleep(0.3)
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0].data, {"food": "tacos"})
        finally:
            self.mc.bus.remove(LEGACY_TOPIC, hits.append)

    @pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
    def test_legacy_twin_reemitted_when_compat_enabled(self):
        """A canonical dispatch must re-emit the suffixed ``.intent`` twin
        for the still-listening legacy consumer, carrying identical data
        and context, exactly once."""
        _enable_emit_legacy()
        twin_hits = []
        self.mc.bus.on(LEGACY_TOPIC, twin_hits.append)
        try:
            msg = Message(CANONICAL_TOPIC, {"food": "tacos"},
                         {"session": "legacy-twin-session"})
            self.mc.bus.emit(msg)
            time.sleep(0.5)
            self.assertEqual(len(twin_hits), 1,
                             f"expected exactly one re-emitted legacy twin "
                             f"on {LEGACY_TOPIC!r}, got {len(twin_hits)}")
            self.assertEqual(twin_hits[0].data, msg.data)
            self.assertEqual(twin_hits[0].context.get("session"),
                             "legacy-twin-session")
        finally:
            self.mc.bus.remove(LEGACY_TOPIC, twin_hits.append)
            _disable_emit_legacy()

    def test_no_twin_when_compat_disabled(self):
        """Paired negative control for the case above: with the compat knob
        off (its default — nothing implements the re-emit yet), only the
        canonical topic is observed. The canonical listener firing is the
        positive control proving the dispatch actually happened; the
        suffixed twin must NOT appear."""
        _disable_emit_legacy()
        canonical_hits = []
        twin_hits = []
        self.mc.bus.on(CANONICAL_TOPIC, canonical_hits.append)
        self.mc.bus.on(LEGACY_TOPIC, twin_hits.append)
        try:
            msg = Message(CANONICAL_TOPIC, {"food": "burritos"})
            self.mc.bus.emit(msg)
            time.sleep(0.3)
            self.assertEqual(len(canonical_hits), 1,
                             "canonical dispatch did not arrive")
            self.assertEqual(twin_hits, [],
                             "a legacy .intent twin was emitted even though "
                             "compat is off")
        finally:
            self.mc.bus.remove(CANONICAL_TOPIC, canonical_hits.append)
            self.mc.bus.remove(LEGACY_TOPIC, twin_hits.append)

    @pytest.mark.xfail(strict=True, reason=_XFAIL_REASON)
    def test_fakebus_supports_emit_legacy_wiring(self):
        """``FakeBus`` (ovos-utils#411) must expose the same re-emit hook the
        real bus client gets from bus-client#271, so end-to-end intent-compat
        tests can run against FakeBus without a live MQ."""
        bus = FakeBus()
        twin_hits = []
        bus.on(LEGACY_TOPIC, twin_hits.append)
        try:
            bus.emit(Message(CANONICAL_TOPIC, {"x": 1}),
                    intent_topic_compat={"emit_legacy": True})
            self.assertEqual(len(twin_hits), 1)
        finally:
            bus.remove(LEGACY_TOPIC, twin_hits.append)


if __name__ == "__main__":
    import unittest
    unittest.main()
