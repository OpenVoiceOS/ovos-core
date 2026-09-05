import threading
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_spec_tools import SpecMessage, migration_counterpart
from ovos_utils.log import LOG

from ovos_workshop.skills.converse import ConversationalSkill
from ovoscope import End2EndTest, get_minicroft

# Topics come from the ovos-spec-tools SpecMessage enum (spec namespace); the
# legacy counterpart is derived via migration_counterpart, never hardcoded.
SPEC_UTTERANCE = SpecMessage.UTTERANCE.value              # ovos.utterance.handle
LEGACY_UTTERANCE = migration_counterpart(SPEC_UTTERANCE)  # recognizer_loop:utterance
# PIPELINE-1 orchestrator-emitted matched-path messages: §9.2 ovos.intent.matched
# (before dispatch) and §8.1 ovos.intent.handler.start. The converse:skill
# dispatch is a reserved-name dispatch with no mycroft.skill.handler.* done-signal,
# so its §8 terminal resolves via the §8.3 timeout (after the end-marker, not
# captured here).

# The two namespace paths the utterance-injecting scenario is run on.
#   key       -> (modernize, emit_legacy, utterance_topic)
NAMESPACE_PATHS = {
    # pure spec: inject on ovos.* and assert no bridging
    "spec": (False, False, SPEC_UTTERANCE),
    # legacy producer bridged to the spec listener via modernize
    "legacy": (True, False, LEGACY_UTTERANCE),
}


class TestSkill(ConversationalSkill):

    def initialize(self):
        self.add_event("test_activate", self.handle_activate_test)
        self.add_event("test_deactivate", self.handle_deactivate_test)

    def handle_activate_test(self, message: Message):
        self.activate()

    def handle_deactivate_test(self, message: Message):
        self.deactivate()

    def can_converse(self, message: Message) -> bool:
        return True

    def converse(self, message: Message):
        self.log.debug("I dont wanna converse anymore")
        self.deactivate()


class TestDeactivate(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "test_activation.openvoiceos"
        self.minicroft = get_minicroft([self.skill_id],
                                       extra_skills={self.skill_id: TestSkill})

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_activate(self):
        session = Session("123")
        session.lang = "en-US"
        session.deactivate_skill(self.skill_id) # start with skill inactive

        message = Message("test_activate",
                          context={"session": session.serialize(),
                                   "source": "A", "destination": "B"})

        final_session = Session("123")
        final_session.lang = "en-US"
        final_session.active_skills = [(self.skill_id, 0.0)]

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            deactivation_points=[message.msg_type],
            final_session=final_session,
            activation_points=["intent.service.skills.activated"],
            # this scenario is a plain bus event, NOT an utterance: no pipeline
            # runs, so PIPELINE-1 §9.5 ``ovos.utterance.handled`` (the ovoscope
            # default end-marker) is never emitted and must not be waited for.
            # The skill's own activation ack is the terminal message here.
            eof_msgs=[f"{self.skill_id}.activate"],
            # messages internal to ovos-core, i.e. would not be sent to clients such as hivemind
            keep_original_src=[
                #"intent.service.skills.activate", # TODO
                #f"{self.skill_id}.activate", # TODO
            ],
            expected_messages=[
                message,
                # handler code
                Message("intent.service.skills.activate",
                        data={"skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message("intent.service.skills.activated",
                        data={"skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message(f"{self.skill_id}.activate",
                        data={},
                        context={"skill_id": self.skill_id}),
            ]
        )

        test.execute(timeout=10)

    def test_deactivate(self):
        session = Session("123")
        session.lang = "en-US"
        session.activate_skill(self.skill_id) # start with skill active

        message = Message("test_deactivate",
                          context={"session": session.serialize(),
                                   "source": "A", "destination": "B"})

        final_session = Session("123")
        final_session.lang = "en-US"
        final_session.active_skills = []

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            source_message=message,
            final_session=final_session,
            activation_points=[message.msg_type], # starts activated
            deactivation_points=["intent.service.skills.deactivated"],
            # plain bus event, not an utterance — see test_activate above.
            eof_msgs=[f"{self.skill_id}.deactivate"],
            # messages internal to ovos-core, i.e. would not be sent to clients such as hivemind
            keep_original_src=[
                #"intent.service.skills.deactivate", # TODO
                #f"{self.skill_id}.deactivate", # TODO
                #f"{self.skill_id}.activate", # TODO
            ],
            expected_messages=[
                message,
                # handler code
                Message("intent.service.skills.deactivate",
                        data={"skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message("intent.service.skills.deactivated",
                        data={"skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message(f"{self.skill_id}.deactivate",
                        data={},
                        context={"skill_id": self.skill_id}),
            ]
        )

        test.execute(timeout=10)

    def _run_deactivate_inside_converse(self, namespace):
        """A converse handler that deactivates its own skill mid-utterance.

        The utterance is injected on ``recognizer_loop:utterance`` (a migrated
        topic), so this scenario runs on both namespace paths: pure spec
        (inject on ``ovos.utterance.handle``) and legacy bridged to the spec
        listener via ``modernize``. The captured sequence is identical on both
        paths except message[0]'s topic.
        """
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id],
                                  extra_skills={self.skill_id: TestSkill},
                                  modernize=modernize, emit_legacy=emit_legacy)

        session = Session("123")
        session.lang = "en-US"
        session.activate_skill(self.skill_id) # start with skill active
        # OVOS-CONVERSE-1 §2.1: converse candidacy is read from
        # converse_handlers, a list independent of active_handlers -- seed
        # it too so the skill is offered the poll below.
        session.add_converse_handler(self.skill_id)

        message1 = Message(utt_topic,
                          {"utterances": ["deactivate skill from within converse"], "lang": session.lang},
                          {"session": session.serialize(), "source": "A", "destination": "B"})
        # OVOS-CONVERSE-1 §2.1/B1: a skill that deactivates itself from
        # within converse() must leave converse_handlers too, not just
        # active_handlers -- otherwise it hijacks every later utterance in
        # the session. This third utterance (following the session's own
        # earlier activation and this scenario's converse-and-deactivate
        # turn) must NOT be polled at all: converse_handlers is empty, so
        # ConverseService.match() returns None without ever emitting a ping.
        # NOTE: no session in context -- End2EndTest threads the round's
        # own session forward from message1, same as test_converse.py's
        # multi-turn scenarios.
        message2 = Message(utt_topic,
                          {"utterances": ["are you still there"], "lang": session.lang},
                          {"source": "A", "destination": "B"})

        # the skill deactivates itself inside converse, so the session ends
        # with the skill inactive (no re-activation — the skill explicitly
        # requested deactivation).
        final_session = Session("123")
        final_session.lang = "en-US"
        final_session.active_skills = []

        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=[self.skill_id],
            source_message=[message1, message2],
            final_session=final_session,
            activation_points=[message1.msg_type], # starts activated
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            deactivation_points=["intent.service.skills.deactivated"],
            # messages internal to ovos-core, i.e. would not be sent to clients such as hivemind
            keep_original_src=[
                f"{self.skill_id}.converse.ping",
                f"{self.skill_id}.converse.request",
                # ovos.converse.pong (OVOS-CONVERSE-1 §4.2 broadcast answer,
                # ovos-workshop#534) is emitted on the entry source/destination
                # pair, not flipped like the per-round response messages.
                "ovos.converse.pong",
                #"intent.service.skills.deactivate", # TODO
                #f"{self.skill_id}.deactivate", # TODO
                #f"{self.skill_id}.activate", # TODO
            ],
            expected_messages=[
                message1,
                # OVOS-CONVERSE-1 §4.2: one broadcast poll per round, emitted
                # before the legacy per-skill pings (dual-emit compat window).
                Message("ovos.converse.ping",
                        data={"utterances": ["deactivate skill from within converse"], "lang": session.lang},
                        context={}),
                # OVOS-CONVERSE-1 §4.2 broadcast answer (ovos-workshop#534);
                # result mirrors the legacy skill.converse.pong can_handle=True below.
                Message("ovos.converse.pong",
                        data={"skill_id": self.skill_id, "result": True},
                        context={}),
                Message(f"{self.skill_id}.converse.ping",
                        data={"utterances": ["deactivate skill from within converse"], "skill_id": self.skill_id},
                        context={}),
                Message("skill.converse.pong",
                        data={"can_handle": True, "skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message(f"{self.skill_id}.activate",
                        data={},
                        context={"skill_id": self.skill_id}),
                # PIPELINE-1 §9.2: matched notification precedes the dispatch
                Message(SpecMessage.INTENT_MATCHED,
                        data={"skill_id": self.skill_id,
                              "intent_name": "converse:skill"},
                        context={"skill_id": self.skill_id}),
                # PIPELINE-1 §8.1: orchestrator start immediately before the dispatch
                Message(SpecMessage.INTENT_HANDLER_START,
                        data={"skill_id": self.skill_id,
                              "intent_name": "skill"},
                        context={"skill_id": self.skill_id}),
                Message("converse:skill",
                        data={"utterances": ["deactivate skill from within converse"], "lang": session.lang,
                              "skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                # ConverseService reports the converse dispatch lifecycle to the
                # orchestrator via the mycroft.skill.handler.* done-signal
                Message("mycroft.skill.handler.start",
                        data={"handler": f"{self.skill_id}.converse"},
                        context={"skill_id": self.skill_id}),
                Message(f"{self.skill_id}.converse.request",
                        data={"utterances": ["deactivate skill from within converse"], "lang": session.lang},
                        context={"skill_id": self.skill_id}),
                # converse handler code
                Message("intent.service.skills.deactivate",
                        data={"skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message("intent.service.skills.deactivated",
                        data={"skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message(f"{self.skill_id}.deactivate",
                        data={},
                        context={"skill_id": self.skill_id}),
                # post converse handler
                Message("skill.converse.response",
                        data={"skill_id": self.skill_id},
                        context={"skill_id": self.skill_id}),
                Message("mycroft.skill.handler.complete",
                        data={"handler": f"{self.skill_id}.converse"},
                        context={"skill_id": self.skill_id}),
                # PIPELINE-1 §8 terminal: orchestrator correlates the done-signal
                Message(SpecMessage.INTENT_HANDLER_COMPLETE,
                        data={"skill_id": self.skill_id, "intent_name": "skill"},
                        context={"skill_id": self.skill_id}),
                Message(SpecMessage.UTTERANCE_HANDLED,
                        data={},
                        context={"skill_id": self.skill_id}),

                # --- message2: the skill must not be a converse candidate
                # any more. No ovos.converse.ping / {skill_id}.converse.ping
                # appear at all -- ConverseService._collect_converse_skills
                # short-circuits on an empty candidate set (§4.2) before
                # ever broadcasting -- so nothing else in the pipeline
                # matches this utterance either.
                message2,
                Message("mycroft.audio.play_sound", data={"uri": "snd/error.mp3"}),
                Message(SpecMessage.INTENT_UNMATCHED),
                Message(SpecMessage.UTTERANCE_HANDLED),
            ]
        )

        try:
            test.execute(timeout=10)
        finally:
            minicroft.stop()

    def test_deactivate_inside_converse(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_deactivate_inside_converse(namespace)


class TestActiveHandlersOnlyIsNotPolled(TestCase):
    """OVOS-CONVERSE-1 §2.1: "session.converse_handlers ... is distinct from
    session.active_handlers (OVOS-PIPELINE-1 §7.1)". The converse plugin's
    candidate set (ConverseService.get_active_skills) MUST be read from
    converse_handlers, never active_handlers -- a skill present only on
    active_handlers must not be offered a converse turn.

    This fails against unfixed ovos-core (get_active_skills reads
    active_handlers, so the skill is polled and claims); it passes here
    (get_active_skills reads converse_handlers, which was never populated
    for this skill)."""

    skill_id = "ovos-skill-parrot.openvoiceos"

    def setUp(self):
        LOG.set_level("DEBUG")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def test_active_handlers_only_skill_is_not_polled(self):
        minicroft = get_minicroft([self.skill_id], modernize=False, emit_legacy=False)
        try:
            session = Session("789")
            session.lang = "en-US"
            session.pipeline = ["ovos-converse-pipeline-plugin",
                                "ovos-padatious-pipeline-plugin-high"]
            # candidacy source under test: active_handlers ONLY.
            # converse_handlers is left empty.
            session.activate_skill(self.skill_id)
            self.assertEqual(session.converse_handlers, [])

            message = Message(SpecMessage.UTTERANCE.value,
                              {"utterances": ["echo test"], "lang": session.lang},
                              {"session": session.serialize(),
                               "source": "A", "destination": "B"})

            captured = []
            done = threading.Event()

            def _capture(msg):
                captured.append(msg.msg_type)

            def _finish(msg):
                done.set()

            minicroft.bus.on("ovos.converse.ping", _capture)
            minicroft.bus.on(f"{self.skill_id}.converse.ping", _capture)
            minicroft.bus.on(SpecMessage.UTTERANCE_HANDLED.value, _finish)
            try:
                minicroft.bus.emit(message)
                done.wait(timeout=10)
            finally:
                minicroft.bus.remove("ovos.converse.ping", _capture)
                minicroft.bus.remove(f"{self.skill_id}.converse.ping", _capture)
                minicroft.bus.remove(SpecMessage.UTTERANCE_HANDLED.value, _finish)

            self.assertTrue(done.is_set(), "utterance round never completed")
            self.assertNotIn("ovos.converse.ping", captured,
                            f"{self.skill_id} was polled via the broadcast leg "
                            f"despite being absent from converse_handlers")
            self.assertNotIn(f"{self.skill_id}.converse.ping", captured,
                            f"{self.skill_id} was polled via the legacy leg "
                            f"despite being absent from converse_handlers")
        finally:
            minicroft.stop()
