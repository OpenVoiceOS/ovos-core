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
"""Mycroft util library.

A collections of utils and tools for making skill development easier.
"""
from __future__ import absolute_import

from ovos_utils import camel_case_split
from ovos_utils.sound import play_audio as play_ogg, play_audio as play_mp3, play_audio as play_wav
from mycroft.util.audio_utils import (play_audio_file, find_input_device)
from mycroft.util.file_utils import (
    read_stripped_lines,
    read_dict,
    create_file,
    ensure_directory_exists,
    curate_cache)
from ovos_utils.file_utils import resolve_resource_file, get_cache_directory, get_temp_path
from mycroft.util.network_utils import connected
from mycroft.util.process_utils import (create_echo_function,
                                        start_message_bus_client)

from ovos_utils import wait_for_exit_signal, create_daemon
from ovos_utils.process_utils import reset_sigint_handler

from mycroft.util.parse import extract_datetime, extract_number, normalize
from ovos_utils.signal import check_for_signal, create_signal, \
    get_ipc_directory
from mycroft.util.platform import get_arch
from ovos_utils.log import init_service_logger, LOG


def record(*args, **kwargs):
    from mycroft.util.audio_test import record
    record(*args, **kwargs)
