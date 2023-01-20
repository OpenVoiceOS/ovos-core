# Copyright 2018 Mycroft AI Inc.
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
"""Handling of skill data such as intents and regular expressions."""
# backwards compat imports, do not delete
from ovos_utils.intents.intent_service_interface import munge_intent_parser
from ovos_workshop.resource_files import SkillResourceTypes, ResourceType, ResourceFile, \
    QmlFile, DialogFile, VocabularyFile, NamedValueFile, ListFile, TemplateFile, RegexFile, WordFile, \
    CoreResources, UserResources, SkillResources, RegexExtractor, locate_base_directories, \
    locate_lang_directories, find_resource
from mycroft.deprecated.skills import (
    read_value_file, read_translated_file, read_vocab_file,
    load_vocabulary, load_regex, load_regex_from_file, to_alnum,
    munge_regex
)
