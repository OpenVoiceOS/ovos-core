# Copyright 2017 Mycroft AI Inc.
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
"""Load, update and manage skills on this device."""
from ovos_backend_client.pairing import is_paired
from mycroft.deprecated.skills.settings import UploadQueue, SkillSettingsDownloader
from mycroft.deprecated.skills.skill_updater import SkillUpdater
from mycroft.skills.skill_updater import SeleneSkillManifestUploader
from ovos_core.skill_manager import SkillManager as _SM
from ovos_utils.log import LOG
# do not delete - backwards compat imports
from ovos_utils.process_utils import ProcessState
from ovos_core.skill_manager import on_error, on_stopping, on_ready, on_alive, on_started
from ovos_workshop.skill_launcher import SKILL_MAIN_MODULE
from ovos_workshop.skill_launcher import get_skill_directories, SkillLoader, PluginSkillLoader


class SkillManager(_SM):

    def __init__(self, *args, **kwargs):
        self.manifest_uploader = SeleneSkillManifestUploader()
        self.upload_queue = UploadQueue()  # DEPRECATED
        super().__init__(*args, **kwargs)

    @property
    def msm(self):
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning and returns None
        """
        LOG.warning("msm has been deprecated!")
        return None

    @property
    def settings_downloader(self):
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning and returns None
        """
        LOG.warning("settings_downloader has been deprecated, "
                    "it is now managed at skill level")
        return SkillSettingsDownloader(self.bus)

    @property
    def skill_updater(self):
        LOG.warning("SkillUpdater has been deprecated! Please use self.manifest_uploader instead")
        return SkillUpdater()

    @staticmethod
    def create_msm():
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning and returns None
        """
        return None

    def schedule_now(self, _):
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning
        """

    def handle_paired(self, _):
        """DEPRECATED: do not use, method only for api backwards compatibility
        upload of settings is done at individual skill level in ovos-core """
        pass

    def handle_internet_connected(self, message):
        super().handle_internet_connected(message)

        # Sync backend and skills.
        # why does selene need to know about skills without settings?
        if is_paired():
            self.manifest_uploader.post_manifest()






    def _unload_removed_skills(self):
        removed_skills = super()._unload_removed_skills()
        # If skills were removed make sure to update the manifest on the
        # mycroft backend.
        if removed_skills and self._connected_event.is_set():
            self.manifest_uploader.post_manifest(reload_skills_manifest=True)


    def stop(self):
        """Tell the manager to shutdown."""
        super().stop()
        self.upload_queue.stop()

