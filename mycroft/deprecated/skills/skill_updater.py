# Copyright 2019 Mycroft AI Inc.
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
"""Periodically run by skill manager to update skills and post the manifest."""

from combo_lock import ComboLock

from ovos_utils.file_utils import get_temp_path
from ovos_utils.log import LOG
from ovos_config.config import Configuration

ONE_HOUR = 3600
FIVE_MINUTES = 300  # number of seconds in a minute


class SkillUpdater:
    """
    DEPRECATED - most of this class is now useless and logs warnings only
    Please use SeleneSkillManifestUploader to post skills manifest
    Skill updates are no longer handled by core

    Class facilitating skill update / install actions.

    Arguments
        bus (MessageBusClient): Optional bus emitter Used to communicate
                                with the mycroft core system and handle
                                commands.
    """

    def __init__(self, bus=None):
        self.installed_skills = set()
        self.msm_lock = ComboLock(get_temp_path('mycroft-msm.lck'))
        self.install_retries = 0
        self.config = Configuration()
        update_interval = self.config['skills'].get('update_interval', 1.0)
        self.update_interval = int(update_interval) * ONE_HOUR
        self.dot_msm_path = "/tmp/.msm"
        self.next_download = 0
        self.default_skill_install_error = False

        self.post_manifest(True)
        if bus:
            LOG.warning("bus argument has been deprecated")

    @property
    def installed_skills_file_path(self):
        """Property representing the path of the installed skills file."""
        from mycroft.skills.skill_updater import SeleneSkillManifestUploader
        return SeleneSkillManifestUploader().skill_manifest.path

    @property
    def msm(self):
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning and returns None
        """
        # unused but need to keep api backwards compatible
        # log a warning and move on
        LOG.warning("msm has been deprecated\n"
                    "DO NOT use self.msm property")
        return None

    @property
    def default_skill_names(self) -> tuple:
        """Property representing the default skills expected to be installed"""
        LOG.warning("msm has been deprecated\n"
                    "skill install/update is no longer handled by ovos-core")
        return ()

    def update_skills(self, quick=False):
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning and returns True
        """
        LOG.warning("msm has been deprecated\n"
                    "skill install/update is no longer handled by ovos-core")
        return True

    def handle_not_connected(self):
        """"DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning
        """
        LOG.warning("msm has been deprecated\n"
                    "no update will be scheduled")

    def post_manifest(self, reload_skills_manifest=False):
        """Post the manifest of the device's skills to the backend."""
        from mycroft.skills.skill_updater import SeleneSkillManifestUploader
        uploader = SeleneSkillManifestUploader()
        uploader.post_manifest(reload_skills_manifest)

    def install_or_update(self, skill):
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning
        """
        LOG.warning("msm has been deprecated\n"
                    f"{skill} will not be changed")

    def defaults_installed(self):
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning and returns True
        """
        LOG.warning("msm has been deprecated\n"
                    "skill install/update is no longer handled by ovos-core")
        return True
