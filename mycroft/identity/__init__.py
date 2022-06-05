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
import json
import time
import os
from os.path import isfile, dirname, expanduser
import shutil

from ovos_utils.configuration import get_xdg_config_save_path, get_xdg_base
from mycroft.util.log import LOG
from combo_lock import ComboLock

identity_lock = ComboLock('/tmp/identity-lock')


class DeviceIdentity:
    def __init__(self, **kwargs):
        self.uuid = kwargs.get("uuid", "")
        self.access = kwargs.get("access", "")
        self.refresh = kwargs.get("refresh", "")
        self.expires_at = kwargs.get("expires_at", 0)

    def is_expired(self):
        return self.refresh and 0 < self.expires_at <= time.time()

    def has_refresh(self):
        return self.refresh != ""


class IdentityManager:
    IDENTITY_FILE = f"{get_xdg_config_save_path()}/identity/identity2.json"
    OLD_IDENTITY_FILE = expanduser(f"~/.{get_xdg_base()}/identity/identity2.json")
    __identity = None

    @staticmethod
    def _load():
        if isfile(IdentityManager.OLD_IDENTITY_FILE) and \
                not isfile(IdentityManager.IDENTITY_FILE):
            os.makedirs(dirname(IdentityManager.IDENTITY_FILE), exist_ok=True)
            shutil.move(IdentityManager.OLD_IDENTITY_FILE, IdentityManager.IDENTITY_FILE)
        if isfile(IdentityManager.IDENTITY_FILE):
            LOG.debug('Loading identity')
            try:
                with open(IdentityManager.IDENTITY_FILE) as f:
                    IdentityManager.__identity = DeviceIdentity(**json.load(f))
                return
            except Exception:
                pass
        IdentityManager.__identity = DeviceIdentity()

    @staticmethod
    def load(lock=True):
        try:
            if lock:
                identity_lock.acquire()
                IdentityManager._load()
        finally:
            if lock:
                identity_lock.release()
        return IdentityManager.__identity

    @staticmethod
    def save(login=None, lock=True):
        LOG.debug('Saving identity')
        if lock:
            identity_lock.acquire()
        try:
            if login:
                IdentityManager._update(login)

            os.makedirs(dirname(IdentityManager.IDENTITY_FILE), exist_ok=True)

            with open(IdentityManager.IDENTITY_FILE, "w") as f:
                json.dump(IdentityManager.__identity.__dict__, f)
                f.flush()
                os.fsync(f.fileno())
        finally:
            if lock:
                identity_lock.release()

    @staticmethod
    def _update(login=None):
        LOG.debug('Updaing identity')
        login = login or {}
        expiration = login.get("expiration", 0)
        IdentityManager.__identity.uuid = login.get("uuid", "")
        IdentityManager.__identity.access = login.get("accessToken", "")
        IdentityManager.__identity.refresh = login.get("refreshToken", "")
        IdentityManager.__identity.expires_at = time.time() + expiration

    @staticmethod
    def update(login=None, lock=True):
        if lock:
            identity_lock.acquire()
        try:
            IdentityManager._update()
        finally:
            if lock:
                identity_lock.release()

    @staticmethod
    def get():
        if not IdentityManager.__identity:
            IdentityManager.load()
        return IdentityManager.__identity
