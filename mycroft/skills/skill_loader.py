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
"""Periodically run by skill manager to load skills into memory."""
import os
from time import time
from ovos_utils.log import LOG

# backwards compat imports do not delete
from mycroft.deprecated.skills.settings import SettingsMetaUploader
from ovos_plugin_manager.skills import find_skill_plugins, get_default_skills_directory
from ovos_workshop.skill_launcher import SKILL_MAIN_MODULE, get_skill_directories,\
    remove_submodule_refs, load_skill_module, get_skill_class, \
    get_create_skill_function, SkillLoader as _SL, PluginSkillLoader as _PSL


def _bad_mod_times(mod_times):
    """Return all entries with modification time in the future.

    Args:
        mod_times (dict): dict mapping file paths to modification times.

    Returns:
        List of files with bad modification times.
    """
    current_time = time()
    return [path for path in mod_times if mod_times[path] > current_time]


def _get_last_modified_time(path):
    """Get the last modified date of the most recently updated file in a path.

    Exclude compiled python files, hidden directories and the settings.json
    file.

    Args:
        path: skill directory to check

    Returns:
        int: time of last change
    """
    all_files = []
    for root_dir, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for f in files:
            ignore_file = (
                    f.endswith('.pyc') or
                    f == 'settings.json' or
                    f.startswith('.') or
                    f.endswith('.qmlc')
            )
            if not ignore_file:
                all_files.append(os.path.join(root_dir, f))

    # check files of interest in the skill root directory
    mod_times = {f: os.path.getmtime(f) for f in all_files}
    # Ensure modification times are valid
    bad_times = _bad_mod_times(mod_times)
    if bad_times:
        raise OSError(f'{bad_times} had bad modification times')
    if all_files:
        return max(os.path.getmtime(f) for f in all_files)
    else:
        return 0


class SkillLoader(_SL):
    def __init__(self, bus, skill_directory=None):
        super().__init__(bus, skill_directory)
        self.last_modified = 0
        self.modtime_error_log_written = False

    def _handle_filechange(self, path):
        super()._handle_filechange(path)
        # NOTE: below could be removed, but is kept for api backwards compatibility
        # users of SkillLoader will still have all properties properly updated
        # TODO on ntp sync last_modified needs to be updated
        try:
            self.last_modified = _get_last_modified_time(self.skill_directory)
        except OSError as err:
            self.last_modified = self.last_loaded
            if not self.modtime_error_log_written:
                self.modtime_error_log_written = True
                LOG.error(f'Failed to get last_modification time ({err})')
        else:
            self.modtime_error_log_written = False

    def reload_needed(self):
        """DEPRECATED: backwards compatibility only

        this is now event based and always returns False after initial load
        """
        return self.instance is None


class PluginSkillLoader(SkillLoader, _PSL):

    def reload_needed(self):
        return False
