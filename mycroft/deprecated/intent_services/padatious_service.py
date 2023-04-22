# Copyright 2020 Mycroft AI Inc.
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
"""Intent service wrapping padatious."""
from threading import Event
from time import time as get_time
from mycroft.configuration import Configuration
from mycroft.messagebus.message import Message
from mycroft.util.log import LOG
from ovos_plugin_manager.templates.intents import IntentMatch


class PadatiousMatcher:
    """Matcher class to avoid redundancy in padatious intent matching."""

    def __init__(self, service):
        self.service = service
        self.has_result = False
        self.ret = None
        self.conf = None
        LOG.error("PadatiousMatcher has been deprecated, stop importing this class!!!")

    def match_high(self, utterances, lang=None, __=None):
        """DEPRECATED - use padatious intent plugin directly instead"""
        LOG.error("PadatiousMatcher has been deprecated, stop importing this class!!!")

    def match_medium(self, utterances, lang=None, __=None):
        """DEPRECATED - use padatious intent plugin directly instead"""
        LOG.error("PadatiousMatcher has been deprecated, stop importing this class!!!")

    def match_low(self, utterances, lang=None, __=None):
        """DEPRECATED - use padatious intent plugin directly instead"""
        LOG.error("PadatiousMatcher has been deprecated, stop importing this class!!!")


class PadatiousService:
    """DEPRECATED - use padatious intent plugin directly instead"""

    def __init__(self, bus, config):
        self.padatious_config = config
        self.bus = bus

        self.lang = Configuration.get().get("lang", "en-us")

        self.containers = {}

        self.finished_training_event = Event()
        self.finished_initial_train = True
        self.finished_training_event.set()

        self.train_delay = self.padatious_config['train_delay']
        self.train_time = get_time() + self.train_delay

        self.registered_intents = []
        self.registered_entities = []
        LOG.error("PadatiousService has been deprecated, stop importing this class!!!")

    def train(self, message=None):
        """DEPRECATED - use padatious intent plugin directly instead"""
        LOG.error("PadatiousService has been deprecated, stop importing this class!!!")

    def wait_and_train(self):
        """DEPRECATED - use padatious intent plugin directly instead"""
        LOG.error("PadatiousService has been deprecated, stop importing this class!!!")

    def handle_detach_intent(self, message):
        """DEPRECATED - use padatious intent plugin directly instead"""
        LOG.error("PadatiousService has been deprecated, stop importing this class!!!")

    def handle_detach_skill(self, message):
        """DEPRECATED - use padatious intent plugin directly instead"""
        LOG.error("PadatiousService has been deprecated, stop importing this class!!!")

    def register_intent(self, message):
        """DEPRECATED - use padatious intent plugin directly instead"""
        LOG.error("PadatiousService has been deprecated, stop importing this class!!!")

    def register_entity(self, message):
        """DEPRECATED - use padatious intent plugin directly instead"""
        LOG.error("PadatiousService has been deprecated, stop importing this class!!!")

    def calc_intent(self, utt, lang=None):
        """DEPRECATED - use padatious intent plugin directly instead"""
        LOG.error("PadatiousService has been deprecated, stop importing this class!!!")