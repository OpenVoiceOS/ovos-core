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
import time

import mycroft.lock
from mycroft import dialog
from mycroft.api import is_paired, BackendDown, DeviceApi
from mycroft.audio import wait_while_speaking
from mycroft.configuration import Configuration, setup_locale
from mycroft.enclosure.api import EnclosureAPI
from mycroft.messagebus.message import Message
from mycroft.skills.api import SkillApi
from mycroft.skills.core import FallbackSkill
from mycroft.skills.event_scheduler import EventScheduler
from mycroft.skills.intent_service import IntentService
from mycroft.skills.skill_manager import SkillManager, on_error, on_stopping, on_ready, on_alive, on_started
from mycroft.util import (
    connected,
    reset_sigint_handler,
    start_message_bus_client,
    wait_for_exit_signal
)
from mycroft.util.log import LOG


RASPBERRY_PI_PLATFORMS = ('mycroft_mark_1', 'picroft', 'mycroft_mark_2pi')


class DevicePrimer:
    """Container handling the device preparation.

    Args:
        message_bus_client: Bus client used to interact with the system
        config (dict): Mycroft configuration
    """

    def __init__(self, message_bus_client, config=None):
        config = config or Configuration.get()
        self.bus = message_bus_client
        self.platform = config['enclosure'].get("platform", "unknown")
        self.enclosure = EnclosureAPI(self.bus)
        self.backend_down = False

    @property
    def is_paired(self):
        return is_paired()

    def prepare_device(self):
        """Internet dependent updates of various aspects of the device."""
        if connected():
            self._update_system()
            # Above will block during update process and kill this instance if
            # new software is installed
            self._display_skill_loading_notification()
            self.bus.emit(Message('mycroft.internet.connected'))
            self._update_device_attributes_on_backend()
        else:
            LOG.warning('Cannot prime device because there is no '
                        'internet connection, this is OK 99% of the time, '
                        'but it might affect integration with mycroft '
                        'backend')

    def _display_skill_loading_notification(self):
        """Indicate to the user that skills are being loaded."""
        self.enclosure.eyes_color(189, 183, 107)  # dark khaki
        self.enclosure.mouth_text(dialog.get("message_loading.skills"))

    def _update_device_attributes_on_backend(self):
        """Communicate version information to the backend.

        The backend tracks core version, enclosure version, platform build
        and platform name for each device, if it is known.
        """
        if self.is_paired:
            LOG.info('Sending updated device attributes to the backend...')
            try:
                api = DeviceApi()
                api.update_version()
            except Exception:
                pass

    def _update_system(self):
        """Emit an update event that will be handled by the admin service.
        TODO: deprecate this, only used in mark1, admin service doesnt exist anywhere else
        """
        if not self.is_paired:
            LOG.info('Attempting system update...')
            self.bus.emit(Message('system.update'))
            msg = Message(
                'system.update',
                dict(paired=self.is_paired, platform=self.platform)
            )
            resp = self.bus.wait_for_response(msg, 'system.update.processing')

            if resp and (resp.data or {}).get('processing', True):
                self.bus.wait_for_response(
                    Message('system.update.waiting'),
                    'system.update.complete',
                    1000
                )


def main(alive_hook=on_alive, started_hook=on_started, ready_hook=on_ready,
         error_hook=on_error, stopping_hook=on_stopping, watchdog=None):
    """Create a thread that monitors the loaded skills, looking for updates

    Returns:
        SkillManager instance or None if it couldn't be initialized
    """
    reset_sigint_handler()
    # Create PID file, prevent multiple instances of this service
    mycroft.lock.Lock('skills')

    setup_locale()

    # Connect this process to the Mycroft message bus
    bus = start_message_bus_client("SKILLS")
    _register_intent_services(bus)
    event_scheduler = EventScheduler(bus, autostart=False)
    event_scheduler.setDaemon(True)
    event_scheduler.start()
    SkillApi.connect_bus(bus)
    skill_manager = SkillManager(bus, watchdog,
                                 alive_hook=alive_hook,
                                 started_hook=started_hook,
                                 stopping_hook=stopping_hook,
                                 ready_hook=ready_hook,
                                 error_hook=error_hook)

    device_primer = DevicePrimer(bus)
    skill_manager.start()
    device_primer.prepare_device()

    wait_for_exit_signal()

    shutdown(skill_manager, event_scheduler)


def _register_intent_services(bus):
    """Start up the all intent services and connect them as needed.

    Args:
        bus: messagebus client to register the services on
    """
    service = IntentService(bus)
    # Register handler to trigger fallback system
    bus.on(
        'mycroft.skills.fallback',
        FallbackSkill.make_intent_failure_handler(bus)
    )
    return service


def shutdown(skill_manager, event_scheduler):
    LOG.info('Shutting down Skills service')
    if event_scheduler is not None:
        event_scheduler.shutdown()
    # Terminate all running threads that update skills
    if skill_manager is not None:
        skill_manager.stop()
        skill_manager.join()
    LOG.info('Skills service shutdown complete!')


if __name__ == "__main__":
    main()
