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
"""Load, update and manage skills on this device."""
import os
import threading
from threading import Thread, Event, Lock

from ovos_bus_client.apis.enclosure import EnclosureAPI
from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_config.config import Configuration
from ovos_config.locations import get_xdg_config_save_path
from ovos_utils.file_utils import FileWatcher
from ovos_utils.gui import is_gui_connected
from ovos_utils.log import LOG
from ovos_utils.network_utils import is_connected_http
from ovos_utils.process_utils import ProcessStatus, StatusCallbackMap, ProcessState
from ovos_workshop.skill_launcher import PluginSkillLoader

from ovos_plugin_manager.skills import find_skill_plugins


def on_started():
    """
    Logs that the Skills Manager is starting up.
    """
    LOG.info('Skills Manager is starting up.')


def on_alive():
    LOG.info('Skills Manager is alive.')


def on_ready():
    LOG.info('Skills Manager is ready.')


def on_error(e='Unknown'):
    LOG.info(f'Skills Manager failed to launch ({e})')


def on_stopping():
    LOG.info('Skills Manager is shutting down...')


class SkillManager(Thread):
    """Manages the loading, activation, and deactivation of Mycroft skills."""

    def __init__(self, bus, watchdog=None, alive_hook=on_alive, started_hook=on_started, ready_hook=on_ready,
                 error_hook=on_error, stopping_hook=on_stopping):
        """
                 Initializes the SkillManager thread for managing plugin skill lifecycles.
                 
                 Sets up status callbacks, event synchronization primitives, configuration, and internal data structures for plugin skill management. Registers message bus event handlers, initializes a file watcher for skill settings changes, and binds process status to the message bus. Marks the thread as a daemon for asynchronous operation.
                 """
        super(SkillManager, self).__init__()
        self.bus = bus
        self._settings_watchdog = None
        # Set watchdog to argument or function returning None
        self._watchdog = watchdog or (lambda: None)
        callbacks = StatusCallbackMap(on_started=started_hook,
                                      on_alive=alive_hook,
                                      on_ready=ready_hook,
                                      on_error=error_hook,
                                      on_stopping=stopping_hook)
        self.status = ProcessStatus('skills', callback_map=callbacks)
        self.status.set_started()

        self._setup_event = Event()
        self._stop_event = Event()
        self._connected_event = Event()
        self._network_event = Event()
        self._gui_event = Event()
        self._network_loaded = Event()
        self._internet_loaded = Event()
        self._network_skill_timeout = 300
        self._allow_state_reloads = True
        self._logged_skill_warnings = list()
        self._detected_installed_skills = bool(find_skill_plugins())
        if not self._detected_installed_skills:
            LOG.warning(
                "No installed skills detected! if you are running skills in standalone mode ignore this warning,"
                " otherwise you probably want to install skills first!")

        self.config = Configuration()

        self.plugin_skills = {}
        self.enclosure = EnclosureAPI(bus)
        self.num_install_retries = 0
        self.empty_skill_dirs = set()  # Save a record of empty skill dirs.

        self._define_message_bus_events()
        self.daemon = True

        self.status.bind(self.bus)
        self._init_filewatcher()

    @property
    def blacklist(self):
        """
        Returns the list of skill IDs that are blacklisted in the configuration.
        
        Returns:
            list: Blacklisted skill IDs.
        """
        return Configuration().get("skills", {}).get("blacklisted_skills", [])

    def _init_filewatcher(self):
        """
        Initializes a file watcher to monitor skill settings files for changes.
        
        Sets up a file watcher on the skills settings directory to detect modifications, triggering a callback when a skill's settings file changes.
        """
        sspath = f"{get_xdg_config_save_path()}/skills/"
        os.makedirs(sspath, exist_ok=True)
        self._settings_watchdog = FileWatcher([sspath],
                                              callback=self._handle_settings_file_change,
                                              recursive=True,
                                              ignore_creation=True)

    def _handle_settings_file_change(self, path: str):
        """Handle changes to skill settings files.

        Args:
            path (str): Path to the settings file that has changed.
        """
        if path.endswith("/settings.json"):
            skill_id = path.split("/")[-2]
            LOG.info(f"skill settings.json change detected for {skill_id}")
            self.bus.emit(Message("ovos.skills.settings_changed",
                                  {"skill_id": skill_id}))

    def _sync_skill_loading_state(self):
        """Synchronize the loading state of skills with the current system state."""
        resp = self.bus.wait_for_response(Message("ovos.PHAL.internet_check"))
        network = False
        internet = False
        if not self._gui_event.is_set() and is_gui_connected(self.bus):
            self._gui_event.set()

        if resp:
            if resp.data.get('internet_connected'):
                network = internet = True
            elif resp.data.get('network_connected'):
                network = True
        else:
            LOG.debug("ovos-phal-plugin-connectivity-events not detected, performing direct network checks")
            network = internet = is_connected_http()

        if internet and not self._connected_event.is_set():
            LOG.debug("Notify internet connected")
            self.bus.emit(Message("mycroft.internet.connected"))
        elif network and not self._network_event.is_set():
            LOG.debug("Notify network connected")
            self.bus.emit(Message("mycroft.network.connected"))

    def _define_message_bus_events(self):
        """Define message bus events with handlers defined in this class."""
        # Update upon request
        self.bus.on('skillmanager.list', self.send_skill_list)
        self.bus.on('skillmanager.deactivate', self.deactivate_skill)
        self.bus.on('skillmanager.keep', self.deactivate_except)
        self.bus.on('skillmanager.activate', self.activate_skill)

        # Load skills waiting for connectivity
        self.bus.on("mycroft.network.connected", self.handle_network_connected)
        self.bus.on("mycroft.internet.connected", self.handle_internet_connected)
        self.bus.on("mycroft.gui.available", self.handle_gui_connected)
        self.bus.on("mycroft.network.disconnected", self.handle_network_disconnected)
        self.bus.on("mycroft.internet.disconnected", self.handle_internet_disconnected)
        self.bus.on("mycroft.gui.unavailable", self.handle_gui_disconnected)

    @property
    def skills_config(self):
        """Get the skills service configuration.

        Returns:
            dict: Skills configuration.
        """
        return self.config['skills']

    def handle_gui_connected(self, message):
        """Handle GUI connection event.

        Args:
            message: Message containing information about the GUI connection.
        """
        # Some GUI extensions, such as mobile, may request that skills never unload
        self._allow_state_reloads = not message.data.get("permanent", False)
        if not self._gui_event.is_set():
            LOG.debug("GUI Connected")
            self._gui_event.set()
            self._load_new_skills()

    def handle_gui_disconnected(self, message):
        """Handle GUI disconnection event.

        Args:
            message: Message containing information about the GUI disconnection.
        """
        if self._allow_state_reloads:
            self._gui_event.clear()
            self._unload_on_gui_disconnect()

    def handle_internet_disconnected(self, message):
        """Handle internet disconnection event.

        Args:
            message: Message containing information about the internet disconnection.
        """
        if self._allow_state_reloads:
            self._connected_event.clear()
            self._unload_on_internet_disconnect()

    def handle_network_disconnected(self, message):
        """Handle network disconnection event.

        Args:
            message: Message containing information about the network disconnection.
        """
        if self._allow_state_reloads:
            self._network_event.clear()
            self._unload_on_network_disconnect()

    def handle_internet_connected(self, message):
        """Handle internet connection event.

        Args:
            message: Message containing information about the internet connection.
        """
        if not self._connected_event.is_set():
            LOG.debug("Internet Connected")
            self._network_event.set()
            self._connected_event.set()
            self._load_on_internet()

    def handle_network_connected(self, message):
        """Handle network connection event.

        Args:
            message: Message containing information about the network connection.
        """
        if not self._network_event.is_set():
            LOG.debug("Network Connected")
            self._network_event.set()
            self._load_on_network()

    def load_plugin_skills(self, network=None, internet=None):
        """
        Loads new plugin skills according to current network and internet connectivity.
        
        If a skill is blacklisted, it is skipped and a warning is logged. Only skills whose runtime requirements are satisfied by the current connectivity state are loaded. Returns True if any new skills were loaded.
        
        Args:
            network: If specified, overrides the detected network connection status.
            internet: If specified, overrides the detected internet connection status.
        
        Returns:
            True if any new plugin skills were loaded; otherwise, False.
        """
        loaded_new = False
        if network is None:
            network = self._network_event.is_set()
        if internet is None:
            internet = self._connected_event.is_set()
        plugins = find_skill_plugins()
        for skill_id, plug in plugins.items():
            if skill_id in self.blacklist:
                if skill_id not in self._logged_skill_warnings:
                    self._logged_skill_warnings.append(skill_id)
                    LOG.warning(f"{skill_id} is blacklisted, it will NOT be loaded")
                    LOG.info(f"Consider uninstalling {skill_id} instead of blacklisting it")
                continue
            if skill_id not in self.plugin_skills:
                skill_loader = self._get_plugin_skill_loader(skill_id, init_bus=False,
                                                             skill_class=plug)
                requirements = skill_loader.runtime_requirements
                if not network and requirements.network_before_load:
                    continue
                if not internet and requirements.internet_before_load:
                    continue
                self._load_plugin_skill(skill_id, plug)
                loaded_new = True
        return loaded_new

    def _get_internal_skill_bus(self):
        """Get a dedicated skill bus connection per skill.

        Returns:
            MessageBusClient: Internal skill bus.
        """
        if not self.config["websocket"].get("shared_connection", True):
            # See BusBricker skill to understand why this matters.
            # Any skill can manipulate the bus from other skills.
            # This patch ensures each skill gets its own connection that can't be manipulated by others.
            # https://github.com/EvilJarbas/BusBrickerSkill
            bus = MessageBusClient(cache=True)
            bus.run_in_thread()
        else:
            bus = self.bus
        return bus

    def _get_plugin_skill_loader(self, skill_id, init_bus=True, skill_class=None):
        """Get a plugin skill loader.

        Args:
            skill_id (str): ID of the skill.
            init_bus (bool): Whether to initialize the internal skill bus.

        Returns:
            PluginSkillLoader: Plugin skill loader instance.
        """
        bus = None
        if init_bus:
            bus = self._get_internal_skill_bus()
        loader = PluginSkillLoader(bus, skill_id)
        if skill_class:
            loader.skill_class = skill_class
        return loader

    def _load_plugin_skill(self, skill_id, skill_plugin):
        """
        Attempts to load a plugin skill and registers its loader.
        
        If loading fails, logs the exception and still registers the loader in the internal dictionary.
        
        Args:
            skill_id: The unique identifier of the skill.
            skill_plugin: The plugin skill class or instance to be loaded.
        
        Returns:
            The PluginSkillLoader instance if the skill was loaded successfully, or None if loading failed.
        """
        skill_loader = self._get_plugin_skill_loader(skill_id, skill_class=skill_plugin)
        try:
            load_status = skill_loader.load(skill_plugin)
        except Exception:
            LOG.exception(f'Load of skill {skill_id} failed!')
            load_status = False
        finally:
            self.plugin_skills[skill_id] = skill_loader

        return skill_loader if load_status else None

    def wait_for_intent_service(self):
        """
        Blocks execution until the IntentService reports readiness to receive skill messages.
        
        This method repeatedly queries the IntentService via the message bus and waits until
        a positive readiness response is received before returning.
        """
        response = self.bus.wait_for_response(
            Message(f'mycroft.intents.is_ready',
                    context={"source": "skills", "destination": "intents"}))
        if response and response.data['status']:
            return
        threading.Event().wait(1)
        self.wait_for_intent_service()

    def run(self):
        """
        Main loop for the SkillManager thread, handling skill loading and lifecycle events.
        
        Waits for the IntentService to become ready, loads offline skills, synchronizes skill loading state, emits initialization events, and periodically checks for new or updated skills. Continues running until signaled to stop.
        """
        self.status.set_alive()

        LOG.debug("Waiting for IntentService startup")
        self.wait_for_intent_service()
        LOG.debug("IntentService reported ready")

        self._load_on_startup()

        # trigger a sync so we dont need to wait for the plugin to volunteer info
        self._sync_skill_loading_state()

        if not all((self._network_loaded.is_set(),
                    self._internet_loaded.is_set())):
            self.bus.emit(Message(
                'mycroft.skills.error',
                {'internet_loaded': self._internet_loaded.is_set(),
                 'network_loaded': self._network_loaded.is_set()}))

        self.bus.emit(Message('mycroft.skills.initialized'))

        self.status.set_ready()

        LOG.info("ovos-core is ready! additional skills can now be loaded")

        # Scan the file folder that contains Skills.  If a Skill is updated,
        # unload the existing version from memory and reload from the disk.
        while not self._stop_event.wait(30):
            try:
                self._load_new_skills()
                self._watchdog()
            except Exception:
                LOG.exception('Something really unexpected has occurred '
                              'and the skill manager loop safety harness was '
                              'hit.')

    def _load_on_network(self):
        """Load skills that require a network connection."""
        if self._detected_installed_skills:  # ensure we have skills installed
            LOG.info('Loading skills that require network...')
            self._load_new_skills(network=True, internet=False)
        self._network_loaded.set()

    def _load_on_internet(self):
        """Load skills that require both internet and network connections."""
        if self._detected_installed_skills:  # ensure we have skills installed
            LOG.info('Loading skills that require internet (and network)...')
            self._load_new_skills(network=True, internet=True)
        self._internet_loaded.set()
        self._network_loaded.set()

    def _unload_on_network_disconnect(self):
        """
        Placeholder for unloading skills that require a network connection when disconnected.
        
        Currently not implemented.
        """
        # TODO - implementation missing

    def _unload_on_internet_disconnect(self):
        """
        Placeholder for unloading skills that require an internet connection when connectivity is lost.
        """
        # TODO - implementation missing

    def _unload_on_gui_disconnect(self):
        """
        Placeholder for unloading skills that require a GUI when the GUI disconnects.
        
        This method is not yet implemented.
        """
        # TODO - implementation missing

    def _load_on_startup(self):
        """
        Loads all offline plugin skills during startup.
        
        This method checks for installed skills and initiates loading of skills that do not require network or internet connectivity.
        """
        if self._detected_installed_skills:  # ensure we have skills installed
            LOG.info('Loading offline skills...')
            self._load_new_skills(network=False, internet=False)

    def _load_new_skills(self, network=None, internet=None, gui=None):
        """
        Loads any newly installed plugin skills based on current connectivity status.
        
        If new skills are loaded, triggers intent training and logs the outcome.
        
        Args:
            network: Optional; current network connection status.
            internet: Optional; current internet connection status.
            gui: Optional; current GUI connection status.
        """
        if network is None:
            network = self._network_event.is_set()
        if internet is None:
            internet = self._connected_event.is_set()
        if gui is None:
            gui = self._gui_event.is_set() or is_gui_connected(self.bus)

        loaded_new = self.load_plugin_skills(network=network, internet=internet)

        if loaded_new:
            LOG.debug("Requesting pipeline intent training")
            try:
                response = self.bus.wait_for_response(Message("mycroft.skills.train"),
                                                      "mycroft.skills.trained",
                                                      timeout=60)  # 60 second timeout
                if not response:
                    LOG.error("Intent training timed out")
                elif response.data.get('error'):
                    LOG.error(f"Intent training failed: {response.data['error']}")
                else:
                    LOG.debug(f"pipelines trained and ready to go")
            except Exception as e:
                LOG.exception(f"Error during Intent training: {e}")

    def _unload_plugin_skill(self, skill_id):
        """
        Unloads a plugin skill by shutting it down and removing it from the manager.
        
        Args:
            skill_id (str): The identifier of the plugin skill to unload.
        """
        if skill_id in self.plugin_skills:
            LOG.info('Unloading plugin skill: ' + skill_id)
            skill_loader = self.plugin_skills[skill_id]
            if skill_loader.instance is not None:
                try:
                    skill_loader.instance.default_shutdown()
                except Exception:
                    LOG.exception('Failed to shutdown plugin skill: ' + skill_loader.skill_id)
            self.plugin_skills.pop(skill_id)

    def is_alive(self, message=None):
        """Respond to is_alive status request."""
        return self.status.state >= ProcessState.ALIVE

    def is_all_loaded(self, message=None):
        """ Respond to all_loaded status request."""
        return self.status.state == ProcessState.READY

    def send_skill_list(self, message=None):
        """
        Emits a message containing the list of currently loaded plugin skills and their active status.
        
        The message is sent on the bus with the type 'mycroft.skills.list' and includes each skill's ID and whether it is active and loaded.
        """
        try:
            message_data = {}
            # TODO handle external skills, OVOSAbstractApp/Hivemind skills are not accounted for
            skills = self.plugin_skills
            for skill_loader in skills.values():
                message_data[skill_loader.skill_id] = {
                    "active": skill_loader.active and skill_loader.loaded,
                    "id": skill_loader.skill_id}

            self.bus.emit(Message('mycroft.skills.list', data=message_data))
        except Exception:
            LOG.exception('Failed to send skill list')

    def deactivate_skill(self, message):
        """
        Deactivates a specified plugin skill in response to a message.
        
        If the skill is found, it is deactivated and a response is emitted on the message bus. If deactivation fails, an error response is emitted.
        """
        try:
            # TODO handle external skills, OVOSAbstractApp/Hivemind skills are not accounted for
            skills = self.plugin_skills
            for skill_loader in skills.values():
                if message.data['skill'] == skill_loader.skill_id:
                    LOG.info("Deactivating skill: " + skill_loader.skill_id)
                    skill_loader.deactivate()
                    self.bus.emit(message.response())
        except Exception as err:
            LOG.exception('Failed to deactivate ' + message.data['skill'])
            self.bus.emit(message.response({'error': f'failed: {err}'}))

    def deactivate_except(self, message):
        """
        Deactivates all plugin skills except the specified one.
        
        The skill to remain active is identified by the 'skill' field in the message data.
        """
        try:
            skill_to_keep = message.data['skill']
            LOG.info(f'Deactivating all skills except {skill_to_keep}')
            # TODO handle external skills, OVOSAbstractApp/Hivemind skills are not accounted for
            skills = self.plugin_skills
            for skill in skills.values():
                if skill.skill_id != skill_to_keep:
                    skill.deactivate()
            LOG.info('Couldn\'t find skill ' + message.data['skill'])
        except Exception:
            LOG.exception('An error occurred during skill deactivation!')

    def activate_skill(self, message):
        """
        Activates a specified deactivated plugin skill or all plugin skills.
        
        If the skill name in the message is "all", all inactive plugin skills are activated. Emits a response message upon activation or if an error occurs.
        """
        try:
            # TODO handle external skills, OVOSAbstractApp/Hivemind skills are not accounted for
            skills = self.plugin_skills
            for skill_loader in skills.values():
                if (message.data['skill'] in ('all', skill_loader.skill_id)
                        and not skill_loader.active):
                    skill_loader.activate()
                    self.bus.emit(message.response())
        except Exception as err:
            LOG.exception(f'Couldn\'t activate skill {message.data["skill"]}')
            self.bus.emit(message.response({'error': f'failed: {err}'}))

    def stop(self):
        """
        Signals the skill manager to stop and performs a clean shutdown of all plugin skills.
        
        Shuts down all loaded plugin skills and the settings file watcher if active.
        """
        self.status.set_stopping()
        self._stop_event.set()

        # Do a clean shutdown of all skills
        for skill_id in list(self.plugin_skills.keys()):
            self._unload_plugin_skill(skill_id)

        if self._settings_watchdog:
            self._settings_watchdog.shutdown()
