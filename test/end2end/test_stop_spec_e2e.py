"""End-to-end conformance tests for OVOS-STOP-1 — the spec dispatch surface.

These assert the primary, spec-mandated behaviour of the stop pipeline plugin:

- a **targeted** stop is dispatched on ``<skill_id>:stop`` with
  ``Match.skill_id == skill_id`` (§2, §3.1);
- a **global** stop is dispatched on ``<pipeline_id>:global_stop`` with
  ``Match.skill_id == pipeline_id`` and broadcasts ``ovos.stop`` (§5);
- ``suppress_activation`` (§6.2/§7.3) means neither dispatch emits a
  ``{skill_id}.activate`` — a stop terminates participation, it does not
  activate;
- the §5.2/§6 session drain is committed before dispatch.

The un-migrated ``ovos-skill-count`` still subscribes to the legacy
``<skill_id>.stop``; the ovos-spec-tools namespace translator bridges the spec
``<skill_id>:stop`` dispatch onto it, so the targeted scenario runs with
``modernize=True, emit_legacy=True`` (the translator active). The global
scenario needs no skill and runs on the pure spec namespace.
"""
import time
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session, SessionManager
from ovos_spec_tools import SpecMessage
from ovos_utils import create_daemon
from ovos_utils.log import LOG

from ovoscope import End2EndTest, get_minicroft

from ovos_core.intent_services.stop_service import StopService

SPEC_UTTERANCE = SpecMessage.UTTERANCE.value
STOP_BROADCAST = SpecMessage.STOP.value                     # ovos.stop (§5.3)
PIPELINE_ID = StopService.pipeline_id
GLOBAL_STOP = f"{PIPELINE_ID}:global_stop"                  # §5 global dispatch

# Legacy-bridge and framework topics that wrap or shadow the spec dispatch;
# ignored so the spec assertions stay focused on the STOP-1 surface. The
# per-pipeline ``{pipeline_id}.activate`` / ``{skill_id}.activate`` topics are
# deliberately NOT ignored: their absence is the §6.2 suppress_activation guard.
_IGNORE = [
    SpecMessage.INTENT_MATCHED,
    SpecMessage.INTENT_HANDLER_START,
    SpecMessage.INTENT_HANDLER_COMPLETE,
    SpecMessage.INTENT_HANDLER_ERROR,
    SpecMessage.SPEAK,
    "recognizer_loop:audio_output_start",
    "recognizer_loop:audio_output_end",
    "mycroft.skill.handler.start",
    "mycroft.skill.handler.complete",
    # pre-STOP-1 legacy bridge surface (asserted by test_stop_legacy_e2e.py)
    "stop.openvoiceos.activate",
    "stop:global",
    "stop:skill",
    "mycroft.stop",
    # other pipeline-plugin skills answering the ovos.stop / mycroft.stop broadcast
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


class TestGlobalStopSpec(TestCase):
    """§5 global stop dispatches on ``<pipeline_id>:global_stop`` + ``ovos.stop``."""

    def setUp(self):
        LOG.set_level("DEBUG")

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def test_global_stop_no_skills(self):
        """Bare 'stop' with no active skills → global stop on the pipeline_id.

        Asserts: the §5 dispatch topic carries ``skill_id == pipeline_id``, it
        broadcasts ``ovos.stop`` (§5.3), and — because suppress_activation is
        set — NO ``{pipeline_id}.activate`` is emitted (§6.2/§7.3)."""
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
                eof_msgs=[SpecMessage.UTTERANCE_HANDLED],
                flip_points=[SPEC_UTTERANCE],
                entry_points=[SPEC_UTTERANCE],
                ignore_messages=_IGNORE,
                source_message=message,
                expected_messages=[
                    message,
                    Message(GLOBAL_STOP, {},
                            {"skill_id": PIPELINE_ID}),
                    Message(STOP_BROADCAST, {},
                            {"skill_id": PIPELINE_ID}),
                    Message(SpecMessage.UTTERANCE_HANDLED, {},
                            {"skill_id": PIPELINE_ID}),
                ]
            )
            test.execute()
        finally:
            minicroft.stop()


class TestTargetedStopSpec(TestCase):
    """§2/§3.1 targeted stop dispatches on ``<skill_id>:stop``."""

    def setUp(self):
        LOG.set_level("DEBUG")
        self.skill_id = "ovos-skill-count.openvoiceos"

    def tearDown(self):
        LOG.set_level("CRITICAL")

    def test_targeted_stop_dispatch_shape(self):
        """A running skill is stopped via ``<skill_id>:stop`` with Match.skill_id
        equal to the skill, no ``{skill_id}.activate`` (suppress_activation), and
        the §6 drain removing the skill from active_handlers.

        The translator (modernize/emit_legacy) bridges the spec ``:stop``
        dispatch onto the skill's legacy ``.stop`` subscription."""
        minicroft = get_minicroft([self.skill_id], modernize=True, emit_legacy=True)
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

            # Filter to the spec targeted dispatch (skill_id=<skill>); the skill's
            # own §8 trio is the deterministic dispatch lifecycle. eof_count=2 lets
            # capture span both utterances' terminals before filtering.
            test = End2EndTest(
                minicroft=minicroft,
                skill_ids=[],
                skill_id=self.skill_id,
                eof_msgs=[SpecMessage.UTTERANCE_HANDLED],
                eof_count=2,
                test_active_skills=False,
                ignore_messages=_IGNORE + [
                    f"{self.skill_id}.stop.response",
                    f"{self.skill_id}.stop.ping",
                    "skill.stop.pong",
                    f"{self.skill_id}:count_to_n.intent",
                ],
                source_message=message,
                expected_messages=[
                    # the §2 targeted dispatch, Match.skill_id == the skill
                    Message(f"{self.skill_id}:stop", {},
                            {"skill_id": self.skill_id}),
                    # two §9.5 terminals carry the skill_id: the stop dispatch and
                    # the interrupted count intent's own (aborted) handler.
                    Message(SpecMessage.UTTERANCE_HANDLED, {},
                            {"skill_id": self.skill_id}),
                    Message(SpecMessage.UTTERANCE_HANDLED, {},
                            {"skill_id": self.skill_id}),
                ]
            )
            test.execute()

            # §6.2: the stopped skill is drained from active_handlers.
            drained = SessionManager.sessions[session.session_id]
            self.assertNotIn(self.skill_id,
                             [s[0] for s in drained.active_skills])
        finally:
            minicroft.stop()
