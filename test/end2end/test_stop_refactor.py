"""End-to-end tests for the StopService OVOSAbstractApplication refactor.

These tests verify behaviour introduced or changed when StopService was
refactored to subclass OVOSAbstractApplication:

1. Vocabulary loaded from .voc files (renamed from .intent) still matches.
2. global_stop.voc phrases trigger a global stop even when skills are active.
3. can_handle=False default: a skill that declines the stop ping is still
   tried via the active-skills fallback.
4. StopService (as OVOSSkill) emits stop.openvoiceos.stop.response when
   mycroft.stop is broadcast — verified via ignore_messages pattern.

Every scenario that injects an utterance is run on BOTH bus namespace paths via
``self.subTest(namespace=...)``:

- **spec**: ``modernize=False, emit_legacy=False`` — the utterance is injected
  on the spec topic ``ovos.utterance.handle`` and no bridging occurs.
- **legacy**: ``modernize=True, emit_legacy=False`` — the utterance is injected
  on the legacy topic ``recognizer_loop:utterance`` and modernized to the spec
  listener.

The captured sequence is identical on both paths except message[0]'s topic
(the injected utterance topic); a fresh MiniCroft is built per path so the
``modernize``/``emit_legacy`` flags can differ.
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
INTENT_MATCHED = SpecMessage.INTENT_MATCHED.value         # ovos.intent.matched (§9.2)
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
# always ignored so they don't pollute assertion counts. The stop pipeline
# speaks on the spec topic ovos.utterance.speak (no legacy mirror because
# emit_legacy=False on both paths).
_STOP_RESPONSES = [
    SPEC_SPEAK,
    "recognizer_loop:audio_output_start",  # TTS mock duck
    "recognizer_loop:audio_output_end",  # TTS mock unduck
    # ovos.intent.matched (§9.2) precedes every dispatch; these scenarios assert
    # stop routing/activation, not the matched broadcast, so it is filtered here.
    INTENT_MATCHED,
    # the §8 handler-lifecycle trio also wraps every dispatch; filtered here
    # (covered by the adapt/padatious suites).
    HANDLER_START,
    HANDLER_COMPLETE,
    HANDLER_ERROR,
    "ovos.common_play.stop.response",
    "common_query.openvoiceos.stop.response",
    "persona.openvoiceos.stop.response",
    "ovos-hivemind-pipeline-plugin.stop.response",
    # StopService now subclasses OVOSAbstractApplication — it also responds to mycroft.stop
    "stop.openvoiceos.stop.response",
]


class TestGlobalStopVocabulary(TestCase):
    """global_stop.voc phrases trigger stop:global when no skills are active.

    These tests verify that the .voc file rename (from .intent) preserved the
    vocabulary content and that voc_match (now delegated to OVOSAbstractApplication)
    correctly distinguishes 'stop' from 'stop everything'.

    No skills are loaded here so mycroft.stop does not produce any extra
    {skill_id}.stop.response messages beyond stop.openvoiceos.stop.response.
    """

    def setUp(self):
        LOG.set_level("DEBUG")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def _run_global_stop_voc_no_active_skills(self, namespace):
        """'stop everything' matches global_stop.voc and emits stop:global."""
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([], modernize=modernize, emit_legacy=emit_legacy)

        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ["ovos-stop-pipeline-plugin-high"]
        message = Message(utt_topic,
                          {"utterances": ["stop everything"], "lang": session.lang},
                          {"session": session.serialize()})

        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=[],
            eof_msgs=[UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            ignore_messages=_STOP_RESPONSES,
            source_message=message,
            expected_messages=[
                message,
                Message("stop.openvoiceos.activate", {}),
                Message("stop:global", {}),
                Message("mycroft.stop", {}),
                Message(UTTERANCE_HANDLED, {}),
            ]
        )
        test.execute()
        minicroft.stop()

    def test_global_stop_voc_no_active_skills(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_global_stop_voc_no_active_skills(namespace)

    def _run_stop_voc_exact_still_works(self, namespace):
        """Bare 'stop' without active skills still matches stop.voc and emits stop:global.

        Regression: confirms the .voc rename did not break the stop vocabulary.
        """
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([], modernize=modernize, emit_legacy=emit_legacy)

        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ["ovos-stop-pipeline-plugin-high"]
        message = Message(utt_topic,
                          {"utterances": ["stop"], "lang": session.lang},
                          {"session": session.serialize()})

        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=[],
            eof_msgs=[UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            ignore_messages=_STOP_RESPONSES,
            source_message=message,
            expected_messages=[
                message,
                Message("stop.openvoiceos.activate", {}),
                Message("stop:global", {}),
                Message("mycroft.stop", {}),
                Message(UTTERANCE_HANDLED, {}),
            ]
        )
        test.execute()
        minicroft.stop()

    def test_stop_voc_exact_still_works(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_stop_voc_exact_still_works(namespace)


class TestGlobalStopVocWithActiveSkill(TestCase):
    """global_stop.voc still triggers stop:global even when a skill is active.

    This is the key distinction from 'stop' + active skill (which emits
    stop:skill instead).  global_stop.voc unconditionally triggers global stop.
    """

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-count.openvoiceos"

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def _run_global_stop_voc_with_active_skill(self, namespace):
        """'stop everything now' emits stop:global regardless of active skills."""
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id], modernize=modernize,
                                  emit_legacy=emit_legacy)

        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ["ovos-stop-pipeline-plugin-high",
                             "ovos-padatious-pipeline-plugin-high"]
        # Activate the count skill so it is in the active-skills list
        session.activate_skill(self.skill_id)

        message = Message(utt_topic,
                          {"utterances": ["stop everything now"], "lang": session.lang},
                          {"session": session.serialize()})

        # count skill also emits stop.response when mycroft.stop is broadcast
        ignore = _STOP_RESPONSES + [f"{self.skill_id}.stop.response"]

        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=[],
            eof_msgs=[UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            ignore_messages=ignore,
            source_message=message,
            expected_messages=[
                message,
                Message("stop.openvoiceos.activate", {}),
                Message("stop:global", {}),
                Message("mycroft.stop", {}),
                Message(UTTERANCE_HANDLED, {}),
            ]
        )
        test.execute()
        minicroft.stop()

    def test_global_stop_voc_with_active_skill(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_global_stop_voc_with_active_skill(namespace)


class TestStopSkillCanHandleFalse(TestCase):
    """Verify the can_handle=False default and active-skills fallback.

    When a skill responds to the stop ping with can_handle=False, want_stop
    is empty and the code falls back to returning all active_skills — so the
    skill is still stopped.  This test drives a running count-to-infinity skill
    and checks the full ping-pong-stop sequence.
    """

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-count.openvoiceos"

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def _run_stop_with_active_skill_ping_pong(self, namespace):
        """Stop a running skill via the ping-pong mechanism.

        Asserts the full message sequence:
          stop.ping → skill.stop.pong (can_handle=True) → stop:skill →
          {skill_id}.stop → {skill_id}.stop.response
        """
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([self.skill_id], modernize=modernize,
                                  emit_legacy=emit_legacy)

        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ["ovos-stop-pipeline-plugin-high",
                             "ovos-padatious-pipeline-plugin-high"]

        def make_it_count():
            nonlocal session
            msg = Message(utt_topic,
                          {"utterances": ["count to infinity"], "lang": session.lang},
                          {"session": session.serialize(), "source": "A", "destination": "B"})
            session.activate_skill(self.skill_id)
            minicroft.bus.emit(msg)

        create_daemon(make_it_count)
        time.sleep(2)

        message = Message(utt_topic,
                          {"utterances": ["stop"], "lang": session.lang},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        expected = [
            message,
            Message(f"{self.skill_id}.stop.ping", {"skill_id": self.skill_id}),
            Message("skill.stop.pong",
                    {"skill_id": self.skill_id, "can_handle": True},
                    {"skill_id": self.skill_id}),
            Message("stop.openvoiceos.activate", context={"skill_id": "stop.openvoiceos"}),
            Message("stop:skill", context={"skill_id": "stop.openvoiceos"}),
            Message(f"{self.skill_id}.stop", context={"skill_id": "stop.openvoiceos"}),
            Message(f"{self.skill_id}.stop.response",
                    {"skill_id": self.skill_id, "result": True},
                    {"skill_id": self.skill_id}),
            Message("mycroft.skill.handler.complete",
                    {"name": "CountSkill.handle_how_are_you_intent"},
                    {"skill_id": self.skill_id}),
            # §8 spec terminal for that active-skill dispatch, emitted by the
            # orchestrator when the daemon intent finally completes (on stop)
            Message(HANDLER_COMPLETE,
                    {},
                    {"skill_id": self.skill_id}),
            Message(UTTERANCE_HANDLED,
                    {},
                    {"skill_id": self.skill_id}),
        ]

        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=[],
            eof_msgs=[],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            keep_original_src=[
                f"{self.skill_id}.stop.ping",
                f"{self.skill_id}.stop",
                "mycroft.skills.abort_question",
                "ovos.skills.converse.force_timeout",
            ],
            async_messages=["ovos.skills.converse.force_timeout"],
            ignore_messages=_STOP_RESPONSES,
            source_message=message,
            expected_messages=expected,
        )
        test.execute()
        minicroft.stop()

    def test_stop_with_active_skill_ping_pong(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_stop_with_active_skill_ping_pong(namespace)


class TestStopServiceAsSkill(TestCase):
    """Verify that StopService behaves correctly as an OVOSAbstractApplication.

    Since StopService now subclasses OVOSAbstractApplication it is registered
    as a skill under skill_id='stop.openvoiceos'.  It therefore:
      - responds to mycroft.stop with stop.openvoiceos.stop.response
      - emits stop.openvoiceos.activate when the stop pipeline matches

    These messages are already filtered via ignore_messages in other tests;
    here we explicitly verify their presence.
    """

    def setUp(self):
        LOG.set_level("DEBUG")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def _run_stop_service_emits_activate_and_stop_response(self, namespace):
        """After a global stop, stop.openvoiceos.activate and stop.openvoiceos.stop.response
        are both emitted — confirming the service participates in skill lifecycle."""
        modernize, emit_legacy, utt_topic = NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([], modernize=modernize, emit_legacy=emit_legacy)

        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ["ovos-stop-pipeline-plugin-high"]
        message = Message(utt_topic,
                          {"utterances": ["stop"], "lang": session.lang},
                          {"session": session.serialize()})

        # Do NOT ignore stop.openvoiceos.stop.response here — we want to assert it appears
        ignore = [m for m in _STOP_RESPONSES if m != "stop.openvoiceos.stop.response"]

        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=[],
            eof_msgs=[UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            ignore_messages=ignore,
            source_message=message,
            expected_messages=[
                message,
                Message("stop.openvoiceos.activate", {}),
                Message("stop:global", {}),
                Message("mycroft.stop", {}),
                # StopService as OVOSSkill handles mycroft.stop and replies
                Message("stop.openvoiceos.stop.response",
                        {"result": False, "skill_id": "stop.openvoiceos"}),
                Message(UTTERANCE_HANDLED, {}),
            ]
        )
        test.execute()
        minicroft.stop()

    def test_stop_service_emits_activate_and_stop_response(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_stop_service_emits_activate_and_stop_response(namespace)
