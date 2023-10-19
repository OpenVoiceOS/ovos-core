from time import sleep

from ovos_bus_client.session import SessionManager, Session
from ovos_bus_client.util.scheduler import EventScheduler
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
        self.scheduler = EventScheduler(bus, schedule_file="/tmp/schetest.json")

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
        self.scheduler.shutdown()
        SessionManager.bus = None
        SessionManager.sessions = {}
        SessionManager.default_session = SessionManager.sessions["default"] = Session("default")


def get_minicroft(skill_id):
    if isinstance(skill_id, str):
        skill_id = [skill_id]
    assert isinstance(skill_id, list)
    croft1 = MiniCroft(skill_id)
    croft1.start()
    while croft1.status.state != ProcessState.READY:
        sleep(0.2)
    return croft1
