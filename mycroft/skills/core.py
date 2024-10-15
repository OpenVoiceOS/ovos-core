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
""" Collection of core functions of the mycroft skills system.

This file is now depricated and skill should now import directly from
mycroft.skills.
"""
# Import moved methods for backwards compatibility
# This will need to remain here for quite some time since removing it
# would break most of the skills out there.
from ovos_workshop.skills.ovos import OVOSSkill as MycroftSkill
from ovos_workshop.skills.fallback import FallbackSkill
from mycroft.skills.mycroft_skill import resting_screen_handler, intent_handler, intent_file_handler, skill_api_method


