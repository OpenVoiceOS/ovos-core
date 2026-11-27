"""End-to-end proof of the OVOS-SESSION-2 §2.6 completion sync.

A real ovos-workshop skill running under MiniCroft speaks and then writes an
intent-context entry, exactly as a skill setting up a follow-up question does.
The skill's session object is not core's — the dispatch crosses the bus and the
skill mutates its own copy — so the entry reaches the orchestrator only if the
round's working session is synced with the handler's mutations at completion.

The first test asserts the entry rides the round's canonical end-marker,
``ovos.utterance.handled``, which is what a client adopts (§3.3). The second
follows the consequence through: the client re-declares the session it adopted,
and a ``requires_context`` intent that was ungated on the first turn matches on
the second.
"""
import time
from threading import Event
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
from ovos_spec_tools import SpecMessage
from ovos_utils.log import LOG
from ovos_workshop.decorators import intent_handler
from ovos_workshop.intents import IntentBuilder
from ovos_workshop.skills import OVOSSkill

from ovoscope import get_minicroft

SKILL_ID = "test-completion-sync.openvoiceos"
CONTEXT_KEY = "confirming"
STORED_KEY = f"{SKILL_ID}:{CONTEXT_KEY}"
REARM_KEY = "rearming"
STORED_REARM_KEY = f"{SKILL_ID}:{REARM_KEY}"
#: short enough that the entry is dead by the next turn, so that turn's
#: pre-match prune removes it while the handler re-arms it again
REARM_TTL = 1.0
UTTERANCE_HANDLED = SpecMessage.UTTERANCE_HANDLED.value


class ContextWritingSkill(OVOSSkill):
    """Asks a question, then arms the follow-up with an intent-context entry.

    The write goes straight into ``session.intent_context`` — the only context
    write path OVOS-CONTEXT-1 §5.0 defines — on the session the skill received
    with its dispatch, which is the §5.3 handler pathway.
    """

    def initialize(self):
        self.register_vocabulary("delete everything", "DeleteKeyword")
        self.register_vocabulary("yes", "YesKeyword")
        self.register_vocabulary("clear the queue", "RearmKeyword")
        self.register_vocabulary("go ahead", "GoAheadKeyword")

    @intent_handler(IntentBuilder("DeleteIntent").require("DeleteKeyword"))
    def handle_delete(self, message):
        self.speak("are you sure?")
        SessionManager.get(message).set_intent_context(
            CONTEXT_KEY, True, owner_id=self.skill_id)

    @intent_handler(IntentBuilder("ConfirmIntent").require("YesKeyword"),
                    requires_context=[CONTEXT_KEY])
    def handle_confirm(self, message):
        self.speak("deleted")

    @intent_handler(IntentBuilder("RearmIntent").require("RearmKeyword"))
    def handle_rearm(self, message):
        """Arms a short-lived confirmation window on every invocation — the
        shape of any skill that asks the same follow-up question twice."""
        self.speak("are you sure?")
        SessionManager.get(message).set_intent_context(
            REARM_KEY, time.time(), owner_id=self.skill_id,
            expires_at=time.time() + REARM_TTL)

    @intent_handler(IntentBuilder("RearmConfirmIntent").require("GoAheadKeyword"),
                    requires_context=[REARM_KEY])
    def handle_rearm_confirm(self, message):
        self.speak("queue cleared")


class TestCompletionSyncE2E(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        self.minicroft = get_minicroft(
            [SKILL_ID], extra_skills={SKILL_ID: ContextWritingSkill})
        self.bus = self.minicroft.bus

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def _session(self) -> Session:
        session = Session("client-1")
        session.lang = "en-US"
        session.pipeline = ["ovos-adapt-pipeline-plugin-high"]
        return session

    def _say(self, utterance: str, session: Session) -> Session:
        """Run one utterance and return the session the end-marker carried."""
        done = Event()
        captured = []

        def on_handled(message: Message):
            captured.append(message.context.get("session") or {})
            done.set()

        self.bus.on(UTTERANCE_HANDLED, on_handled)
        try:
            self.bus.emit(Message(
                "recognizer_loop:utterance",
                {"utterances": [utterance], "lang": session.lang},
                {"session": session.serialize(),
                 "source": "A", "destination": "B"}))
            self.assertTrue(done.wait(timeout=20),
                            f"no ovos.utterance.handled for '{utterance}'")
        finally:
            self.bus.remove(UTTERANCE_HANDLED, on_handled)
        return Session.deserialize(captured[0])

    def test_handler_context_write_rides_the_end_marker(self):
        adopted = self._say("delete everything", self._session())
        self.assertIn(STORED_KEY, adopted.intent_context or {},
                      "the entry the skill wrote during its handler never "
                      "reached ovos.utterance.handled")

    def test_the_follow_up_turn_resolves_the_requires_context_gate(self):
        adopted = self._say("delete everything", self._session())
        # a conformant client re-declares the session it adopted (§3)
        adopted.pipeline = ["ovos-adapt-pipeline-plugin-high"]
        spoken = []
        self.bus.on(SpecMessage.SPEAK.value,
                    lambda m: spoken.append(m.data.get("utterance")))

        self._say("yes", adopted)

        self.assertIn("deleted", spoken,
                      "the context-gated follow-up intent did not match, so "
                      "the entry never survived the first round")

    def test_a_rearmed_entry_survives_the_prune_of_its_own_predecessor(self):
        """The decay beats a stale carry-over, not a fresh write.

        The entry armed on the first turn is dead by the second, so the second
        turn's pre-match prune removes it — and the handler arms it again in
        the same round. That write is the handler's, not an echo of what the
        prune dropped, so it must reach the end marker and gate the third turn.
        """
        first = self._say("clear the queue", self._session())
        self.assertIn(STORED_REARM_KEY, first.intent_context or {})
        time.sleep(REARM_TTL + 0.5)

        second = self._say("clear the queue", first)
        self.assertIn(STORED_REARM_KEY, second.intent_context or {},
                      "the handler re-armed a key this round's pre-match "
                      "prune had removed; the write was dropped")

        spoken = []
        self.bus.on(SpecMessage.SPEAK.value,
                    lambda m: spoken.append(m.data.get("utterance")))
        second.pipeline = ["ovos-adapt-pipeline-plugin-high"]
        self._say("go ahead", second)
        self.assertIn("queue cleared", spoken,
                      "the re-armed gate did not match on the next turn")
