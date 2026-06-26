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
from ovos_bus_client.session import Session
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
    "ovos.common_play.stop.response",
    "common_query.openvoiceos.stop.response",
    "persona.openvoiceos.stop.response",
    "ovos-hivemind-pipeline-plugin.stop.response",
    # StopService now subclasses OVOSAbstractApplication,
    # so it also emits a stop.response when mycroft.stop is broadcast
    "stop.openvoiceos.stop.response",
]


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
                    Message("mycroft.stop", {}),

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
                    Message("complete_intent_failure", {}),
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
                    Message("mycroft.stop", {}),

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
                session.activate_skill(self.skill_id)  # ensure in active skill list
                minicroft.bus.emit(msg)

            # count to infinity, the skill will keep running in the background
            create_daemon(make_it_count)

            time.sleep(2)

            message = Message(utt_topic,
                              {"utterances": ["stop"], "lang": session.lang},
                              {"session": session.serialize(), "source": "A", "destination": "B"})

            stop_skill_active = [
                message,
                Message(f"{self.skill_id}.stop.ping",
                        {"skill_id": self.skill_id}),
                Message("skill.stop.pong",
                        {"skill_id": self.skill_id, "can_handle": True},
                        {"skill_id": self.skill_id}),

                Message("stop.openvoiceos.activate",
                        context={"skill_id": "stop.openvoiceos"}),
                Message("stop:skill",
                        context={"skill_id": "stop.openvoiceos"}),
                Message(f"{self.skill_id}.stop",
                        context={"skill_id": "stop.openvoiceos"}),
                Message(f"{self.skill_id}.stop.response",
                        {"skill_id": self.skill_id, "result": True},
                        {"skill_id": self.skill_id}),

                # async stop pipeline callback emits these messages
                # but we cant guarantee where in the test they will be emitted

                # if skill is in middle of get_response
                #Message("mycroft.skills.abort_question",
                #        {"skill_id": self.skill_id},
                #        {"skill_id": self.skill_id}),

                # if skill is in active_list
                #Message("ovos.skills.converse.force_timeout",
                #        {"skill_id": self.skill_id},
                #        {"skill_id": self.skill_id}),

                # if skill is executing TTS
                #Message("mycroft.audio.speech.stop",
                #        {"skill_id": self.skill_id},
                #        {"skill_id": self.skill_id}),

                # the intent running in the daemon thread exits cleanly
                Message("mycroft.skill.handler.complete",
                        {"name": "CountSkill.handle_how_are_you_intent"},
                        {"skill_id": self.skill_id}),
                Message(UTTERANCE_HANDLED,
                        {"name": "CountSkill.handle_how_are_you_intent"},
                        {"skill_id": self.skill_id})
            ]
            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[],
                eof_msgs=[],
                flip_points=[utt_topic],
                entry_points=[utt_topic],
                # messages in 'keep_original_src' would not be sent to hivemind clients
                # i.e. they are directed towards ovos-core
                keep_original_src=[f"{self.skill_id}.stop.ping",
                                   f"{self.skill_id}.stop",
                                   "mycroft.skills.abort_question",
                                   "ovos.skills.converse.force_timeout",
                                   # "stop.openvoiceos.activate" # TODO
                                   ],
                async_messages=[
                    "ovos.skills.converse.force_timeout"
                ],  # order that it wil be received unknown
                ignore_messages=IGNORE_MESSAGES,
                source_message=message,
                expected_messages=stop_skill_active
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
            stop_skill_from_global = [
                message,
                Message("stop.openvoiceos.activate", {}),  # stop pipeline counts as active_skill

                Message("stop:global", {}),  # global stop, no active skill
                Message("mycroft.stop", {}),

                Message(f"{self.skill_id}.stop.response",
                        {"skill_id": self.skill_id, "result": True}),
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
                expected_messages=stop_skill_from_global,
                #keep_original_src=["stop.openvoiceos.activate"],  # TODO
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
                nonlocal session
                msg = Message(utt_topic,
                              {"utterances": ["count to infinity"], "lang": session.lang},
                              {"session": session.serialize(), "source": "A", "destination": "B"})
                session.activate_skill(self.skill_id)  # ensure in active skill list
                minicroft.bus.emit(msg)

            # count to infinity, the skill will keep running in the background
            create_daemon(make_it_count)

            time.sleep(2)

            message = Message(utt_topic,
                              {"utterances": ["full stop"], "lang": session.lang},
                              {"session": session.serialize(), "source": "A", "destination": "B"})

            stop_skill_active = [
                message,
                Message(f"{self.skill_id}.stop.ping",
                        {"skill_id": self.skill_id}),
                Message("skill.stop.pong",
                        {"skill_id": self.skill_id, "can_handle": True},
                        {"skill_id": self.skill_id}),

                Message("stop.openvoiceos.activate",
                        context={"skill_id": "stop.openvoiceos"}),
                Message("stop:skill",
                        context={"skill_id": "stop.openvoiceos"}),
                Message(f"{self.skill_id}.stop",
                        context={"skill_id": "stop.openvoiceos"}),
                Message(f"{self.skill_id}.stop.response",
                        {"skill_id": self.skill_id, "result": True},
                        {"skill_id": self.skill_id}),

                # async stop pipeline callback emits these messages
                # but we cant guarantee where in the test they will be emitted

                # if skill is in middle of get_response
                #Message("mycroft.skills.abort_question",
                #        {"skill_id": self.skill_id},
                #        {"skill_id": self.skill_id}),

                # if skill is in active_list
                #Message("ovos.skills.converse.force_timeout",
                #        {"skill_id": self.skill_id},
                #        {"skill_id": self.skill_id}),

                # if skill is executing TTS
                #Message("mycroft.audio.speech.stop",
                #        {"skill_id": self.skill_id},
                #        {"skill_id": self.skill_id}),

                # the intent running in the daemon thread exits cleanly
                Message("mycroft.skill.handler.complete",
                        {"name": "CountSkill.handle_how_are_you_intent"},
                        {"skill_id": self.skill_id}),
                Message(UTTERANCE_HANDLED,
                        {"name": "CountSkill.handle_how_are_you_intent"},
                        {"skill_id": self.skill_id})
            ]
            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[],
                eof_msgs=[],
                flip_points=[utt_topic],
                entry_points=[utt_topic],
                # messages in 'keep_original_src' would not be sent to hivemind clients
                # i.e. they are directed towards ovos-core
                keep_original_src=[f"{self.skill_id}.stop.ping",
                                   f"{self.skill_id}.stop",
                                   "mycroft.skills.abort_question",
                                   # "stop.openvoiceos.activate", # TODO
                                   "ovos.skills.converse.force_timeout"],
                ignore_messages=IGNORE_MESSAGES,
                async_messages=[
                    "ovos.skills.converse.force_timeout"
                ],  # order that it wil be received unknown
                source_message=message,
                expected_messages=stop_skill_active
            )
            test.execute()
        finally:
            minicroft.stop()

    def test_count_infinity_stop_low(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_count_infinity_stop_low(namespace)
