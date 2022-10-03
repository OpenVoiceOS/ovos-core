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
from mycroft.deprecated.api import Api, UUID, GeolocationApi, STTApi, DeviceApi
from ovos_config.config import Configuration
from ovos_backend_client.exceptions import BackendDown, InternetDown
from functools import wraps
from ovos_backend_client.pairing import has_been_paired as _hp, is_paired as _ip, check_remote_pairing

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
