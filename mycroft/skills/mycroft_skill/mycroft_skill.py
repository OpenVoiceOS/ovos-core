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
"""Common functionality relating to the implementation of mycroft skills."""

# backwards compat imports, do not delete!
from ovos_workshop.intents import Intent, IntentBuilder, IntentServiceInterface, to_alnum
from ovos_utils.skills import get_non_properties
from ovos_workshop.skills.base import SkillGUI
from ovos_bus_client.message import Message, dig_for_message
from mycroft.metrics import report_metric
from ovos_bus_client.util.scheduler import EventScheduler, EventSchedulerInterface
from ovos_utils.events import get_handler_name, create_wrapper, EventContainer
from ovos_bus_client.apis.enclosure import EnclosureAPI
from ovos_bus_client.util import get_message_lang

from mycroft.deprecated.skills import (
    read_vocab_file, read_value_file, read_translated_file,
    load_vocabulary, load_regex)
from mycroft.deprecated.skills.settings import SettingsMetaUploader
from ovos_workshop.skills.mycroft_skill import MycroftSkill
