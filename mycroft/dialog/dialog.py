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
"""
Provides utilities for reading dialog files and rendering dialogs populated
with custom data.
"""
from ovos_utils.dialog import MustacheDialogRenderer, load_dialogs, get_dialog


def get(phrase, lang=None, context=None):
    """Looks up a resource file for the given phrase.

    If no file is found, the requested phrase is returned as the string. This
    will use the default language for translations.

    Args:
        phrase (str): resource phrase to retrieve/translate
        lang (str): the language to use
        context (dict): values to be inserted into the string

    Returns:
        str: a randomized and/or translated version of the phrase
    """
    if not lang:
        from ovos_config.config import Configuration
        lang = Configuration().get('lang', "en-us")
    return get_dialog(phrase, lang, context)
