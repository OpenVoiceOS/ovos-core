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
from mycroft.deprecated.skills import (
    read_value_file, read_translated_file, read_vocab_file,
    load_vocabulary, load_regex, load_regex_from_file,
    to_alnum
)
# backwards compat imports, do not delete
from ovos_workshop.resource_files import SkillResourceTypes, ResourceType, ResourceFile, \
    QmlFile, DialogFile, VocabularyFile, NamedValueFile, ListFile, TemplateFile, RegexFile, WordFile, \
    CoreResources, UserResources, SkillResources, RegexExtractor, locate_base_directories, locate_lang_directories, find_resource


def munge_regex(regex, skill_id):
    """Insert skill id as letters into match groups.

    Args:
        regex (str): regex string
        skill_id (str): skill identifier
    Returns:
        (str) munged regex
    """
    base = '(?P<' + to_alnum(skill_id)
    return base.join(regex.split('(?P<'))


def munge_intent_parser(intent_parser, name, skill_id):
    """Rename intent keywords to make them skill exclusive
    This gives the intent parser an exclusive name in the
    format <skill_id>:<name>.  The keywords are given unique
    names in the format <Skill id as letters><Intent name>.

    The function will not munge instances that's already been
    munged

    Args:
        intent_parser: (IntentParser) object to update
        name: (str) Skill name
        skill_id: (int) skill identifier
    """
    # Munge parser name
    if not name.startswith(str(skill_id) + ':'):
        intent_parser.name = str(skill_id) + ':' + name
    else:
        intent_parser.name = name

    # Munge keywords
    skill_id = to_alnum(skill_id)
    # Munge required keyword
    reqs = []
    for i in intent_parser.requires:
        if not i[0].startswith(skill_id):
            kw = (skill_id + i[0], skill_id + i[0])
            reqs.append(kw)
        else:
            reqs.append(i)
    intent_parser.requires = reqs

    # Munge optional keywords
    opts = []
    for i in intent_parser.optional:
        if not i[0].startswith(skill_id):
            kw = (skill_id + i[0], skill_id + i[0])
            opts.append(kw)
        else:
            opts.append(i)
    intent_parser.optional = opts

    # Munge at_least_one keywords
    at_least_one = []
    for i in intent_parser.at_least_one:
        element = [skill_id + e.replace(skill_id, '') for e in i]
        at_least_one.append(tuple(element))
    intent_parser.at_least_one = at_least_one

    # NOTE: this functionality is a open PR in adapt not yet merged
    # partially supported in ovos and already deployed in the mk2
    if hasattr(intent_parser, "excludes"):
        # Munge excluded keywords
        excludes = []
        for i in intent_parser.excludes:
            if not i.startswith(skill_id):
                kw = skill_id + i
                excludes.append(kw)
            else:
                excludes.append(i)
        intent_parser.excludes = excludes


