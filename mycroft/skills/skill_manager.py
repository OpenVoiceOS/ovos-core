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
from os.path import basename
from glob import glob
from threading import Thread, Event, Lock
from time import sleep, monotonic
from mycroft.util.process_utils import ProcessStatus, StatusCallbackMap, ProcessState

from ovos_backend_client.pairing import is_paired
from mycroft.enclosure.api import EnclosureAPI
from ovos_config.config import Configuration
from mycroft.messagebus.message import Message
from mycroft.util.log import LOG
from mycroft.util import connected
from mycroft.skills.skill_loader import get_skill_directories, SkillLoader, PluginSkillLoader, find_skill_plugins
from mycroft.skills.skill_updater import SeleneSkillManifestUploader
from mycroft.messagebus import MessageBusClient

# do not delete - bacwards compat imports
from mycroft.deprecated.skills.settings import UploadQueue, SkillSettingsDownloader
from mycroft.deprecated.skills.skill_updater import SkillUpdater

SKILL_MAIN_MODULE = '__init__.py'


def _shutdown_skill(instance):
    """Shutdown a skill.

    Call the default_shutdown method of the skill, will produce a warning if
    the shutdown process takes longer than 1 second.

    Args:
        instance (MycroftSkill): Skill instance to shutdown
    """
    try:
        ref_time = monotonic()
        # Perform the shutdown
        instance.default_shutdown()

        shutdown_time = monotonic() - ref_time
        if shutdown_time > 1:
            LOG.warning(f'{instance.skill_id} shutdown took {shutdown_time} seconds')
    except Exception:
        LOG.exception(f'Failed to shut down skill: {instance.skill_id}')


def on_started():
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

    def __init__(self, bus, watchdog=None, alive_hook=on_alive, started_hook=on_started, ready_hook=on_ready,
         error_hook=on_error, stopping_hook=on_stopping):
        """Constructor

        Args:
            bus (event emitter): Mycroft messagebus connection
            watchdog (callable): optional watchdog function
        """
        super(SkillManager, self).__init__()
        self.bus = bus
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
        self.config = Configuration()
        self.manifest_uploader = SeleneSkillManifestUploader()
        self.upload_queue = UploadQueue()  # DEPRECATED

        self.skill_loaders = {}
        self.plugin_skills = {}
        self.enclosure = EnclosureAPI(bus)
        self.initial_load_complete = False
        self.num_install_retries = 0
        self.empty_skill_dirs = set()  # Save a record of empty skill dirs.

        self._define_message_bus_events()
        self.daemon = True

        self.status.bind(self.bus)

    def _define_message_bus_events(self):
        """Define message bus events with handlers defined in this class."""
        # Update on initial connection
        self.bus.once(
            'mycroft.internet.connected',
            lambda x: self._connected_event.set()
        )

        # Update upon request
        self.bus.on('skillmanager.list', self.send_skill_list)
        self.bus.on('skillmanager.deactivate', self.deactivate_skill)
        self.bus.on('skillmanager.keep', self.deactivate_except)
        self.bus.on('skillmanager.activate', self.activate_skill)
        self.bus.once('mycroft.skills.initialized',
                      self.handle_check_device_readiness)
        self.bus.once('mycroft.skills.trained', self.handle_initial_training)

    def is_device_ready(self):
        is_ready = False
        # different setups will have different needs
        # eg, a server does not care about audio
        # pairing -> device is paired
        # internet -> device is connected to the internet - NOT IMPLEMENTED
        # skills -> skills reported ready
        # speech -> stt reported ready
        # audio -> audio playback reported ready
        # gui -> gui websocket reported ready - NOT IMPLEMENTED
        # enclosure -> enclosure/HAL reported ready - NOT IMPLEMENTED
        services = {k: False for k in
                    self.config.get("ready_settings", ["skills"])}
        start = monotonic()
        while not is_ready:
            is_ready = self.check_services_ready(services)
            if is_ready:
                break
            elif monotonic() - start >= 60:
                raise TimeoutError(
                    f'Timeout waiting for services start. services={services}')
            else:
                sleep(3)
        return is_ready

    def handle_check_device_readiness(self, message):
        ready = False
        while not ready:
            try:
                ready = self.is_device_ready()
            except TimeoutError:
                if is_paired():
                    LOG.warning("mycroft should already have reported ready!")
                sleep(5)

        LOG.info("Mycroft is all loaded and ready to roll!")
        self.bus.emit(message.reply('mycroft.ready'))

    def check_services_ready(self, services):
        """Report if all specified services are ready.

        services (iterable): service names to check.
        """
        backend_type = self.config.get("server", {}).get("backend_type", "offline")
        for ser, rdy in services.items():
            if rdy:
                # already reported ready
                continue
            if ser in ["pairing", "setup"]:

                def setup_finish_interrupt(message):
                    nonlocal services
                    services[ser] = True

                # if setup finishes naturally be ready early
                self.bus.once("ovos.setup.finished", setup_finish_interrupt)

                # pairing service (setup skill) needs to be available
                # in offline mode (default) is_paired always returns True
                # but setup skill may enable backend
                # wait for backend selection event
                response = self.bus.wait_for_response(Message('ovos.setup.state.get',
                                                              context={"source": "skills",
                                                                       "destination": "ovos-setup"}), 'ovos.setup.state')
                if response:
                    state = response.data['state']
                    LOG.debug(f"Setup state: {state}")
                    if state == "finished":
                        services[ser] = True
                elif not services[ser] and backend_type == "selene":
                    # older verson / alternate setup skill installed
                    services[ser] = is_paired(ignore_errors=True)
            elif ser in ["gui", "enclosure"]:
                # not implemented
                services[ser] = True
                continue
            response = self.bus.wait_for_response(
                Message(f'mycroft.{ser}.is_ready',
                        context={"source": "skills", "destination": ser}))
            if response and response.data['status']:
                services[ser] = True
        return all([services[ser] for ser in services])

    @property
    def skills_config(self):
        return self.config['skills']

    @property
    def msm(self):
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning and returns None
        """
        LOG.warning("msm has been deprecated!")
        return None

    @property
    def settings_downloader(self):
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning and returns None
        """
        LOG.warning("settings_downloader has been deprecated, "
                    "it is now managed at skill level")
        return SkillSettingsDownloader(self.bus)

    @property
    def skill_updater(self):
        LOG.warning("SkillUpdater has been deprecated! Please use self.manifest_uploader instead")
        return SkillUpdater()

    @staticmethod
    def create_msm():
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning and returns None
        """
        return None

    def schedule_now(self, _):
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning
        """

    def handle_paired(self, _):
        """DEPRECATED: do not use, method only for api backwards compatibility
        upload of settings is done at individual skill level in ovos-core """
        pass

    def load_plugin_skills(self):
        plugins = find_skill_plugins()
        loaded_skill_ids = [basename(p) for p in self.skill_loaders]
        for skill_id, plug in plugins.items():
            if skill_id not in self.plugin_skills and skill_id not in loaded_skill_ids:
                self._load_plugin_skill(skill_id, plug)

    def _load_plugin_skill(self, skill_id, skill_plugin):
        skill_loader = PluginSkillLoader(self.bus, skill_id)
        try:
            load_status = skill_loader.load(skill_plugin)
        except Exception:
            LOG.exception(f'Load of skill {skill_id} failed!')
            load_status = False
        finally:
            self.plugin_skills[skill_id] = skill_loader

        return skill_loader if load_status else None

    def load_priority(self):
        skill_ids = {os.path.basename(skill_path): skill_path
                     for skill_path in self._get_skill_directories()}
        priority_skills = self.skills_config.get("priority_skills") or []
        for skill_id in priority_skills:
            skill_path = skill_ids.get(skill_id)
            if skill_path is not None:
                self._load_skill(skill_path)
            else:
                LOG.error(f'Priority skill {skill_id} can\'t be found')

    def handle_initial_training(self, message):
        self.initial_load_complete = True

    def run(self):
        """Load skills and update periodically from disk and internet."""
        self._remove_git_locks()

        self.load_priority()

        self.status.set_alive()

        if self.skills_config.get("wait_for_internet", True):
            while not connected() and not self._connected_event.is_set():
                sleep(1)
            self._connected_event.set()

        self._load_on_startup()

        # Sync backend and skills.
        # why does selene need to know about skills without settings?
        if is_paired():
            self.manifest_uploader.post_manifest()

        # wait for initial intents training
        while not self.initial_load_complete:
            sleep(0.5)
        self.status.set_ready()

        # Scan the file folder that contains Skills.  If a Skill is updated,
        # unload the existing version from memory and reload from the disk.
        while not self._stop_event.is_set():
            try:
                self._unload_removed_skills()
                self._load_new_skills()
                self._watchdog()
                sleep(2)  # Pause briefly before beginning next scan
            except Exception:
                LOG.exception('Something really unexpected has occured '
                              'and the skill manager loop safety harness was '
                              'hit.')
                sleep(30)

    def _remove_git_locks(self):
        """If git gets killed from an abrupt shutdown it leaves lock files."""
        for skills_dir in get_skill_directories():
            lock_path = os.path.join(skills_dir, '*/.git/index.lock')
            for i in glob(lock_path):
                LOG.warning('Found and removed git lock file: ' + i)
                os.remove(i)

    def _load_on_startup(self):
        """Handle initial skill load."""
        self.load_plugin_skills()
        LOG.info('Loading installed skills...')
        self._load_new_skills()
        LOG.info("Skills all loaded!")
        self.bus.emit(Message('mycroft.skills.initialized'))

    def _load_new_skills(self):
        """Handle load of skills installed since startup."""
        for skill_dir in self._get_skill_directories():
            replaced_skills = []
            # by definition skill_id == folder name
            skill_id = os.path.basename(skill_dir)

            # a local source install is replacing this plugin, unload it!
            if skill_id in self.plugin_skills:
                LOG.info(f"{skill_id} plugin will be replaced by a local version: {skill_dir}")
                self._unload_plugin_skill(skill_id)

            for old_skill_dir, skill_loader in self.skill_loaders.items():
                if old_skill_dir != skill_dir and \
                        skill_loader.skill_id == skill_id:
                    # a higher priority equivalent has been detected!
                    replaced_skills.append(old_skill_dir)

            for old_skill_dir in replaced_skills:
                # unload the old skill
                self._unload_skill(old_skill_dir)

            if skill_dir not in self.skill_loaders:
                self._load_skill(skill_dir)

    def _load_skill(self, skill_directory):
        if not self.config["websocket"].get("shared_connection", True):
            # see BusBricker skill to understand why this matters
            # any skill can manipulate the bus from other skills
            # this patch ensures each skill gets it's own
            # connection that can't be manipulated by others
            # https://github.com/EvilJarbas/BusBrickerSkill
            bus = MessageBusClient(cache=True)
            bus.run_in_thread()
        else:
            bus = self.bus
        skill_loader = SkillLoader(bus, skill_directory)
        try:
            load_status = skill_loader.load()
        except Exception:
            LOG.exception(f'Load of skill {skill_directory} failed!')
            load_status = False
        finally:
            self.skill_loaders[skill_directory] = skill_loader

        return skill_loader if load_status else None

    def _unload_skill(self, skill_dir):
        if skill_dir in self.skill_loaders:
            skill = self.skill_loaders[skill_dir]
            LOG.info(f'removing {skill.skill_id}')
            try:
                skill.unload()
            except Exception:
                LOG.exception('Failed to shutdown skill ' + skill.id)
            del self.skill_loaders[skill_dir]

    def _get_skill_directories(self):
        # let's scan all valid directories, if a skill folder name exists in
        # more than one of these then it should override the previous
        skillmap = {}
        for skills_dir in get_skill_directories():
            if not os.path.isdir(skills_dir):
                continue
            for skill_id in os.listdir(skills_dir):
                skill = os.path.join(skills_dir, skill_id)
                # NOTE: empty folders mean the skill should NOT be loaded
                if os.path.isdir(skill):
                    skillmap[skill_id] = skill

        for skill_id, skill_dir in skillmap.items():
            # TODO: all python packages must have __init__.py!  Better way?
            # check if folder is a skill (must have __init__.py)
            if SKILL_MAIN_MODULE in os.listdir(skill_dir):
                if skill_dir in self.empty_skill_dirs:
                    self.empty_skill_dirs.discard(skill_dir)
            else:
                if skill_dir not in self.empty_skill_dirs:
                    self.empty_skill_dirs.add(skill_dir)
                    LOG.debug('Found skills directory with no skill: ' +
                              skill_dir)

        return skillmap.values()

    def _unload_removed_skills(self):
        """Shutdown removed skills."""
        skill_dirs = self._get_skill_directories()
        # Find loaded skills that don't exist on disk
        removed_skills = [
            s for s in self.skill_loaders.keys() if s not in skill_dirs
        ]
        for skill_dir in removed_skills:
            self._unload_skill(skill_dir)

        # If skills were removed make sure to update the manifest on the
        # mycroft backend.
        if removed_skills:
            self.manifest_uploader.post_manifest(reload_skills_manifest=True)

    def _unload_plugin_skill(self, skill_id):
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

    def send_skill_list(self, _):
        """Send list of loaded skills."""
        try:
            message_data = {}
            # TODO handle external skills, OVOSAbstractApp/Hivemind skills are not accounted for
            skills = {**self.skill_loaders, **self.plugin_skills}

            for skill_loader in skills.values():
                message_data[skill_loader.skill_id] = {
                    "active": skill_loader.active and skill_loader.loaded,
                    "id": skill_loader.skill_id}

            self.bus.emit(Message('mycroft.skills.list', data=message_data))
        except Exception:
            LOG.exception('Failed to send skill list')

    def deactivate_skill(self, message):
        """Deactivate a skill."""
        try:
            # TODO handle external skills, OVOSAbstractApp/Hivemind skills are not accounted for
            skills = {**self.skill_loaders, **self.plugin_skills}
            for skill_loader in skills.values():
                if message.data['skill'] == skill_loader.skill_id:
                    LOG.info("Deactivating skill: " + skill_loader.skill_id)
                    skill_loader.deactivate()
        except Exception:
            LOG.exception('Failed to deactivate ' + message.data['skill'])

    def deactivate_except(self, message):
        """Deactivate all skills except the provided."""
        try:
            skill_to_keep = message.data['skill']
            LOG.info(f'Deactivating all skills except {skill_to_keep}')
            # TODO handle external skills, OVOSAbstractApp/Hivemind skills are not accounted for
            skills = {**self.skill_loaders, **self.plugin_skills}
            for skill in skills.values():
                if skill.skill_id != skill_to_keep:
                    skill.deactivate()
            LOG.info('Couldn\'t find skill ' + message.data['skill'])
        except Exception:
            LOG.exception('An error occurred during skill deactivation!')

    def activate_skill(self, message):
        """Activate a deactivated skill."""
        try:
            # TODO handle external skills, OVOSAbstractApp/Hivemind skills are not accounted for
            skills = {**self.skill_loaders, **self.plugin_skills}
            for skill_loader in skills.values():
                if (message.data['skill'] in ('all', skill_loader.skill_id)
                        and not skill_loader.active):
                    skill_loader.activate()
        except Exception:
            LOG.exception('Couldn\'t activate skill')

    def stop(self):
        """Tell the manager to shutdown."""
        self.status.set_stopping()
        self._stop_event.set()
        self.upload_queue.stop()

        # Do a clean shutdown of all skills
        for skill_loader in self.skill_loaders.values():
            if skill_loader.instance is not None:
                _shutdown_skill(skill_loader.instance)

        # Do a clean shutdown of all plugin skills
        for skill_id in list(self.plugin_skills.keys()):
            self._unload_plugin_skill(skill_id)
