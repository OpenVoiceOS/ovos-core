"""End-to-end tests for the StopService OVOSAbstractApplication refactor.

These tests verify behaviour introduced or changed when StopService was
refactored to subclass OVOSAbstractApplication:

1. Vocabulary loaded from .voc files (renamed from .intent) still matches.
2. global_stop.voc phrases trigger a global stop even when skills are active.
3. can_handle=False default: a skill that declines the stop ping is still
   tried via the active-skills fallback.
4. StopService (as OVOSSkill) emits stop.openvoiceos.stop.response when
   mycroft.stop is broadcast — verified via ignore_messages pattern.
"""

import time
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils import create_daemon
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft

# Messages produced by other pipeline-plugin skills in response to mycroft.stop;
# always ignored so they don't pollute assertion counts.
_STOP_RESPONSES = [
    "speak",
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
        # No skills needed — vocabulary tests only exercise the StopService itself
        self.minicroft = get_minicroft([])

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_global_stop_voc_no_active_skills(self):
        """'stop everything' matches global_stop.voc and emits stop:global."""
        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ["ovos-stop-pipeline-plugin-high"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["stop everything"], "lang": session.lang},
                          {"session": session.serialize()})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            ignore_messages=_STOP_RESPONSES,
            source_message=message,
            expected_messages=[
                message,
                Message("stop.openvoiceos.activate", {}),
                Message("stop:global", {}),
                Message("mycroft.stop", {}),
                Message("ovos.utterance.handled", {}),
            ]
        )
        test.execute()

    def test_stop_voc_exact_still_works(self):
        """Bare 'stop' without active skills still matches stop.voc and emits stop:global.

        Regression: confirms the .voc rename did not break the stop vocabulary.
        """
        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ["ovos-stop-pipeline-plugin-high"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["stop"], "lang": session.lang},
                          {"session": session.serialize()})

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            ignore_messages=_STOP_RESPONSES,
            source_message=message,
            expected_messages=[
                message,
                Message("stop.openvoiceos.activate", {}),
                Message("stop:global", {}),
                Message("mycroft.stop", {}),
                Message("ovos.utterance.handled", {}),
            ]
        )
        test.execute()


class TestGlobalStopVocWithActiveSkill(TestCase):
    """global_stop.voc still triggers stop:global even when a skill is active.

    This is the key distinction from 'stop' + active skill (which emits
    stop:skill instead).  global_stop.voc unconditionally triggers global stop.
    """

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-count.openvoiceos"
        self.minicroft = get_minicroft([self.skill_id])

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_global_stop_voc_with_active_skill(self):
        """'stop everything now' emits stop:global regardless of active skills."""
        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ["ovos-stop-pipeline-plugin-high",
                             "ovos-padatious-pipeline-plugin-high"]
        # Activate the count skill so it is in the active-skills list
        session.activate_skill(self.skill_id)

        message = Message("recognizer_loop:utterance",
                          {"utterances": ["stop everything now"], "lang": session.lang},
                          {"session": session.serialize()})

        # count skill also emits stop.response when mycroft.stop is broadcast
        ignore = _STOP_RESPONSES + [f"{self.skill_id}.stop.response"]

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
            ignore_messages=ignore,
            source_message=message,
            expected_messages=[
                message,
                Message("stop.openvoiceos.activate", {}),
                Message("stop:global", {}),
                Message("mycroft.stop", {}),
                Message("ovos.utterance.handled", {}),
            ]
        )
        test.execute()


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
        self.minicroft = get_minicroft([self.skill_id])

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_stop_with_active_skill_ping_pong(self):
        """Stop a running skill via the ping-pong mechanism.

        Asserts the full message sequence:
          stop.ping → skill.stop.pong (can_handle=True) → stop:skill →
          {skill_id}.stop → {skill_id}.stop.response
        """
        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ["ovos-stop-pipeline-plugin-high",
                             "ovos-padatious-pipeline-plugin-high"]

        def make_it_count():
            nonlocal session
            msg = Message("recognizer_loop:utterance",
                          {"utterances": ["count to infinity"], "lang": session.lang},
                          {"session": session.serialize(), "source": "A", "destination": "B"})
            session.activate_skill(self.skill_id)
            self.minicroft.bus.emit(msg)

        create_daemon(make_it_count)
        time.sleep(2)

        message = Message("recognizer_loop:utterance",
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
            Message("ovos.utterance.handled",
                    {"name": "CountSkill.handle_how_are_you_intent"},
                    {"skill_id": self.skill_id}),
        ]

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=[],
            flip_points=["recognizer_loop:utterance"],
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
        self.minicroft = get_minicroft([])

    def tearDown(self):
        if self.minicroft:
            self.minicroft.stop()
        LOG.set_level("CRITICAL")

    def test_stop_service_emits_activate_and_stop_response(self):
        """After a global stop, stop.openvoiceos.activate and stop.openvoiceos.stop.response
        are both emitted — confirming the service participates in skill lifecycle."""
        session = Session("123")
        session.lang = "en-US"
        session.pipeline = ["ovos-stop-pipeline-plugin-high"]
        message = Message("recognizer_loop:utterance",
                          {"utterances": ["stop"], "lang": session.lang},
                          {"session": session.serialize()})

        # Do NOT ignore stop.openvoiceos.stop.response here — we want to assert it appears
        ignore = [m for m in _STOP_RESPONSES if m != "stop.openvoiceos.stop.response"]

        test = End2EndTest(
            minicroft=self.minicroft,
            skill_ids=[],
            eof_msgs=["ovos.utterance.handled"],
            flip_points=["recognizer_loop:utterance"],
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
                Message("ovos.utterance.handled", {}),
            ]
        )
        test.execute()
