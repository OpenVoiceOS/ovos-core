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
from copy import deepcopy
from pathlib import Path
from shutil import rmtree
from unittest import TestCase
from unittest.mock import Mock, patch

from ovos_bus_client.message import Message
from ovos_config import Configuration
from ovos_config import LocalConf, DEFAULT_CONFIG
from ovos_core.skill_manager import SkillManager
from ovos_workshop.skill_launcher import SkillLoader


class MessageBusMock:
    """Replaces actual message bus calls in unit tests.

    The message bus should not be running during unit tests so mock it
    out in a way that makes it easy to test code that calls it.
    """

    def __init__(self):
        self.message_types = []
        self.message_data = []
        self.event_handlers = []

    def emit(self, message):
        self.message_types.append(message.msg_type)
        self.message_data.append(message.data)

    def on(self, event, _):
        self.event_handlers.append(event)

    def once(self, event, _):
        self.event_handlers.append(event)

    def wait_for_response(self, message):
        self.emit(message)


def mock_config():
    """Supply a reliable return value for the Configuration.get() method."""
    config = deepcopy(LocalConf(DEFAULT_CONFIG))
    config['skills']['priority_skills'] = ['foobar']
    config['data_dir'] = str(tempfile.mkdtemp())
    config['enclosure'] = {}
    return config


@patch.dict(Configuration._Configuration__patch, mock_config())
class TestSkillManager(TestCase):
    mock_package = 'ovos_core.skill_manager.'

    def setUp(self):
        temp_dir = tempfile.mkdtemp()
        self.temp_dir = Path(temp_dir)
        self.message_bus_mock = MessageBusMock()
        self._mock_log()
        self.skill_manager = SkillManager(self.message_bus_mock)
        self._mock_skill_loader_instance()

    def _mock_log(self):
        log_patch = patch(self.mock_package + 'LOG')
        self.addCleanup(log_patch.stop)
        self.log_mock = log_patch.start()

    def tearDown(self):
        rmtree(str(self.temp_dir))

    def _mock_skill_loader_instance(self):
        self.skill_dir = self.temp_dir.joinpath('test_skill')
        self.skill_loader_mock = Mock(spec=SkillLoader)
        self.skill_loader_mock.instance = Mock()
        self.skill_loader_mock.instance.default_shutdown = Mock()
        self.skill_loader_mock.instance.converse = Mock()
        self.skill_loader_mock.instance.converse.return_value = True
        self.skill_loader_mock.skill_id = 'test_skill'
        self.skill_manager.plugin_skills = {
            str(self.skill_dir): self.skill_loader_mock
        }

    def test_instantiate(self):
        expected_result = [
            'skillmanager.list',
            'skillmanager.deactivate',
            'skillmanager.keep',
            'skillmanager.activate',
            #'mycroft.skills.initialized',
            'mycroft.network.connected',
            'mycroft.internet.connected',
            'mycroft.gui.available',
            'mycroft.network.disconnected',
            'mycroft.internet.disconnected',
            'mycroft.gui.unavailable',
            'mycroft.skills.is_alive',
            'mycroft.skills.is_ready',
            'mycroft.skills.all_loaded'
        ]

        self.assertListEqual(expected_result,
                             self.message_bus_mock.event_handlers)


    def test_send_skill_list(self):
        self.skill_loader_mock.active = True
        self.skill_loader_mock.loaded = True
        self.skill_manager.send_skill_list(None)

        self.assertListEqual(
            ['mycroft.skills.list'],
            self.message_bus_mock.message_types
        )
        message_data = self.message_bus_mock.message_data[-1]
        self.assertIn('test_skill', message_data.keys())
        skill_data = message_data['test_skill']
        self.assertDictEqual(dict(active=True, id='test_skill'), skill_data)

    def test_stop(self):
        self.skill_manager.stop()

        self.assertTrue(self.skill_manager._stop_event.is_set())
        instance = self.skill_loader_mock.instance
        instance.default_shutdown.assert_called_once_with()

    def test_deactivate_skill(self):
        message = Message("test.message", {'skill': 'test_skill'})
        message.response = Mock()
        self.skill_manager.deactivate_skill(message)
        self.skill_loader_mock.deactivate.assert_called_once()
        message.response.assert_called_once()

    def test_deactivate_except(self):
        message = Message("test.message", {'skill': 'test_skill'})
        message.response = Mock()
        self.skill_loader_mock.active = True
        foo_skill_loader = Mock(spec=SkillLoader)
        foo_skill_loader.skill_id = 'foo'
        foo2_skill_loader = Mock(spec=SkillLoader)
        foo2_skill_loader.skill_id = 'foo2'
        test_skill_loader = Mock(spec=SkillLoader)
        test_skill_loader.skill_id = 'test_skill'
        self.skill_manager.plugin_skills['foo'] = foo_skill_loader
        self.skill_manager.plugin_skills['foo2'] = foo2_skill_loader
        self.skill_manager.plugin_skills['test_skill'] = test_skill_loader

        self.skill_manager.deactivate_except(message)
        foo_skill_loader.deactivate.assert_called_once()
        foo2_skill_loader.deactivate.assert_called_once()
        self.assertFalse(test_skill_loader.deactivate.called)

    def test_activate_skill(self):
        message = Message("test.message", {'skill': 'test_skill'})
        message.response = Mock()
        test_skill_loader = Mock(spec=SkillLoader)
        test_skill_loader.skill_id = 'test_skill'
        test_skill_loader.active = False

        self.skill_manager.plugin_skills = {}
        self.skill_manager.plugin_skills['test_skill'] = test_skill_loader

        self.skill_manager.activate_skill(message)
        test_skill_loader.activate.assert_called_once()
        message.response.assert_called_once()

    def test_load_plugin_skill_success(self):
        """Test successful plugin skill loading emits the correct message."""
        skill_id = 'test.plugin.skill'
        mock_plugin = Mock()

        # Setup mock loader following existing patterns
        mock_loader = Mock(spec=SkillLoader)
        mock_loader.skill_id = skill_id
        mock_loader.load.return_value = True

        # Mock _get_plugin_skill_loader to return our mock
        self.skill_manager._get_plugin_skill_loader = Mock(return_value=mock_loader)

        # Reset message tracking
        self.message_bus_mock.message_types = []
        self.message_bus_mock.message_data = []
        self.skill_manager.plugin_skills = {}

        # Call the method
        result = self.skill_manager._load_plugin_skill(skill_id, mock_plugin)

        # Verify message was emitted
        self.assertIn('mycroft.skill.loaded', self.message_bus_mock.message_types)
        loaded_msg_idx = self.message_bus_mock.message_types.index('mycroft.skill.loaded')
        self.assertEqual(
            {'skill_id': skill_id},
            self.message_bus_mock.message_data[loaded_msg_idx]
        )

        # Verify loader was called
        mock_loader.load.assert_called_once_with(mock_plugin)

        # Verify skill was added to plugin_skills
        self.assertIn(skill_id, self.skill_manager.plugin_skills)
        self.assertEqual(mock_loader, self.skill_manager.plugin_skills[skill_id])

        # Verify return value
        self.assertEqual(result, mock_loader)

    def test_load_plugin_skill_failure(self):
        """Test failed plugin skill loading is handled gracefully."""
        skill_id = 'test.failing.skill'
        mock_plugin = Mock()

        # Setup mock loader to raise exception
        mock_loader = Mock(spec=SkillLoader)
        mock_loader.skill_id = skill_id
        mock_loader.load.side_effect = Exception("Skill load failed!")

        # Mock _get_plugin_skill_loader to return our mock
        self.skill_manager._get_plugin_skill_loader = Mock(return_value=mock_loader)

        # Reset message tracking
        self.message_bus_mock.message_types = []
        self.message_bus_mock.message_data = []
        self.skill_manager.plugin_skills = {}

        # Call the method
        result = self.skill_manager._load_plugin_skill(skill_id, mock_plugin)

        # Verify NO success message was emitted
        self.assertNotIn('mycroft.skill.loaded', self.message_bus_mock.message_types)

        # Verify exception was logged
        self.log_mock.exception.assert_called_once()

        # Verify skill was still added to plugin_skills (even on failure)
        self.assertIn(skill_id, self.skill_manager.plugin_skills)
        self.assertEqual(mock_loader, self.skill_manager.plugin_skills[skill_id])

        # Verify return value is None on failure
        self.assertIsNone(result)

    def test_load_plugin_skill_returns_false(self):
        """Test plugin skill loading that returns False (load failed gracefully)."""
        skill_id = 'test.false.skill'
        mock_plugin = Mock()

        # Setup mock loader to return False (failed but no exception)
        mock_loader = Mock(spec=SkillLoader)
        mock_loader.skill_id = skill_id
        mock_loader.load.return_value = False

        # Mock _get_plugin_skill_loader to return our mock
        self.skill_manager._get_plugin_skill_loader = Mock(return_value=mock_loader)

        # Reset message tracking
        self.message_bus_mock.message_types = []
        self.skill_manager.plugin_skills = {}

        # Call the method
        result = self.skill_manager._load_plugin_skill(skill_id, mock_plugin)

        # Verify message WAS emitted (happens before status check)
        self.assertIn('mycroft.skill.loaded', self.message_bus_mock.message_types)

        # Verify skill was added to plugin_skills
        self.assertIn(skill_id, self.skill_manager.plugin_skills)

        # Verify return value is None when load returns False
        self.assertIsNone(result)
