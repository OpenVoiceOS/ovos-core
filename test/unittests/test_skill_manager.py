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
from threading import Event, Thread
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
        # With default config (deferred_loading: false), connectivity handlers are NOT registered
        expected_result = [
            'skillmanager.list',
            'skillmanager.deactivate',
            'skillmanager.keep',
            'skillmanager.activate',
            #'mycroft.skills.initialized',
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

    def test_handle_gui_connected_defers_skill_loading_until_startup_complete(self):
        self.skill_manager._load_new_skills = Mock()

        self.skill_manager.handle_gui_connected(
            Message("mycroft.gui.available", {"permanent": False})
        )

        self.assertTrue(self.skill_manager._gui_event.is_set())
        self.assertTrue(self.skill_manager._deferred_skill_load_event.is_set())
        self.skill_manager._load_new_skills.assert_not_called()

        self.assertTrue(
            self.skill_manager._mark_startup_complete_and_consume_deferred()
        )
        self.skill_manager._process_deferred_skill_load()

        self.assertFalse(self.skill_manager._deferred_skill_load_event.is_set())
        self.skill_manager._load_new_skills.assert_called_once_with()

    def test_handle_internet_connected_defers_skill_loading_until_startup_complete(self):
        self.skill_manager._load_on_internet = Mock()

        self.skill_manager.handle_internet_connected(
            Message("mycroft.internet.connected")
        )

        self.assertTrue(self.skill_manager._network_event.is_set())
        self.assertTrue(self.skill_manager._connected_event.is_set())
        self.assertTrue(self.skill_manager._deferred_skill_load_event.is_set())
        self.skill_manager._load_on_internet.assert_not_called()

        self.assertTrue(
            self.skill_manager._mark_startup_complete_and_consume_deferred()
        )
        self.skill_manager._process_deferred_skill_load()

        self.assertFalse(self.skill_manager._deferred_skill_load_event.is_set())
        self.skill_manager._load_on_internet.assert_called_once_with()

    def test_mark_startup_complete_and_consume_deferred_is_atomic(self):
        """Test that startup completion is atomic - only one thread sees True."""
        self.skill_manager._deferred_skill_load_event.set()

        results = []

        def call_mark_complete():
            result = self.skill_manager._mark_startup_complete_and_consume_deferred()
            results.append(result)

        # Start two threads calling concurrently to test atomicity
        thread1 = Thread(target=call_mark_complete)
        thread2 = Thread(target=call_mark_complete)

        thread1.start()
        thread2.start()

        thread1.join()
        thread2.join()

        # Exactly one thread should see True (the winner of the race)
        # The other should see False (already marked complete)
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 1)


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

    @patch('ovos_core.skill_manager.find_skill_plugins')
    def test_load_plugin_skills_skips_skill_already_loading(self, mock_find_skill_plugins):
        """Test plugin discovery skips a skill that is already being loaded."""
        skill_id = 'test.loading.skill'
        mock_find_skill_plugins.return_value = {skill_id: Mock()}
        self.skill_manager.plugin_skills = {}
        self.skill_manager._loading_plugin_skills.add(skill_id)
        self.skill_manager._get_plugin_skill_loader = Mock()
        self.skill_manager._load_plugin_skill = Mock()

        loaded_new = self.skill_manager.load_plugin_skills(network=True, internet=True)

        self.assertFalse(loaded_new)
        self.skill_manager._get_plugin_skill_loader.assert_not_called()
        self.skill_manager._load_plugin_skill.assert_not_called()

    def test_load_plugin_skill_tracks_loading_state(self):
        """Test a skill is marked loading before PluginSkillLoader.load runs."""
        skill_id = 'test.tracked.skill'
        mock_plugin = Mock()
        mock_loader = Mock(spec=SkillLoader)
        mock_loader.skill_id = skill_id

        def load_side_effect(plugin):
            self.assertEqual(plugin, mock_plugin)
            self.assertIn(skill_id, self.skill_manager._loading_plugin_skills)
            return True

        mock_loader.load.side_effect = load_side_effect
        self.skill_manager._get_plugin_skill_loader = Mock(return_value=mock_loader)
        self.skill_manager.plugin_skills = {}

        result = self.skill_manager._load_plugin_skill(skill_id, mock_plugin)

        self.assertEqual(result, mock_loader)
        self.assertNotIn(skill_id, self.skill_manager._loading_plugin_skills)
        self.assertEqual(mock_loader, self.skill_manager.plugin_skills[skill_id])

    def test_load_plugin_skill_skips_concurrent_duplicate_attempt(self):
        """Test concurrent loads for the same skill only execute once."""
        skill_id = 'test.concurrent.skill'
        mock_plugin = Mock()
        mock_loader = Mock(spec=SkillLoader)
        mock_loader.skill_id = skill_id
        load_started = Event()
        allow_finish = Event()
        results = {}

        def load_side_effect(plugin):
            self.assertEqual(plugin, mock_plugin)
            load_started.set()
            self.assertTrue(allow_finish.wait(2))
            return True

        mock_loader.load.side_effect = load_side_effect
        self.skill_manager._get_plugin_skill_loader = Mock(return_value=mock_loader)
        self.skill_manager.plugin_skills = {}

        def first_load():
            results['first'] = self.skill_manager._load_plugin_skill(skill_id, mock_plugin)

        thread = Thread(target=first_load)
        thread.start()
        self.assertTrue(load_started.wait(1))

        results['second'] = self.skill_manager._load_plugin_skill(skill_id, mock_plugin)

        allow_finish.set()
        thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(results['first'], mock_loader)
        self.assertIsNone(results['second'])
        self.assertEqual(1, self.skill_manager._get_plugin_skill_loader.call_count)
        mock_loader.load.assert_called_once_with(mock_plugin)
        self.assertNotIn(skill_id, self.skill_manager._loading_plugin_skills)
        self.assertEqual(mock_loader, self.skill_manager.plugin_skills[skill_id])

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
        self.assertNotIn(skill_id, self.skill_manager._loading_plugin_skills)

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

        # Verify NO success message was emitted (load returned False)
        self.assertNotIn('mycroft.skill.loaded', self.message_bus_mock.message_types)

        # Verify skill was added to plugin_skills
        self.assertIn(skill_id, self.skill_manager.plugin_skills)
        self.assertNotIn(skill_id, self.skill_manager._loading_plugin_skills)

        # Verify return value is None when load returns False
        self.assertIsNone(result)


class TestDeferredLoadingConfigFlag(TestCase):
    """Test suite for the optional deferred loading config flag."""

    mock_package = 'ovos_core.skill_manager.'

    def setUp(self):
        self.message_bus_mock = MessageBusMock()
        self._mock_log()

    def _mock_log(self):
        log_patch = patch(self.mock_package + 'LOG')
        self.addCleanup(log_patch.stop)
        self.log_mock = log_patch.start()

    def test_deferred_loading_disabled_by_default(self):
        """Test that deferred loading is disabled by default (use_deferred_loading: false)."""
        with patch.dict(Configuration._Configuration__patch, mock_config()):
            skill_manager = SkillManager(self.message_bus_mock)

            self.assertFalse(skill_manager._use_deferred_loading)

    def test_deferred_loading_enabled_via_config(self):
        """Test that deferred loading can be enabled via config."""
        config = mock_config()
        config['skills']['use_deferred_loading'] = True
        with patch.dict(Configuration._Configuration__patch, config):
            skill_manager = SkillManager(self.message_bus_mock)
            self.assertTrue(skill_manager._use_deferred_loading)

    def test_connectivity_handlers_not_registered_when_deferred_loading_disabled(self):
        """Test that connectivity event handlers are NOT registered when deferred loading is disabled."""
        with patch.dict(Configuration._Configuration__patch, mock_config()):
            SkillManager(self.message_bus_mock)

            # When deferred loading is disabled, connectivity handlers should not be registered
            expected_handlers = [
                'skillmanager.list',
                'skillmanager.deactivate',
                'skillmanager.keep',
                'skillmanager.activate',
                'mycroft.skills.is_alive',
                'mycroft.skills.is_ready',
                'mycroft.skills.all_loaded'
            ]

            self.assertListEqual(expected_handlers, self.message_bus_mock.event_handlers)
            # Connectivity handlers should NOT be in the list
            self.assertNotIn('mycroft.network.connected', self.message_bus_mock.event_handlers)
            self.assertNotIn('mycroft.internet.connected', self.message_bus_mock.event_handlers)
            self.assertNotIn('mycroft.gui.available', self.message_bus_mock.event_handlers)

    def test_connectivity_handlers_registered_when_deferred_loading_enabled(self):
        """Test that connectivity event handlers ARE registered when deferred loading is enabled."""
        config = mock_config()
        config['skills']['use_deferred_loading'] = True
        with patch.dict(Configuration._Configuration__patch, config):
            SkillManager(self.message_bus_mock)

        # When deferred loading is enabled, connectivity handlers should be registered
        expected_handlers = [
            'skillmanager.list',
            'skillmanager.deactivate',
            'skillmanager.keep',
            'skillmanager.activate',
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

        self.assertListEqual(expected_handlers, self.message_bus_mock.event_handlers)

    @patch('ovos_core.skill_manager.find_skill_plugins')
    def test_load_plugin_skills_no_gating_when_deferred_loading_disabled(self, mock_find):
        """Test that load_plugin_skills does not gate when deferred loading is disabled."""
        with patch.dict(Configuration._Configuration__patch, mock_config()):
            skill_manager = SkillManager(self.message_bus_mock)

            # Mock a skill plugin
            mock_plugin = Mock()
            mock_find.return_value = {'test.skill': mock_plugin}

            # Mock skill loader with network/internet requirements
            mock_loader = Mock(spec=SkillLoader)
            mock_loader.runtime_requirements = Mock()
            mock_loader.runtime_requirements.network_before_load = True
            mock_loader.runtime_requirements.internet_before_load = True
            mock_loader.load.return_value = True

            skill_manager._get_plugin_skill_loader = Mock(return_value=mock_loader)
            skill_manager._load_plugin_skill = Mock(return_value=mock_loader)

            # Call load_plugin_skills with network and internet requirements met
            # When deferred loading is disabled, skills should load unconditionally
            result = skill_manager.load_plugin_skills(network=True, internet=True)

            # Skill should be loaded despite having network/internet requirements
            skill_manager._load_plugin_skill.assert_called_once_with('test.skill', mock_plugin)
            self.assertTrue(result)

    @patch('ovos_core.skill_manager.find_skill_plugins')
    def test_load_plugin_skills_gating_when_deferred_loading_enabled(self, mock_find):
        """Test that load_plugin_skills DOES gate on network/internet when enabled."""
        config = mock_config()
        config['skills']['use_deferred_loading'] = True
        with patch.dict(Configuration._Configuration__patch, config):
            skill_manager = SkillManager(self.message_bus_mock)

            # Mock a skill plugin with network requirement
            mock_plugin = Mock()
            mock_find.return_value = {'test.skill': mock_plugin}

            # Mock skill loader with network requirement
            mock_loader = Mock(spec=SkillLoader)
            mock_loader.runtime_requirements = Mock()
            mock_loader.runtime_requirements.network_before_load = True
            mock_loader.runtime_requirements.internet_before_load = False
            mock_loader.load.return_value = True

            skill_manager._get_plugin_skill_loader = Mock(return_value=mock_loader)
            skill_manager._load_plugin_skill = Mock(return_value=mock_loader)

            # Call load_plugin_skills without network (not connected)
            result = skill_manager.load_plugin_skills(network=False, internet=False)

            # Skill should NOT be loaded due to network requirement not being met
            skill_manager._load_plugin_skill.assert_not_called()
            self.assertFalse(result)

    def test_run_calls_load_new_skills_when_deferred_loading_disabled(self):
        """Test that run() calls _load_new_skills directly when deferred loading is disabled."""
        with patch.dict(Configuration._Configuration__patch, mock_config()):
            skill_manager = SkillManager(self.message_bus_mock)

            # Mock dependencies
            skill_manager.wait_for_intent_service = Mock()
            skill_manager._load_new_skills = Mock()
            skill_manager._load_on_startup = Mock()
            skill_manager._sync_skill_loading_state = Mock()
            skill_manager._mark_startup_complete_and_consume_deferred = Mock()
            skill_manager._stop_event.set()  # Stop immediately to avoid infinite loop

            # Run should call _load_new_skills directly
            skill_manager.run()

            # Verify _load_new_skills was called (unconditional path)
            skill_manager._load_new_skills.assert_called()
            # Verify deferred loading methods were NOT called (they're only for enabled flag)
            skill_manager._load_on_startup.assert_not_called()
            skill_manager._sync_skill_loading_state.assert_not_called()
            skill_manager._mark_startup_complete_and_consume_deferred.assert_not_called()

    def test_run_uses_deferred_loading_when_enabled(self):
        """Test that run() uses deferred loading flow when flag is enabled."""
        config = mock_config()
        config['skills']['use_deferred_loading'] = True
        with patch.dict(Configuration._Configuration__patch, config):
            skill_manager = SkillManager(self.message_bus_mock)

            # Mock dependencies
            skill_manager.wait_for_intent_service = Mock()
            skill_manager._load_on_startup = Mock()
            skill_manager._sync_skill_loading_state = Mock()
            skill_manager._mark_startup_complete_and_consume_deferred = Mock(return_value=False)
            skill_manager._load_new_skills = Mock()
            skill_manager._stop_event.set()  # Stop immediately to avoid infinite loop

            # Run should use the deferred loading path
            skill_manager.run()

            # Verify deferred loading methods were called (deferred path)
            skill_manager._load_on_startup.assert_called()
            skill_manager._sync_skill_loading_state.assert_called()
            skill_manager._mark_startup_complete_and_consume_deferred.assert_called()
            # Verify _load_new_skills is NOT called in deferred startup path (only in loop)
            skill_manager._load_new_skills.assert_not_called()
