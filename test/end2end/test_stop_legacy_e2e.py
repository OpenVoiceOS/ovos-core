"""End-to-end tests for the pre-OVOS-STOP-1 dispatch surface (``_LegacyStopBridge``).

The stop plugin dispatches on the spec topics ``<skill_id>:stop`` /
``<pipeline_id>:global_stop``. For deployments still observing the pre-spec
``stop:global`` / ``stop:skill`` dispatch — and skills consuming the legacy
``<skill_id>.stop`` / ``mycroft.stop`` topics without the namespace translator
active — the droppable ``_LegacyStopBridge`` re-emits that surface.

These tests assert that legacy surface is still produced. They are filtered to
``skill_id="stop.openvoiceos"`` (the identity the pre-spec dispatch reported),
which isolates the bridge emissions from the concurrent spec dispatch (whose
skill_id is the target skill or the pipeline_id). When the bridge is removed
these tests fail — the legacy topics are gone — which is the intended signal
that the compatibility unit was dropped.
"""
import time
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
from ovos_spec_tools import SpecMessage
from ovos_utils import create_daemon
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft

SPEC_UTTERANCE = SpecMessage.UTTERANCE.value
LEGACY_SKILL_ID = "stop.openvoiceos"

# Spec/framework topics and cross-skill stop responses filtered out; the
# skill_id="stop.openvoiceos" End2EndTest filter already drops everything not
# emitted under the legacy identity, but the shared broadcast responses and the
# §8 trio need explicit ignores where they carry that identity or none.
_IGNORE = [
    SpecMessage.INTENT_MATCHED,
    SpecMessage.INTENT_HANDLER_START,
    SpecMessage.INTENT_HANDLER_COMPLETE,
    SpecMessage.INTENT_HANDLER_ERROR,
    SpecMessage.SPEAK,
    "recognizer_loop:audio_output_start",
    "recognizer_loop:audio_output_end",
    "ovos.common_play.stop.response",
    "common_query.openvoiceos.stop.response",
    "persona.openvoiceos.stop.response",
    "ovos-hivemind-pipeline-plugin.stop.response",
    "mycroft.skills.abort_question",
    "ovos.skills.converse.force_timeout",
    "mycroft.audio.speech.stop",
    "ovos.skills.settings_changed",
]


def _wait_for_active_skill(session_id, skill_id, timeout=10, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        sess = SessionManager.sessions.get(session_id)
        if sess and sess.is_active(skill_id):
            return
        time.sleep(interval)
    raise TimeoutError(f"Skill {skill_id} did not activate within {timeout}s")


class TestLegacyGlobalStop(TestCase):
    """The bridge re-emits ``stop:global`` → ``mycroft.stop``."""

    def setUp(self):
        LOG.set_level("DEBUG")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def test_global_stop_no_skills(self):
        minicroft = get_minicroft([], modernize=False, emit_legacy=False)
        try:
            session = Session("123")
            session.lang = "en-US"
            session.pipeline = ["ovos-stop-pipeline-plugin-high"]
            message = Message(SPEC_UTTERANCE,
                              {"utterances": ["stop"], "lang": session.lang},
                              {"session": session.serialize()})

            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[],
                skill_id=LEGACY_SKILL_ID,
                eof_msgs=[SpecMessage.UTTERANCE_HANDLED],
                eof_count=1,
                test_active_skills=False,
                ignore_messages=_IGNORE,
                source_message=message,
                expected_messages=[
                    Message(f"{LEGACY_SKILL_ID}.activate", {},
                            {"skill_id": LEGACY_SKILL_ID}),
                    Message("stop:global", {},
                            {"skill_id": LEGACY_SKILL_ID}),
                    Message("mycroft.skill.handler.start",
                            {"name": "StopService.handle_global_stop"},
                            {"skill_id": LEGACY_SKILL_ID}),
                    Message("mycroft.stop", {},
                            {"skill_id": LEGACY_SKILL_ID}),
                    Message("mycroft.skill.handler.complete",
                            {"name": "StopService.handle_global_stop"},
                            {"skill_id": LEGACY_SKILL_ID}),
                ]
            )
            test.execute()
        finally:
            minicroft.stop()


class TestLegacyTargetedStop(TestCase):
    """The bridge re-emits ``stop:skill`` → ``<skill_id>.stop``."""

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-count.openvoiceos"

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def test_targeted_stop_running_skill(self):
        minicroft = get_minicroft([self.skill_id], modernize=False, emit_legacy=False)
        try:
            session = Session("123")
            session.lang = "en-US"
            session.pipeline = ["ovos-stop-pipeline-plugin-high",
                                "ovos-padatious-pipeline-plugin-high"]

            def make_it_count():
                minicroft.bus.emit(Message(
                    SPEC_UTTERANCE,
                    {"utterances": ["count to infinity"], "lang": session.lang},
                    {"session": session.serialize(), "source": "A", "destination": "B"}))

            create_daemon(make_it_count)
            _wait_for_active_skill(session.session_id, self.skill_id)

            live = SessionManager.sessions[session.session_id]
            message = Message(SPEC_UTTERANCE,
                              {"utterances": ["stop"], "lang": live.lang},
                              {"session": live.serialize(), "source": "A", "destination": "B"})

            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[],
                skill_id=LEGACY_SKILL_ID,
                eof_msgs=[SpecMessage.UTTERANCE_HANDLED],
                eof_count=2,
                test_active_skills=False,
                ignore_messages=_IGNORE,
                source_message=message,
                expected_messages=[
                    Message(f"{LEGACY_SKILL_ID}.activate", {},
                            {"skill_id": LEGACY_SKILL_ID}),
                    Message("stop:skill", {"skill_id": self.skill_id},
                            {"skill_id": LEGACY_SKILL_ID}),
                    Message("mycroft.skill.handler.start",
                            {"name": "StopService.handle_skill_stop"},
                            {"skill_id": LEGACY_SKILL_ID}),
                    Message(f"{self.skill_id}.stop", {},
                            {"skill_id": LEGACY_SKILL_ID}),
                    Message("mycroft.skill.handler.complete",
                            {"name": "StopService.handle_skill_stop"},
                            {"skill_id": LEGACY_SKILL_ID}),
                ]
            )
            test.execute()
        finally:
            minicroft.stop()
