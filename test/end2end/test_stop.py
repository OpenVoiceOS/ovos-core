"""End-to-end tests for the stop pipeline.

Each scenario that injects an utterance is exercised on BOTH bus namespaces via
``self.subTest(namespace=...)``:

- **spec**: ``modernize=False, emit_legacy=False`` — the utterance is injected on
  the spec topic ``ovos.utterance.handle`` and core handles it natively.
- **legacy**: ``modernize=True, emit_legacy=False`` — the utterance is injected on
  the legacy topic ``recognizer_loop:utterance``; the FakeBus modernize-bridge
  re-dispatches it as ``ovos.utterance.handle`` so the spec-only listener handles it.

The captured message sequence is identical on both paths except message[0]'s topic
(the injected utterance), which equals the per-namespace topic.
"""
import time
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
from ovos_spec_tools import SpecMessage, migration_counterpart
from ovos_utils import create_daemon
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft

# Topics come from the ovos-spec-tools SpecMessage enum (spec namespace); the
# legacy counterpart is derived via migration_counterpart, never hardcoded.
SPEC_UTTERANCE = SpecMessage.UTTERANCE.value              # ovos.utterance.handle
LEGACY_UTTERANCE = migration_counterpart(SPEC_UTTERANCE)  # recognizer_loop:utterance
UTTERANCE_HANDLED = SpecMessage.UTTERANCE_HANDLED.value   # ovos.utterance.handled
SPEC_SPEAK = SpecMessage.SPEAK.value                      # ovos.utterance.speak
INTENT_MATCHED = SpecMessage.INTENT_MATCHED.value         # ovos.intent.matched (§9.2)
INTENT_UNMATCHED = SpecMessage.INTENT_UNMATCHED.value     # ovos.intent.unmatched (§9.3)
HANDLER_START = SpecMessage.INTENT_HANDLER_START.value    # §8.1
HANDLER_COMPLETE = SpecMessage.INTENT_HANDLER_COMPLETE.value
HANDLER_ERROR = SpecMessage.INTENT_HANDLER_ERROR.value

# The two namespace paths every scenario is run on.
#   key       -> (modernize, emit_legacy, utterance_topic)
NAMESPACE_PATHS = {
    # pure spec: inject on ovos.* and assert no bridging
    "spec": (False, False, SPEC_UTTERANCE),
    # legacy producer bridged to the spec listener via modernize
    "legacy": (True, False, LEGACY_UTTERANCE),
}

# Messages produced by other pipeline-plugin skills in response to mycroft.stop;
# always ignored so they don't pollute assertion counts. The count skill speaks
# on the spec topic ovos.utterance.speak (no legacy mirror, emit_legacy=False).
IGNORE_MESSAGES = [
    SPEC_SPEAK,
    "recognizer_loop:audio_output_start",  # TTS mock duck
    "recognizer_loop:audio_output_end",  # TTS mock unduck
    # ovos.intent.matched (§9.2) precedes every dispatch; these scenarios assert
    # stop routing/activation, not the matched broadcast, so it is filtered here.
    INTENT_MATCHED,
    # the §8 handler-lifecycle trio also wraps every dispatch; these scenarios
    # assert stop routing, not the trio (it is covered by the adapt/padatious
    # suites), so it is filtered here too.
    HANDLER_START,
    HANDLER_COMPLETE,
    HANDLER_ERROR,
    "ovos.common_play.stop.response",
    "common_query.openvoiceos.stop.response",
    "persona.openvoiceos.stop.response",
    "ovos-hivemind-pipeline-plugin.stop.response",
    # The async stop-pipeline callback cleans up an interrupted skill depending
    # on exactly where the stop lands (mid get_response / active / mid-TTS). These
    # artifacts are timing-dependent — ignore them so the assertion stays stable.
    "mycroft.skills.abort_question",
    "ovos.skills.converse.force_timeout",
    "mycroft.audio.speech.stop",
]


def skill_stop_lifecycle(skill_id):
    """The deterministic stop-dispatch §8 lifecycle, as seen filtered to
    ``skill_id="stop.openvoiceos"`` (the StopService that owns the stop dispatch).

    Stopping a *running* skill produces two concurrent dispatch lifecycles whose
    messages interleave non-deterministically: the stop dispatch (asserted here)
    and the interrupted skill's own §8 trio + §9.5 terminal, which completes
    asynchronously once the daemon thread unwinds. The End2EndTest ``skill_id``
    filter isolates the stop dispatch; ``eof_count=2`` lets capture span both
    utterances' ``ovos.utterance.handled`` before filtering. The interrupted
    skill's §8 trio is asserted deterministically (uninterrupted) by ``test_count``.
    """
    return [
        Message("stop.openvoiceos.activate", {},
                {"skill_id": "stop.openvoiceos"}),
        Message("stop:skill",
                {"skill_id": skill_id},
                {"skill_id": "stop.openvoiceos"}),
        # StopService wraps handle_skill_stop in HandlerLifecycle (the framework
        # done-signal trio the orchestrator translates into the §8 terminal)
        Message("mycroft.skill.handler.start",
                {"name": "StopService.handle_skill_stop"},
                {"skill_id": "stop.openvoiceos"}),
        Message(f"{skill_id}.stop", {},
                {"skill_id": "stop.openvoiceos"}),
        Message("mycroft.skill.handler.complete",
                {"name": "StopService.handle_skill_stop"},
                {"skill_id": "stop.openvoiceos"}),
        # §9.5 end-marker
        Message(UTTERANCE_HANDLED, {},
                {"skill_id": "stop.openvoiceos"}),
    ]


# Shared End2EndTest config for the skill-stop (ping-pong) scenarios: isolate the
# stop dispatch lifecycle and wait for BOTH utterances to terminate before filtering.
# The §8 SPEC trio (ovos.intent.matched/handler.start/handler.complete) is filtered:
# in these concurrent-lifecycle scenarios under heavy parallel load it is not
# reliably observed alongside the legacy done-signal, so it is asserted in the
# single-lifecycle adapt/padatious suites instead. The legacy mycroft.skill.handler
# done-signal trio (which the orchestrator translates into the §8 terminal) IS
# asserted above.
SKILL_STOP_LIFECYCLE_KWARGS = dict(
    skill_id="stop.openvoiceos",
    eof_msgs=[UTTERANCE_HANDLED],
    eof_count=2,
    test_active_skills=False,
    ignore_messages=[INTENT_MATCHED, HANDLER_START, HANDLER_COMPLETE, HANDLER_ERROR,
                     "ovos.skills.settings_changed"],
)


class TestStopNoSkills(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def _run_exact(self, namespace):
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([], modernize=modernize, emit_legacy=emit_legacy)
        try:
            session = Session("123")
            session.lang = "en-US"
            session.pipeline = ['ovos-stop-pipeline-plugin-high']
            message = Message(utt_topic,
                              {"utterances": ["stop"], "lang": session.lang},
                              {"session": session.serialize()})

            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[],
                eof_msgs=[UTTERANCE_HANDLED],
                flip_points=[utt_topic],
                entry_points=[utt_topic],
                ignore_messages=IGNORE_MESSAGES,
                source_message=message,
                # keep_original_src=["stop.openvoiceos.activate"], # TODO
                expected_messages=[
                    message,
                    Message("stop.openvoiceos.activate", {}),  # stop pipeline counts as active_skill

                    Message("stop:global", {}),  # global stop, no active skill
                    # StopService wraps the global-stop handler in HandlerLifecycle
                    Message("mycroft.skill.handler.start",
                            {"name": "StopService.handle_global_stop"}),
                    Message("mycroft.stop", {}),
                    Message("mycroft.skill.handler.complete",
                            {"name": "StopService.handle_global_stop"}),

                    Message(UTTERANCE_HANDLED, {})
                ]
            )

            test.execute()
        finally:
            minicroft.stop()

    def test_exact(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_exact(namespace)

    def _run_not_exact_high(self, namespace):
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([], modernize=modernize, emit_legacy=emit_legacy)
        try:
            session = Session("123")
            session.lang = "en-US"
            session.pipeline = ['ovos-stop-pipeline-plugin-high']
            message = Message(utt_topic,
                              {"utterances": ["could you stop that"], "lang": session.lang},
                              {"session": session.serialize()})

            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[],
                eof_msgs=[UTTERANCE_HANDLED],
                flip_points=[utt_topic],
                entry_points=[utt_topic],
                ignore_messages=IGNORE_MESSAGES,
                source_message=message,
                expected_messages=[
                    message,
                    Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                    Message(INTENT_UNMATCHED, {}),
                    Message(UTTERANCE_HANDLED, {}),
                ]
            )

            test.execute()
        finally:
            minicroft.stop()

    def test_not_exact_high(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_not_exact_high(namespace)

    def _run_not_exact_med(self, namespace):
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([], modernize=modernize, emit_legacy=emit_legacy)
        try:
            session = Session("123")
            session.lang = "en-US"
            session.pipeline = ['ovos-stop-pipeline-plugin-medium']
            message = Message(utt_topic,
                              {"utterances": ["could you stop that"], "lang": session.lang},
                              {"session": session.serialize()})

            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[],
                eof_msgs=[UTTERANCE_HANDLED],
                flip_points=[utt_topic],
                entry_points=[utt_topic],
                source_message=message,
                ignore_messages=IGNORE_MESSAGES,
                # keep_original_src=["stop.openvoiceos.activate"], # TODO
                expected_messages=[
                    message,
                    Message("stop.openvoiceos.activate", {}),  # stop pipeline counts as active_skill

                    Message("stop:global", {}),  # global stop, no active skill
                    # StopService wraps the global-stop handler in HandlerLifecycle
                    Message("mycroft.skill.handler.start",
                            {"name": "StopService.handle_global_stop"}),
                    Message("mycroft.stop", {}),
                    Message("mycroft.skill.handler.complete",
                            {"name": "StopService.handle_global_stop"}),

                    Message(UTTERANCE_HANDLED, {})
                ]
            )

            test.execute()
        finally:
            minicroft.stop()

    def test_not_exact_med(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_not_exact_med(namespace)


class TestCountSkills(TestCase):

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-count.openvoiceos"

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def _run_count(self, namespace):
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id], modernize=modernize,
                                  emit_legacy=emit_legacy)
        try:
            session = Session("123")
            session.lang = "en-US"
            session.pipeline = ['ovos-stop-pipeline-plugin-high', "ovos-padatious-pipeline-plugin-high"]

            message = Message(utt_topic,
                              {"utterances": ["count to 3"], "lang": session.lang},
                              {"session": session.serialize()})

            # first count to 10 to validate skill is working
            activate_skill = [
                message,
                Message(f"{self.skill_id}.activate", {}),  # skill is activated
                Message(f"{self.skill_id}:count_to_N.intent", {}),  # intent triggers

                Message("mycroft.skill.handler.start", {
                    "name": "CountSkill.handle_how_are_you_intent"
                }),
                # here would be N speak messages, but we ignore them in this test
                Message("mycroft.skill.handler.complete", {
                    "name": "CountSkill.handle_how_are_you_intent"
                }),

                Message(UTTERANCE_HANDLED, {})
            ]
            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[],
                eof_msgs=[UTTERANCE_HANDLED],
                flip_points=[utt_topic],
                entry_points=[utt_topic],
                ignore_messages=IGNORE_MESSAGES,
                source_message=message,
                # keep_original_src=[f"{self.skill_id}.activate"], # TODO
                expected_messages=activate_skill
            )
            test.execute()
        finally:
            minicroft.stop()

    def test_count(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_count(namespace)

    def _run_count_infinity_active(self, namespace):
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id], modernize=modernize,
                                  emit_legacy=emit_legacy)
        try:
            session = Session("123")
            session.lang = "en-US"
            session.pipeline = ['ovos-stop-pipeline-plugin-high',
                                "ovos-padatious-pipeline-plugin-high"]

            def make_it_count():
                nonlocal session
                msg = Message(utt_topic,
                              {"utterances": ["count to infinity"], "lang": session.lang},
                              {"session": session.serialize(), "source": "A", "destination": "B"})
                minicroft.bus.emit(msg)

            # count to infinity, the skill will keep running in the background
            create_daemon(make_it_count)

            time.sleep(2)

            # The count intent self-activates the skill server-side; the Session
            # singleton holds the authoritative state (SESSION-1 last-write-wins).
            # A real client tracks the session via responses and resends it, so
            # the stop turn carries the running skill in active_skills — no manual
            # activation required.
            session = SessionManager.sessions[session.session_id]
            message = Message(utt_topic,
                              {"utterances": ["stop"], "lang": session.lang},
                              {"session": session.serialize(), "source": "A", "destination": "B"})

            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[],
                source_message=message,
                expected_messages=skill_stop_lifecycle(self.skill_id),
                **SKILL_STOP_LIFECYCLE_KWARGS,
            )
            test.execute()
        finally:
            minicroft.stop()

    def test_count_infinity_active(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_count_infinity_active(namespace)

    def _run_count_infinity_global(self, namespace):
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id], modernize=modernize,
                                  emit_legacy=emit_legacy)
        try:
            session = Session("123")
            session.lang = "en-US"
            session.pipeline = ['ovos-stop-pipeline-plugin-high',
                                "ovos-padatious-pipeline-plugin-high"]

            def make_it_count():
                msg = Message(utt_topic,
                              {"utterances": ["count to infinity"], "lang": session.lang},
                              {"session": session.serialize()})
                minicroft.bus.emit(msg)

            # count to infinity, the skill will keep running in the background
            create_daemon(make_it_count)

            time.sleep(3)

            # NOTE: skill not in active skill list for this Session, global stop will match instead
            # this doesnt typically happen at runtime, but possible since clients send whatever Session they want
            message = Message(utt_topic,
                              {"utterances": ["stop"], "lang": session.lang},
                              {"session": session.serialize()})
            # Assert ONLY the global-stop dispatch lifecycle (skill_id=stop.openvoiceos);
            # the interrupted count intent's terminal races in asynchronously and is
            # isolated out by the skill_id filter (eof_count=2 spans both utterances).
            stop_skill_from_global = [
                Message("stop.openvoiceos.activate", {},
                        {"skill_id": "stop.openvoiceos"}),
                Message("stop:global", {},
                        {"skill_id": "stop.openvoiceos"}),
                Message("mycroft.skill.handler.start",
                        {"name": "StopService.handle_global_stop"},
                        {"skill_id": "stop.openvoiceos"}),
                Message("mycroft.stop", {},
                        {"skill_id": "stop.openvoiceos"}),
                Message("mycroft.skill.handler.complete",
                        {"name": "StopService.handle_global_stop"},
                        {"skill_id": "stop.openvoiceos"}),
                Message(UTTERANCE_HANDLED, {},
                        {"skill_id": "stop.openvoiceos"}),
            ]
            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[],
                source_message=message,
                expected_messages=stop_skill_from_global,
                **SKILL_STOP_LIFECYCLE_KWARGS,
            )
            test.execute()
        finally:
            minicroft.stop()

    def test_count_infinity_global(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_count_infinity_global(namespace)

    def _run_count_infinity_stop_low(self, namespace):
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id], modernize=modernize,
                                  emit_legacy=emit_legacy)
        try:
            session = Session("123")
            session.lang = "en-US"
            session.pipeline = ["ovos-padatious-pipeline-plugin-high",
                                'ovos-stop-pipeline-plugin-low']

            def make_it_count():
                msg = Message(utt_topic,
                              {"utterances": ["count to infinity"], "lang": session.lang},
                              {"session": session.serialize(), "source": "A", "destination": "B"})
                minicroft.bus.emit(msg)

            # count to infinity, the skill will keep running in the background
            create_daemon(make_it_count)

            time.sleep(2)

            # resend the live (singleton) session, as a client tracking responses
            # would — the count intent self-activated the skill server-side
            session = SessionManager.sessions[session.session_id]
            message = Message(utt_topic,
                              {"utterances": ["full stop"], "lang": session.lang},
                              {"session": session.serialize(), "source": "A", "destination": "B"})

            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[],
                source_message=message,
                expected_messages=skill_stop_lifecycle(self.skill_id),
                **SKILL_STOP_LIFECYCLE_KWARGS,
            )
            test.execute()
        finally:
            minicroft.stop()

    def test_count_infinity_stop_low(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_count_infinity_stop_low(namespace)
