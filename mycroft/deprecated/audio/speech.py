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

"""
NOTE: this is dead code! do not use!
This file is only present to ensure backwards compatibility
in case someone is importing from here
This is only meant for 3rd party code expecting ovos-core
to be a drop in replacement for mycroft-core
"""

from threading import Lock
from mycroft_bus_client import MessageBusClient, Message
from mycroft.util import LOG

bus: MessageBusClient = None
tts = None
tts_hash = None
lock = Lock()
config = None
mimic_fallback_obj = None


def _get_messagebus():
    global bus
    if not bus:
        bus = MessageBusClient()
        bus.run_in_thread()
    return bus


def handle_speak(event):
    LOG.warning("speech.handle_speak has been deprecated!")
    LOG.error("speak message not handled")


def mute_and_speak(utterance, ident, listen=False):
    LOG.warning("speech.mute_and_speak has been deprecated!")
    bus.emit(Message("speak", {"utterance": utterance,
                               "expect_response": listen}, {"ident": ident}))


def mimic_fallback_tts(utterance, ident, listen):
    """
    DEPRECATED: use execute_fallback_tts instead
    This method is only kept around for backwards api compat
    """
    LOG.warning("speech.mimic_fallback_tts is deprecated! "
                "use audio.service.service.execute_fallback_tts instead")
    mute_and_speak(utterance, ident, listen)


def handle_stop(event):
    LOG.warning("speech.handle_stop has been deprecated!")
    _get_messagebus().emit(Message("mycroft.stop"))


def init(_):
    LOG.warning("speech.init has been deprecated!")


def shutdown():
    """Shutdown the audio service cleanly.
    Stop any playing audio and make sure threads are joined correctly.
    """
    LOG.warning("speech.shutdown has been deprecated!")
