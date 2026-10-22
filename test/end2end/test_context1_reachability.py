"""Cross-repo end-to-end reachability proof for OVOS-CONTEXT-1.

A skill calling the real
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

``test_named_session_context_survives_a_second_stale_client_message`` below
proves a related invariant: in-lifecycle ``set_context`` on a NAMED session
must survive to the terminal event, even when a second, stale client message
arrives in between. It drives the REAL registered-session two-message flow:
a NAMED session is registered in the real ``SessionManager.sessions``
singleton (no mocking); ``set_context`` is invoked from inside a simulated
utterance-handling frame (so ``dig_for_message`` finds the same in-flight
``message`` a real skill handler would see); what would be serialized onto
the terminal ``ovos.utterance.handled`` event is read back directly from
``SessionManager.sessions[sid]`` (never from a private test-local
reference); and a second message simulates the conformant client's echo of
the previously-adopted session (SESSION-2 - the client declares the session
on every subsequent message) to prove the gate stays satisfied across that
hand-off too. A test that mocks ``SessionManager.get`` to always hand back
one fixed, never-folded ``Session`` object cannot observe this class of
defect, because it never exercises ``SessionManager.get(message)``'s real
fold at all.
"""
from threading import Event
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import DEFAULT_SESSION_ID, Session, SessionManager
from ovos_utils.fakebus import FakeBus
from ovos_spec_tools.context import gate_satisfied

from ovos_core.intent_services.service import IntentService
from ovos_core.intent_services.working_session import close_round, open_round
from ovos_workshop.skills.ovos import OVOSSkill

SKILL_ID = "my.skill"
CONTEXT_KEY = "kitchen"
SESSION_ID = "ctx1-e2e-r4"


class TestContext1EndToEndReachability(TestCase):
    """Drives the real workshop producer against the real core consumer and
    asks the real gate whether the declaration is satisfied - proving
    OVOS-CONTEXT-1 reachability end to end, including across a real
    two-message NAMED-session flow."""

    def setUp(self):
        self.bus = FakeBus()
        self.requires = [CONTEXT_KEY]
        self.excludes = []

        self._saved_sessions = dict(SessionManager.sessions)
        SessionManager.sessions.clear()
        self.session = Session(SESSION_ID)
        # OVOS-SESSION-2 §2.2 keeps the orchestrator stateless for a named
        # session, so core resolves one through the round's working session.
        # ovos-workshop's producer still resolves through the registry, so the
        # same object is planted there too and both halves write the one
        # session a real round would be running on.
        SessionManager.sessions[SESSION_ID] = self.session

        self.bus.on("add_context", IntentService.handle_add_context)
        self.bus.on("remove_context", IntentService.handle_remove_context)

        self.skill = OVOSSkill(bus=self.bus, skill_id=SKILL_ID)

        self.addCleanup(self._restore_sessions)

    def _restore_sessions(self):
        SessionManager.sessions.clear()
        SessionManager.sessions.update(self._saved_sessions)

    def _live_intent_context(self) -> dict:
        """What ``ovos.utterance.handled`` would serialize: the session the
        round is running on, read through the working-session registry rather
        than off a variable the test happens to still be holding."""
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
        """set_context (real workshop API) must open the real gate;
        remove_context must close it again. Without either half of the fix,
        this assertion fails: the producer's munged legacy key alone can
        never satisfy the declarative gate's resolved-key lookup.

        The workshop producer's ``set_context``/``remove_context`` build
        their outgoing message via ``dig_for_message() or Message("")`` -
        with no explicit in-flight message supplied by this test, whatever
        ambient ``Message`` the OVOSSkill machinery happens to have left on
        the call stack is used, and it carries the real ``default`` session
        (the handlers resolve registry-first off the message's declared
        session_id, so a fixed-return ``SessionManager.get`` mock alone
        does not control which session object gets mutated once the message
        actually names a session that is live in the registry - the
        registry entry wins). This test substitutes the object registered
        under the live ``default`` session_id for the duration of the test
        (restored after), so it isolates the ONE thing it is about:
        private-key resolution reachability, not the fold-discipline fix
        (that is what
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
        """A stale second message must not wipe a NAMED session's context
        before it reaches the terminal event.

        Step 1 drives the REAL producer (``OVOSSkill.set_context``) over the
        bus, in-handler (so ``dig_for_message`` finds the driving message),
        exactly like the repro above, but on an explicit NAMED session
        on an explicit NAMED session. This opens the gate and moves the
        round's session forward.

        ``Message.forward()`` (used internally by the workshop producer)
        self-heals staleness for messages derived *within this same
        process* - ``sync_message_session`` re-stamps a derived message's
        session with the CURRENT live registry state at forward-time, so an
        in-process round-trip alone can never observe this defect.
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

        The frame belongs to the round, so it carries the round's
        ``utterance_id`` and reaches the working session that way
        (OVOS-SESSION-2 §2.6). What it must NOT do is adopt its own stale
        snapshot: that would full-replace the named session and wipe step 1's
        entry, so the ``"kitchen" entry present`` assertion below fails.
        """
        # Step 1: real producer, real consumer, over the bus, in-handler.
        stale_snapshot = self.session.serialize()  # captured BEFORE any write

        def _handler(message):
            self.skill.set_context(CONTEXT_KEY, CONTEXT_KEY)
            self.bus.emit(message.forward("ovos.utterance.handled"))

        inbound = Message("recognizer_loop:utterance",
                          {"utterances": ["irrelevant"]},
                          {"session": self.session.serialize(),
                           "skill_id": SKILL_ID,
                           "utterance_id": "uid-ctx1-e2e"})
        open_round(inbound, self.session)
        self.addCleanup(close_round, inbound)
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
            {"session": stale_snapshot, "skill_id": SKILL_ID,
             "utterance_id": "uid-ctx1-e2e"})
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
