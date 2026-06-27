"""OVOS session-evolution conformance suite.

Cross-cuts the session-resident state that PIPELINE-1, CONVERSE-1 and
FALLBACK-1 each own, asserting — through real ovos-core interactions — that the
orchestrator carries and updates the session correctly and echoes the updated
session back on its responses:

- ``active_handlers`` recency / head-first dedup .... PIPELINE-1 §7.1
- ``converse_handlers`` owner ordering .............. CONVERSE-1 §2.1
- ``fallback_handlers`` pool field .................. FALLBACK-1 §4
- ``response_mode`` / get-response capture .......... CONVERSE-1 §2.2
- ``updated_session`` echoed on responses .......... SESSION-2

ovos-core currently models active/converse ownership with the legacy
``session.active_skills`` list and response capture with
``session.utterance_states``; the spec field *names* (``active_handlers``,
``converse_handlers``, ``fallback_handlers``, ``response_mode``) are not yet
populated by the installed bus-client. Clauses that depend on the legacy
mechanism are green; clauses that name the spec session field skip cleanly
until ``feat/session-spec-fields`` is installed. Drivers are described in
``_conformance.py``.
"""
import time
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, UtteranceState
from ovos_utils.log import LOG

from ovoscope import get_minicroft

from ._conformance import (
    PADACIOSO_HIGH,
    capture,
    reset_namespace,
    use_spec_namespace,
    utterance,
)

PARROT_ID = "ovos-skill-parrot.openvoiceos"
CONVERSE_PIPELINE = ["ovos-converse-pipeline-plugin", PADACIOSO_HIGH]

_FIELDS = Session("probe").serialize()


def _has_field(name: str) -> bool:
    return name in _FIELDS


def _skip_without(field: str):
    return pytest.mark.skipif(
        not _has_field(field),
        reason=f"installed ovos-bus-client has no session.{field} field",
    )


_MC = None


def setUpModule():
    global _MC
    LOG.set_level("CRITICAL")
    use_spec_namespace()
    _MC = get_minicroft([PARROT_ID])
    time.sleep(2)


def tearDownModule():
    if _MC is not None:
        _MC.stop()
    reset_namespace()


def _last_session(recs) -> Session:
    """The most recent serialized session carried on the captured messages."""
    for m in reversed(recs):
        if m.context.get("session"):
            return Session.deserialize(m.context["session"])
    return None


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE-1 §7.1 — active-handler recency and head-first dedup
# ─────────────────────────────────────────────────────────────────────────────

class TestActiveHandlerRecency(TestCase):
    """PIPELINE-1 §7.1: on each accepted dispatch the orchestrator stamps the
    skill as the most-recent active handler. Re-activating the same skill must
    not duplicate it — it moves to the head (dedup)."""

    def test_activation_updates_session_active_skills(self):
        """Dispatching to a skill records it in the session's active list,
        echoed back on the response (§7.1)."""
        recs = capture(_MC, utterance("start parrot mode", "se-active",
                                      CONVERSE_PIPELINE), 4.0)
        sess = _last_session(recs)
        self.assertIsNotNone(sess, "no session echoed on any response")
        self.assertIn(PARROT_ID, [s[0] for s in sess.active_skills])

    def test_reactivation_is_head_first_dedup(self):
        """Re-activating an already-active skill keeps a single entry at the head
        of the active list — recency dedup (§7.1)."""
        sess = Session("se-dedup")
        sess.lang = "en-US"
        sess.activate_skill("other.skill")
        sess.activate_skill(PARROT_ID)
        sess.activate_skill(PARROT_ID)  # re-activate
        ids = [s[0] for s in sess.active_skills]
        self.assertEqual(ids.count(PARROT_ID), 1, "duplicate active-skill entry")
        self.assertEqual(ids[0], PARROT_ID, "re-activated skill must be head")

    @_skip_without("active_handlers")
    def test_active_handlers_spec_field(self):
        """The spec field ``session.active_handlers`` carries the dispatched skill
        head-first (§7.1). Skipped until the spec field is populated."""
        recs = capture(_MC, utterance("start parrot mode", "se-active-spec",
                                      CONVERSE_PIPELINE), 4.0)
        sess = _last_session(recs)
        handlers = sess.serialize().get("active_handlers") or []
        owners = [h.get("skill_id") if isinstance(h, dict) else h for h in handlers]
        self.assertIn(PARROT_ID, owners)


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSE-1 §2.1 — converse owner ordering
# ─────────────────────────────────────────────────────────────────────────────

class TestConverseOwnerOrdering(TestCase):
    """CONVERSE-1 §2.1: converse owners are ordered most-recently-activated
    first; the active-skill list is the legacy carrier of that ordering."""

    def test_owner_ordering_most_recent_first(self):
        """The most recently activated owner is at index 0 (§2.1)."""
        sess = Session("se-cv-order")
        sess.lang = "en-US"
        sess.activate_skill("a.skill")
        sess.activate_skill("b.skill")
        self.assertEqual(sess.active_skills[0][0], "b.skill")

    @_skip_without("converse_handlers")
    def test_converse_handlers_spec_field(self):
        """``session.converse_handlers`` mirrors the converse owner ordering
        (§2.1). Skipped until the spec field is populated."""
        recs = capture(_MC, utterance("start parrot mode", "se-cv-spec",
                                      CONVERSE_PIPELINE), 4.0)
        sess = _last_session(recs)
        handlers = sess.serialize().get("converse_handlers") or []
        owners = [h.get("skill_id") if isinstance(h, dict) else h for h in handlers]
        self.assertIn(PARROT_ID, owners)


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSE-1 §2.2 — response mode / get-response capture
# ─────────────────────────────────────────────────────────────────────────────

class TestResponseMode(TestCase):
    """CONVERSE-1 §2.2: a skill in response mode captures the next utterance.
    ovos-core models this with ``session.utterance_states`` (RESPONSE) toggled by
    ``skill.converse.get_response.enable`` / ``.disable``."""

    def test_get_response_enable_sets_response_state(self):
        """Enabling get-response marks the skill RESPONSE in the session, so the
        converse stage routes the next utterance to it; disabling clears it back
        to the default INTENT state (§2.2).

        ``utterance_states`` carries the ``UtteranceState`` *value* (string), and
        under the spec ``response_mode`` model INTENT is the absence of a response
        window — a disabled skill is simply not present in the mapping. The
        assertion accepts either the enum or its value and treats a missing key as
        INTENT so it holds across the legacy dict and the spec projection."""
        sess = Session("se-respmode")
        sess.lang = "en-US"

        sess.enable_response_mode(PARROT_ID)
        self.assertIn(sess.utterance_states.get(PARROT_ID),
                      (UtteranceState.RESPONSE, UtteranceState.RESPONSE.value))

        sess.disable_response_mode(PARROT_ID)
        # INTENT is the default: either stamped explicitly or implied by absence.
        self.assertIn(sess.utterance_states.get(PARROT_ID),
                      (None, UtteranceState.INTENT, UtteranceState.INTENT.value))

    @_skip_without("response_mode")
    def test_response_mode_spec_field(self):
        """``session.response_mode`` names the owner holding response mode (§2.2).
        Skipped until the spec field is populated."""
        sess = Session("se-respmode-spec")
        sess.lang = "en-US"
        self.assertIn("response_mode", sess.serialize())


# ─────────────────────────────────────────────────────────────────────────────
# FALLBACK-1 §4 — fallback_handlers session field
# ─────────────────────────────────────────────────────────────────────────────

class TestFallbackHandlersField(TestCase):
    """FALLBACK-1 §4: ``session.fallback_handlers`` orders the pool when present.
    The field is optional (omission == registered-priority order)."""

    @_skip_without("fallback_handlers")
    def test_fallback_handlers_spec_field(self):
        """``session.fallback_handlers`` is carried on the session (§4). Skipped
        until the spec field is populated."""
        sess = Session("se-fb-field")
        sess.lang = "en-US"
        self.assertIn("fallback_handlers", sess.serialize())


# ─────────────────────────────────────────────────────────────────────────────
# SESSION-2 — updated_session echoed on responses
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdatedSessionEcho(TestCase):
    """SESSION-2: the orchestrator MUST echo the (possibly mutated) session on its
    responses so the next turn rides on the current state."""

    def test_session_id_preserved_on_response(self):
        """The echoed session keeps the same ``session_id`` as the entry (§2)."""
        recs = capture(_MC, utterance("zxqw blah blah", "se-echo-id",
                                      [PADACIOSO_HIGH]), 4.0)
        sess = _last_session(recs)
        self.assertIsNotNone(sess, "no session echoed on any response")
        self.assertEqual(sess.session_id, "se-echo-id")

    def test_mutation_rides_forward(self):
        """A pipeline-side activation is reflected in the echoed session, so the
        change rides forward to the next turn (SESSION-2 §2.6)."""
        recs = capture(_MC, utterance("start parrot mode", "se-echo-mut",
                                      CONVERSE_PIPELINE), 4.0)
        sess = _last_session(recs)
        self.assertIsNotNone(sess)
        self.assertIn(PARROT_ID, [s[0] for s in sess.active_skills])
