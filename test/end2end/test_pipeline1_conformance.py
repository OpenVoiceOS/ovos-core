"""OVOS-PIPELINE-1 conformance suite.

Encodes the normative *Conformance* clauses (§11) and the message-shape rules
of OVOS-PIPELINE-1 (``ovos/org/architecture/ovos-pipeline-1.md``) as ovoscope
end-to-end assertions against the ovos-core orchestrator.

Each test class maps to one spec section; each method docstring quotes the
MUST/SHOULD clause it checks. Drivers and the xfail discipline are described in
``_conformance.py``.

During the transition both the legacy and the spec topic names are emitted, so
every clause below is now green.

Coverage map (clause -> status against current ovos-core):
- §5.1 effective-pipeline ordering / unknown-id skip ............ green
- §5.3 blacklisted_skills orchestrator backstop ................. green
- §6.4 every utterance terminates with the end-marker .......... green
- §6.4 cancelled utterance emits ``ovos.utterance.cancelled`` .. green
- §7   dispatch on ``<skill_id>:<intent_name>`` ................ green
- §7.1 ``context.skill_id`` stamped on dispatch ................ green
- §7.1 ``context.pipeline_id`` stamped on dispatch ............. green
- §8   handler-lifecycle trio ``ovos.intent.handler.*`` ........ green (alongside legacy)
- §8.1 raising handler emits ``ovos.intent.handler.error`` ..... green (workshop)
- §9.1 entry topic ``ovos.utterance.handle`` ................... green (alongside legacy)
- §9.2 ``ovos.intent.matched`` notification .................... green
- §9.3 ``ovos.intent.unmatched`` on no-match ................... green (alongside legacy)
- §9.5 exactly one ``ovos.utterance.handled`` per utterance .... green
- §9.6 response on ``ovos.utterance.speak`` .................... green (alongside legacy)
"""
import time
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_utils.log import LOG
from ovos_workshop.skills.ovos import OVOSSkill

from ovoscope import get_minicroft, register_padatious_intent

# §8 (handler trio) and §9.6 (speak) are emitted by ovos-workshop. When an
# ovos-workshop without the spec dual-emit is installed (e.g. before it is
# released), those two tests skip cleanly instead of failing — they pass once
# the workshop side is present.
_WORKSHOP_HAS_SPEC_TOPICS = hasattr(OVOSSkill, "_intent_handler_data")
_requires_spec_workshop = pytest.mark.skipif(
    not _WORKSHOP_HAS_SPEC_TOPICS,
    reason="ovos-workshop spec bus-message dual-emit not installed",
)

from ._conformance import (
    PADACIOSO_HIGH,
    STOP_HIGH,
    capture,
    first,
    reset_namespace,
    types,
    use_spec_namespace,
    utterance,
)

SKILL_ID = "ovos-conformance-echo.test"
GREET_INTENT = "conformance.skill:greet"
GREET_SKILL_ID, GREET_NAME = GREET_INTENT.split(":")
GREET_SAMPLES = ["hello", "hi", "hey", "greetings", "good morning"]


BOOM_INTENT = "conformance.skill:boom"
BOOM_SKILL_ID, BOOM_NAME = BOOM_INTENT.split(":")
BOOM_SAMPLES = ["detonate the test", "make it explode", "boom now please"]


class _EchoSkill(OVOSSkill):
    """Intent-style handler: registered with the handler-lifecycle prefix so the
    §8 trio fires, and speaking so the §9.6 response topic fires.

    Also registers a handler on the pipeline dispatch topic ``BOOM_INTENT`` that
    raises, so the §8.1 error path (``ovos.intent.handler.error``) can be driven
    through a real utterance that reaches the orchestrator's end-marker.
    """

    def initialize(self):
        self.add_event("conformance.echo", self.handle_echo,
                       handler_info="mycroft.skill.handler", is_intent=True)
        # dispatch topic for a padatious-matched, raising handler
        self.add_event(BOOM_INTENT, self.handle_boom,
                       handler_info="mycroft.skill.handler", is_intent=True)

    def handle_echo(self, message: Message):
        self.speak(message.data.get("text", "echo"))

    def handle_boom(self, message: Message):
        raise RuntimeError("conformance: deliberate handler failure (§8.1)")


_MC = None


def setUpModule():
    global _MC
    LOG.set_level("CRITICAL")
    use_spec_namespace()  # assert the ovos.* spec topics
    _MC = get_minicroft([SKILL_ID], extra_skills={SKILL_ID: _EchoSkill})
    register_padatious_intent(_MC.bus, GREET_INTENT, GREET_SAMPLES)
    register_padatious_intent(_MC.bus, BOOM_INTENT, BOOM_SAMPLES)
    time.sleep(2)


def tearDownModule():
    if _MC is not None:
        _MC.stop()
    reset_namespace()


# ─────────────────────────────────────────────────────────────────────────────
# §5 — Effective pipeline: preference, availability, policy
# ─────────────────────────────────────────────────────────────────────────────

class TestSec5EffectivePipeline(TestCase):
    """§5.1 / §6.2: the orchestrator iterates ``session.pipeline`` in order and
    skips unknown ``pipeline_id``s without aborting the utterance."""

    def test_known_stage_matches(self):
        """A loaded stage in ``session.pipeline`` matches and dispatches (§5.1)."""
        recs = capture(_MC, utterance("hello", "p1-known", [PADACIOSO_HIGH]), 3.0)
        self.assertIn(GREET_INTENT, types(recs))

    def test_unknown_stage_is_skipped_not_aborted(self):
        """An unknown ``pipeline_id`` is skipped; the remaining known stage still
        matches — the orchestrator MUST NOT abort over an unknown id (§5.1)."""
        recs = capture(
            _MC,
            utterance("hello", "p1-unknown", ["no-such-stage-xyz", PADACIOSO_HIGH]),
            3.0,
        )
        self.assertIn(GREET_INTENT, types(recs))


class TestSec53BlacklistBackstop(TestCase):
    """§5.3: a pipeline plugin SHOULD-not and the orchestrator MUST backstop —
    a match whose ``skill_id`` is in ``session.blacklisted_skills`` is treated as
    if the plugin had declined."""

    def test_blacklisted_skill_suppresses_match(self):
        """With the matching skill blacklisted, the utterance falls through to a
        terminal no-match — its dispatch topic is never emitted (§5.3)."""
        recs = capture(
            _MC,
            utterance("hello", "p1-bl", [PADACIOSO_HIGH],
                      blacklisted_skills=[GREET_SKILL_ID]),
            4.0,
        )
        self.assertNotIn(GREET_INTENT, types(recs))
        self.assertIn("ovos.utterance.handled", types(recs))


# ─────────────────────────────────────────────────────────────────────────────
# §6.4 / §9.5 — Terminal events and the universal end-marker
# ─────────────────────────────────────────────────────────────────────────────

class TestSec95EndMarker(TestCase):
    """§9.5: a conformant orchestrator MUST emit exactly one
    ``ovos.utterance.handled`` per entry-topic Message, on every terminal path."""

    def test_exactly_one_handled_on_no_match(self):
        """No-match path terminates with exactly one end-marker (§6.4, §9.5)."""
        recs = capture(_MC, utterance("zxqw blah blah", "p1-eof-nm", [PADACIOSO_HIGH]), 4.0)
        self.assertEqual(types(recs).count("ovos.utterance.handled"), 1)

    def test_exactly_one_handled_on_stop(self):
        """Stop (global) path terminates with exactly one end-marker (§6.4, §9.5)."""
        recs = capture(_MC, utterance("stop", "p1-eof-stop", [STOP_HIGH]), 4.0)
        self.assertEqual(types(recs).count("ovos.utterance.handled"), 1)


# ─────────────────────────────────────────────────────────────────────────────
# §7 — Dispatch
# ─────────────────────────────────────────────────────────────────────────────

class TestSec7Dispatch(TestCase):
    """§7 / §7.1: dispatch is emitted on ``<skill_id>:<intent_name>`` with the
    candidate utterance forwarded verbatim and ``context.skill_id`` stamped."""

    def _dispatch(self):
        recs = capture(_MC, utterance("hello", "p1-dispatch", [PADACIOSO_HIGH]), 3.0)
        msg = first(recs, GREET_INTENT)
        self.assertIsNotNone(msg, f"no dispatch on {GREET_INTENT}")
        return msg

    def test_dispatch_topic_shape(self):
        """The dispatch topic is exactly ``<Match.skill_id>:<Match.intent_name>`` (§7)."""
        msg = self._dispatch()
        self.assertEqual(msg.msg_type, f"{GREET_SKILL_ID}:{GREET_NAME}")

    def test_utterance_forwarded_verbatim(self):
        """``data.utterance`` is the winning candidate string, verbatim (§7.1)."""
        self.assertEqual(self._dispatch().data.get("utterance"), "hello")

    def test_skill_id_stamped(self):
        """The orchestrator MUST stamp ``context['skill_id']`` on every dispatch (§7.1)."""
        self.assertEqual(self._dispatch().context.get("skill_id"), GREET_SKILL_ID)

    def test_pipeline_id_stamped(self):
        """The orchestrator MUST stamp ``context['pipeline_id']`` on dispatch (§7.1)."""
        self.assertTrue(self._dispatch().context.get("pipeline_id"))


# ─────────────────────────────────────────────────────────────────────────────
# §8 — Handler-lifecycle trio
# ─────────────────────────────────────────────────────────────────────────────

class TestSec8HandlerTrio(TestCase):
    """§8.1: for each accepted dispatch the orchestrator MUST emit
    ``ovos.intent.handler.start`` then exactly one of
    ``ovos.intent.handler.complete`` / ``.error``."""

    @_requires_spec_workshop
    def test_handler_trio_topics(self):
        """A handler invocation is wrapped by ``ovos.intent.handler.start`` and
        exactly one ``ovos.intent.handler.complete`` (§8.1)."""
        recs = capture(_MC, Message("conformance.echo", {"text": "hi"}), 3.0)
        seq = types(recs)
        self.assertIn("ovos.intent.handler.start", seq)
        self.assertEqual(seq.count("ovos.intent.handler.complete"), 1)


# ─────────────────────────────────────────────────────────────────────────────
# §9 — Utterance-layer message names
# ─────────────────────────────────────────────────────────────────────────────

class TestSec91Entry(TestCase):
    """§9.1: the orchestrator subscribes to the entry topic
    ``ovos.utterance.handle``."""

    def test_entry_topic_consumed(self):
        """An utterance fed on ``ovos.utterance.handle`` is run through the
        lifecycle and reaches the end-marker (§9.1)."""
        entry = Message("ovos.utterance.handle",
                        {"utterances": ["zxqw blah blah"], "lang": "en-US"},
                        {"source": "A", "destination": "B"})
        recs = capture(_MC, entry, 4.0)
        self.assertIn("ovos.utterance.handled", types(recs))


class TestSec92Matched(TestCase):
    """§9.2: the orchestrator emits ``ovos.intent.matched`` on every successful
    claim, before the dispatch."""

    def test_matched_notification_emitted(self):
        """A successful match emits the ``ovos.intent.matched`` notification (§9.2)."""
        recs = capture(_MC, utterance("hello", "p1-matched", [PADACIOSO_HIGH]), 3.0)
        self.assertIn("ovos.intent.matched", types(recs))


class TestSec93Unmatched(TestCase):
    """§9.3: when pipeline iteration completes with no plugin claiming, the
    orchestrator emits ``ovos.intent.unmatched``, followed by the end-marker."""

    def test_unmatched_topic_emitted(self):
        """No-match emits ``ovos.intent.unmatched`` before ``ovos.utterance.handled`` (§9.3)."""
        recs = capture(_MC, utterance("zxqw blah blah", "p1-unmatched", [PADACIOSO_HIGH]), 4.0)
        self.assertIn("ovos.intent.unmatched", types(recs))


class TestSec96Speak(TestCase):
    """§9.6: a handler delivers a natural-language response on
    ``ovos.utterance.speak``."""

    @_requires_spec_workshop
    def test_speak_topic(self):
        """A speaking handler emits on ``ovos.utterance.speak`` (§9.6)."""
        recs = capture(_MC, Message("conformance.echo", {"text": "hello there"}), 3.0)
        self.assertIn("ovos.utterance.speak", types(recs))


# ─────────────────────────────────────────────────────────────────────────────
# §6.4 — Cancelled utterance terminal path
# ─────────────────────────────────────────────────────────────────────────────

class TestSec64Cancelled(TestCase):
    """§6.4: an utterance flagged ``context['canceled']`` (e.g. by a cancel-word
    utterance transformer) is a terminal path — the orchestrator emits
    ``ovos.utterance.cancelled`` and exactly one end-marker, with no dispatch."""

    def _cancelled_entry(self, session_id: str) -> Message:
        msg = utterance("hello", session_id, [PADACIOSO_HIGH])
        msg.context["canceled"] = True
        msg.context["cancel_word"] = "nevermind"
        return msg

    def test_cancelled_topic_emitted(self):
        """A cancelled utterance emits ``ovos.utterance.cancelled`` (§6.4)."""
        recs = capture(_MC, self._cancelled_entry("p1-cancel"), 3.0)
        self.assertIn("ovos.utterance.cancelled", types(recs))

    def test_cancelled_terminates_once(self):
        """The cancelled path terminates with exactly one end-marker (§6.4, §9.5)."""
        recs = capture(_MC, self._cancelled_entry("p1-cancel-eof"), 3.0)
        self.assertEqual(types(recs).count("ovos.utterance.handled"), 1)

    def test_cancelled_does_not_dispatch(self):
        """A cancelled utterance never reaches the matcher — no dispatch fires (§6.4)."""
        recs = capture(_MC, self._cancelled_entry("p1-cancel-nodisp"), 3.0)
        self.assertNotIn(GREET_INTENT, types(recs))


# ─────────────────────────────────────────────────────────────────────────────
# §8.1 — Handler error path
# ─────────────────────────────────────────────────────────────────────────────

class TestSec81HandlerError(TestCase):
    """§8.1: when an accepted handler raises, the orchestrator/handler wrapper
    emits ``ovos.intent.handler.error`` (the terminal of the lifecycle trio) and
    the utterance still terminates with exactly one ``ovos.utterance.handled``."""

    @_requires_spec_workshop
    def test_error_topic_emitted(self):
        """A raising handler emits ``ovos.intent.handler.error`` (§8.1)."""
        recs = capture(
            _MC,
            utterance("make it explode", "p1-err-topic", [PADACIOSO_HIGH]),
            4.0,
        )
        seq = types(recs)
        self.assertIn(BOOM_INTENT, seq)  # the raising handler was dispatched
        self.assertIn("ovos.intent.handler.error", seq)

    def test_error_still_terminates_once(self):
        """Despite the handler raising, the utterance terminates with exactly one
        end-marker — the error does not abort the lifecycle (§8.1, §9.5)."""
        recs = capture(
            _MC,
            utterance("make it explode", "p1-err-eof", [PADACIOSO_HIGH]),
            4.0,
        )
        self.assertEqual(types(recs).count("ovos.utterance.handled"), 1)
