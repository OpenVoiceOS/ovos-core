from time import sleep
from unittest import TestCase

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session
from ovos_core.intent_services import IntentService
from ovos_core.skill_manager import SkillManager
from ovos_plugin_manager.skills import find_skill_plugins
from ovos_utils.log import LOG
from ovos_utils.messagebus import FakeBus
from ovos_utils.process_utils import ProcessState
from ovos_workshop.skills.fallback import FallbackSkill


class MiniCroft(SkillManager):
    def __init__(self, skill_ids, *args, **kwargs):
        bus = FakeBus()
        super().__init__(bus, *args, **kwargs)
        self.skill_ids = skill_ids
        self.intent_service = self._register_intent_services()

    def _register_intent_services(self):
        """Start up the all intent services and connect them as needed.

        Args:
            bus: messagebus client to register the services on
        """
        service = IntentService(self.bus)
        # Register handler to trigger fallback system
        self.bus.on(
            'mycroft.skills.fallback',
            FallbackSkill.make_intent_failure_handler(self.bus)
        )
        return service

    def load_plugin_skills(self):
        LOG.info("loading skill plugins")
        plugins = find_skill_plugins()
        for skill_id, plug in plugins.items():
            LOG.debug(skill_id)
            if skill_id not in self.skill_ids:
                continue
            if skill_id not in self.plugin_skills:
                self._load_plugin_skill(skill_id, plug)

    def run(self):
        """Load skills and update periodically from disk and internet."""
        self.status.set_alive()

        self.load_plugin_skills()

        self.status.set_ready()

        LOG.info("Skills all loaded!")

    def stop(self):
        super().stop()
        SessionManager.bus = None
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")


def get_minicroft(skill_id):
    croft1 = MiniCroft([skill_id])
    croft1.start()
    while croft1.status.state != ProcessState.READY:
        sleep(0.2)
    return croft1


class TestSessions(TestCase):

    def setUp(self):
        self.skill_id = "skill-ovos-fallback-unknown.openvoiceos"
        self.core = get_minicroft(self.skill_id)

    def test_complete_failure(self):
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")
        SessionManager.default_session.lang = "en-us"
        messages = []

        def new_msg(msg):
            nonlocal messages
            m = Message.deserialize(msg)
            if m.msg_type in ["ovos.skills.settings_changed"]:
                return  # skip these, only happen in 1st run
            messages.append(m)
            print(len(messages), msg)

        def wait_for_n_messages(n):
            nonlocal messages
            while len(messages) < n:
                sleep(0.1)

        self.core.bus.on("message", new_msg)

        utt = Message("recognizer_loop:utterance",
                      {"utterances": ["invalid"]},
                      {"session": SessionManager.default_session.serialize()})
        self.core.bus.emit(utt)

        # confirm all expected messages are sent
        expected_messages = [
            "recognizer_loop:utterance",
            "skill.converse.ping",
            "skill.converse.pong",
            "ovos.skills.fallback.ping",
            "ovos.skills.fallback.pong",
            f"ovos.skills.fallback.{self.skill_id}.request",
            f"ovos.skills.fallback.{self.skill_id}.start",
            "enclosure.active_skill",
            "speak",
            f"ovos.skills.fallback.{self.skill_id}.response",
            "intent.service.skills.activated",
            f"{self.skill_id}.activate",
            "ovos.session.update_default"
        ]
        wait_for_n_messages(len(expected_messages))

        self.assertEqual(len(expected_messages), len(messages))

        mtypes = [m.msg_type for m in messages]
        for m in expected_messages:
            self.assertTrue(m in mtypes)

        # verify that contexts are kept around
        for m in messages:
            self.assertEqual(m.context["session"]["session_id"], "default")

        # verify converse ping/pong answer from skill
        self.assertEqual(messages[1].msg_type, "skill.converse.ping")
        self.assertEqual(messages[2].msg_type, "skill.converse.pong")
        self.assertEqual(messages[2].data["skill_id"], self.skill_id)
        self.assertEqual(messages[2].context["skill_id"], self.skill_id)
        self.assertFalse(messages[2].data["can_handle"])

        # verify fallback ping/pong answer from skill
        self.assertEqual(messages[3].msg_type, "ovos.skills.fallback.ping")
        self.assertEqual(messages[4].msg_type, "ovos.skills.fallback.pong")
        self.assertEqual(messages[4].data["skill_id"], self.skill_id)
        self.assertEqual(messages[4].context["skill_id"], self.skill_id)
        self.assertTrue(messages[4].data["can_handle"])

        return
        # high prio fallback
        self.assertEqual(messages[3].msg_type, "mycroft.skills.fallback")
        self.assertEqual(messages[3].data["fallback_range"], [0, 5])
        self.assertEqual(messages[4].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[4].data["handler"], "fallback")
        self.assertEqual(messages[5].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[5].data["handler"], "fallback")
        self.assertEqual(messages[6].msg_type, "mycroft.skills.fallback.response")
        self.assertFalse(messages[6].data["handled"])

        # medium prio fallback
        self.assertEqual(messages[7].msg_type, "mycroft.skills.fallback")
        self.assertEqual(messages[7].data["fallback_range"], [5, 90])
        self.assertEqual(messages[8].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[8].data["handler"], "fallback")
        self.assertEqual(messages[9].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[9].data["handler"], "fallback")
        self.assertEqual(messages[10].msg_type, "mycroft.skills.fallback.response")
        self.assertFalse(messages[10].data["handled"])

        # low prio fallback
        self.assertEqual(messages[11].msg_type, "mycroft.skills.fallback")
        self.assertEqual(messages[11].data["fallback_range"], [90, 101])
        self.assertEqual(messages[12].msg_type, "mycroft.skill.handler.start")
        self.assertEqual(messages[12].data["handler"], "fallback")
        self.assertEqual(messages[13].msg_type, "mycroft.skill.handler.complete")
        self.assertEqual(messages[13].data["handler"], "fallback")
        self.assertEqual(messages[14].msg_type, "mycroft.skills.fallback.response")
        self.assertFalse(messages[14].data["handled"])

        # complete intent failure
        self.assertEqual(messages[15].msg_type, "mycroft.audio.play_sound")
        self.assertEqual(messages[15].data["uri"], "snd/error.mp3")
        self.assertEqual(messages[16].msg_type, "complete_intent_failure")

        # verify default session is now updated
        self.assertEqual(messages[17].msg_type, "ovos.session.update_default")
        self.assertEqual(messages[17].data["session_data"]["session_id"], "default")
