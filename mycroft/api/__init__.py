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
from mycroft.version import VersionManager, OVOS_VERSION_STR
from selene_api.api import DeviceApi as _DeviceApi
from mycroft.deprecated.api import Api, UUID, GeolocationApi, STTApi
from ovos_config.config import Configuration
from selene_api.exceptions import BackendDown, InternetDown
from functools import wraps
from selene_api.pairing import has_been_paired as _hp, is_paired as _ip, check_remote_pairing
_paired_cache = False


def has_been_paired():
    """ Determine if this device has ever been paired with a web backend

    Returns:
        bool: True if ever paired with backend (not factory reset)
    """
    if is_backend_disabled():
        return True
    return _hp()


def is_paired(ignore_errors=True):
    """Determine if this device is actively paired with a web backend

    Determines if the installation of Mycroft has been paired by the user
    with the backend system, and if that pairing is still active.

    Returns:
        bool: True if paired with backend
    """
    if is_backend_disabled():
        return True
    return _ip(ignore_errors)


def is_backend_disabled():
    config = Configuration()
    if not config.get("server"):
        # missing server block implies disabling backend
        return True
    return config["server"].get("disabled") or False


def requires_backend(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not is_backend_disabled():
            return f(*args, **kwargs)
        return {}

    return decorated


class DeviceApi(Api):
    """ Web API wrapper for obtaining device-level information
    selene_api is not used directly to account for disabled_backend setting"""

    def __init__(self):
        super(DeviceApi, self).__init__("device")

    @property
    def _backend_url(self):
        """ this is a property to reflect live updates to mycroft.conf
         this value can change during pairing process or via GUI setup
         """
        config = Configuration()
        config_server = config.get("server") or {}
        self.backend_url = config_server.get("url") or self.backend_url or "https://api.mycroft.ai"
        return self.backend_url

    @property
    def _backend_version(self):
        """ this is a property to reflect live updates to mycroft.conf
         this value can change during pairing process or via GUI setup
         """
        config = Configuration()
        config_server = config.get("server") or {}
        self.backend_version = config_server.get("version") or self.backend_version or "v1"
        return self.backend_version

    @property
    def _real_api(self):
        """ this is a property to reflect live updates to backend url """
        return _DeviceApi(self._backend_url, self._backend_version)

    @requires_backend
    def get_code(self, state):
        return self._real_api.get_code(state)

    @requires_backend
    def activate(self, state, token):
        version = VersionManager.get()
        platform = "ovos-core"
        platform_build = OVOS_VERSION_STR
        return self._real_api.activate(state, token, version.get("coreVersion"),
                                       platform, platform_build, version.get("enclosureVersion"))

    @requires_backend
    def update_version(self):
        version = VersionManager.get()
        platform = "ovos-core"
        platform_build = OVOS_VERSION_STR
        return self._real_api.update_version(version.get("coreVersion"),
                                             platform, platform_build,
                                             version.get("enclosureVersion"))

    @requires_backend
    def send_email(self, title, body, sender):
        return self._real_api.send_email(title, body, sender)

    @requires_backend
    def report_metric(self, name, data):
        return self._real_api.report_metric(name, data)

    @requires_backend
    def get(self):
        """ Retrieve all device information from the web backend """
        return self._real_api.get()

    @requires_backend
    def get_settings(self):
        """ Retrieve device settings information from the web backend

        Returns:
            str: JSON string with user configuration information.
        """
        return self._real_api.get_settings()

    @requires_backend
    def get_location(self):
        """ Retrieve device location information from the web backend

        Returns:
            str: JSON string with user location.
        """
        return self._real_api.get_location()

    @requires_backend
    def get_subscription(self):
        """
            Get information about type of subscrition this unit is connected
            to.

            Returns: dictionary with subscription information
        """
        return self._real_api.get_subscription()

    @property
    def is_subscriber(self):
        """
            status of subscription. True if device is connected to a paying
            subscriber.
        """
        return self._real_api.is_subscriber

    @requires_backend
    def get_subscriber_voice_url(self, voice=None):
        return self._real_api.get_subscriber_voice_url(voice)

    @requires_backend
    def get_oauth_token(self, dev_cred):
        """
            Get Oauth token for dev_credential dev_cred.

            Argument:
                dev_cred:   development credentials identifier

            Returns:
                json string containing token and additional information
        """
        return self._real_api.get_oauth_token(dev_cred)

    @requires_backend
    def get_skill_settings(self):
        """Get the remote skill settings for all skills on this device."""
        return self._real_api.get_skill_settings()

    @requires_backend
    def upload_skill_metadata(self, settings_meta):
        """Upload skill metadata.

        Args:
            settings_meta (dict): skill info and settings in JSON format
        """
        return self._real_api.upload_skill_metadata(settings_meta)

    @requires_backend
    def upload_skills_data(self, data):
        """ Upload skills.json file. This file contains a manifest of installed
        and failed installations for use with the Marketplace.

        Args:
             data: dictionary with skills data from msm
        """
        return self._real_api.upload_skills_data(data)
