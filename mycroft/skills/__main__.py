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
"""Daemon launched at startup to handle skill activities.

In this repo, you will not find an entry called mycroft-skills in the bin
directory.  The executable gets added to the bin directory when installed
(see setup.py)
"""
from ovos_core.__main__ import main, shutdown

# keep these imports for backwards compat!
from mycroft.skills.api import SkillApi
from ovos_workshop.skills.fallback import FallbackSkill
from ovos_bus_client.util.scheduler import EventScheduler
from mycroft.skills.intent_service import IntentService
from mycroft.skills.skill_manager import SkillManager, on_error, on_stopping, on_ready, on_alive, on_started
from mycroft.deprecated.skills import DevicePrimer, RASPBERRY_PI_PLATFORMS


if __name__ == "__main__":
    main()
