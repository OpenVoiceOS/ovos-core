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
"""
from copy import deepcopy
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft


class TestIntentPipelineRouting(TestCase):
    """Verify that pipeline stage ordering controls which handler fires."""

    def setUp(self) -> None:
        """Set up a shared MiniCroft instance with the count skill loaded."""
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-count.openvoiceos"
        self.minicroft = get_minicroft([self.skill_id])
        # Filter noisy bus messages that are not relevant to pipeline routing.
        self.ignore_messages = [
            "speak",
            "ovos.common_play.stop.response",
            "common_query.openvoiceos.stop.response",
            "persona.openvoiceos.stop.response",
            "ovos-hivemind-pipeline-plugin.stop.response",
            "stop.openvoiceos.stop.response",
        ]

    def tearDown(self) -> None:
        """Stop MiniCroft and restore log level."""
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    # ------------------------------------------------------------------
    # Scenario 1: Padatious intent matched end-to-end
    # ------------------------------------------------------------------

    def test_padatious_intent_matched(self) -> None:
        """A padatious intent for 'count to 3' is matched and the handler fires."""
        session = Session("pipeline-test-1")
        session.lang = "en-US"
        session.pipeline = ["ovos-padatious-pipeline-plugin-high"]

        message = Message(
            "recognizer_loop:utterance",
            {"utterances": ["count to 3"], "lang": session.lang},
            {"session": session.serialize(), "source": "A", "destination": "B"},
        )

        final_session = deepcopy(session)
        final_session.active_skills = [(self.skill_id, 0.0)]

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            ignore_messages=self.ignore_messages,
            source_message=message,
            final_session=final_session,
            activation_points=[f"{self.skill_id}:count_to_N.intent"],
            expected_messages=[
                message,
                Message(
                    f"{self.skill_id}.activate",
                    data={},
                    context={"skill_id": self.skill_id},
                ),
                Message(
                    f"{self.skill_id}:count_to_N.intent",
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
                Message(
                    "ovos.utterance.handled",
                    data={},
                    context={"skill_id": self.skill_id},
                ),
            ],
        )

        test.execute(timeout=15)

    # ------------------------------------------------------------------
    # Scenario 2: Pipeline ordering — high stage fires, low stage skipped
    # ------------------------------------------------------------------

    def test_high_priority_stage_handles_before_low(self) -> None:
        """When padatious-high is listed first it matches; stop-high is listed after
        and must NOT fire (no ``stop:global`` / ``mycroft.stop`` messages)."""
        session = Session("pipeline-test-2")
        session.lang = "en-US"
        # padatious-high before stop-high: count should be handled by padatious
        session.pipeline = [
            "ovos-padatious-pipeline-plugin-high",
            "ovos-stop-pipeline-plugin-high",
        ]

        message = Message(
            "recognizer_loop:utterance",
            {"utterances": ["count to 3"], "lang": session.lang},
            {"session": session.serialize(), "source": "A", "destination": "B"},
        )

        final_session = deepcopy(session)
        final_session.active_skills = [(self.skill_id, 0.0)]

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            ignore_messages=self.ignore_messages,
            source_message=message,
            final_session=final_session,
            activation_points=[f"{self.skill_id}:count_to_N.intent"],
            expected_messages=[
                message,
                Message(
                    f"{self.skill_id}.activate",
                    data={},
                    context={"skill_id": self.skill_id},
                ),
                Message(
                    f"{self.skill_id}:count_to_N.intent",
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
                Message(
                    "ovos.utterance.handled",
                    data={},
                    context={"skill_id": self.skill_id},
                ),
            ],
        )

        test.execute(timeout=15)

    # ------------------------------------------------------------------
    # Scenario 3: No pipeline stage matches → complete_intent_failure
    # ------------------------------------------------------------------

    def test_no_match_produces_intent_failure(self) -> None:
        """An utterance that no configured pipeline stage can handle produces
        ``complete_intent_failure`` and the error sound, not a skill activation."""
        session = Session("pipeline-test-3")
        session.lang = "en-US"
        # Only stop-high is configured; "blah blah blah" won't match stop
        session.pipeline = ["ovos-stop-pipeline-plugin-high"]

        message = Message(
            "recognizer_loop:utterance",
            {"utterances": ["blah blah blah"], "lang": session.lang},
            {"session": session.serialize(), "source": "A", "destination": "B"},
        )

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            ignore_messages=self.ignore_messages,
            source_message=message,
            final_session=session,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {}),
                Message("ovos.utterance.handled", {}),
            ],
        )

        test.execute(timeout=15)

    # ------------------------------------------------------------------
    # Scenario 4: Blacklisted skill causes intent failure even when padatious matches
    # ------------------------------------------------------------------

    def test_blacklisted_skill_falls_through_to_failure(self) -> None:
        """When the matching skill is blacklisted in the session, the utterance
        falls through all pipeline stages and produces ``complete_intent_failure``."""
        session = Session("pipeline-test-4")
        session.lang = "en-US"
        session.pipeline = ["ovos-padatious-pipeline-plugin-high"]
        session.blacklisted_skills = [self.skill_id]

        message = Message(
            "recognizer_loop:utterance",
            {"utterances": ["count to 3"], "lang": session.lang},
            {"session": session.serialize(), "source": "A", "destination": "B"},
        )

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[self.skill_id],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            ignore_messages=self.ignore_messages,
            source_message=message,
            final_session=session,
            expected_messages=[
                message,
                Message("mycroft.audio.play_sound", {"uri": "snd/error.mp3"}),
                Message("complete_intent_failure", {}),
                Message("ovos.utterance.handled", {}),
            ],
        )

        test.execute(timeout=15)
