# Copyright 2019 Mycroft AI Inc.
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
import tempfile
from pathlib import Path
from shutil import rmtree
from unittest import TestCase
from unittest.mock import patch

from .mocks import base_config, MessageBusMock
from mycroft.configuration import Configuration


def mock_config():
    """Supply a reliable return value for the Configuration.get() method."""
    config = base_config()
    config['skills']['priority_skills'] = ['foobar']
    config['data_dir'] = str(tempfile.mkdtemp())
    config['server']['metrics'] = False
    config['enclosure'] = {}
    return config


@patch.dict(Configuration._Configuration__patch, mock_config())
class MycroftUnitTestBase(TestCase):
    mock_package = None

    def setUp(self):
        temp_dir = tempfile.mkdtemp()
        self.temp_dir = Path(temp_dir)
        self.message_bus_mock = MessageBusMock()
        self._mock_log()

    def _mock_log(self):
        log_patch = patch(self.mock_package + 'LOG')
        self.addCleanup(log_patch.stop)
        self.log_mock = log_patch.start()

    def tearDown(self):
        rmtree(str(self.temp_dir))
