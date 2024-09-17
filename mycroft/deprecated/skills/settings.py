"""
NOTE: this is dead code! do not use!
This file is only present to ensure backwards compatibility
in case someone is importing from here
This is only meant for 3rd party code expecting ovos-core
to be a drop in replacement for mycroft-core
"""

import json
import os
from os.path import dirname, basename
from pathlib import Path
from threading import Timer, Lock

import yaml

from ovos_backend_client.pairing import is_paired
from ovos_backend_client.api import DeviceApi
from ovos_bus_client.message import Message
from mycroft.util.file_utils import ensure_directory_exists
from ovos_utils.log import LOG
from ovos_config.config import Configuration
from ovos_config.locations import get_xdg_cache_save_path
from ovos_backend_client.settings import get_display_name


# Path to remote cache
REMOTE_CACHE = Path(get_xdg_cache_save_path(), 'remote_skill_settings.json')


class UploadQueue:
    """Queue for holding loaders with data that still needs to be uploaded.

    This queue can be used during startup to capture all loaders
    and then processing can be triggered at a later stage when the system is
    connected to the backend.

    After all queued settingsmeta has been processed and the queue is empty
    the queue will set the self.started flag.
    """

    def __init__(self):
        self._queue = []
        self.started = False
        self.lock = Lock()

    def start(self):
        """Start processing of the queue."""
        self.started = True
        self.send()

    def stop(self):
        """Stop the queue, and hinder any further transmissions."""
        self.started = False

    def send(self):
        """Loop through all stored loaders triggering settingsmeta upload."""
        with self.lock:
            queue = self._queue
            self._queue = []
        if queue:
            LOG.info('New Settings meta to upload.')
            for loader in queue:
                if self.started:
                    loader.instance.settings_meta.upload()
                else:
                    break

    def __len__(self):
        return len(self._queue)

    def put(self, loader):
        """Append a skill loader to the queue.

        If a loader is already present it's removed in favor of the new entry.
        """
        if self.started:
            LOG.info('Updating settings meta during runtime...')
        with self.lock:
            # Remove existing loader
            self._queue = [e for e in self._queue if e != loader]
            self._queue.append(loader)


class SettingsMetaUploader:
    """Synchronize the contents of the settingsmeta.json file with the backend.

    The settingsmeta.json (or settingsmeta.yaml) file is defined by the skill
    author.  It defines the user-configurable settings for a skill and contains
    instructions for how to display the skill's settings in the Selene web
    application (https://account.mycroft.ai).
    """
    _msm_skill_display_name = None
    _settings_meta_path = None

    def __init__(self, skill_directory: str, skill_name="", skill_id=""):
        self.skill_directory = Path(skill_directory)
        if skill_name:
            LOG.warning("skill_name is deprecated! use skill_id instead")
        self.skill_id = skill_id or skill_name or basename(self.skill_directory)
        self.json_path = self.skill_directory.joinpath('settingsmeta.json')
        self.yaml_path = self.skill_directory.joinpath('settingsmeta.yaml')
        self.config = Configuration()
        self.settings_meta = {}
        self.api = None
        self.upload_timer = None
        self.sync_enabled = self.config["server"] \
                .get("sync_skill_settings", False)
        if not self.sync_enabled:
            LOG.info("Skill settings sync is disabled, settingsmeta will "
                     "not be uploaded")

        self._stopped = None

    @property
    def skill_name(self):
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning and returns self.skill_id
        """
        LOG.warning("self.skill_name is deprecated! use self.skill_id instead")
        return self.skill_id

    @skill_name.setter
    def skill_name(self, val):
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning and sets self.skill_id
        """
        LOG.warning("self.skill_name is deprecated! use self.skill_id instead")
        self.skill_id = val

    @property
    def msm(self):
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning and returns None
        """
        # unused but need to keep api backwards compatible
        # log a warning and move on
        LOG.warning("msm has been deprecated\n"
                    "DO NOT use self.msm property")
        return None

    def get_local_skills(self):
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning and returns empty dictionary
        """
        # unused but need to keep api backwards compatible
        # log a warning and move on
        LOG.warning("msm has been deprecated, do not use this utility method\n"
                    "get_local_skills always returns an empty dict")
        return {}

    @property
    def skill_gid(self):
        """Skill identifier recognized by selene backend"""
        api = self.api or DeviceApi()
        if api.identity.uuid:
            return f'@{api.identity.uuid}|{self.skill_id}'
        return f'@|{self.skill_id}'

    @property
    def msm_skill_display_name(self):
        """DEPRECATED: do not use, method only for api backwards compatibility
        Logs a warning and returns self.skill_display_name
        """
        LOG.warning("msm_skill_display_name has been deprecated\n"
                    "use skill_display_name instead")
        return self.skill_display_name

    @property
    def skill_display_name(self):
        """Display name for use in settings meta."""
        return get_display_name(self.skill_id.split(".")[0])

    @property
    def settings_meta_path(self):
        """Fully qualified path to the settingsmeta file."""
        if self._settings_meta_path is None:
            if self.yaml_path.is_file():
                self._settings_meta_path = self.yaml_path
            else:
                self._settings_meta_path = self.json_path

        return self._settings_meta_path

    def upload(self):
        """Upload the contents of the settingsmeta file to Mycroft servers.

        The settingsmeta file does not change often, if at all.  Only perform
        the upload if a change in the file is detected.

        NOTE: docstrs are wrong, no checks if file changed anywhere
        """
        if not self.sync_enabled:
            return
        synced = False
        if is_paired():
            self.api = DeviceApi()
            if self.api.identity.uuid:
                settings_meta_file_exists = (
                        self.json_path.is_file() or
                        self.yaml_path.is_file()
                )
                if settings_meta_file_exists:
                    self._load_settings_meta_file()

                self._update_settings_meta()
                LOG.debug('Uploading settings meta for ' + self.skill_gid)
                synced = self._issue_api_call()
            else:
                LOG.debug('settingsmeta.json not uploaded - no identity')
        else:
            LOG.debug('settingsmeta.json not uploaded - device is not paired')

        if not synced and not self._stopped:
            self.upload_timer = Timer(60, self.upload)
            self.upload_timer.daemon = True
            self.upload_timer.start()

    def stop(self):
        """Stop upload attempts if Timer is running."""
        if self.upload_timer:
            self.upload_timer.cancel()
        # Set stopped flag if upload is running when stop is called.
        self._stopped = True

    def _load_settings_meta_file(self):
        """Read the contents of the settingsmeta file into memory."""
        _, ext = os.path.splitext(str(self.settings_meta_path))
        is_json_file = self.settings_meta_path.suffix == ".json"
        try:
            with open(str(self.settings_meta_path)) as meta_file:
                if is_json_file:
                    self.settings_meta = json.load(meta_file)
                else:
                    self.settings_meta = yaml.safe_load(meta_file)
        except Exception:
            LOG.error(f"Failed to load settingsmeta file: {self.settings_meta_path}")

    def _update_settings_meta(self):
        """Make sure the skill gid and name are included in settings meta."""
        # Insert skill_gid and display_name
        self.settings_meta.update(
            skill_gid=self.skill_gid,
            display_name=(
                    self.skill_display_name or
                    self.settings_meta.get('name') or
                    get_display_name(self.skill_id.split(".")[0])
            )
        )
        for deprecated in ('color', 'identifier', 'name'):
            if deprecated in self.settings_meta:
                LOG.warning(
                    f'DEPRECATION WARNING: The "{deprecated}" attribute in the '
                    'settingsmeta file is no longer supported.'
                )
                del (self.settings_meta[deprecated])

    def _issue_api_call(self):
        """Use the API to send the settings meta to the server.

        NOTE: mycroft-core  will upload settings meta JSON containing
        a skill gid and name even if a skill does not have a settingsmeta file

        In ovos-core we do not upload this, selene does not need to
        know about the skills we have installed if they dont require web settings
        """
        if not self.settings_meta.get("skillMetadata"):
            return False
        try:
            self.api.upload_skill_metadata(self.settings_meta)
        except Exception as e:
            LOG.error(f'Failed to upload skill settings meta for {self.skill_gid}')
            return False
        return True


def load_remote_settings_cache():
    """Load cached remote skill settings.

    Returns:
        (dict) Loaded remote settings cache or None of none exists.
    """
    remote_settings = {}
    if REMOTE_CACHE.exists():
        try:
            with open(str(REMOTE_CACHE)) as cache:
                remote_settings = json.load(cache)
        except Exception as error:
            LOG.warning('Failed to read remote_cache ({})'.format(error))
    return remote_settings


def save_remote_settings_cache(remote_settings):
    """Save updated remote settings to cache file.

    Args:
        remote_settings (dict): downloaded remote settings.
    """
    try:
        ensure_directory_exists(dirname(str(REMOTE_CACHE)))
        with open(str(REMOTE_CACHE), 'w') as cache:
            json.dump(remote_settings, cache)
    except Exception as error:
        LOG.warning('Failed to write remote_cache. ({})'.format(error))
    else:
        LOG.debug('Updated local cache of remote skill settings.')


class SkillSettingsDownloader:
    """Manages download of skill settings.

    Performs settings download on a repeating Timer. If a change is seen
    the data is sent to the relevant skill.
    """

    def __init__(self, bus):
        self.bus = bus
        self.continue_downloading = True
        self.last_download_result = load_remote_settings_cache()

        self.api = DeviceApi()
        self.download_timer = None

        self.sync_enabled = Configuration().get("server", {}).get("sync_skill_settings", False)

        if not self.sync_enabled:
            LOG.debug("Skill settings sync is disabled, backend settings will "
                      "not be downloaded")

    def stop_downloading(self):
        """Stop synchronizing backend and core."""
        self.continue_downloading = False
        if self.download_timer:
            self.download_timer.cancel()

    # TODO: implement as websocket
    def download(self, message=None):
        """Download the settings stored on the backend and check for changes

        When used as a messagebus handler a message is passed but not used.
        """
        if not self.sync_enabled:
            return
        if is_paired():
            remote_settings = self._get_remote_settings()
            if remote_settings:
                settings_changed = self.last_download_result != remote_settings
                if settings_changed:
                    LOG.debug('Skill settings changed since last download')
                    self._emit_settings_change_events(remote_settings)
                    self.last_download_result = remote_settings
                    save_remote_settings_cache(remote_settings)
                else:
                    LOG.debug('No skill settings changes since last download')
        else:
            LOG.debug('Settings not downloaded - device is not paired')
        # If this method is called outside of the timer loop, ensure the
        # existing timer is canceled before starting a new one.
        if self.download_timer:
            self.download_timer.cancel()

        if self.continue_downloading:
            self.download_timer = Timer(60, self.download)
            self.download_timer.daemon = True
            self.download_timer.start()

    def _get_remote_settings(self):
        """Get the settings for this skill from the server

        Returns:
            skill_settings (dict or None): returns a dict on success, else None
        """
        try:
            remote_settings = self.api.get_skill_settings()
        except Exception:
            LOG.error('Failed to download remote settings from server.')
            remote_settings = None

        return remote_settings

    def _emit_settings_change_events(self, remote_settings):
        """Emit changed settings events for each affected skill."""
        for skill_gid, skill_settings in remote_settings.items():
            settings_changed = False
            try:
                previous_settings = self.last_download_result.get(skill_gid)
            except Exception:
                LOG.error('error occurred handling setting change events')
            else:
                if previous_settings != skill_settings:
                    settings_changed = True
            if settings_changed:
                LOG.info(f'Emitting skill.settings.change event for skill {skill_gid}')
                message = Message(
                    'mycroft.skills.settings.changed',
                    data={skill_gid: skill_settings}
                )
                self.bus.emit(message)
