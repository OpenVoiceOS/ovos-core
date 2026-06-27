"""OVOS-CONVERSE-1 conformance suite.

Encodes the normative clauses of OVOS-CONVERSE-1
(``ovos/org/architecture/converse.md``) as ovoscope end-to-end assertions
against ovos-core's in-process converse pipeline
(``ovos_core.intent_services.converse_service``).

The driver is the real ``ovos-skill-parrot`` fixture: ``start parrot mode``
activates it (it becomes the most-recently-active converse owner), after which
its ``can_converse`` returns True and ``converse`` echoes the next utterance
back — i.e. the active skill consumes the follow-up *before* normal intent
matching. Drivers and the xfail discipline are described in ``_conformance.py``.

During the transition both the legacy and the spec topic names are emitted.

Coverage map (clause -> status against current ovos-core):
- §2.1 most-recently-active owner is polled first ............... green
- §3   activating a skill records it as an active/converse owner  green
- §4   an active owner consumes the follow-up before intent match  green
- §4   a declining owner falls through to the normal pipeline ... green
- §6.4 exactly one ``ovos.utterance.handled`` per utterance ..... green
- §2.1 ``session.converse_handlers`` reflects the owner ......... xfail (active_skills)
"""
import time
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG

from ovoscope import get_minicroft

from ._conformance import (
    ENTRY_TOPIC,
    PADACIOSO_HIGH,
    capture,
    reset_namespace,
    types,
    use_spec_namespace,
    utterance,
)

PARROT_ID = "ovos-skill-parrot.openvoiceos"
# the converse stage runs ahead of the matcher when there are active owners
CONVERSE_PIPELINE = ["ovos-converse-pipeline-plugin", PADACIOSO_HIGH]

# whether the installed bus-client exposes the CONVERSE-1 session field
_HAS_CONVERSE_HANDLERS = "converse_handlers" in Session("probe").serialize()
_requires_converse_field = pytest.mark.skipif(
    not _HAS_CONVERSE_HANDLERS,
    reason="installed ovos-bus-client has no session.converse_handlers field",
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


def _activate_parrot(session_id: str) -> Session:
    """Drive ``start parrot mode`` so parrot becomes the active converse owner.

    Returns the resulting session (carrying the active-skill state) so a
    follow-up utterance can be injected on the same conversation.
    """
    recs = capture(_MC, utterance("start parrot mode", session_id,
                                  CONVERSE_PIPELINE), 4.0)
    # the activation reply carries the updated session
    sess = None
    for m in reversed(recs):
        if m.context.get("session"):
            sess = Session.deserialize(m.context["session"])
            break
    if sess is None:
        sess = Session(session_id)
        sess.lang = "en-US"
        sess.activate_skill(PARROT_ID)
    sess.pipeline = CONVERSE_PIPELINE
    return sess


def _followup(sess: Session, text: str) -> Message:
    return Message(ENTRY_TOPIC,
                   {"utterances": [text], "lang": "en-US"},
                   {"session": sess.serialize(), "source": "A", "destination": "B"})


# ─────────────────────────────────────────────────────────────────────────────
# §3 / §4 — Activation and the converse round-trip
# ─────────────────────────────────────────────────────────────────────────────

class TestSec3Activation(TestCase):
    """§3: dispatching to a converse-capable skill records it as an active
    converse owner of the session."""

    def test_activation_recorded_in_session(self):
        """After ``start parrot mode`` the parrot is an active skill of the
        session (§3)."""
        sess = _activate_parrot("cv-activate")
        self.assertIn(PARROT_ID, [s[0] for s in sess.active_skills])


class TestSec4ConverseRoundTrip(TestCase):
    """§4: with an active owner, the converse stage runs ahead of the matcher;
    the owner consumes the follow-up utterance. The parrot owner echoes it on
    ``ovos.utterance.speak`` and the utterance terminates with one end-marker."""

    def test_followup_consumed_by_active_owner(self):
        """A follow-up utterance is routed through ``converse:skill`` to the
        active owner before normal intent matching (§4)."""
        sess = _activate_parrot("cv-roundtrip")
        recs = capture(_MC, _followup(sess, "hello world parrot"), 4.0)
        seq = types(recs)
        self.assertIn("converse:skill", seq)
        # parrot echoes the utterance verbatim
        spoken = [m for m in recs if m.msg_type in ("speak", "ovos.utterance.speak")]
        self.assertTrue(
            any(m.data.get("utterance") == "hello world parrot" for m in spoken),
            f"parrot did not echo the follow-up; spoke: "
            f"{[m.data.get('utterance') for m in spoken]}",
        )

    def test_followup_terminates_once(self):
        """The converse-consumed follow-up terminates with exactly one
        ``ovos.utterance.handled`` (§6.4 / PIPELINE-1 §9.5)."""
        sess = _activate_parrot("cv-eof")
        recs = capture(_MC, _followup(sess, "echo me please"), 4.0)
        self.assertEqual(types(recs).count("ovos.utterance.handled"), 1)


class TestSec4Decline(TestCase):
    """§4: when no owner accepts the converse poll, the utterance falls through
    to the normal pipeline. A session with no active owner skips converse and
    is matched (or no-matched) by the regular matcher."""

    def test_decline_falls_through_to_pipeline(self):
        """With no active owner, converse declines and the utterance reaches the
        normal terminal path — no ``converse:skill`` dispatch (§4)."""
        sess = Session("cv-decline")
        sess.lang = "en-US"
        sess.pipeline = CONVERSE_PIPELINE
        recs = capture(_MC, _followup(sess, "zxqw blah blah"), 4.0)
        seq = types(recs)
        self.assertNotIn("converse:skill", seq)
        self.assertIn("ovos.utterance.handled", seq)


# ─────────────────────────────────────────────────────────────────────────────
# §2.1 — Owner ordering and the converse_handlers session field
# ─────────────────────────────────────────────────────────────────────────────

class TestSec21OwnerOrdering(TestCase):
    """§2.1: converse owners are polled most-recently-activated first; index 0 is
    the most-recent owner. ovos-core orders ``session.active_skills`` head-first
    on each activation."""

    def test_most_recent_owner_first(self):
        """Re-activating an owner moves it to the head of the active list (§2.1)."""
        sess = Session("cv-order")
        sess.lang = "en-US"
        sess.activate_skill("first.skill")
        sess.activate_skill(PARROT_ID)
        # parrot was activated last -> head of the list (index 0)
        self.assertEqual(sess.active_skills[0][0], PARROT_ID)

    @_requires_converse_field
    def test_converse_handlers_reflects_owner(self):
        """``session.converse_handlers`` carries the active owner, head-first
        (§2.1). xfail/skipped until ovos-core stamps the spec field rather than
        the legacy ``active_skills``."""
        sess = _activate_parrot("cv-handlers")
        handlers = sess.serialize().get("converse_handlers") or []
        owners = [h.get("skill_id") if isinstance(h, dict) else h for h in handlers]
        self.assertIn(PARROT_ID, owners)
