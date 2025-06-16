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

The executable gets added to the bin directory when installed
(see setup.py)
"""

from ovos_bus_client import MessageBusClient
from ovos_config.locale import setup_locale
from ovos_utils import wait_for_exit_signal
from ovos_utils.log import LOG, init_service_logger

from ovos_core.skill_manager import SkillManager, on_error, on_stopping, on_ready, on_alive, on_started


def main(alive_hook=on_alive, started_hook=on_started, ready_hook=on_ready,
         error_hook=on_error, stopping_hook=on_stopping, watchdog=None,
         enable_file_watcher=True,
         enable_skill_api=True,
         enable_intent_service=True,
         enable_installer=True,
         enable_event_scheduler=True):
    """Create a thread that monitors the loaded skills, looking for updates

    Returns:
        SkillManager instance or None if it couldn't be initialized
    """
    init_service_logger("skills")

    setup_locale()

    # Connect this process to the OpenVoiceOS message bus
    bus = MessageBusClient()
    bus.run_in_thread()
    bus.connected_event.wait()

    skill_manager = SkillManager(bus, watchdog,
                                 enable_file_watcher=enable_file_watcher,
                                 enable_skill_api=enable_skill_api,
                                 enable_intent_service=enable_intent_service,
                                 enable_installer=enable_installer,
                                 enable_event_scheduler=enable_event_scheduler,
                                 alive_hook=alive_hook,
                                 started_hook=started_hook,
                                 stopping_hook=stopping_hook,
                                 ready_hook=ready_hook,
                                 error_hook=error_hook)

    skill_manager.start()

    wait_for_exit_signal()

    skill_manager.shutdown()

    LOG.info('Skills service shutdown complete!')


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Start the OpenVoiceOS Skill Manager")

    parser.add_argument("--disable-file-watcher", action="store_false", dest="enable_file_watcher",
                        help="Disable automatic file watching for skill settings.json")
    parser.add_argument("--disable-skill-api", action="store_false", dest="enable_skill_api",
                        help="Disable the Skill bus API (microservices provided by skills)")
    parser.add_argument("--disable-intent-service", action="store_false", dest="enable_intent_service",
                        help="Disable the intent service")
    parser.add_argument("--disable-installer", action="store_false", dest="enable_installer",
                        help="Disable skill installer")
    parser.add_argument("--disable-event-scheduler", action="store_false", dest="enable_event_scheduler",
                        help="Disable the bus event scheduler")

    args = parser.parse_args()

    main(enable_file_watcher=args.enable_file_watcher,
         enable_skill_api=args.enable_skill_api,
         enable_intent_service=args.enable_intent_service,
         enable_installer=args.enable_installer,
         enable_event_scheduler=args.enable_event_scheduler)
