from datetime import datetime, timedelta
from os import makedirs
from os.path import isdir
from ovos_config.config import Configuration
from ovos_skills_manager.osm import OVOSSkillsManager
from ovos_skills_manager.skill_entry import SkillEntry
from ovos_utils.event_scheduler import EventSchedulerInterface
from typing import List, Optional, Generator, Union

from ovos_utils.log import LOG


class SkillsStore:
    def __init__(self, bus, config=None):
        self.config = config or Configuration()["skills"]
        self.osm = OVOSSkillsManager()
        self.bus = bus
        self.scheduler = EventSchedulerInterface(skill_id="osm",
                                                 bus=self.bus)
        if self.config.get("appstore_sync_interval"):
            self.schedule_sync()

        self.bus.on("ovos.skills.install", self.handle_install_skill)
        self.bus.on("ovos.skills.sync", self.handle_sync_appstores)

    def schedule_sync(self):
        """
        Use the EventScheduler to update osm with updated appstore data
        """
        # every X hours
        interval = 60 * 60 * self.config["appstore_sync_interval"]
        when = datetime.now() + timedelta(seconds=interval)
        self.scheduler.schedule_repeating_event(self.handle_sync_appstores,
                                                when, interval=interval,
                                                name="appstores.sync")

    def handle_sync_appstores(self, message=None):
        """
        Scheduled action to update OSM appstore listings
        """
        try:
            self.osm.sync_appstores()
        except Exception as e:
            LOG.error(f"appstore sync failed: {e}")

    def shutdown(self):
        self.scheduler.shutdown()

    def handle_install_skill(self, message: Message):
        url = message.data["url"]
        # TODO - update OSM to use latest pip install methods and setup.py
        entry = SkillEntry.from_github_url(url)
        success = entry.install(*args, **kwargs)
        if success:
            self.bus.emit(message.reply("ovos.skills.install.complete"))
        else:
            self.bus.emit(message.reply("ovos.skills.install.failed"))
