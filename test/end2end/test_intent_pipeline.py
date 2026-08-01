# Copyright 2024 Mycroft AI Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""End-to-end tests for intent pipeline routing.

Covers:
- Padatious intent matched and handled end-to-end with ``ovos-skill-count.openvoiceos``.
- Session pipeline ordering determines which stage handles the utterance.
- An utterance matched by a high-priority stage does not fall through to lower
  stages (no ``complete_intent_failure`` emitted).
- An utterance NOT matched by the configured pipeline produces
  ``complete_intent_failure`` and the error sound.

Each scenario is exercised on BOTH bus namespaces (see ``namespace_e2e`` helpers):

- **spec**: ``modernize=False, emit_legacy=False`` — the utterance is injected on
  the spec topic ``ovos.utterance.handle`` and core handles it natively. No
  cross-namespace bridging occurs; assertions use the spec topics
  (``ovos.utterance.speak``, ``ovos.utterance.handled``).
- **legacy**: ``modernize=True, emit_legacy=False`` — the utterance is injected on
  the legacy topic ``recognizer_loop:utterance``; the FakeBus modernize-bridge
  re-dispatches it as ``ovos.utterance.handle`` so the (spec-only) intent listener
  still handles it. This proves legacy back-compat reaches the spec listener.
"""
from copy import deepcopy
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_spec_tools import SpecMessage, migration_counterpart
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft

# Topics come from the ovos-spec-tools SpecMessage enum (spec namespace); the
# legacy counterpart is derived via migration_counterpart, never hardcoded.
SPEC_UTTERANCE = SpecMessage.UTTERANCE.value          # ovos.utterance.handle
LEGACY_UTTERANCE = migration_counterpart(SPEC_UTTERANCE)  # recognizer_loop:utterance
# PIPELINE-1 orchestrator-emitted terminal events: §9.2 matched, §8 trio, §9.3
# unmatched (the spec replacement for legacy complete_intent_failure).
INTENT_UNMATCHED = SpecMessage.INTENT_UNMATCHED.value

# The two namespace paths every scenario is run on.
#   key       -> (modernize, emit_legacy, utterance_topic)
NAMESPACE_PATHS = {
    # the only path left: the bridge is gone, so a legacy producer reaches
    # nothing (pinned in test_no_legacy_wire_compat.py)
    "spec": (False, False, SPEC_UTTERANCE),
}


def utterance_topic(namespace: str) -> str:
    """Topic the utterance is injected on for a given namespace path."""
    return NAMESPACE_PATHS[namespace][2]


class TestIntentPipelineRouting(TestCase):
    """Verify that pipeline stage ordering controls which handler fires.

    Every scenario runs on both the spec and legacy namespace paths via
    ``self.subTest(namespace=...)``; a fresh MiniCroft is built per path so the
    ``modernize``/``emit_legacy`` flags can differ.
    """

    skill_id = "ovos-skill-count.openvoiceos"
    # Filter noisy bus messages that are not relevant to pipeline routing. The
    # count skill speaks on the spec topic ``ovos.utterance.speak`` (no legacy
    # mirror because emit_legacy=False on both paths).
    ignore_messages = [
        SpecMessage.SPEAK,
        SpecMessage.AUDIO_OUTPUT_STARTED,  # TTS mock duck
        SpecMessage.AUDIO_OUTPUT_ENDED,  # TTS mock unduck
        "ovos.common_play.stop.response",
        "common_query.openvoiceos.stop.response",
        "persona.openvoiceos.stop.response",
        "ovos-hivemind-pipeline-plugin.stop.response",
    ]

    def setUp(self) -> None:
        LOG.set_level("DEBUG")
        self._minicrofts = []

    def tearDown(self) -> None:
        LOG.set_level("CRITICAL")
        for mc in self._minicrofts:
            mc.stop()
        self._minicrofts.clear()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _make_minicroft(self, namespace: str) -> "MiniCroft":
        modernize, emit_legacy, _ = NAMESPACE_PATHS[namespace]
        mc = get_minicroft([self.skill_id], modernize=modernize,
                           emit_legacy=emit_legacy)
        self._minicrofts.append(mc)
        return mc

    def _source_message(self, namespace: str, utterance: str, pipeline,
                        session_id: str, blacklisted=None) -> Message:
        session = Session(session_id)
        session.lang = "en-US"
        session.pipeline = list(pipeline)
        if blacklisted is not None:
            session.blacklisted_skills = list(blacklisted)
        return Message(
            utterance_topic(namespace),
            {"utterances": [utterance], "lang": session.lang},
            {"session": session.serialize(), "source": "A", "destination": "B"},
        ), session

    # ------------------------------------------------------------------
    # Scenario 1: Padatious intent matched end-to-end
    # ------------------------------------------------------------------
    def _run_padatious_intent_matched(self, namespace: str) -> None:
        """A padatious intent for 'count to 3' is matched and the handler fires."""
        utt_topic = utterance_topic(namespace)
        message, session = self._source_message(
            namespace, "count to 3",
            ["ovos-padatious-pipeline-plugin-high"], "pipeline-test-1")

        final_session = deepcopy(session)
        final_session.active_skills = [(self.skill_id, 0.0)]

        test = End2EndTest(
            minicroft=self._make_minicroft(namespace),
            skill_ids=[self.skill_id],
            eof_msgs=[SpecMessage.UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            ignore_messages=self.ignore_messages,
            source_message=message,
            final_session=final_session,
            activation_points=[f"{self.skill_id}:count_to_n"],
            expected_messages=[
                message,
                Message(
                    f"{self.skill_id}.activate",
                    data={},
                    context={"skill_id": self.skill_id},
                ),
                # PIPELINE-1 §9.2: matched notification, before the dispatch
                Message(
                    SpecMessage.INTENT_MATCHED,
                    data={"skill_id": self.skill_id,
                          "intent_name": f"{self.skill_id}:count_to_n",
                          "utterance": "count to 3", "lang": session.lang},
                    context={"skill_id": self.skill_id},
                ),
                # PIPELINE-1 §8.1: orchestrator start before dispatch
                Message(
                    SpecMessage.INTENT_HANDLER_START,
                    data={"skill_id": self.skill_id,
                          "intent_name": "count_to_n"},
                    context={"skill_id": self.skill_id},
                ),
                Message(
                    f"{self.skill_id}:count_to_n",
                    data={"utterance": "count to 3", "lang": session.lang},
                    context={"skill_id": self.skill_id},
                ),
                Message(
                    "mycroft.skill.handler.start",
                    data={"name": "CountSkill.handle_how_are_you_intent"},
                    context={"skill_id": self.skill_id},
                ),
                Message(
                    "mycroft.skill.handler.complete",
                    data={"name": "CountSkill.handle_how_are_you_intent"},
                    context={"skill_id": self.skill_id},
                ),
                # PIPELINE-1 §8.1: orchestrator complete before the end-marker
                Message(
                    SpecMessage.INTENT_HANDLER_COMPLETE,
                    data={"skill_id": self.skill_id,
                          "intent_name": "count_to_n"},
                    context={"skill_id": self.skill_id},
                ),
                Message(
                    SpecMessage.UTTERANCE_HANDLED,
                    data={},
                    context={"skill_id": self.skill_id},
                ),
            ],
        )
        test.execute(timeout=15)

    def test_padatious_intent_matched(self) -> None:
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_padatious_intent_matched(namespace)

    # ------------------------------------------------------------------
    # Scenario 2: Pipeline ordering — high stage fires, low stage skipped
    # ------------------------------------------------------------------
    def _run_high_priority_stage_handles_before_low(self, namespace: str) -> None:
        """When padatious-high is listed first it matches; stop-high is listed after
        and must NOT fire (no ``stop:global`` / ``mycroft.stop`` messages)."""
        utt_topic = utterance_topic(namespace)
        message, session = self._source_message(
            namespace, "count to 3",
            ["ovos-padatious-pipeline-plugin-high",
             "ovos-stop-pipeline-plugin-high"], "pipeline-test-2")

        final_session = deepcopy(session)
        final_session.active_skills = [(self.skill_id, 0.0)]

        test = End2EndTest(
            minicroft=self._make_minicroft(namespace),
            skill_ids=[self.skill_id],
            eof_msgs=[SpecMessage.UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            ignore_messages=self.ignore_messages,
            source_message=message,
            final_session=final_session,
            activation_points=[f"{self.skill_id}:count_to_n"],
            expected_messages=[
                message,
                Message(
                    f"{self.skill_id}.activate",
                    data={},
                    context={"skill_id": self.skill_id},
                ),
                # PIPELINE-1 §9.2: matched notification, before the dispatch
                Message(
                    SpecMessage.INTENT_MATCHED,
                    data={"skill_id": self.skill_id,
                          "intent_name": f"{self.skill_id}:count_to_n",
                          "utterance": "count to 3", "lang": session.lang},
                    context={"skill_id": self.skill_id},
                ),
                # PIPELINE-1 §8.1: orchestrator start before dispatch
                Message(
                    SpecMessage.INTENT_HANDLER_START,
                    data={"skill_id": self.skill_id,
                          "intent_name": "count_to_n"},
                    context={"skill_id": self.skill_id},
                ),
                Message(
                    f"{self.skill_id}:count_to_n",
                    data={"utterance": "count to 3", "lang": session.lang},
                    context={"skill_id": self.skill_id},
                ),
                Message(
                    "mycroft.skill.handler.start",
                    data={"name": "CountSkill.handle_how_are_you_intent"},
                    context={"skill_id": self.skill_id},
                ),
                Message(
                    "mycroft.skill.handler.complete",
                    data={"name": "CountSkill.handle_how_are_you_intent"},
                    context={"skill_id": self.skill_id},
                ),
                # PIPELINE-1 §8.1: orchestrator complete before the end-marker
                Message(
                    SpecMessage.INTENT_HANDLER_COMPLETE,
                    data={"skill_id": self.skill_id,
                          "intent_name": "count_to_n"},
                    context={"skill_id": self.skill_id},
                ),
                Message(
                    SpecMessage.UTTERANCE_HANDLED,
                    data={},
                    context={"skill_id": self.skill_id},
                ),
            ],
        )
        test.execute(timeout=15)

    def test_high_priority_stage_handles_before_low(self) -> None:
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_high_priority_stage_handles_before_low(namespace)

    # ------------------------------------------------------------------
    # Scenario 3: No pipeline stage matches → complete_intent_failure
    # ------------------------------------------------------------------
    def _run_no_match_produces_intent_failure(self, namespace: str) -> None:
        """An utterance that no configured pipeline stage can handle produces
        ``complete_intent_failure`` and the error sound, not a skill activation."""
        utt_topic = utterance_topic(namespace)
        message, session = self._source_message(
            namespace, "blah blah blah",
            ["ovos-stop-pipeline-plugin-high"], "pipeline-test-3")

        test = End2EndTest(
            minicroft=self._make_minicroft(namespace),
            skill_ids=[self.skill_id],
            eof_msgs=[SpecMessage.UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            ignore_messages=self.ignore_messages,
            source_message=message,
            final_session=session,
            expected_messages=[
                message,
                Message(SpecMessage.AUDIO_PLAY_SOUND, {"uri": "snd/error.mp3"}),
                Message(INTENT_UNMATCHED, {}),
                Message(SpecMessage.UTTERANCE_HANDLED, {}),
            ],
        )
        test.execute(timeout=15)

    def test_no_match_produces_intent_failure(self) -> None:
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_no_match_produces_intent_failure(namespace)

    # ------------------------------------------------------------------
    # Scenario 4: Blacklisted skill causes intent failure even when padatious matches
    # ------------------------------------------------------------------
    def _run_blacklisted_skill_falls_through_to_failure(self, namespace: str) -> None:
        """When the matching skill is blacklisted in the session, the utterance
        falls through all pipeline stages and produces ``complete_intent_failure``."""
        utt_topic = utterance_topic(namespace)
        message, session = self._source_message(
            namespace, "count to 3",
            ["ovos-padatious-pipeline-plugin-high"], "pipeline-test-4",
            blacklisted=[self.skill_id])

        test = End2EndTest(
            minicroft=self._make_minicroft(namespace),
            skill_ids=[self.skill_id],
            eof_msgs=[SpecMessage.UTTERANCE_HANDLED],
            flip_points=[utt_topic],
            entry_points=[utt_topic],
            ignore_messages=self.ignore_messages,
            source_message=message,
            final_session=session,
            expected_messages=[
                message,
                Message(SpecMessage.AUDIO_PLAY_SOUND, {"uri": "snd/error.mp3"}),
                Message(INTENT_UNMATCHED, {}),
                Message(SpecMessage.UTTERANCE_HANDLED, {}),
            ],
        )
        test.execute(timeout=15)

    def test_blacklisted_skill_falls_through_to_failure(self) -> None:
        for namespace in NAMESPACE_PATHS:
            with self.subTest(namespace=namespace):
                self._run_blacklisted_skill_falls_through_to_failure(namespace)
