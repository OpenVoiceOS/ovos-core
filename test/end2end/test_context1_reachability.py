"""Cross-repo end-to-end reachability proof for OVOS-CONTEXT-1.

Verified defect (audit-loop wave 1): a skill calling the real
``OVOSSkill.set_context`` API (ovos-workshop) could never satisfy the
declarative ``requires_context`` / ``excludes_context`` gate
(``ovos_spec_tools.context.gate_satisfied`` / ``resolve_key``), because the
producer only ever emitted the legacy ADAPT-munged key
(``alphanumeric_skill_id + context``, no separator, sanitized) while the gate
resolves a private declaration to ``<raw_skill_id>:<key>`` (colon-separated,
unsanitized). ``"my_skillkitchen"`` never equals ``"my.skill:kitchen"``.

This test drives the REAL producer (``ovos_workshop.skills.ovos.OVOSSkill.
set_context``, installed from the sibling fix worktree) against the REAL
consumer (``ovos_core.intent_services.service.IntentService.
handle_add_context``) over a FakeBus, then asks the REAL gate
(``ovos_spec_tools.context.gate_satisfied``) whether a
``requires_context=["kitchen"]`` declaration owned by the skill is satisfied.

It must FAIL (utterance-would-not-match, i.e. gate closed) with EITHER half
of the fix reverted:
- workshop reverted (no ``data["key"]`` emitted) -> core never learns the
  original key -> gate stays closed even after ``set_context``.
- core reverted (mirror write dropped) -> ``data["key"]`` arrives but is
  never resolved into ``session.intent_context`` -> gate stays closed.

Only with BOTH halves in place does the gate open after ``set_context`` and
close again after ``remove_context`` - proving the fix is reachable from the
real skill API, not just from hand-crafted messages.
"""
from threading import Event
from unittest import TestCase, mock

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
from ovos_utils.fakebus import FakeBus
from ovos_spec_tools.context import gate_satisfied

from ovos_core.intent_services.service import IntentService
from ovos_workshop.skills.ovos import OVOSSkill

SKILL_ID = "my.skill"
CONTEXT_KEY = "kitchen"


class TestContext1EndToEndReachability(TestCase):
    """Drives the real workshop producer against the real core consumer and
    asks the real gate whether the declaration is satisfied - the auditor's
    repro for OVOS-CONTEXT-1 reachability."""

    def setUp(self):
        self.bus = FakeBus()
        self.session = Session("ctx1-e2e")
        # OVOS-CONTEXT-1 gate is private-scope by construction for the skill
        # API; declaration lives on the (would-be) registered intent, but we
        # only need the resolved gate check here - the registration/matching
        # half of OVOS-CONTEXT-1 is covered by the adapt-pipeline-plugin's
        # own test_context1_gating.py and is out of scope for this fix.
        self.requires = [CONTEXT_KEY]
        self.excludes = []

        def _add_context(message):
            IntentService.handle_add_context(message)

        def _remove_context(message):
            IntentService.handle_remove_context(message)

        self.bus.on("add_context", _add_context)
        self.bus.on("remove_context", _remove_context)

        self._session_patch = mock.patch(
            "ovos_core.intent_services.service.SessionManager.get",
            return_value=self.session)
        self._session_patch.start()
        self.addCleanup(self._session_patch.stop)

        self.skill = OVOSSkill(bus=self.bus, skill_id=SKILL_ID)

    def _gate_open(self) -> bool:
        return gate_satisfied(self.session.intent_context or {},
                              self.requires, self.excludes,
                              owner_id=SKILL_ID)

    def _emit_and_wait(self, topic, method, *args):
        done = Event()
        self.bus.once(topic, lambda m: done.set())
        method(*args)
        self.assertTrue(done.wait(2), f"{topic} was never emitted")

    def test_gate_unreachable_before_set_context(self):
        """Before set_context, the gate MUST be closed (nothing declared
        live yet)."""
        self.assertFalse(self._gate_open())

    def test_set_context_then_remove_context_round_trip(self):
        """The auditor's repro: set_context (real workshop API) must open
        the real gate; remove_context must close it again. This is the
        assertion that fails with either half of the fix reverted."""
        self.assertFalse(self._gate_open(),
                         "precondition: gate must start closed")

        self._emit_and_wait("add_context", self.skill.set_context,
                            CONTEXT_KEY, CONTEXT_KEY)
        self.assertTrue(
            self._gate_open(),
            "OVOS-CONTEXT-1 gate did not open after the real "
            "OVOSSkill.set_context() call - the fix is not reachable from "
            "the real skill API (verify BOTH ovos-workshop set_context "
            "carries data['key'] AND ovos-core handle_add_context mirrors "
            "it under resolve_key(key, 'private', skill_id))")

        self._emit_and_wait("remove_context", self.skill.remove_context,
                            CONTEXT_KEY)
        self.assertFalse(
            self._gate_open(),
            "OVOS-CONTEXT-1 gate did not close after remove_context - "
            "the mirrored resolved-key entry was not removed symmetrically")
