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
"""Keep the settingsmeta.json and settings.json files in sync with the backend.

The SkillSettingsMeta and SkillSettings classes run a synchronization every
minute to ensure the device and the server have the same values.

The settingsmeta.json file (or settingsmeta.yaml, if you prefer working with
yaml) in the skill's root directory contains instructions for the Selene UI on
how to display and update a skill's settings, if there are any.

For example, you might have a setting named "username".  In the settingsmeta
you can describe the interface to edit that value with:
    ...
    "fields": [
        {
            "name": "username",
            "type": "email",
            "label": "Email address to associate",
            "placeholder": "example@mail.com",
            "value": ""
        }
    ]
    ...

When the user changes the setting via the web UI, it will be sent down to all
the devices related to an account and automatically placed into
settings['username'].  Any local changes made to the value (e.g. via a verbal
interaction) will also be synchronized to the server to show on the web
interface.

The settings.json file contains name/value pairs for each setting.  There can
be entries in settings.json that are not related to those the user can
manipulate on the web.  There is logic in the SkillSettings class to ensure
these "hidden" settings are not affected when the synchronization occurs.  A
skill can define a function that will be called when any settings change.

SkillSettings Usage Example:
    from mycroft.skill.settings import SkillSettings

        s = SkillSettings('./settings.json', 'ImportantSettings')
        s.skill_settings['meaning of life'] = 42
        s.skill_settings['flower pot sayings'] = 'Not again...'
        s.save_settings()  # This happens automagically in a MycroftSkill
"""
import json
from os.path import isfile
import yaml

from threading import Timer
from ovos_backend_client.api import DeviceApi
from ovos_backend_client.pairing import is_paired, requires_backend
from ovos_utils.log import LOG
from ovos_backend_client.settings import RemoteSkillSettings, get_display_name
from mycroft_bus_client.message import Message, dig_for_message

# backwards compat imports
from mycroft.deprecated.skills.settings import SkillSettingsDownloader, SettingsMetaUploader, load_remote_settings_cache, \
    save_remote_settings_cache, REMOTE_CACHE
# these 2 methods are maintained as part of ovos_utils but need to be available from this location for compatibility
from ovos_utils.skills.settings import get_local_settings, save_settings


class SkillSettingsManager:
    def __init__(self, skill):
        self.download_timer = None
        self.skill = skill
        self.api = DeviceApi()
        self.remote_settings = RemoteSkillSettings(self.skill_id,
                                                   settings=dict(self.skill.settings),
                                                   meta=self.load_meta(),
                                                   remote_id=self.skill_gid)
        self.register_bus_handlers()

    def start(self):
        self._download()

    def _download(self):
        # If this method is called outside of the timer loop, ensure the
        # existing timer is canceled before starting a new one.
        if self.download_timer:
            self.download_timer.cancel()

        self.download()

        # prepare to download again in 60 seconds
        self.download_timer = Timer(60, self._download)
        self.download_timer.daemon = True
        self.download_timer.start()

    def stop(self):
        # If this method is called outside of the timer loop, ensure the
        # existing timer is canceled
        if self.download_timer:
            self.download_timer.cancel()

    @property
    def bus(self):
        return self.skill.bus

    @property
    def skill_id(self):
        return self.skill.skill_id

    @property
    def display_name(self):
        return get_display_name(self.skill_id)

    @property
    def skill_gid(self):
        return f"@{self.api.uuid}|{self.skill_id}"

    @property
    def skill_meta(self):
        return self.remote_settings.meta

    def register_bus_handlers(self):
        self.skill.add_event('mycroft.skills.settings.update',
                             self.handle_download_remote)  # backwards compat
        self.skill.add_event('mycroft.skills.settings.download',
                             self.handle_download_remote)
        self.skill.add_event('mycroft.skills.settings.upload',
                             self.handle_upload_local)
        self.skill.add_event('mycroft.skills.settings.upload.meta',
                             self.handle_upload_meta)
        self.skill.add_event('mycroft.paired',
                             self.handle_upload_local)

    def load_meta(self):
        json_path = f"{self.skill.root_dir}/settingsmeta.json"
        yaml_path = f"{self.skill.root_dir}/settingsmeta.yaml"
        if isfile(yaml_path):
            with open(yaml_path) as meta_file:
                return yaml.safe_load(meta_file)
        elif isfile(json_path):
            with open(json_path) as meta_file:
                return json.load(meta_file)
        return {}

    def save_meta(self, generate=False):
        # unset reload flag to avoid a reload on settingmeta change
        # TODO - support for settingsmeta XDG paths
        reload = self.skill.reload_skill
        self.skill.reload_skill = False

        # generate meta for missing fields
        if generate:
            self.remote_settings.generate_meta()

        # write to disk
        json_path = f"{self.skill.root_dir}/settingsmeta.json"
        yaml_path = f"{self.skill.root_dir}/settingsmeta.yaml"
        if isfile(yaml_path):
            with open(yaml_path) as meta_file:
                yaml.dump(self.remote_settings.meta, meta_file)
        else:
            with open(json_path, "w") as meta_file:
                json.dump(self.remote_settings.meta, meta_file)

        # reset reloading flag
        self.skill.reload_skill = reload

    @requires_backend
    def upload(self, generate=False):
        if not is_paired():
            LOG.error("Device needs to be paired to upload settings")
            return
        self.remote_settings.settings = dict(self.skill.settings)
        if generate:
            self.remote_settings.generate_meta()
        self.remote_settings.upload()

    @requires_backend
    def upload_meta(self, generate=False):
        if not is_paired():
            LOG.error("Device needs to be paired to upload settingsmeta")
            return
        if generate:
            self.remote_settings.settings = dict(self.skill.settings)
            self.remote_settings.generate_meta()
        self.remote_settings.upload_meta()

    @requires_backend
    def download(self):
        if not is_paired():
            LOG.error("Device needs to be paired to download remote settings")
            return
        self.remote_settings.download()
        # we do not update skill object settings directly
        # skill will handle the event and trigger a callback
        if self.skill.settings != self.remote_settings.settings:
            # dig old message to keep context
            msg = dig_for_message() or Message("")
            msg = msg.forward('mycroft.skills.settings.changed')

            msg.data[self.skill_id] = self.remote_settings.settings
            self.bus.emit(msg)

    def handle_upload_meta(self, message):
        skill_id = message.data.get("skill_id")
        if skill_id == self.skill_id:
            self.upload_meta()

    def handle_upload_local(self, message):
        skill_id = message.data.get("skill_id")
        if skill_id == self.skill_id:
            self.upload()

    def handle_download_remote(self, message):
        self.download()
