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

# The following lines are replaced during the release process.
# START_VERSION_BLOCK
OVOS_VERSION_MAJOR = 0
OVOS_VERSION_MINOR = 0
OVOS_VERSION_BUILD = 8
OVOS_VERSION_ALPHA = 119

# END_VERSION_BLOCK


OVOS_VERSION_TUPLE = (OVOS_VERSION_MAJOR,
                      OVOS_VERSION_MINOR,
                      OVOS_VERSION_BUILD)
OVOS_VERSION_STR = '.'.join(map(str, OVOS_VERSION_TUPLE))


class VersionManager:
    @staticmethod
    def get():
        return {"OpenVoiceOSVersion": OVOS_VERSION_STR}


def check_version(version_string):
    """
        Check if current version is equal or higher than the
        version string provided to the function

        Args:
            version_string (string): version string ('Major.Minor.Build')
    """
    version_tuple = tuple(map(int, version_string.split('.')))
    return OVOS_VERSION_TUPLE >= version_tuple
