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

import importlib
import sys
from os import listdir
from os.path import abspath, dirname, basename, isdir, join
from mycroft.util import LOG
from ovos_plugin_manager.audio import setup_audio_service as setup_service, load_audio_service_plugins as load_plugins

MAINMODULE = '__init__'


def create_service_spec(service_folder):
    """Prepares a descriptor that can be used together with imp.

        Args:
            service_folder: folder that shall be imported.

        Returns:
            Dict with import information
    """
    module_name = 'audioservice_' + basename(service_folder)
    path = join(service_folder, MAINMODULE + '.py')
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    info = {'spec': spec, 'mod': mod, 'module_name': module_name}
    return {"name": basename(service_folder), "info": info}


def get_services(services_folder):
    """
        Load and initialize services from all subfolders.

        Args:
            services_folder: base folder to look for services in.

        Returns:
            Sorted list of audio services.
    """
    LOG.info("Loading services from " + services_folder)
    services = []
    possible_services = listdir(services_folder)
    for i in possible_services:
        location = join(services_folder, i)
        if (isdir(location) and
                not MAINMODULE + ".py" in listdir(location)):
            for j in listdir(location):
                name = join(location, j)
                if (not isdir(name) or
                        not MAINMODULE + ".py" in listdir(name)):
                    continue
                try:
                    services.append(create_service_spec(name))
                except Exception:
                    LOG.error('Failed to create service from ' + name,
                              exc_info=True)
        if (not isdir(location) or
                not MAINMODULE + ".py" in listdir(location)):
            continue
        try:
            services.append(create_service_spec(location))
        except Exception:
            LOG.error('Failed to create service from ' + location,
                      exc_info=True)
    return sorted(services, key=lambda p: p.get('name'))


def load_internal_services(config, bus, path=None):
    """Load audio services included in Mycroft-core.

    Args:
        config: configuration dict for the audio backends.
        bus: Mycroft messagebus
        path: (default None) optional path for builtin audio service
              implementations

    Returns:
        List of started services
    """
    if path is None:
        path = dirname(abspath(__file__)) + '/services/'
    service_directories = get_services(path)
    service = []
    for descriptor in service_directories:
        try:
            service_module = descriptor['info']['mod']
            spec = descriptor['info']['spec']
            module_name = descriptor['info']['module_name']
            sys.modules[module_name] = service_module
            spec.loader.exec_module(service_module)
        except Exception as e:
            LOG.error('Failed to import module ' + descriptor['name'] + '\n' +
                      repr(e))
        else:
            s = setup_service(service_module, config, bus)
            if s:
                LOG.info('Loaded ' + descriptor['name'])
                service += s

    return service


def load_services(config, bus, path=None):
    """Load builtin services as well as service plugins

    The builtin service folder is scanned (or a folder indicated by the path
    parameter) for services and plugins registered with the
    "mycroft.plugin.audioservice" entrypoint group.

    Args:
        config: configuration dict for the audio backends.
        bus: Mycroft messagebus
        path: (default None) optional path for builtin audio service
              implementations

    Returns:
        List of started services.
    """
    return (load_internal_services(config, bus, path) +
            load_plugins(config, bus))
