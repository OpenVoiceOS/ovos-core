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

from mycroft.util.string_utils import camel_case_split
from mycroft.util.audio_utils import (play_audio_file, play_wav, play_ogg,
                                      play_mp3, record, find_input_device)
from mycroft.util.file_utils import (
    resolve_resource_file,
    read_stripped_lines,
    read_dict,
    create_file,
    get_temp_path,
    ensure_directory_exists,
    curate_cache,
    get_cache_directory)
from mycroft.util.network_utils import connected
from mycroft.util.process_utils import (reset_sigint_handler, create_daemon,
                                        wait_for_exit_signal,
                                        create_echo_function,
                                        start_message_bus_client)
from mycroft.util.log import LOG
from mycroft.util.parse import extract_datetime, extract_number, normalize
from mycroft.util.signal import check_for_signal, create_signal, \
    get_ipc_directory
from mycroft.util.platform import get_arch
from ovos_config import Configuration


def init_service_logger(service_name):
    # this is makes all logs from this service be configured to write to service_name.log file
    # if this is not called in every __main__.py entrypoint logs will be written
    # to a generic OVOS.log file shared across all services
    _cfg = Configuration()
    _log_level = _cfg.get("log_level", "INFO")
    _logs_conf = _cfg.get("logs") or {}
    _logs_conf["level"] = _log_level
    LOG.name = service_name
    LOG.init(_logs_conf)  # read log level from config

