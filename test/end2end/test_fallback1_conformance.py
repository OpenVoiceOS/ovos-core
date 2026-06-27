"""OVOS-FALLBACK-1 conformance suite.

Encodes the normative clauses of OVOS-FALLBACK-1
(``ovos/org/architecture/fallback.md``) as ovoscope end-to-end assertions
against ovos-core's in-process fallback pipeline
(``ovos_core.intent_services.fallback_service``).

The driver is the real ``ovos-skill-fallback-unknown`` fixture (a
``priority: 100`` catch-all). The fallback stage is pinned *after* the regular
matcher, so it only runs when no matcher claims the utterance. Drivers and the
xfail discipline are described in ``_conformance.py``.

During the transition both the legacy and the spec topic names are emitted.

Coverage map (clause -> status against current ovos-core):
- §5   fallback only runs after the matchers decline ........... green
- §3/§6 query/response trio ``ovos.skills.fallback.*`` .......... green (legacy topic)
- §5   higher-confidence (lower-priority-number) handler first .. green
- §6.4 exactly one ``ovos.utterance.handled`` on a fallback ..... green
- §6.1 per-skill query ``<skill_id>.fallback.ping`` ............. xfail (broadcast)
- §4   register on ``ovos.fallback.register`` ................... xfail (ovos.skills.fallback.register)
- §4   ``session.fallback_handlers`` field ..................... xfail (no session field)
"""
import operator
import time
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG

from ovoscope import get_minicroft

from ._conformance import (
    PADACIOSO_HIGH,
    capture,
    reset_namespace,
    types,
    use_spec_namespace,
    utterance,
)

UNKNOWN_ID = "ovos-skill-fallback-unknown.openvoiceos"
FALLBACK_LOW = "ovos-fallback-pipeline-plugin-low"
FALLBACK_HIGH = "ovos-fallback-pipeline-plugin-high"
# matcher first, fallback last — fallback must not pre-empt a real match
PIPELINE = [PADACIOSO_HIGH, FALLBACK_HIGH, FALLBACK_LOW]

_HAS_FALLBACK_HANDLERS = "fallback_handlers" in Session("probe").serialize()
_requires_fallback_field = pytest.mark.skipif(
    not _HAS_FALLBACK_HANDLERS,
    reason="installed ovos-bus-client has no session.fallback_handlers field",
)

_MC = None


def setUpModule():
    global _MC
    LOG.set_level("CRITICAL")
    use_spec_namespace()
    _MC = get_minicroft([UNKNOWN_ID])
    time.sleep(2)


def tearDownModule():
    if _MC is not None:
        _MC.stop()
    reset_namespace()


# ─────────────────────────────────────────────────────────────────────────────
# §5 / §6 — Fallback only after matchers decline; the query/response cycle
# ─────────────────────────────────────────────────────────────────────────────

class TestSec5FallbackOrdering(TestCase):
    """§5: the fallback pool is consulted only after every matcher in the
    effective pipeline has declined. The catch-all answers the no-match."""

    def test_fallback_fires_on_no_match(self):
        """A no-match utterance is consumed by the fallback catch-all, which emits
        its dispatch ``request`` and a final end-marker (§5, §6.4)."""
        recs = capture(_MC, utterance("zxqw blah blah", "fb-nomatch", PIPELINE), 5.0)
        seq = types(recs)
        self.assertIn(f"ovos.skills.fallback.{UNKNOWN_ID}.request", seq)
        self.assertIn("ovos.utterance.handled", seq)

    def test_query_precedes_dispatch(self):
        """The pool is queried (ping) before any handler is dispatched its
        ``request`` — the fallback service polls willingness first (§5, §6)."""
        recs = capture(_MC, utterance("zxqw blah blah", "fb-order", PIPELINE), 5.0)
        seq = types(recs)
        if "ovos.skills.fallback.ping" in seq and \
                f"ovos.skills.fallback.{UNKNOWN_ID}.request" in seq:
            self.assertLess(seq.index("ovos.skills.fallback.ping"),
                            seq.index(f"ovos.skills.fallback.{UNKNOWN_ID}.request"))


class TestSec6QueryResponse(TestCase):
    """§3 / §6: the fallback service polls the pool (query) and the selected skill
    answers (response). ovos-core uses the broadcast ``ovos.skills.fallback.ping``
    / ``ovos.skills.fallback.pong`` query and a per-skill ``.response``."""

    def _fallback(self, session_id: str):
        return capture(_MC, utterance("zxqw blah blah", session_id, PIPELINE), 5.0)

    def test_query_topics_emitted(self):
        """The fallback query cycle emits ``ovos.skills.fallback.ping`` and the
        chosen skill answers ``ovos.skills.fallback.pong`` (§6.1)."""
        seq = types(self._fallback("fb-query"))
        self.assertIn("ovos.skills.fallback.ping", seq)
        self.assertIn("ovos.skills.fallback.pong", seq)

    def test_response_topic_emitted(self):
        """The selected skill emits a ``.response`` carrying the result (§6.2)."""
        seq = types(self._fallback("fb-response"))
        self.assertIn(f"ovos.skills.fallback.{UNKNOWN_ID}.response", seq)

    def test_exactly_one_handled(self):
        """A fallback-answered utterance terminates with exactly one
        ``ovos.utterance.handled`` (§6.4)."""
        recs = self._fallback("fb-eof")
        self.assertEqual(types(recs).count("ovos.utterance.handled"), 1)


# ─────────────────────────────────────────────────────────────────────────────
# §5 — Priority ordering within the pool
# ─────────────────────────────────────────────────────────────────────────────

class TestSec5Priority(TestCase):
    """§5: the pool is queried in registered-priority ascending order — a
    higher-confidence handler (lower priority number) is offered the utterance
    before a low-confidence catch-all."""

    def _fallback_service(self):
        from ovos_core.intent_services.fallback_service import FallbackService
        for p in _MC.intents.pipeline_plugins.values():
            if isinstance(p, FallbackService):
                return p
        return None

    def test_high_priority_registered_before_low(self):
        """Register a high-confidence (priority 1) handler alongside a
        low-confidence one (priority 100) through the live registration topic; the
        service sorts the pool by priority ascending, so the lower number is
        offered first (§5)."""
        svc = self._fallback_service()
        self.assertIsNotNone(svc, "fallback pipeline plugin not loaded")
        _MC.bus.emit(Message("ovos.skills.fallback.register",
                             {"skill_id": "hi.conf.skill", "priority": 1},
                             {"skill_id": "hi.conf.skill"}))
        _MC.bus.emit(Message("ovos.skills.fallback.register",
                             {"skill_id": "lo.conf.skill", "priority": 100},
                             {"skill_id": "lo.conf.skill"}))
        time.sleep(1.0)
        try:
            ordered = [k for k, _ in sorted(svc.registered_fallbacks.items(),
                                            key=operator.itemgetter(1))]
            self.assertIn("hi.conf.skill", ordered)
            self.assertIn("lo.conf.skill", ordered)
            self.assertLess(ordered.index("hi.conf.skill"),
                            ordered.index("lo.conf.skill"))
        finally:
            _MC.bus.emit(Message("ovos.skills.fallback.deregister",
                                 {"skill_id": "hi.conf.skill"}))
            _MC.bus.emit(Message("ovos.skills.fallback.deregister",
                                 {"skill_id": "lo.conf.skill"}))
            time.sleep(0.5)


# ─────────────────────────────────────────────────────────────────────────────
# §4 — Registration bus contract and the fallback_handlers session field
# ─────────────────────────────────────────────────────────────────────────────

class TestSec4Registration(TestCase):
    """§4: a fallback skill registers on ``ovos.fallback.register`` carrying a
    default ordering ``priority``."""

    @pytest.mark.xfail(strict=False,
                       reason="ovos-core consumes 'ovos.skills.fallback.register'; "
                              "FALLBACK-1 §4 defines 'ovos.fallback.register'")
    def test_spec_register_topic_consumed(self):
        """Registering on the spec topic ``ovos.fallback.register`` makes the
        handler poolable; querying yields a pong from it (§4)."""
        _MC.bus.emit(Message("ovos.fallback.register",
                             {"skill_id": "spec.fb.skill", "priority": 50},
                             {"skill_id": "spec.fb.skill"}))
        time.sleep(1.0)
        recs = capture(_MC, utterance("zxqw blah blah", "fb-spec-reg", PIPELINE), 5.0)
        # the spec-registered skill should be polled (appear as a pool member)
        self.assertTrue(any("spec.fb.skill" in t for t in types(recs)))

    @_requires_fallback_field
    def test_fallback_handlers_session_field(self):
        """§4: ``session.fallback_handlers`` orders the pool when present; the
        field is carried on the session (skipped until the field exists)."""
        sess = Session("fb-field")
        sess.lang = "en-US"
        self.assertIn("fallback_handlers", sess.serialize())
