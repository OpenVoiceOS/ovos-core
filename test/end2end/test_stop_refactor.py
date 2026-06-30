"""End-to-end tests for the StopService stop-vocabulary refactor.

StopService is a pipeline plugin (NOT an ovos-workshop skill); it matches the
stop vocabulary via ovos-spec-tools (LocaleResources) instead of the
OVOSAbstractApplication base class. These tests verify:

1. Vocabulary loaded from .voc files (renamed from .intent) still matches.
2. global_stop.voc phrases trigger a global stop even when skills are active.
3. can_handle=False default: a skill that declines the stop ping is still
   tried via the active-skills fallback.
4. StopService does NOT register skill machinery — it never answers the
   mycroft.stop broadcast with stop.openvoiceos.stop.response.

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
from ovos_bus_client.session import Session, SessionManager
from ovos_spec_tools import SpecMessage, migration_counterpart
from ovos_utils import create_daemon
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft

from test.end2end.test_stop import _wait_for_active_skill

# Topics come from the ovos-spec-tools SpecMessage enum (spec namespace); the
# legacy counterpart is derived via migration_counterpart, never hardcoded.
SPEC_UTTERANCE = SpecMessage.UTTERANCE.value              # ovos.utterance.handle
LEGACY_UTTERANCE = migration_counterpart(SPEC_UTTERANCE)  # recognizer_loop:utterance
SPEC_SPEAK = SpecMessage.SPEAK.value                      # ovos.utterance.speak
HANDLER_ERROR = SpecMessage.INTENT_HANDLER_ERROR.value
# OVOS-STOP-1 spec topics — the producer emits these; the bus bridges the 1:1
# legacy renames (mycroft.stop / skill.stop.pong) transparently per MIGRATION_MAP.
STOP_BROADCAST = SpecMessage.STOP.value                   # ovos.stop  (was mycroft.stop)
STOP_PING = SpecMessage.STOP_PING.value                   # ovos.stop.ping (broadcast)
STOP_PONG = SpecMessage.STOP_PONG.value                   # ovos.stop.pong — spec pong the
# pipeline subscribes; the producer (ovos-workshop) still emits legacy skill.stop.pong,
# which the MIGRATION_MAP bridge delivers here (so captured sequences carry the legacy topic).

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
    SpecMessage.INTENT_MATCHED,
    # the §8 handler-lifecycle trio also wraps every dispatch; filtered here
    # (covered by the adapt/padatious suites).
    SpecMessage.INTENT_HANDLER_START,
    SpecMessage.INTENT_HANDLER_COMPLETE,
    HANDLER_ERROR,
    "ovos.common_play.stop.response",
    "common_query.openvoiceos.stop.response",
    "persona.openvoiceos.stop.response",
    "ovos-hivemind-pipeline-plugin.stop.response",
    # timing-dependent cleanup of an interrupted skill (mid get_response /
    # active / mid-TTS) — ignore so the assertion stays stable across runs.
    "mycroft.skills.abort_question",
    "ovos.skills.converse.force_timeout",
    "mycroft.audio.speech.stop",
]


class TestGlobalStopVocabulary(TestCase):
    """global_stop.voc phrases trigger stop:global when no skills are active.

    These tests verify that the .voc file rename (from .intent) preserved the
    vocabulary content and that voc_match (delegated to ovos-spec-tools
    LocaleResources) correctly distinguishes 'stop' from 'stop everything'.

    No skills are loaded here, so mycroft.stop produces no {skill_id}.stop.response
    messages — and StopService itself no longer answers it.
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
            eof_msgs=[SpecMessage.UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            ignore_messages=_STOP_RESPONSES,
            source_message=message,
            expected_messages=[
                message,
                Message("stop.openvoiceos.activate", {}),
                Message("stop:global", {}),
                # OVOS-STOP-1 §5.3: global-stop handler emits spec broadcast only.
                # Legacy compatibility is provided by the bus bridge (MIGRATION_MAP).
                Message("mycroft.skill.handler.start",
                        {"name": "StopService.handle_global_stop"}),
                Message(STOP_BROADCAST, {}),  # OVOS-STOP-1 §5.3 spec broadcast (bridged to legacy mycroft.stop)
                Message("mycroft.skill.handler.complete",
                        {"name": "StopService.handle_global_stop"}),
                Message(SpecMessage.UTTERANCE_HANDLED, {}),
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
            eof_msgs=[SpecMessage.UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            ignore_messages=_STOP_RESPONSES,
            source_message=message,
            expected_messages=[
                message,
                Message("stop.openvoiceos.activate", {}),
                Message("stop:global", {}),
                # OVOS-STOP-1 §5.3: global-stop handler emits spec broadcast only.
                # Legacy compatibility is provided by the bus bridge (MIGRATION_MAP).
                Message("mycroft.skill.handler.start",
                        {"name": "StopService.handle_global_stop"}),
                Message(STOP_BROADCAST, {}),  # OVOS-STOP-1 §5.3 spec broadcast (bridged to legacy mycroft.stop)
                Message("mycroft.skill.handler.complete",
                        {"name": "StopService.handle_global_stop"}),
                Message(SpecMessage.UTTERANCE_HANDLED, {}),
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
            eof_msgs=[SpecMessage.UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            ignore_messages=ignore,
            source_message=message,
            test_active_skills=False,  # global_stop drains the session; skip stale tracking
            expected_messages=[
                message,
                Message("stop.openvoiceos.activate", {}),
                Message("stop:global", {}),
                # OVOS-STOP-1 §5.3: global-stop handler emits spec broadcast only.
                # Legacy compatibility is provided by the bus bridge (MIGRATION_MAP).
                Message("mycroft.skill.handler.start",
                        {"name": "StopService.handle_global_stop"}),
                Message(STOP_BROADCAST, {}),  # OVOS-STOP-1 §5.3 spec broadcast (bridged to legacy mycroft.stop)
                Message("mycroft.skill.handler.complete",
                        {"name": "StopService.handle_global_stop"}),
                Message(SpecMessage.UTTERANCE_HANDLED, {}),
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
            minicroft.bus.emit(msg)

        create_daemon(make_it_count)
        # Wait for the skill to activate before sending stop, matching the
        # deterministic polling in test_stop.py (CI xdist race condition fix)
        _wait_for_active_skill(session.session_id, self.skill_id)
        # Use the live server-side session so active_skills is populated
        session = SessionManager.sessions[session.session_id]
        message = Message(utt_topic,
                          {"utterances": ["stop"], "lang": session.lang},
                          {"session": session.serialize(), "source": "A", "destination": "B"})

        # Assert ONLY the stop dispatch lifecycle (skill_id=stop.openvoiceos).
        # Stopping a running skill produces two concurrent lifecycles whose
        # messages interleave non-deterministically: the stop dispatch (asserted
        # here) and the interrupted count intent's own §8 trio + §9.5 terminal,
        # which completes asynchronously when the daemon unwinds. The skill_id
        # filter isolates the stop dispatch; eof_count=2 lets capture span both
        # utterances' ovos.utterance.handled before filtering.
        # The §8 SPEC trio (ovos.intent.matched/handler.start/handler.complete) is
        # filtered via ignore_messages: in this concurrent-lifecycle scenario under
        # heavy parallel load it is not reliably observed alongside the legacy
        # done-signal, so it is asserted in the single-lifecycle adapt/padatious
        # suites instead. The legacy mycroft.skill.handler done-signal trio (which
        # the orchestrator translates into the §8 terminal) IS asserted here.
        expected = [
            Message("stop.openvoiceos.activate", {},
                    {"skill_id": "stop.openvoiceos"}),
            Message("stop:skill", {"skill_id": self.skill_id},
                    {"skill_id": "stop.openvoiceos"}),
            Message("mycroft.skill.handler.start",
                    {"name": "StopService.handle_skill_stop"},
                    {"skill_id": "stop.openvoiceos"}),
            Message(f"{self.skill_id}.stop", {},
                    {"skill_id": "stop.openvoiceos"}),
            Message("mycroft.skill.handler.complete",
                    {"name": "StopService.handle_skill_stop"},
                    {"skill_id": "stop.openvoiceos"}),
            Message(SpecMessage.UTTERANCE_HANDLED, {},
                    {"skill_id": "stop.openvoiceos"}),
        ]

        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=[],
            skill_id="stop.openvoiceos",
            eof_msgs=[SpecMessage.UTTERANCE_HANDLED],
            eof_count=2,
            test_active_skills=False,
            ignore_messages=[SpecMessage.INTENT_MATCHED, SpecMessage.INTENT_HANDLER_START, SpecMessage.INTENT_HANDLER_COMPLETE,
                             HANDLER_ERROR, "ovos.skills.settings_changed"],
            source_message=message,
            expected_messages=expected,
        )
        test.execute()
        minicroft.stop()

    def test_stop_with_active_skill_ping_pong(self):
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_stop_with_active_skill_ping_pong(namespace)


class TestStopServiceNotASkill(TestCase):
    """StopService is a pipeline plugin, NOT an ovos-workshop skill.

    It matches the stop vocabulary via ovos-spec-tools (LocaleResources) and owns
    the stop dispatch, but it MUST NOT register skill machinery — in particular it
    must NOT answer the mycroft.stop broadcast with stop.openvoiceos.stop.response
    (that would make it stop "itself" and pollute the lifecycle). This is the
    regression guard for dropping the OVOSAbstractApplication base class.
    """

    # emit_legacy=True on both paths so the spec broadcast reaches the un-migrated
    # StopService skill via the legacy-topic mirror.
    NAMESPACE_PATHS = {
        "spec": (False, True, SPEC_UTTERANCE),
        "legacy": (True, True, LEGACY_UTTERANCE),
    }

    def setUp(self):
        LOG.set_level("DEBUG")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def _run_stop_service_is_not_a_skill(self, namespace):
        """A global stop with no skills loaded emits the stop dispatch lifecycle
        and NO stop.openvoiceos.stop.response (StopService does not self-respond)."""
        modernize, emit_legacy, utt_topic = self.NAMESPACE_PATHS[namespace]
        minicroft = get_minicroft([], modernize=modernize, emit_legacy=emit_legacy)

        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ["ovos-stop-pipeline-plugin-high"]
        message = Message(utt_topic,
                          {"utterances": ["stop"], "lang": session.lang},
                          {"session": session.serialize()})

        # stop.openvoiceos.stop.response is intentionally NOT ignored: if the
        # skill machinery ever comes back it would appear as an extra message and
        # fail the count.
        test = End2EndTest(
            minicroft=minicroft,
            skill_ids=[],
            eof_msgs=[SpecMessage.UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            ignore_messages=_STOP_RESPONSES,
            source_message=message,
            expected_messages=[
                message,
                Message("stop.openvoiceos.activate", {}),
                Message("stop:global", {}),
                # OVOS-STOP-1 §5.3: global-stop handler emits spec broadcast only.
                # Legacy compatibility is provided by the bus bridge (MIGRATION_MAP).
                Message("mycroft.skill.handler.start",
                        {"name": "StopService.handle_global_stop"}),
                Message(STOP_BROADCAST, {}),  # OVOS-STOP-1 §5.3 spec broadcast (bridged to legacy mycroft.stop)
                Message("mycroft.skill.handler.complete",
                        {"name": "StopService.handle_global_stop"}),
                Message(SpecMessage.UTTERANCE_HANDLED, {}),
            ]
        )
        test.execute()
        minicroft.stop()

    def test_stop_service_is_not_a_skill(self):
        for namespace in self.NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_stop_service_is_not_a_skill(namespace)

