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

Round 4 (wave-3 CONFIRMED / this file's known weakness fixed): the original
version of this test mocked ``SessionManager.get`` to always hand back one
fixed, never-folded ``Session`` object, so it could never observe the
wave-3 defect - "in-lifecycle set_context on a NAMED session never survives
to the terminal event" - because it never exercised
``SessionManager.get(message)``'s real fold at all. That is exactly why the
defect escaped to wave 3. ``test_named_session_context_survives_a_second_
stale_client_message`` below drives the REAL registered-session two-message
flow instead: a NAMED session is registered in the real
``SessionManager.sessions`` singleton (no mocking); ``set_context`` is
invoked from inside a simulated utterance-handling frame (so
``dig_for_message`` finds the same in-flight ``message`` a real skill
handler would see); what would be serialized onto the terminal
``ovos.utterance.handled`` event is read back directly from
``SessionManager.sessions[sid]`` (never from a private test-local
reference); and a second message simulates the conformant client's echo of
the previously-adopted session (SESSION-2 - the client declares the
session on every subsequent message) to prove the gate stays satisfied
across that hand-off too.
"""
from threading import Event
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import DEFAULT_SESSION_ID, Session, SessionManager
from ovos_utils.fakebus import FakeBus
from ovos_spec_tools.context import gate_satisfied

from ovos_core.intent_services.service import IntentService
from ovos_workshop.skills.ovos import OVOSSkill

SKILL_ID = "my.skill"
CONTEXT_KEY = "kitchen"
SESSION_ID = "ctx1-e2e-r4"


class TestContext1EndToEndReachability(TestCase):
    """Drives the real workshop producer against the real core consumer and
    asks the real gate whether the declaration is satisfied - the auditor's
    repro for OVOS-CONTEXT-1 reachability, extended (round 4) into the real
    two-message NAMED-session flow so it also proves the wave-3 fix."""

    def setUp(self):
        self.bus = FakeBus()
        self.requires = [CONTEXT_KEY]
        self.excludes = []

        # Register a REAL named session in the shared singleton registry -
        # nothing is mocked here by default. This is what
        # SessionManager.get(message) would fold onto for any message
        # declaring session_id=SESSION_ID.
        self._saved_sessions = dict(SessionManager.sessions)
        SessionManager.sessions.clear()
        self.session = Session(SESSION_ID)
        SessionManager.sessions[SESSION_ID] = self.session

        self.bus.on("add_context", IntentService.handle_add_context)
        self.bus.on("remove_context", IntentService.handle_remove_context)

        self.skill = OVOSSkill(bus=self.bus, skill_id=SKILL_ID)

        self.addCleanup(self._restore_sessions)

    def _restore_sessions(self):
        SessionManager.sessions.clear()
        SessionManager.sessions.update(self._saved_sessions)

    def _live_intent_context(self) -> dict:
        """What ``ovos.utterance.handled`` would serialize (SESSION-1/SESSION-2:
        the terminal event carries the live registry session, not a private
        reference) - read directly off the singleton, never off a variable
        the test happens to still be holding."""
        return SessionManager.sessions[SESSION_ID].intent_context or {}

    def _gate_open(self) -> bool:
        return gate_satisfied(self._live_intent_context(),
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
        assertion that fails with either half of the round-1 fix reverted.

        The workshop producer's ``set_context``/``remove_context`` build
        their outgoing message via ``dig_for_message() or Message("")`` -
        with no explicit in-flight message supplied by this test, whatever
        ambient ``Message`` the OVOSSkill machinery happens to have left on
        the call stack is used, and it carries the real ``default`` session
        (round-4: the handlers now resolve registry-first off the message's
        declared session_id, so a fixed-return ``SessionManager.get`` mock
        alone no longer controls which session object gets mutated once the
        message actually names a session that is live in the registry - the
        registry entry wins). This test substitutes the object registered
        under the live ``default`` session_id for the duration of the test
        (restored after), so it isolates the ONE thing it is about:
        private-key resolution reachability, not the round-4 fold-discipline
        fix (that is what
        ``test_named_session_context_survives_a_second_stale_client_message``
        below exercises, over an explicit NAMED session)."""
        saved_default = SessionManager.sessions.get(DEFAULT_SESSION_ID)
        self.session.session_id = DEFAULT_SESSION_ID
        SessionManager.sessions[DEFAULT_SESSION_ID] = self.session

        def _gate_open():
            return gate_satisfied(self.session.intent_context or {},
                                  self.requires, self.excludes,
                                  owner_id=SKILL_ID)

        try:
            self.assertFalse(_gate_open(),
                             "precondition: gate must start closed")

            self._emit_and_wait("add_context", self.skill.set_context,
                                CONTEXT_KEY, CONTEXT_KEY)
            self.assertTrue(
                _gate_open(),
                "OVOS-CONTEXT-1 gate did not open after the real "
                "OVOSSkill.set_context() call - the fix is not reachable from "
                "the real skill API (verify BOTH ovos-workshop set_context "
                "carries data['key'] AND ovos-core handle_add_context mirrors "
                "it under resolve_key(key, 'private', skill_id))")

            self._emit_and_wait("remove_context", self.skill.remove_context,
                                CONTEXT_KEY)
            self.assertFalse(
                _gate_open(),
                "OVOS-CONTEXT-1 gate did not close after remove_context - "
                "the mirrored resolved-key entry was not removed symmetrically")
        finally:
            if saved_default is not None:
                SessionManager.sessions[DEFAULT_SESSION_ID] = saved_default
            else:
                SessionManager.sessions.pop(DEFAULT_SESSION_ID, None)

    def test_named_session_context_survives_a_second_stale_client_message(self):
        """Wave-3 CONFIRMED (round 4).

        Step 1 drives the REAL producer (``OVOSSkill.set_context``) over the
        bus, in-handler (so ``dig_for_message`` finds the driving message),
        exactly like the round-1 repro above, but on an explicit NAMED
        session registered in the real ``SessionManager.sessions`` registry.
        This opens the gate and moves the registry forward.

        ``Message.forward()`` (used internally by the workshop producer)
        self-heals staleness for messages derived *within this same
        process* - ``sync_message_session`` re-stamps a derived message's
        session with the CURRENT live registry state at forward-time, so an
        in-process round-trip alone can never observe the wave-3 defect.
        The defect is specifically about a REMOTE client's message: one that
        arrives over the wire carrying an already-serialized session
        snapshot that no local ``forward()`` gets to refresh. Step 2
        reproduces exactly that: a hand-built ``add_context`` message,
        shaped like a genuine second producer call (same data shape
        ``OVOSSkill.set_context`` would emit for a different key) but
        carrying a STALE session snapshot taken before step 1 ran - as a
        real second client message arriving before it has seen step 1's
        response would. It is dispatched straight to the REAL consumer
        (``IntentService.handle_add_context``), matching how a
        ``MessageBusClient`` hands a deserialized wire message to the
        registered handler.

        Before the round-4 fix, ``handle_add_context`` called
        ``SessionManager.get(message)``, which folds this stale snapshot
        onto the registry entry BEFORE writing - for a NAMED session that
        fold is full-replace, wiping step 1's entry. This must be RED before
        the round-4 fix at the ``"kitchen" entry present`` assertion below.
        """
        # Step 1: real producer, real consumer, over the bus, in-handler.
        stale_snapshot = self.session.serialize()  # captured BEFORE any write

        def _handler(message):
            self.skill.set_context(CONTEXT_KEY, CONTEXT_KEY)
            self.bus.emit(message.forward("ovos.utterance.handled"))

        inbound = Message("recognizer_loop:utterance",
                          {"utterances": ["irrelevant"]},
                          {"session": self.session.serialize(),
                           "skill_id": SKILL_ID})
        self.bus.on("recognizer_loop:utterance", _handler)
        self._emit_and_wait("ovos.utterance.handled",
                            lambda: self.bus.emit(inbound))
        self.bus.remove("recognizer_loop:utterance", _handler)

        self.assertTrue(
            self._gate_open(),
            "OVOS-CONTEXT-1 gate not satisfied after the real "
            "OVOSSkill.set_context() call on the NAMED session")

        # Step 2: a genuinely stale, externally-arriving second message
        # (data shaped exactly like a real workshop set_context call for a
        # different key), dispatched directly to the real consumer - the
        # remote-client scenario `Message.forward()` cannot self-heal.
        stale_second_message = Message(
            "add_context",
            {"context": "my_skillother", "word": "other", "origin": "",
             "key": "other"},
            {"session": stale_snapshot, "skill_id": SKILL_ID})
        IntentService.handle_add_context(stale_second_message)

        ctx = self._live_intent_context()
        self.assertIn(
            "my_skillkitchen", ctx,
            "step 1's context entry was wiped by step 2's stale-snapshot "
            "fold - a second, stale client message must not erase context "
            "already live on a NAMED session")
        self.assertIn("my_skillother", ctx,
                      "step 2's own context entry is also missing")
        self.assertTrue(
            self._gate_open(),
            "OVOS-CONTEXT-1 gate not satisfied after the second, stale "
            "client message")

        # Finally: the conformant client's echo of the FULL, now-current
        # adopted session (SESSION-2 - the client declares the session on
        # every message) must still see the gate satisfied.
        adopted_snapshot = SessionManager.sessions[SESSION_ID].serialize()
        self.assertTrue(
            gate_satisfied(
                adopted_snapshot.get("intent_context") or {},
                self.requires, self.excludes, owner_id=SKILL_ID),
            "the adopted session snapshot a conformant client would echo "
            "back does not itself satisfy the gate")
