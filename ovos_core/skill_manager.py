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
import importlib
import os
import sys
import threading
import time
from importlib.metadata import distributions, entry_points
from packaging.utils import canonicalize_name
from threading import Thread, Event
from typing import Callable, Dict, FrozenSet, List, Optional, Set

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_bus_client.util.scheduler import EventScheduler
from ovos_config.config import Configuration
from ovos_config.locations import get_xdg_config_save_path
from ovos_utils.file_utils import FileWatcher
from ovos_utils.gui import is_gui_connected
from ovos_utils.log import LOG
from ovos_utils.network_utils import is_connected_http
from ovos_utils.process_utils import ProcessStatus, StatusCallbackMap, ProcessState
from ovos_workshop.skill_launcher import PluginSkillLoader
from ovos_core.skill_installer import SkillsStore
from ovos_core.intent_services import IntentService
from ovos_workshop.skills.api import SkillApi

from ovos_plugin_manager.skills import find_skill_plugins
from ovos_plugin_manager.utils import DEPRECATED_ENTRYPOINTS, PluginTypes

# Backoff schedule for retrying a plugin skill whose load raised before a
# `PluginSkillLoader` instance existed (eg. an error in the skill's own
# `__init__`). Without a backoff such a skill is indistinguishable from
# "never attempted" on the next scan and gets fully re-instantiated - and its
# intents re-registered - on every 30s scan, forever.
PLUGIN_SKILL_RETRY_BASE_SECONDS = 30
PLUGIN_SKILL_RETRY_MAX_SECONDS = 15 * 60


def on_started() -> None:
    LOG.info('Skills Manager is starting up.')


def on_alive() -> None:
    LOG.info('Skills Manager is alive.')


def on_ready() -> None:
    LOG.info('Skills Manager is ready.')


def on_error(e: str = 'Unknown') -> None:
    LOG.info(f'Skills Manager failed to launch ({e})')


def on_stopping() -> None:
    LOG.info('Skills Manager is shutting down...')


#: Modules the runtime is itself built from. A changed distribution that
#: installs one of these is NOT forgotten: re-importing it under a live
#: process leaves every running skill an instance of a class its own module
#: no longer defines, which trades a dead skill for a corrupt one. A change
#: here legitimately needs the process to restart.
PROTECTED_RUNTIME_MODULES = frozenset({
    "ovos_core",
    "ovos_bus_client",
    "ovos_config",
    "ovos_plugin_manager",
    "ovos_utils",
    "ovos_workshop",
})


def _live_runtime_modules() -> FrozenSet[str]:
    """Top-level packages this process has already imported, plus the floor.

    The named six are the ones that are always the runtime. They are not all
    of it: importing ``ovos_core.skill_manager`` alone pulls in nine more --
    ``padacioso``, ``quebra_frases``, ``ovos_spec_tools``, ``langcodes``,
    ``combo_lock``, ``ovos_number_parser``, ``ovos_yes_no``,
    ``ovos_option_matcher_fuzzy``, ``ovos_gui_api_client`` -- and a live
    manager holds live objects from them. Forgetting one and re-importing it
    leaves ``isinstance(running_thing, new_module.Thing)`` False, which is the
    corrupt-skill outcome the floor exists to prevent, so anything already
    imported when the manager starts is protected too.

    A snapshot, not a live read: a module a SKILL imports after start is not
    the runtime and stays evictable, which is the whole point of the feature.
    """
    imported = {name.split(".", 1)[0] for name in list(sys.modules)}
    return frozenset(PROTECTED_RUNTIME_MODULES | {
        name for name in imported if name and name.isidentifier()
        and not name.startswith("_")
    })

class SkillManager(Thread):
    """Manages the loading, activation, and deactivation of Mycroft skills."""

    def __init__(self, bus: MessageBusClient,
                 watchdog: Optional[Callable[[], None]] = None,
                 alive_hook: Callable[[], None] = on_alive,
                 started_hook: Callable[[], None] = on_started,
                 ready_hook: Callable[[], None] = on_ready,
                 error_hook: Callable[..., None] = on_error,
                 stopping_hook: Callable[[], None] = on_stopping,
                 enable_installer: bool = False,
                 enable_intent_service: bool = False,
                 enable_event_scheduler: bool = False,
                 enable_file_watcher: bool = True,
                 enable_skill_api: bool = False) -> None:
        """Constructor

        Args:
            bus (event emitter): Mycroft messagebus connection
            watchdog (callable): optional watchdog function
            alive_hook (callable): callback function for skill alive status
            started_hook (callable): callback function for skill started status
            ready_hook (callable): callback function for skill ready status
            error_hook (callable): callback function for skill error status
            stopping_hook (callable): callback function for skill stopping status
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
        self._startup_complete_event = Event()
        self._deferred_skill_load_event = Event()
        self._startup_lock = threading.Lock()
        self._connected_event = Event()
        self._network_event = Event()
        self._gui_event = Event()
        self._network_loaded = Event()
        self._internet_loaded = Event()
        self._network_skill_timeout = 300
        self._allow_state_reloads = True
        self._logged_skill_warnings = set()
        self._detected_installed_skills = bool(find_skill_plugins())
        if not self._detected_installed_skills:
            LOG.warning(
                "No installed skills detected! if you are running skills in standalone mode ignore this warning,"
                " otherwise you probably want to install skills first!")

        self.config = Configuration()

        # Config flag to enable deferred skill loading based on network/internet/GUI requirements.
        # When disabled (default), all skills load unconditionally at startup.
        # When enabled, skills with network_before_load, internet_before_load, or GUI requirements
        # are deferred until those conditions are met.
        self._use_deferred_loading = self.config.get("skills", {}).get("use_deferred_loading", False)

        self.plugin_skills = {}
        self._plugin_skills_lock = threading.RLock()
        self._loading_plugin_skills = set()
        # the serial of the attempt behind each tracked loader or reserved load,
        # so that a pass judging a snapshot can tell the attempt it read from a
        # later one under the same id
        self._plugin_skill_serials: Dict[str, int] = {}
        self._plugin_skill_last_serial = 0
        # ids whose package went undiscoverable while their load held the
        # reservation. The sweep that noticed had no loader to detach yet, so
        # it leaves the verdict here for `_load_plugin_skill` to honour.
        self._plugin_skill_unload_pending = set()
        #: The installed version each loaded plugin skill was built from,
        #: so an upgrade in place can be told from the version running.
        self._plugin_skill_versions: Dict[str, str] = {}
        # Every installed distribution's version, as of the last installer
        # run. A skill's own package is not the only thing an install can
        # replace: see `_forget_upgraded_dependencies`. Taken when skills are
        # first loaded rather than here -- reading every distribution costs a
        # quarter of a second, and nothing can have been upgraded before the
        # first load anyway. None until a scan has actually succeeded: an
        # empty reading is a real answer on a runtime with nothing installed,
        # and must not be confused with never having looked.
        self._distribution_versions: Optional[Dict[str, str]] = None
        #: dotted modules each distribution ships, filled by _modules_of
        self._distribution_owned: Dict[str, Set[str]] = {}
        #: everything already imported when this manager was built
        self._protected_modules = _live_runtime_modules()
        # skill_id -> (attempt_count, last_attempt_time) for plugin skills whose
        # load raised before a loader object existed (see _load_plugin_skill).
        # These are retried with an exponential backoff instead of every scan.
        self._plugin_skill_failures = {}
        self.num_install_retries = 0
        self.empty_skill_dirs = set()  # Save a record of empty skill dirs.

        self._define_message_bus_events()
        self.daemon = True

        self.status.bind(self.bus)

        # Connect SessionManager to the bus regardless of whether the intent
        # service runs in this process: speak(wait=True)/wait_while_speaking
        # depend on SessionManager.bus being set, and skills-only processes
        # (enable_intent_service=False, e.g. --disable-intent-service) would
        # otherwise never get it. Guarded so the monolith path (intent
        # service enabled in this same process) does not register the five
        # SessionManager bus handlers twice via IntentService.__init__.
        if SessionManager.bus is not self.bus:
            SessionManager.connect_to_bus(self.bus)

        # init subsystems
        self.osm = SkillsStore(self.bus) if enable_installer else None
        self.event_scheduler = EventScheduler(self.bus, autostart=False) if enable_event_scheduler else None
        if self.event_scheduler:
            self.event_scheduler.daemon = True # TODO - add kwarg in EventScheduler
            self.event_scheduler.start()
        self.intents = IntentService(self.bus) if enable_intent_service else None
        if enable_skill_api:
            SkillApi.connect_bus(self.bus)
        if enable_file_watcher:
            self._init_filewatcher()

    @property
    def blacklist(self) -> List[str]:
        """Get the list of blacklisted skills from the configuration.

        Returns:
            list: List of blacklisted skill ids.
        """
        return Configuration().get("skills", {}).get("blacklisted_skills", [])

    def _init_filewatcher(self) -> None:
        """Initialize the file watcher to monitor skill settings files for changes."""
        sspath = f"{get_xdg_config_save_path()}/skills/"
        os.makedirs(sspath, exist_ok=True)
        self._settings_watchdog = FileWatcher([sspath],
                                              callback=self._handle_settings_file_change,
                                              recursive=True,
                                              ignore_creation=True)

    def _handle_settings_file_change(self, path: str) -> None:
        """Handle changes to skill settings files.

        Args:
            path (str): Path to the settings file that has changed.
        """
        if path.endswith("/settings.json"):
            skill_id = path.split("/")[-2]
            LOG.info(f"skill settings.json change detected for {skill_id}")
            self.bus.emit(Message("ovos.skills.settings_changed",
                                  {"skill_id": skill_id}))

    def _sync_skill_loading_state(self) -> None:
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

    def _define_message_bus_events(self) -> None:
        """Define message bus events with handlers defined in this class."""
        # Update upon request
        self.bus.on('skillmanager.list', self.send_skill_list)
        self.bus.on('skillmanager.deactivate', self.deactivate_skill)
        self.bus.on('skillmanager.keep', self.deactivate_except)
        self.bus.on('skillmanager.activate', self.activate_skill)
        self.bus.on('skillmanager.rescan', self.handle_rescan_request)

        # The installer reloads the plugin manager before it reports a
        # completed install, so a scan issued on that report already sees the
        # new entry points; without it the package waited for the periodic scan
        self.bus.on('ovos.skills.install.complete', self.handle_install_complete)
        self.bus.on('ovos.pip.install.complete', self.handle_install_complete)

        # The installer reloads the plugin manager before it reports a
        # completed uninstall, so discovery no longer returns the removed
        # package; drop the loaded skills that went with it
        self.bus.on('ovos.skills.uninstall.complete', self.handle_uninstall_complete)
        self.bus.on('ovos.pip.uninstall.complete', self.handle_uninstall_complete)

        # Load skills waiting for connectivity (only if deferred loading is enabled)
        if self._use_deferred_loading:
            self.bus.on("mycroft.network.connected", self.handle_network_connected)
            self.bus.on("mycroft.internet.connected", self.handle_internet_connected)
            self.bus.on("mycroft.gui.available", self.handle_gui_connected)
            self.bus.on("mycroft.network.disconnected", self.handle_network_disconnected)
            self.bus.on("mycroft.internet.disconnected", self.handle_internet_disconnected)
            self.bus.on("mycroft.gui.unavailable", self.handle_gui_disconnected)

    @property
    def skills_config(self) -> dict:
        """Get the skills service configuration.

        Returns:
            dict: Skills configuration.
        """
        return self.config['skills']

    def _is_plugin_skill_tracked(self, skill_id):
        """Check whether a skill is loaded or currently being loaded."""
        with self._plugin_skills_lock:
            return (skill_id in self.plugin_skills or
                    skill_id in self._loading_plugin_skills)

    def _reserve_plugin_skill_load(self, skill_id):
        """Mark a skill as loading so overlapping scans skip it."""
        with self._plugin_skills_lock:
            if skill_id in self.plugin_skills or skill_id in self._loading_plugin_skills:
                return False
            self._loading_plugin_skills.add(skill_id)
            self._plugin_skill_last_serial += 1
            self._plugin_skill_serials[skill_id] = self._plugin_skill_last_serial
            # a verdict can only speak for the reservation it was recorded
            # against; clearing here keeps an older one from discarding this
            # attempt, which starts from a package that is discoverable again
            self._plugin_skill_unload_pending.discard(skill_id)
            return True

    def _release_plugin_skill_load(self, skill_id):
        """Clear the in-progress marker for a skill load attempt."""
        with self._plugin_skills_lock:
            self._loading_plugin_skills.discard(skill_id)
            self._plugin_skill_serials.pop(skill_id, None)

    def _record_plugin_skill_version(self, skill_id: str,
                                     version: Optional[str] = None) -> None:
        """Remember the installed version a freshly loaded skill was read from.

        The version belongs to the class that was loaded, so the caller passes
        the one it read beside that class. Reading it here instead would let
        an upgrade landing *during* the load be recorded against the previous
        code, and the upgrade check would then find the versions agree and
        leave the old code answering.

        Args:
            skill_id (str): The skill that was loaded.
            version (str): The version read with the class, when known.
        """
        if version is None:
            version = self._declared_skill_versions().get(skill_id)
        if version is None:
            return
        with self._plugin_skills_lock:
            self._plugin_skill_versions[skill_id] = version

    def _should_retry_plugin_skill(self, skill_id: str) -> bool:
        """Check whether enough time has passed to retry a previously failed load."""
        with self._plugin_skills_lock:
            failure = self._plugin_skill_failures.get(skill_id)
        if failure is None:
            return True
        attempts, last_attempt = failure
        delay = min(PLUGIN_SKILL_RETRY_BASE_SECONDS * (2 ** (attempts - 1)),
                    PLUGIN_SKILL_RETRY_MAX_SECONDS)
        return time.time() - last_attempt >= delay

    def _record_plugin_skill_failure(self, skill_id: str) -> None:
        """Record a failed load attempt, extending the backoff before the next retry."""
        with self._plugin_skills_lock:
            attempts, _ = self._plugin_skill_failures.get(skill_id, (0, 0.0))
            self._plugin_skill_failures[skill_id] = (attempts + 1, time.time())

    def _clear_plugin_skill_failure(self, skill_id: str) -> None:
        """Clear any recorded backoff once a skill loads successfully."""
        with self._plugin_skills_lock:
            self._plugin_skill_failures.pop(skill_id, None)

    def _defer_skill_load_until_startup_complete(self):
        """Queue connectivity-triggered skill loads until the intent service is ready."""
        with self._startup_lock:
            if self._startup_complete_event.is_set():
                return False
            self._deferred_skill_load_event.set()
            return True

    def _mark_startup_complete_and_consume_deferred(self):
        """Atomically mark startup complete and consume any deferred load request."""
        with self._startup_lock:
            self._startup_complete_event.set()
            deferred_skill_load_pending = self._deferred_skill_load_event.is_set()
            self._deferred_skill_load_event.clear()
            return deferred_skill_load_pending

    def _process_deferred_skill_load(self):
        """Replay the earliest deferred connectivity-triggered load after startup."""
        if self._connected_event.is_set():
            self._load_on_internet()
        elif self._network_event.is_set():
            self._load_on_network()
        elif self._gui_event.is_set():
            self._load_new_skills()

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
            if self._defer_skill_load_until_startup_complete():
                return
            self._load_new_skills()

    def handle_gui_disconnected(self, message: Message) -> None:
        """Handle GUI disconnection event.

        Args:
            message: Message containing information about the GUI disconnection.
        """
        if self._allow_state_reloads:
            self._gui_event.clear()
            self._unload_on_gui_disconnect()

    def handle_internet_disconnected(self, message: Message) -> None:
        """Handle internet disconnection event.

        Args:
            message: Message containing information about the internet disconnection.
        """
        if self._allow_state_reloads:
            self._connected_event.clear()
            self._unload_on_internet_disconnect()

    def handle_network_disconnected(self, message: Message) -> None:
        """Handle network disconnection event.

        Args:
            message: Message containing information about the network disconnection.
        """
        if self._allow_state_reloads:
            self._network_event.clear()
            self._unload_on_network_disconnect()

    def handle_internet_connected(self, message: Message) -> None:
        """Handle internet connection event.

        Args:
            message: Message containing information about the internet connection.
        """
        if not self._connected_event.is_set():
            LOG.debug("Internet Connected")
            self._network_event.set()
            self._connected_event.set()
            if self._defer_skill_load_until_startup_complete():
                return
            self._load_on_internet()

    def handle_network_connected(self, message: Message) -> None:
        """Handle network connection event.

        Args:
            message: Message containing information about the network connection.
        """
        if not self._network_event.is_set():
            LOG.debug("Network Connected")
            self._network_event.set()
            if self._defer_skill_load_until_startup_complete():
                return
            self._load_on_network()

    def load_plugin_skills(self, network: Optional[bool] = None, internet: Optional[bool] = None) -> bool:
        """Load plugin skills based on network and internet status.

        Args:
            network (bool): Network connection status.
            internet (bool): Internet connection status.

        Returns:
            bool: True if new skills were loaded, False otherwise.
        """
        return bool(self._load_untracked_plugin_skills(network=network, internet=internet))

    def _load_untracked_plugin_skills(self, network: Optional[bool] = None,
                                      internet: Optional[bool] = None) -> List[str]:
        """Load every discoverable plugin skill that is not yet tracked.

        Args:
            network (bool): Network connection status.
            internet (bool): Internet connection status.

        Returns:
            List[str]: Ids of the skills this call loaded, in discovery order.
        """
        if self._distribution_versions is None:
            # The baseline an installer run is later compared against. Seeded
            # here because this is what every startup path reaches -- the
            # usual one is `_load_new_skills`, which never calls
            # `load_plugin_skills` -- and this is the first moment there are
            # skills to upgrade. Doing it in `__init__` made every test that
            # builds a manager pay for a full distribution scan.
            self._distribution_versions = self._installed_distributions()
        loaded: List[str] = []
        if network is None:
            network = self._network_event.is_set()
        if internet is None:
            internet = self._connected_event.is_set()
        plugins = find_skill_plugins()
        blacklist = self.blacklist
        for skill_id, plug in plugins.items():
            if skill_id in blacklist:
                if skill_id not in self._logged_skill_warnings:
                    self._logged_skill_warnings.add(skill_id)
                    LOG.warning(f"{skill_id} is blacklisted, it will NOT be loaded")
                    LOG.info(f"Consider uninstalling {skill_id} instead of blacklisting it")
                continue
            if self._is_plugin_skill_tracked(skill_id):
                continue
            if not self._should_retry_plugin_skill(skill_id):
                continue
            skill_loader = self._get_plugin_skill_loader(skill_id, init_bus=False,
                                                         skill_class=plug)
            requirements = skill_loader.runtime_requirements
            if not network and requirements.network_before_load:
                continue
            if not internet and requirements.internet_before_load:
                continue
            if not self._reserve_plugin_skill_load(skill_id):
                continue
            if self._load_plugin_skill(skill_id, plug, reserved=True) is not None:
                loaded.append(skill_id)
        return loaded

    def _get_internal_skill_bus(self) -> MessageBusClient:
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

    def _get_plugin_skill_loader(self, skill_id: str, init_bus: bool = True,
                                  skill_class: Optional[type] = None) -> PluginSkillLoader:
        """Get a plugin skill loader.

        Args:
            skill_id (str): ID of the skill.
            init_bus (bool): Whether to initialize the internal skill bus.
            skill_class (type): Optional skill class to use.

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

    def _load_plugin_skill(self, skill_id: str, skill_plugin: type, reserved: bool = False,
                           version: Optional[str] = None) -> Optional[PluginSkillLoader]:
        """Load a plugin skill.

        Args:
            skill_id (str): ID of the skill.
            skill_plugin: Plugin skill class.
            reserved (bool): True if the caller already marked the skill as loading.

        Returns:
            PluginSkillLoader: Loaded plugin skill loader instance if successful, None otherwise.
        """
        if not reserved and not self._reserve_plugin_skill_load(skill_id):
            LOG.debug(f"Skipping duplicate load attempt for {skill_id}; load already in progress")
            return None

        # Read before the load, so it belongs to `skill_plugin` -- the class
        # the caller discovered -- and not to an upgrade that lands while
        # this load is running. Recording the later one would leave the
        # upgrade check comparing the new version against itself and the old
        # code still answering.
        if version is None:
            version = self._declared_skill_versions().get(skill_id)

        skill_loader = None
        try:
            skill_loader = self._get_plugin_skill_loader(skill_id, skill_class=skill_plugin)
            load_status = skill_loader.load(skill_plugin)
        except Exception:
            LOG.exception(f'Load of skill {skill_id} failed!')
            load_status = False
        finally:
            with self._plugin_skills_lock:
                # read the verdict and drop the reservation in one step, so a
                # sweep either lands before this (and is honoured here) or
                # after (and detaches the loader itself)
                abandoned = skill_id in self._plugin_skill_unload_pending
                self._plugin_skill_unload_pending.discard(skill_id)
                if skill_loader is not None and not abandoned:
                    # the loader keeps the attempt's serial while it is tracked
                    self.plugin_skills[skill_id] = skill_loader
                else:
                    self._plugin_skill_serials.pop(skill_id, None)
                self._loading_plugin_skills.discard(skill_id)
            if abandoned:
                # the package is gone, so this is not a failure to back off
                # from: a reinstall should load on the next scan
                self._clear_plugin_skill_failure(skill_id)
                self._logged_skill_warnings.discard(skill_id)
                LOG.info(f"Discarding {skill_id}: its package was uninstalled "
                         f"while the skill was loading")
                self._shutdown_skill_loader(skill_loader)
            elif skill_loader is not None:
                if load_status:
                    self._clear_plugin_skill_failure(skill_id)
                    # what this load read from disk, so a later upgrade in
                    # place can be told from the version now running
                    self._record_plugin_skill_version(skill_id, version)
                    # announced once the loader is tracked, and never for a load the
                    # uninstall abandoned: a consumer acting on this finds the skill
                    # present, and is not told about one that was just shut down
                    self.bus.emit(Message("mycroft.skill.loaded", {"skill_id": skill_id}))
            else:
                # `_get_plugin_skill_loader`/`.load()` raised before a loader
                # object existed - there is nothing to track in
                # `self.plugin_skills`, so record the failure separately or
                # this skill would look "never attempted" and get retried
                # (and its intents re-registered) on every 30s scan forever.
                self._record_plugin_skill_failure(skill_id)

        if abandoned:
            return None
        return skill_loader if load_status else None

    def wait_for_intent_service(self) -> None:
        """ensure IntentService reported ready to accept skill messages"""
        max_wait: int = self.config.get("skills", {}).get("intent_service_timeout", 300)
        elapsed: int = 0
        start_time = time.monotonic()
        while not self._stop_event.is_set() and elapsed < max_wait:
            response = self.bus.wait_for_response(
                Message('mycroft.intents.is_ready',
                        context={"source": "skills", "destination": "intents"}),
                timeout=5)
            if response and response.data.get('status'):
                return
            self._stop_event.wait(1)
            elapsed = int(time.monotonic() - start_time)
        if self._stop_event.is_set():
            raise RuntimeError("Skill manager stopped while waiting for intent service")
        raise RuntimeError(
            f"IntentService did not become ready within {max_wait} seconds; "
            "check that the intent service process is running and connected to the bus"
        )

    def run(self) -> None:
        """Run the skill manager thread."""
        self.status.set_alive()

        LOG.debug("Waiting for IntentService startup")
        self.wait_for_intent_service()
        LOG.debug("IntentService reported ready")

        if self._use_deferred_loading:
            # Legacy deferred loading: defer connectivity-triggered loads until intent service is ready
            self._load_on_startup()
            if self._mark_startup_complete_and_consume_deferred():
                self._process_deferred_skill_load()

            # trigger a sync so we dont need to wait for the plugin to volunteer info
            self._sync_skill_loading_state()

            if not all((self._network_loaded.is_set(),
                        self._internet_loaded.is_set())):
                self.bus.emit(Message(
                    'mycroft.skills.error',
                    {'internet_loaded': self._internet_loaded.is_set(),
                     'network_loaded': self._network_loaded.is_set()}))
        else:
            # Default: load all skills unconditionally at startup
            self._load_new_skills()

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

    def _load_on_network(self) -> None:
        """Load skills that require a network connection."""
        if self._detected_installed_skills:  # ensure we have skills installed
            LOG.info('Loading skills that require network...')
            self._load_new_skills(network=True, internet=False)
        self._network_loaded.set()

    def _load_on_internet(self) -> None:
        """Load skills that require both internet and network connections."""
        if self._detected_installed_skills:  # ensure we have skills installed
            LOG.info('Loading skills that require internet (and network)...')
            self._load_new_skills(network=True, internet=True)
        self._internet_loaded.set()
        self._network_loaded.set()

    def _unload_on_network_disconnect(self) -> None:
        """Unload skills that require a network connection to work."""
        # TODO - implementation missing

    def _unload_on_internet_disconnect(self) -> None:
        """Unload skills that require an internet connection to work."""
        # TODO - implementation missing

    def _unload_on_gui_disconnect(self) -> None:
        """Unload skills that require a GUI to work."""
        # TODO - implementation missing

    def _load_on_startup(self) -> None:
        """Handle offline skills load on startup."""
        if self._detected_installed_skills:  # ensure we have skills installed
            LOG.info('Loading offline skills...')
            self._load_new_skills(network=False, internet=False)

    def _load_new_skills(self, network: Optional[bool] = None,
                          internet: Optional[bool] = None,
                          gui: Optional[bool] = None) -> List[str]:
        """Handle loading of skills installed since startup.

        Args:
            network (bool): Network connection status.
            internet (bool): Internet connection status.
            gui (bool): GUI connection status.

        Returns:
            List[str]: Ids of the skills this call loaded.
        """
        if self._use_deferred_loading:
            # When deferred loading is enabled, check event flags for gating
            if network is None:
                network = self._network_event.is_set()
            if internet is None:
                internet = self._connected_event.is_set()
        else:
            # When deferred loading is disabled, bypass gating and load all skills
            if network is None:
                network = True
            if internet is None:
                internet = True

        if gui is None:
            gui = self._gui_event.is_set() or is_gui_connected(self.bus)

        loaded = self._load_untracked_plugin_skills(network=network, internet=internet)

        if loaded:
            # Pipeline engines consume intent registrations as they arrive;
            # engines with a deferred training step (e.g. padatious) train on
            # this request. It is fire-and-forget: no reply topic is part of
            # the spec, a single responder could not speak for every loaded
            # pipeline, and most engines have nothing pending — so blocking
            # here only stalled boot until a timeout on installs without a
            # deferred-training engine.
            LOG.debug("Requesting pipeline intent training")
            self.bus.emit(Message("mycroft.skills.train"))
        return loaded

    def _rescan_plugin_skills(self) -> List[str]:
        """Run one discovery pass now instead of waiting for the periodic scan.

        Until the manager is ready, ``run()`` owns the first load: it waits
        for the intent service so no registration is lost, and anything that
        became discoverable before then is picked up by that load or by the
        periodic scan that follows it.

        Returns:
            List[str]: Ids of the skills this pass loaded.
        """
        if not self.is_all_loaded():
            LOG.debug("Skill manager is not ready yet, leaving the new skills to the startup load")
            return []
        try:
            return self._load_new_skills()
        except Exception:
            LOG.exception("Failed to load newly installed skills")
            return []

    def handle_install_complete(self, message: Message) -> None:
        """Load the plugin skills an installer run just made discoverable.

        Args:
            message: ``ovos.skills.install.complete`` or ``ovos.pip.install.complete``.
        """
        # Upgrades first, and the order matters. Everything below imports:
        # a skill rebuilt while an upgraded dependency is still cached is
        # built against the old library, and one needing a symbol only the
        # new library has cannot be built at all. A rescan run first would
        # build a newly declared skill from the stale modules and record it
        # against the new version, leaving the upgrade check nothing to see.
        forgotten = self._forget_upgraded_dependencies()
        if forgotten:
            LOG.info(f"Forgot upgraded dependencies before reloading: {forgotten}")
        reloaded = self._reload_upgraded_plugin_skills()
        if reloaded:
            LOG.info(f"Reloaded skills the installer upgraded: {reloaded}")
        loaded = self._rescan_plugin_skills()
        if loaded:
            LOG.info(f"Loaded skills reported by the installer: {loaded}")
        if reloaded and not loaded:
            # `_load_new_skills()` trains the deferred engines after a load;
            # a reload registers intents just the same, and an upgrade that
            # changed them leaves padatious on the previous set otherwise.
            # Only when the scan did not already do it.
            self.bus.emit(Message("mycroft.skills.train"))

    def handle_rescan_request(self, message: Message) -> None:
        """Scan for newly installed plugin skills and report what was loaded.

        Args:
            message: ``skillmanager.rescan``; the response carries ``loaded``,
                the ids this scan loaded, empty when it loaded nothing.
        """
        loaded = self._rescan_plugin_skills()
        self.bus.emit(message.response({"loaded": loaded}))

    def _unload_plugin_skill(self, skill_id: str) -> None:
        """Unload a plugin skill.

        Args:
            skill_id (str): Identifier of the plugin skill to unload.
        """
        # Get skill_loader while holding lock, then release lock before shutdown
        # to prevent deadlocks if skill shutdown code tries to re-enter the lock
        skill_loader = None
        with self._plugin_skills_lock:
            if skill_id in self.plugin_skills:
                LOG.info('Unloading plugin skill: ' + skill_id)
                skill_loader = self.plugin_skills.pop(skill_id)
                self._plugin_skill_serials.pop(skill_id, None)
                self._plugin_skill_versions.pop(skill_id, None)

        self._shutdown_skill_loader(skill_loader)

    def _shutdown_skill_loader(self, skill_loader: Optional[PluginSkillLoader]) -> None:
        """Run the shutdown hooks of a loader already detached from tracking.

        The caller holds no lock here: skill shutdown code may re-enter
        ``_plugin_skills_lock`` and running it under that lock deadlocks.

        Args:
            skill_loader: The detached loader, or None when nothing was detached.
        """
        if skill_loader is None or skill_loader.instance is None:
            return
        try:
            skill_loader.instance.shutdown()
        except Exception:
            LOG.exception('Failed to run skill specific shutdown code: ' + skill_loader.skill_id)
        try:
            skill_loader.instance.default_shutdown()
        except Exception:
            LOG.exception('Failed to shutdown skill: ' + skill_loader.skill_id)

    @staticmethod
    def _declared_skill_versions() -> Dict[str, str]:
        """The installed version behind every declared skill entry point.

        Read from package metadata without importing anything, the same way
        `_declared_skill_plugins()` reads the names beside them.

        Returns:
            Entry point name to distribution version. A skill whose metadata
            cannot be read is left out rather than guessed at.
        """
        versions: Dict[str, str] = {}
        try:
            groups = [PluginTypes.SKILL.value]
            groups += [old for old, new in DEPRECATED_ENTRYPOINTS.items()
                       if new == PluginTypes.SKILL.value]
            for group in groups:
                for point in entry_points(group=group):
                    dist = getattr(point, "dist", None)
                    version = getattr(dist, "version", None)
                    if version:
                        versions[point.name] = version
        except Exception:
            LOG.exception("Could not read the declared skill versions")
        return versions

    @staticmethod
    def _installed_distributions() -> Optional[Dict[str, str]]:
        """Every installed distribution's version, read without importing.

        Deliberately does NOT read each distribution's file list: that parses
        a RECORD per package and this runs at every install. The modules are
        read separately, for the handful that actually changed.

        Returns:
            Normalized distribution name to version, or None if the scan
            itself failed. The two are not the same: a runtime with nothing
            installed legitimately reads empty, and treating a failed scan as
            empty would let the next install record a post-upgrade baseline
            and forget nothing, for the life of the process.
        """
        versions: Dict[str, str] = {}
        try:
            for dist in distributions():
                name = (dist.metadata["Name"] if dist.metadata else None) or ""
                version = getattr(dist, "version", None)
                key = canonicalize_name(name.strip()) if name.strip() else ""
                # FIRST wins, not last. One name can be installed twice on one
                # path -- a hosted runtime installs skills into a writable venv
                # layered over the image's, and both copies are returned here.
                # `distributions()` walks sys.path in order, so the first is the
                # one an import actually gets; recording the later one pins the
                # version to a copy nothing ever imports, and an upgrade of the
                # live copy then looks like no change at all.
                if key and version and key not in versions:
                    versions[key] = str(version)
        except Exception:
            LOG.exception("Could not read the installed distributions")
            return None
        return versions

    def _modules_of(self, names: Set[str]) -> Dict[str, Set[str]]:
        """The top-level modules each named distribution installs.

        One pass for all of them. ``top_level.txt`` when the wheel carries
        one, and otherwise the first path component of the files it recorded.
        Nothing is imported.
        """
        found: Dict[str, Set[str]] = {}
        if not names:
            return found
        try:
            for dist in distributions():
                raw = (dist.metadata["Name"] if dist.metadata else None) or ""
                name = canonicalize_name(raw.strip()) if raw.strip() else ""
                if name not in names or name in found:
                    continue
                modules: Set[str] = set()
                try:
                    declared = dist.read_text("top_level.txt") or ""
                    modules.update(line.strip() for line in declared.splitlines() if line.strip())
                    if not modules:
                        for path in dist.files or []:
                            head = str(path).split("/")[0]
                            if head and not head.endswith((".dist-info", ".egg-info", ".pth")):
                                modules.add(head[:-3] if head.endswith(".py") else head)
                except Exception:
                    # Left out of the result on purpose. The caller holds that
                    # distribution at its old version so the next install
                    # tries again, instead of recording the upgrade as done.
                    LOG.debug(f"Could not read the modules of {name}")
                    continue
                # The dotted modules this distribution actually ships, not
                # just their top level. Two distributions can share a
                # namespace -- `shared` from dist-a and `shared.plugin_b` from
                # dist-b -- and evicting everything under a shared top level
                # would forget the other distribution's code on an upgrade
                # that never touched it.
                owned: Set[str] = set()
                try:
                    for path in dist.files or []:
                        parts = [part for part in str(path).split("/") if part]
                        if not parts or parts[0].endswith(
                                (".dist-info", ".egg-info", ".pth")):
                            continue
                        if not parts[-1].endswith(".py"):
                            continue
                        parts[-1] = parts[-1][:-3]
                        if parts[-1] == "__init__":
                            parts.pop()
                        if parts and all(part.isidentifier() for part in parts):
                            owned.add(".".join(parts))
                except Exception:
                    LOG.debug(f"Could not read the file list of {name}")
                found[name] = {m for m in modules if m and m.isidentifier()}
                self._distribution_owned[name] = owned
        except Exception:
            LOG.exception("Could not read the modules of the changed distributions")
        return found

    def _forget_upgraded_dependencies(self) -> List[str]:
        """Drop upgraded DEPENDENCIES from the import cache, not just skills.

        `_forget_skill_modules` forgets the skill's own package. That is not
        enough: an installer upgrading a skill upgrades whatever the new
        version requires, and a shared helper library is the common case. The
        process keeps the old library in `sys.modules` for ever, so every
        skill reloaded afterwards is built against it -- and one that needs a
        symbol only the new version has cannot import at all.

        Seen in production on 2026-09-22: `thalovant-skillkit` went 0.16.0 ->
        0.18.0 as a dependency of a skill upgrade, and the next three skills
        to reload each died on a name the running copy did not have --
        `ShuffleBagPool`, `combined_lines`, `ThalovantConversationalCommonPlaySkill`.
        All three were on disk. The manager logged "not discoverable after
        its upgrade, leaving it unloaded" and gave up, and only a restart of
        the process brought them back.

        The runtime's own machinery is never forgotten. Re-importing it under
        a live process would leave running skills as instances of classes
        their own module no longer defines; a change there is a restart, and
        pretending otherwise would trade a dead skill for a corrupt one.

        Returns:
            List[str]: The distributions whose modules this call forgot.
        """
        previous = self._distribution_versions
        current = self._installed_distributions()
        if current is None:
            # The baseline stands. Replacing it with a guess would be worse
            # than knowing nothing about this install.
            return []
        if previous is None:
            self._distribution_versions = current
            return []
        changed = {name for name, version in current.items()
                   if name in previous and previous[name] != version}
        if not changed:
            self._distribution_versions = current
            return []
        installs = self._modules_of(changed)
        # A changed distribution whose modules could not be read keeps its old
        # version, so the next install sees it as changed and tries again. Any
        # other outcome would record an upgrade that was never acted on and
        # leave the stale modules cached until the process restarts.
        self._distribution_versions = {
            name: (version if name not in changed or name in installs
                   else previous.get(name, version))
            for name, version in current.items()
        }
        forgotten: List[str] = []
        for name in sorted(changed):
            modules = {module for module in installs.get(name, set())
                       if module not in self._protected_modules}
            if not modules:
                continue
            dropped = False
            # Children are taken from the distribution's own recorded modules,
            # so a sibling package that merely shares a namespace prefix is
            # left alone. Falling back to the top level keeps the old,
            # broader behaviour only when the file list could not be read.
            owned = {m for m in self._distribution_owned.get(name) or set()
                     if m.split(".")[0] in modules}
            if owned:
                # Exactly what this distribution ships, plus anything under one
                # of its SUBmodules. The top level is deliberately not expanded:
                # `shared` can be a namespace two distributions share, and
                # expanding it is what forgot `shared.plugin_b` on an upgrade of
                # the distribution that only owns `shared.plugin_a`.
                deeper = {m for m in owned if "." in m}
                def _ours(module: str) -> bool:
                    return (module in owned
                            or any(module.startswith(f"{m}.") for m in deeper))
            else:
                # No readable file list: fall back to the old, broader rule
                # rather than forget nothing at all.
                def _ours(module: str) -> bool:
                    return (module in modules
                            or any(module.startswith(f"{m}.") for m in modules))
            for cached in [n for n in list(sys.modules) if _ours(n)]:
                sys.modules.pop(cached, None)
                dropped = True
            if dropped:
                forgotten.append(name)
                LOG.info(f"{name} changed {previous[name]} -> {current[name]}; "
                         "forgetting its modules so reloads read the new code")
        if forgotten:
            importlib.invalidate_caches()
        return forgotten

    def _forget_skill_modules(self, skill_id: str) -> None:
        """Drop a skill's package from the import cache so it is read again.

        pip replaces the files on disk; `sys.modules` still holds the module
        objects built from the previous ones, and an entry point loaded again
        hands back that same cached module. Without this the manager unloads
        and reloads a skill and gets the version it already had.

        Args:
            skill_id (str): The skill whose package should be forgotten.
        """
        loader = self.plugin_skills.get(skill_id)
        skill_class = getattr(loader, "skill_class", None) if loader else None
        module = getattr(skill_class, "__module__", "") or ""
        package = module.split(".")[0]
        if not package:
            LOG.debug(f"No module recorded for {skill_id}, leaving the import cache alone")
            return
        for name in [n for n in list(sys.modules)
                     if n == package or n.startswith(f"{package}.")]:
            sys.modules.pop(name, None)
        importlib.invalidate_caches()

    def _reload_upgraded_plugin_skills(self) -> List[str]:
        """Reload the loaded plugin skills whose installed version changed.

        An installer that upgrades a skill already running leaves the new
        files on disk and the old code in memory: discovery only ever loads
        what is *new*, so an upgrade in place is silently a no-op and the
        runtime keeps answering from the previous version until the process
        restarts. Seen in the wild as a skill reporting the version it had
        just been upgraded to while still running the one before it.

        Returns:
            List[str]: Ids of the skills this call reloaded.
        """
        installed = self._declared_skill_versions()
        if not installed:
            return []
        with self._plugin_skills_lock:
            loaded = dict(self._plugin_skill_versions)
        upgraded = [skill_id for skill_id, was in loaded.items()
                    if skill_id in installed and installed[skill_id] != was]
        reloaded: List[str] = []
        for skill_id in upgraded:
            now = installed[skill_id]
            LOG.info(f"{skill_id} was upgraded {loaded[skill_id]} -> {now}, reloading it")
            self._forget_skill_modules(skill_id)
            self._unload_plugin_skill(skill_id)
            # Reserve before loading, and keep the reservation for the whole
            # attempt. Without it this pass cannot tell "my load failed" from
            # "a scan got there first": `_load_plugin_skill()` answers None to
            # both, and the detach below would then throw away a loader that
            # the other attempt owns and had already loaded. The modules are
            # forgotten either way, so an attempt that beat us here builds the
            # new code too and there is nothing to redo.
            if not self._reserve_plugin_skill_load(skill_id):
                LOG.debug(f"{skill_id} is already being loaded, leaving its upgrade to that attempt")
                continue
            try:
                plugins = find_skill_plugins()
            except Exception:
                LOG.exception(f"Could not rediscover {skill_id} after its upgrade")
                self._release_plugin_skill_load(skill_id)
                continue
            # read again after the purge: this is the version behind the
            # class discovery just handed back
            now = self._declared_skill_versions().get(skill_id, now)
            plug = plugins.get(skill_id)
            if plug is None:
                # The package went away between the upgrade and here, or its
                # import broke. The undiscoverable pass owns that case.
                LOG.warning(f"{skill_id} is not discoverable after its upgrade, leaving it unloaded")
                with self._plugin_skills_lock:
                    self._plugin_skill_versions.pop(skill_id, None)
                self._release_plugin_skill_load(skill_id)
                continue
            # `_load_plugin_skill()` releases the reservation itself, and a
            # load that succeeded keeps its serial on the tracked loader --
            # releasing again here would take that serial away.
            if self._load_plugin_skill(skill_id, plug, reserved=True, version=now):
                reloaded.append(skill_id)
            else:
                # `_load_plugin_skill()` tracks the loader it built even when
                # the load failed, and records neither a version nor a retry
                # for it. Left alone, the skill is tracked - so every later
                # scan skips it - with nothing for the upgrade check to match
                # on either, and it never loads again. This attempt held the
                # reservation throughout, so the loader to detach is its own.
                LOG.warning(f"{skill_id} failed to load after its upgrade, detaching it for retry")
                self._unload_plugin_skill(skill_id)
                self._record_plugin_skill_failure(skill_id)
        return reloaded

    @staticmethod
    def _declared_skill_plugins() -> Optional[Set[str]]:
        """The skill entry points installed packages declare, without importing any of them.

        `find_skill_plugins()` reports what it could import and swallows the error when an
        import fails, so an empty result means either "every skill package is gone" or
        "nothing would import this time". Only package metadata separates those two, and
        they call for opposite answers.

        Returns:
            The declared entry point names, or None when the metadata could not be read -
            which is "cannot tell", not "nothing is installed".
        """
        try:
            groups = [PluginTypes.SKILL.value]
            groups += [old for old, new in DEPRECATED_ENTRYPOINTS.items()
                       if new == PluginTypes.SKILL.value]
            declared = set()
            for group in groups:
                declared.update(point.name for point in entry_points(group=group))
            return declared
        except Exception:
            LOG.exception("Could not read the declared skill entry points")
            return None

    def _unload_undiscoverable_plugin_skills(self) -> List[str]:
        """Unload the tracked plugin skills whose package is no longer discoverable.

        Returns:
            List[str]: Ids of the skills this call unloaded.
        """
        # What this pass judges is read before the packages are. A loader
        # tracked or a load reserved after this point started from a package
        # installed after the reading below, so it is not this pass's to
        # remove, however stale that reading is by the time the verdicts
        # land; each attempt's serial tells it from the one read here.
        with self._plugin_skills_lock:
            judged = {skill_id: self._plugin_skill_serials.get(skill_id)
                      for skill_id in set(self.plugin_skills) | self._loading_plugin_skills}
        try:
            discoverable = set(find_skill_plugins())
        except Exception:
            LOG.exception("Plugin skill discovery failed, keeping the loaded skills")
            return []
        # `find_skill_plugins()` reports what it could import and swallows the error
        # when an import fails, so a skill whose package is present but whose import
        # broke is missing from `discoverable` exactly like an uninstalled one. Only
        # the entry points the installed packages declare tell those apart, and that
        # is read without importing anything, so it is read on every pass rather than
        # only when nothing imported at all. Unloading on an import failure would shut
        # a still-installed skill down and discard its loader.
        declared = self._declared_skill_plugins()
        if declared is None:
            LOG.warning("The installed skill entry points could not be read, so a "
                        "missing plugin skill cannot be told from one that would not "
                        "import; keeping the loaded skills")
            return []
        installed = discoverable | declared
        if not discoverable and declared:
            LOG.warning(f"Plugin skill discovery returned nothing while {len(declared)} "
                        f"skill entry points are still installed; keeping them")
        with self._plugin_skills_lock:
            gone = [skill_id for skill_id, serial in judged.items()
                    if skill_id not in installed
                    and self._plugin_skill_serials.get(skill_id) == serial]
            removed = [skill_id for skill_id in gone if skill_id in self.plugin_skills]
            # detach under the lock that decided the removal, and keep the
            # loader instance rather than the id: once an id stops being
            # tracked an overlapping pass is free to load a replacement for
            # it, and a detach that named only the id would pop and shut down
            # that replacement instead of the loader this pass chose
            detached = [(skill_id, self.plugin_skills.pop(skill_id))
                        for skill_id in removed]
            for skill_id in removed:
                self._plugin_skill_serials.pop(skill_id, None)
            # a failed load leaves a backoff record and no loader; without
            # this a reinstall of that package would wait out the backoff
            stale_failures = [skill_id for skill_id in self._plugin_skill_failures
                              if skill_id not in installed]
            # a load in flight holds the reservation and is not in
            # `plugin_skills` yet, so there is nothing to detach for it here.
            # Record the verdict instead: `_load_plugin_skill` discards the
            # loader it is about to track rather than reviving a dead package.
            # Only the reservation read above gets it: one made since belongs
            # to a reinstall, and `_reserve_plugin_skill_load` already cleared
            # whatever an older pass had left for that id.
            self._plugin_skill_unload_pending.update(
                skill_id for skill_id in gone
                if skill_id in self._loading_plugin_skills)
        for skill_id, skill_loader in detached:
            LOG.info('Unloading plugin skill: ' + skill_id)
            self._shutdown_skill_loader(skill_loader)
        for skill_id in set(removed) | set(stale_failures):
            self._clear_plugin_skill_failure(skill_id)
            self._logged_skill_warnings.discard(skill_id)
        return removed

    def handle_uninstall_complete(self, message: Message) -> None:
        """Unload the plugin skills an installer run just removed.

        Args:
            message: ``ovos.skills.uninstall.complete`` or ``ovos.pip.uninstall.complete``.
        """
        removed = self._unload_undiscoverable_plugin_skills()
        if removed:
            LOG.info(f"Unloaded skills removed by the installer: {removed}")

    def is_alive(self, message: Optional[Message] = None) -> bool:
        """Respond to is_alive status request."""
        return self.status.state >= ProcessState.ALIVE

    def is_all_loaded(self, message: Optional[Message] = None) -> bool:
        """Respond to all_loaded status request."""
        return self.status.state == ProcessState.READY

    def send_skill_list(self, message: Optional[Message] = None) -> None:
        """Send list of loaded skills."""
        try:
            message_data = {}
            # TODO handle external skills, OVOSAbstractApp/Hivemind skills are not accounted for
            with self._plugin_skills_lock:
                skills = dict(self.plugin_skills)
            for skill_loader in skills.values():
                message_data[skill_loader.skill_id] = {
                    "active": skill_loader.active and skill_loader.loaded,
                    "id": skill_loader.skill_id}

            self.bus.emit(Message('mycroft.skills.list', data=message_data))
        except Exception:
            LOG.exception('Failed to send skill list')

    def deactivate_skill(self, message: Message) -> None:
        """Deactivate a skill."""
        try:
            # TODO handle external skills, OVOSAbstractApp/Hivemind skills are not accounted for
            with self._plugin_skills_lock:
                skills = dict(self.plugin_skills)
            for skill_loader in skills.values():
                if message.data['skill'] == skill_loader.skill_id:
                    LOG.info("Deactivating (unloading) skill: " + skill_loader.skill_id)
                    skill_loader.deactivate()
                    self.bus.emit(message.response())
        except Exception as err:
            LOG.exception('Failed to deactivate ' + message.data['skill'])
            self.bus.emit(message.response({'error': f'failed: {err}'}))

    def deactivate_except(self, message: Message) -> None:
        """Deactivate all skills except the provided."""
        try:
            skill_to_keep = message.data['skill']
            LOG.info(f'Deactivating (unloading) all skills except {skill_to_keep}')
            # TODO handle external skills, OVOSAbstractApp/Hivemind skills are not accounted for
            with self._plugin_skills_lock:
                skills = dict(self.plugin_skills)
            for skill in skills.values():
                if skill.skill_id != skill_to_keep:
                    skill.deactivate()
            LOG.info('Couldn\'t find skill ' + message.data['skill'])
        except Exception:
            LOG.exception('An error occurred during skill deactivation!')

    def activate_skill(self, message: Message) -> None:
        """Activate a deactivated skill."""
        try:
            # TODO handle external skills, OVOSAbstractApp/Hivemind skills are not accounted for
            with self._plugin_skills_lock:
                skills = dict(self.plugin_skills)
            for skill_loader in skills.values():
                if (message.data['skill'] in ('all', skill_loader.skill_id)
                        and not skill_loader.active):
                    skill_loader.activate()
                    self.bus.emit(message.response())
        except Exception as err:
            LOG.exception(f'Couldn\'t activate (load) skill {message.data["skill"]}')
            self.bus.emit(message.response({'error': f'failed: {err}'}))

    def stop(self) -> None:
        """alias for shutdown (backwards compat)"""
        return self.shutdown()

    def shutdown(self) -> None:
        """Tell the manager to shutdown."""
        self.status.set_stopping()
        self._stop_event.set()

        # Do a clean shutdown of all skills
        for skill_id in list(self.plugin_skills.keys()):
            try:
                self._unload_plugin_skill(skill_id)
            except Exception as e:
                LOG.error(f"Failed to cleanly unload skill '{skill_id}' ({e})")
        if self.intents:
            try:
                self.intents.shutdown()
            except Exception as e:
                LOG.error(f"Failed to cleanly unload intent service ({e})")
        if self.osm:
            try:
                self.osm.shutdown()
            except Exception as e:
                LOG.error(f"Failed to cleanly unload skill installer ({e})")
        if self.event_scheduler:
            try:
                self.event_scheduler.shutdown()
            except Exception as e:
                LOG.error(f"Failed to cleanly unload event scheduler ({e})")
        if self._settings_watchdog:
            try:
                self._settings_watchdog.shutdown()
            except Exception as e:
                LOG.error(f"Failed to cleanly unload settings watchdog ({e})")
