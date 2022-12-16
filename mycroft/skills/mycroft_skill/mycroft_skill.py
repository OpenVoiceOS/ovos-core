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
from ovos_utils.intents import Intent, IntentBuilder
from ovos_utils.skills import get_non_properties
from mycroft.gui import SkillGUI
from mycroft.messagebus.message import Message, dig_for_message
from mycroft.metrics import report_metric
from mycroft.skills.event_scheduler import EventSchedulerInterface
from mycroft.skills.intent_service_interface import IntentServiceInterface
from ovos_utils.messagebus import get_handler_name, create_wrapper, EventContainer
from ovos_utils.enclosure.api import EnclosureAPI
from ovos_utils.messagebus import get_message_lang

from mycroft.deprecated.skills import (
    read_vocab_file, read_value_file, read_translated_file,
    load_vocabulary, load_regex, to_alnum)
from mycroft.deprecated.skills.settings import SettingsMetaUploader
from ovos_workshop.skills.mycroft_skill import MycroftSkill
