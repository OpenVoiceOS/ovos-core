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
import time as time_module
from copy import deepcopy
from pathlib import Path
from shutil import rmtree
from threading import Event, Thread
from unittest import TestCase
from unittest.mock import Mock, patch

from ovos_bus_client.message import Message
from ovos_config import Configuration
from ovos_config import LocalConf, DEFAULT_CONFIG
from ovos_bus_client.session import SessionManager
from ovos_core.skill_manager import (SkillManager, PLUGIN_SKILL_RETRY_BASE_SECONDS,
                                      PLUGIN_SKILL_RETRY_MAX_SECONDS)
from ovos_workshop.skill_launcher import SkillLoader

# the retired pre-spec push; OVOS-SESSION-2 §2.7 defines no topic on
# which any participant pushes a session at another
LEGACY_SESSION_SYNC = "ovos.session.sync"


class MessageBusMock:
    """Replaces actual message bus calls in unit tests.

    The message bus should not be running during unit tests so mock it
    out in a way that makes it easy to test code that calls it.
    """

    def __init__(self):
        self.message_types = []
        self.message_data = []
        self.event_handlers = []
        self.handlers = []

    def emit(self, message):
        self.message_types.append(message.msg_type)
        self.message_data.append(message.data)

    def on(self, event, handler):
        self.event_handlers.append(event)
        self.handlers.append((event, handler))

    def once(self, event, handler):
        self.event_handlers.append(event)
        self.handlers.append((event, handler))

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
        SessionManager.bus = None
        self.message_bus_mock = MessageBusMock()
        self._mock_log()
        self.skill_manager = SkillManager(self.message_bus_mock)
        self._mock_skill_loader_instance()
        # SkillManager.__init__ now wires SessionManager.connect_to_bus(),
        # which emits an "ovos.session.update_default" broadcast; drop that
        # setup noise so tests only see messages emitted by the code under test
        self.message_bus_mock.message_types = []
        self.message_bus_mock.message_data = []
        self.addCleanup(self.skill_manager.shutdown)

    def _mock_log(self):
        log_patch = patch(self.mock_package + 'LOG')
        self.addCleanup(log_patch.stop)
        self.log_mock = log_patch.start()

    def tearDown(self):
        rmtree(str(self.temp_dir))
        SessionManager.bus = None

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

    def _warnings_mentioning(self, text):
        """The warnings logged that say `text`. Counted by content, not in
        total: `SkillManager.__init__` warns when no skill package is
        installed at all, so the total depends on the environment the tests
        run in -- a bare venv logs one more than CI, which installs
        skills-essential."""
        return [call.args[0] for call in self.log_mock.warning.call_args_list
                if text in call.args[0]]

    def test_instantiate(self):
        # With default config (deferred_loading: false), connectivity handlers are NOT registered
        # Ensure deferred_loading is explicitly False to isolate from other tests
        config = mock_config()
        config['skills']['use_deferred_loading'] = False
        SessionManager.bus = None
        with patch.dict(Configuration._Configuration__patch, config):
            Configuration._invalidate_cache()
            bus_mock = MessageBusMock()
            skill_manager = SkillManager(bus_mock)
            try:
                expected_result = [
                    'skillmanager.list',
                    'skillmanager.deactivate',
                    'skillmanager.keep',
                    'skillmanager.activate',
                    'skillmanager.rescan',
                    'ovos.skills.install.complete',
                    'ovos.pip.install.complete',
                    'ovos.skills.uninstall.complete',
                    'ovos.pip.uninstall.complete',
                    #'mycroft.skills.initialized',
                    'mycroft.skills.is_alive',
                    'mycroft.skills.is_ready',
                    'mycroft.skills.all_loaded',
                    # SessionManager.connect_to_bus() handlers - wired
                    # unconditionally so skills-only processes (no intent
                    # service) still get SessionManager.bus set
                    'recognizer_loop:record_begin',
                    'recognizer_loop:record_end',
                    'recognizer_loop:audio_output_start',
                    'recognizer_loop:audio_output_end',
                    LEGACY_SESSION_SYNC,
                ]

                self.assertListEqual(expected_result, bus_mock.event_handlers)
            finally:
                skill_manager.shutdown()
        SessionManager.bus = None


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


    def _loader_creation_side_effect(self, error):
        """Build a `_get_plugin_skill_loader` side_effect that succeeds for the
        `load_plugin_skills` runtime-requirements probe (init_bus=False) but
        raises `error` for the real load attempt inside `_load_plugin_skill`
        (init_bus defaults to True there)."""
        def side_effect(skill_id, init_bus=True, skill_class=None):
            if not init_bus:
                requirements = Mock()
                requirements.network_before_load = False
                requirements.internet_before_load = False
                loader = Mock()
                loader.runtime_requirements = requirements
                return loader
            raise error
        return side_effect

    @patch('ovos_core.skill_manager.find_skill_plugins')
    def test_loader_creation_exception_backs_off_before_retry(self, mock_find_skill_plugins):
        """A skill whose loader raises before an instance exists must not be
        retried on every 30s scan - only once a backoff window has elapsed."""
        skill_id = 'test.flaky.loader.skill'
        mock_find_skill_plugins.return_value = {skill_id: Mock()}
        self.skill_manager.plugin_skills = {}
        self.skill_manager._plugin_skill_failures = {}
        self.skill_manager._get_plugin_skill_loader = Mock(
            side_effect=self._loader_creation_side_effect(RuntimeError("boom"))
        )

        fake_now = [1000.0]
        with patch('ovos_core.skill_manager.time.time', side_effect=lambda: fake_now[0]):
            loaded_new = self.skill_manager.load_plugin_skills(network=True, internet=True)
            self.assertFalse(loaded_new)
            first_attempt_calls = self.skill_manager._get_plugin_skill_loader.call_count

            # Still inside the backoff window: no retry attempted.
            fake_now[0] += 5
            self.skill_manager.load_plugin_skills(network=True, internet=True)
            self.assertEqual(
                first_attempt_calls, self.skill_manager._get_plugin_skill_loader.call_count,
                "skill was retried before its backoff window elapsed"
            )

            # Past the base backoff window: retry happens again.
            fake_now[0] += PLUGIN_SKILL_RETRY_BASE_SECONDS
            self.skill_manager.load_plugin_skills(network=True, internet=True)
            self.assertGreater(
                self.skill_manager._get_plugin_skill_loader.call_count, first_attempt_calls,
                "skill was not retried after its backoff window elapsed"
            )

    @patch('ovos_core.skill_manager.find_skill_plugins')
    def test_plugin_skill_success_clears_backoff(self, mock_find_skill_plugins):
        """Once a flaky skill finally loads, its failure record must be
        cleared so a later unrelated reload is not throttled by stale state."""
        skill_id = 'test.recovering.skill'
        mock_plugin = Mock()
        mock_find_skill_plugins.return_value = {skill_id: mock_plugin}
        self.skill_manager.plugin_skills = {}
        self.skill_manager._plugin_skill_failures = {}

        # Record a prior failure directly (mirrors what _load_plugin_skill does).
        self.skill_manager._record_plugin_skill_failure(skill_id)
        self.assertIn(skill_id, self.skill_manager._plugin_skill_failures)

        mock_loader = Mock(spec=SkillLoader)
        mock_loader.skill_id = skill_id
        mock_loader.load.return_value = True
        mock_loader.runtime_requirements.network_before_load = False
        mock_loader.runtime_requirements.internet_before_load = False
        self.skill_manager._get_plugin_skill_loader = Mock(return_value=mock_loader)

        # Move well past the backoff window so the load is attempted at all.
        fake_now = [time_module.time() + PLUGIN_SKILL_RETRY_MAX_SECONDS + 1]
        with patch('ovos_core.skill_manager.time.time', side_effect=lambda: fake_now[0]):
            loaded_new = self.skill_manager.load_plugin_skills(network=True, internet=True)

        self.assertTrue(loaded_new)
        self.assertNotIn(skill_id, self.skill_manager._plugin_skill_failures)
        self.assertIn(skill_id, self.skill_manager.plugin_skills)

    def test_loaded_new_reflects_actual_load_status_not_attempt(self):
        """`loaded_new`/the train request must only fire on confirmed success,
        never merely because a load was attempted."""
        skill_id = 'test.attempt.only.skill'
        mock_plugin = Mock()

        with patch(self.mock_package + 'find_skill_plugins',
                    return_value={skill_id: mock_plugin}):
            self.skill_manager.plugin_skills = {}
            self.skill_manager._plugin_skill_failures = {}
            self.skill_manager._get_plugin_skill_loader = Mock(
                side_effect=self._loader_creation_side_effect(RuntimeError("boom"))
            )
            self.message_bus_mock.message_types = []
            self.skill_manager._use_deferred_loading = False

            # A failed attempt must not request retraining.
            self.skill_manager._load_new_skills(network=True, internet=True, gui=False)
            self.assertNotIn('mycroft.skills.train', self.message_bus_mock.message_types)

            # A successful load must request retraining.
            mock_loader = Mock(spec=SkillLoader)
            mock_loader.skill_id = skill_id
            mock_loader.load.return_value = True
            mock_loader.runtime_requirements.network_before_load = False
            mock_loader.runtime_requirements.internet_before_load = False
            self.skill_manager._get_plugin_skill_loader = Mock(return_value=mock_loader)
            self.skill_manager._plugin_skill_failures = {}
            self.message_bus_mock.message_types = []

            self.skill_manager._load_new_skills(network=True, internet=True, gui=False)
            self.assertIn('mycroft.skills.train', self.message_bus_mock.message_types)

    @patch('ovos_core.skill_manager.find_skill_plugins')
    def test_always_failing_skill_load_attempts_grow_sub_linearly(self, mock_find_skill_plugins):
        """Field shape of the bug: without backoff a flaky skill is retried
        once per 30s scan forever; with backoff, N scans over the same span
        must yield far fewer than N load attempts."""
        skill_id = 'test.always.failing.skill'
        mock_find_skill_plugins.return_value = {skill_id: Mock()}
        self.skill_manager.plugin_skills = {}
        self.skill_manager._plugin_skill_failures = {}
        self.skill_manager._get_plugin_skill_loader = Mock(
            side_effect=self._loader_creation_side_effect(RuntimeError("boom"))
        )

        cycles = 40
        fake_now = [2000.0]
        with patch('ovos_core.skill_manager.time.time', side_effect=lambda: fake_now[0]):
            for _ in range(cycles):
                self.skill_manager.load_plugin_skills(network=True, internet=True)
                fake_now[0] += PLUGIN_SKILL_RETRY_BASE_SECONDS  # one 30s scan tick

        # Each call to `_get_plugin_skill_loader` inside `_load_plugin_skill`
        # is one real load attempt (the runtime-requirements probe is a
        # separate, non-retrying call gated out by the backoff check).
        load_attempts = sum(
            1 for call in self.skill_manager._get_plugin_skill_loader.call_args_list
            if call.kwargs.get('init_bus', True)
        )
        self.assertLess(load_attempts, cycles,
                         "load attempts grew linearly with scan cycles - backoff is not applied")
        self.assertGreater(load_attempts, 0, "skill should still be retried eventually")

    def _mark_ready(self):
        """Put the manager where ``run()`` leaves it once the startup load is done."""
        self.skill_manager.status.set_ready()
        gui_patch = patch(self.mock_package + 'is_gui_connected', return_value=False)
        self.addCleanup(gui_patch.stop)
        gui_patch.start()
        self.message_bus_mock.message_types = []
        self.message_bus_mock.message_data = []

    def _discoverable_plugin(self, skill_id, network_before_load=False):
        """Register a plugin whose loader reports a clean load."""
        mock_loader = Mock(spec=SkillLoader)
        mock_loader.skill_id = skill_id
        mock_loader.load.return_value = True
        mock_loader.runtime_requirements.network_before_load = network_before_load
        mock_loader.runtime_requirements.internet_before_load = False
        self.skill_manager._get_plugin_skill_loader = Mock(return_value=mock_loader)
        self.skill_manager.plugin_skills = {}
        return Mock()

    def test_install_complete_loads_the_new_skill_without_waiting_for_the_scan(self):
        """A skill the installer just made discoverable is loaded on its
        completion report, not on the next periodic scan."""
        for topic in ('ovos.skills.install.complete', 'ovos.pip.install.complete'):
            with self.subTest(topic=topic):
                skill_id = 'test.installed.skill'
                plugin = self._discoverable_plugin(skill_id)
                self._mark_ready()

                with patch(self.mock_package + 'find_skill_plugins',
                           return_value={skill_id: plugin}):
                    self.skill_manager.handle_install_complete(Message(topic))

                self.assertIn(skill_id, self.skill_manager.plugin_skills)
                self.assertIn('mycroft.skill.loaded', self.message_bus_mock.message_types)
                self.assertIn('mycroft.skills.train', self.message_bus_mock.message_types)

    def test_install_complete_before_ready_leaves_the_load_to_startup(self):
        """Before the startup load ran, an install report must not load
        anything: ``run()`` waits for the intent service first."""
        self.skill_manager._load_new_skills = Mock()

        self.skill_manager.handle_install_complete(Message('ovos.skills.install.complete'))

        self.skill_manager._load_new_skills.assert_not_called()

    def test_install_complete_keeps_the_connectivity_gating(self):
        """An install report goes through the same network gate as the scan."""
        skill_id = 'test.network.skill'
        plugin = self._discoverable_plugin(skill_id, network_before_load=True)
        self.skill_manager._use_deferred_loading = True
        self.skill_manager._network_event.clear()
        self._mark_ready()

        with patch(self.mock_package + 'find_skill_plugins',
                   return_value={skill_id: plugin}):
            self.skill_manager.handle_install_complete(Message('ovos.skills.install.complete'))

        self.assertNotIn(skill_id, self.skill_manager.plugin_skills)
        self.assertNotIn('mycroft.skill.loaded', self.message_bus_mock.message_types)

    def test_rescan_reports_only_the_skills_that_call_loaded(self):
        """The rescan response names what this pass loaded, so a caller can
        tell a fresh load from a scan that found nothing new."""
        skill_id = 'test.rescanned.skill'
        plugin = self._discoverable_plugin(skill_id)
        self._mark_ready()

        with patch(self.mock_package + 'find_skill_plugins',
                   return_value={skill_id: plugin}):
            self.skill_manager.handle_rescan_request(Message('skillmanager.rescan'))
            self.skill_manager.handle_rescan_request(Message('skillmanager.rescan'))

        responses = [data for msg_type, data
                     in zip(self.message_bus_mock.message_types, self.message_bus_mock.message_data)
                     if msg_type == 'skillmanager.rescan.response']
        self.assertListEqual([{'loaded': [skill_id]}, {'loaded': []}], responses)

    def test_rescan_before_ready_reports_nothing_loaded(self):
        self.skill_manager._load_new_skills = Mock()

        self.skill_manager.handle_rescan_request(Message('skillmanager.rescan'))

        self.skill_manager._load_new_skills.assert_not_called()
        self.assertIn('skillmanager.rescan.response', self.message_bus_mock.message_types)
        self.assertDictEqual({'loaded': []}, self.message_bus_mock.message_data[-1])
    def _declared(self, *names):
        """Patch what installed packages declare, separately from what imports.

        `find_skill_plugins()` answers "what imported"; the entry point metadata answers
        "what is installed". Only together do they say whether an empty discovery result
        is a removal or a hiccup, so a test that stubs one states the other too.
        """
        return patch.object(self.skill_manager, '_declared_skill_plugins',
                            return_value=set(names))

    def _tracked_loader(self, skill_id):
        """A loaded plugin skill as `_load_plugin_skill` leaves it in `plugin_skills`."""
        loader = Mock(spec=SkillLoader)
        loader.skill_id = skill_id
        loader.instance = Mock()
        self.skill_manager.plugin_skills[skill_id] = loader
        return loader

    def test_uninstall_complete_unloads_the_skill_whose_package_is_gone(self):
        """A loaded skill whose package the installer removed is shut down on
        the completion report; the ones still discoverable are untouched."""
        for topic in ('ovos.skills.uninstall.complete', 'ovos.pip.uninstall.complete'):
            with self.subTest(topic=topic):
                self.skill_manager.plugin_skills = {}
                gone = self._tracked_loader('test.gone.skill')
                kept = self._tracked_loader('test.kept.skill')
                self.skill_manager._plugin_skill_failures = {'test.gone.skill': (2, 0.0)}

                with patch(self.mock_package + 'find_skill_plugins',
                           return_value={'test.kept.skill': Mock()}):
                    self.skill_manager.handle_uninstall_complete(Message(topic))

                self.assertNotIn('test.gone.skill', self.skill_manager.plugin_skills)
                self.assertIn('test.kept.skill', self.skill_manager.plugin_skills)
                gone.instance.shutdown.assert_called_once_with()
                gone.instance.default_shutdown.assert_called_once_with()
                kept.instance.shutdown.assert_not_called()
                kept.instance.default_shutdown.assert_not_called()
                self.assertNotIn('test.gone.skill', self.skill_manager._plugin_skill_failures)

    def test_uninstall_complete_lets_a_reinstall_load_again(self):
        """After the package is removed and reinstalled, the next pass loads it
        again instead of treating it as tracked or waiting out a backoff."""
        skill_id = 'test.reinstalled.skill'
        self.skill_manager.plugin_skills = {}
        self._tracked_loader(skill_id)
        # the shape a load that raised before a loader existed leaves behind:
        # no loader, a backoff record that would hold a fresh attempt for a while
        self.skill_manager._plugin_skill_failures = {skill_id: (6, time_module.time())}

        with patch(self.mock_package + 'find_skill_plugins', return_value={}), self._declared():
            self.skill_manager.handle_uninstall_complete(Message('ovos.skills.uninstall.complete'))

        self.assertDictEqual({}, self.skill_manager.plugin_skills)
        self.assertDictEqual({}, self.skill_manager._plugin_skill_failures)

        mock_loader = Mock(spec=SkillLoader)
        mock_loader.skill_id = skill_id
        mock_loader.load.return_value = True
        mock_loader.runtime_requirements.network_before_load = False
        mock_loader.runtime_requirements.internet_before_load = False
        self.skill_manager._get_plugin_skill_loader = Mock(return_value=mock_loader)
        with patch(self.mock_package + 'find_skill_plugins', return_value={skill_id: Mock()}):
            self.skill_manager._load_new_skills(network=True, internet=True, gui=False)

        self.assertIn(skill_id, self.skill_manager.plugin_skills)
        mock_loader.load.assert_called_once()

    def test_uninstall_complete_keeps_everything_when_discovery_returns_nothing(self):
        """An empty discovery result is a hiccup when the entry points are still
        declared: warn and keep every loaded skill.

        The backoff record for `test.third.skill` is a separate matter. It is not
        declared, so that package really is gone, and leaving its record behind
        would make a reinstall wait out a backoff it no longer owes."""
        self.skill_manager.plugin_skills = {}
        loaders = [self._tracked_loader('test.first.skill'), self._tracked_loader('test.second.skill')]
        self.skill_manager._plugin_skill_failures = {'test.third.skill': (2, 0.0)}
        self.skill_manager._logged_skill_warnings = {'test.first.skill'}

        with patch(self.mock_package + 'find_skill_plugins', return_value={}), \
                self._declared('test.first.skill', 'test.second.skill'):
            self.skill_manager.handle_uninstall_complete(Message('ovos.skills.uninstall.complete'))

        self.assertCountEqual(['test.first.skill', 'test.second.skill'], self.skill_manager.plugin_skills)
        for loader in loaders:
            loader.instance.shutdown.assert_not_called()
            loader.instance.default_shutdown.assert_not_called()
        self.assertDictEqual({}, self.skill_manager._plugin_skill_failures)
        self.assertSetEqual({'test.first.skill'}, self.skill_manager._logged_skill_warnings)
        self.assertEqual(1, len(self._warnings_mentioning('keeping them')))

    def test_uninstall_complete_unloads_the_last_skill_on_empty_discovery(self):
        """With exactly one skill loaded, an empty discovery is the legitimate
        removal of the last skill and it is unloaded."""
        self.skill_manager.plugin_skills = {}
        loader = self._tracked_loader('test.last.skill')

        with patch(self.mock_package + 'find_skill_plugins', return_value={}), self._declared():
            self.skill_manager.handle_uninstall_complete(Message('ovos.skills.uninstall.complete'))

        self.assertDictEqual({}, self.skill_manager.plugin_skills)
        loader.instance.shutdown.assert_called_once_with()
        loader.instance.default_shutdown.assert_called_once_with()
        self.assertEqual([], self._warnings_mentioning('keeping'))

    def test_uninstall_complete_shuts_down_only_the_loader_it_detached(self):
        """A pass detaches the loader instances it decided to remove, so a
        replacement loaded for one of those ids in the meantime survives.

        Two overlapping completion reports can both see the same untracked-yet
        id in their removal list. The moment the first detaches it, a scan or
        an install report is free to load a replacement under that id; the
        second pass must not shut that replacement down."""
        self.skill_manager.plugin_skills = {}
        first = self._tracked_loader('test.first.skill')
        self._tracked_loader('test.second.skill')
        self._tracked_loader('test.kept.skill')

        replacement = Mock(spec=SkillLoader)
        replacement.skill_id = 'test.second.skill'
        replacement.instance = Mock()

        def reload_second():
            # the interleaved load: legitimate, because the id is untracked
            self.skill_manager.plugin_skills['test.second.skill'] = replacement

        first.instance.shutdown.side_effect = reload_second

        with patch(self.mock_package + 'find_skill_plugins',
                   return_value={'test.kept.skill': Mock()}):
            self.skill_manager._unload_undiscoverable_plugin_skills()

        self.assertIs(replacement, self.skill_manager.plugin_skills.get('test.second.skill'))
        replacement.instance.shutdown.assert_not_called()
        replacement.instance.default_shutdown.assert_not_called()

    def test_uninstall_during_load_discards_the_skill_that_was_loading(self):
        """A load in flight when the uninstall lands must not revive the package.

        The loading skill holds the reservation and is not in `plugin_skills`
        yet, so the completion pass finds nothing to detach for it. Without a
        verdict left behind, the load finishes and tracks a skill whose package
        is gone - and since only an uninstall report unloads, nothing removes
        it again."""
        skill_id = 'test.loading.skill'
        self.skill_manager.plugin_skills = {}
        blocked = Event()
        loading = Event()

        mock_loader = Mock(spec=SkillLoader)
        mock_loader.skill_id = skill_id
        mock_loader.instance = Mock()

        def block_until_released(_):
            loading.set()
            blocked.wait(timeout=10)
            return True

        mock_loader.load.side_effect = block_until_released
        self.skill_manager._get_plugin_skill_loader = Mock(return_value=mock_loader)

        loader_thread = Thread(
            target=self.skill_manager._load_plugin_skill,
            args=(skill_id, Mock()), daemon=True)
        loader_thread.start()
        self.assertTrue(loading.wait(timeout=10), "the load never started")
        self.assertIn(skill_id, self.skill_manager._loading_plugin_skills)

        # the package goes away while the load sits inside loader.load()
        with patch(self.mock_package + 'find_skill_plugins', return_value={}), self._declared():
            self.skill_manager.handle_uninstall_complete(
                Message('ovos.skills.uninstall.complete'))

        blocked.set()
        loader_thread.join(timeout=10)
        self.assertFalse(loader_thread.is_alive(), "the load never finished")

        self.assertNotIn(skill_id, self.skill_manager.plugin_skills)
        self.assertNotIn(skill_id, self.skill_manager._loading_plugin_skills)
        mock_loader.instance.shutdown.assert_called_once_with()
        mock_loader.instance.default_shutdown.assert_called_once_with()
        # the package is gone, not broken: a reinstall must not wait out a backoff
        self.assertNotIn(skill_id, self.skill_manager._plugin_skill_failures)

    def test_uninstall_during_load_lets_a_later_reinstall_load(self):
        """The verdict is spent on the load it was recorded against.

        A reinstall reserves the id afresh, so the discarded attempt must not
        leave anything behind that discards the new one too."""
        skill_id = 'test.reloaded.skill'
        self.skill_manager.plugin_skills = {}
        self.skill_manager._loading_plugin_skills = set()
        self.skill_manager._plugin_skill_unload_pending = {skill_id}

        mock_loader = Mock(spec=SkillLoader)
        mock_loader.skill_id = skill_id
        mock_loader.load.return_value = True
        mock_loader.runtime_requirements.network_before_load = False
        mock_loader.runtime_requirements.internet_before_load = False
        self.skill_manager._get_plugin_skill_loader = Mock(return_value=mock_loader)

        with patch(self.mock_package + 'find_skill_plugins', return_value={skill_id: Mock()}):
            self.skill_manager.load_plugin_skills(network=True, internet=True)

        self.assertIn(skill_id, self.skill_manager.plugin_skills)
        self.assertNotIn(skill_id, self.skill_manager._plugin_skill_unload_pending)

    def test_uninstall_keeps_a_loading_skill_when_the_packages_are_installed(self):
        """A skill still loading is kept by the same reasoning as a loaded one: the
        entry points are still declared, so nothing importing is a hiccup."""
        self.skill_manager.plugin_skills = {}
        self._tracked_loader('test.kept.skill')
        self.skill_manager._loading_plugin_skills = {'test.loading.skill'}

        with patch(self.mock_package + 'find_skill_plugins', return_value={}), \
                self._declared('test.kept.skill', 'test.loading.skill'):
            self.skill_manager.handle_uninstall_complete(
                Message('ovos.skills.uninstall.complete'))

        self.assertSetEqual(set(), self.skill_manager._plugin_skill_unload_pending)
        self.assertIn('test.kept.skill', self.skill_manager.plugin_skills)
        self.assertEqual(1, len(self._warnings_mentioning('keeping them')))

    def test_a_skill_that_would_not_import_is_not_treated_as_removed(self):
        """A partial discovery result must not unload a still-installed skill.

        `find_skill_plugins()` swallows the error when one entry point fails to
        import, so that skill is missing from the result exactly like an uninstalled
        one. Its entry point is still declared, and that is what separates the two:
        it stays tracked, keeps its loader, keeps its retry record, and a load in
        flight for it is not marked for discard.
        """
        self.skill_manager.plugin_skills = {}
        good = self._tracked_loader('test.imports.skill')
        broken = self._tracked_loader('test.broken.skill')
        self.skill_manager._plugin_skill_failures = {'test.broken.skill': (1, 0.0)}
        self.skill_manager._loading_plugin_skills = {'test.inflight.skill'}
        self.skill_manager._plugin_skill_unload_pending = set()

        # Only the healthy one imports; all three are still declared.
        with patch(self.mock_package + 'find_skill_plugins',
                   return_value={'test.imports.skill': object()}), \
                self._declared('test.imports.skill', 'test.broken.skill',
                               'test.inflight.skill'):
            removed = self.skill_manager._unload_undiscoverable_plugin_skills()

        self.assertEqual([], removed)
        self.assertIn('test.broken.skill', self.skill_manager.plugin_skills)
        broken.instance.shutdown.assert_not_called()
        good.instance.shutdown.assert_not_called()
        self.assertIn('test.broken.skill', self.skill_manager._plugin_skill_failures)
        self.assertSetEqual(set(), self.skill_manager._plugin_skill_unload_pending)

    def test_a_skill_that_is_neither_importable_nor_declared_is_removed(self):
        """The counterpart: gone from both is a real uninstall, even alongside a
        healthy skill, so a partial result still removes what actually went away."""
        self.skill_manager.plugin_skills = {}
        self._tracked_loader('test.imports.skill')
        gone = self._tracked_loader('test.gone.skill')
        self.skill_manager._plugin_skill_failures = {'test.gone.skill': (1, 0.0)}
        self.skill_manager._loading_plugin_skills = {'test.gone.inflight'}
        self.skill_manager._plugin_skill_unload_pending = set()

        with patch(self.mock_package + 'find_skill_plugins',
                   return_value={'test.imports.skill': object()}), \
                self._declared('test.imports.skill'):
            removed = self.skill_manager._unload_undiscoverable_plugin_skills()

        self.assertEqual(['test.gone.skill'], removed)
        gone.instance.shutdown.assert_called_once_with()
        self.assertNotIn('test.gone.skill', self.skill_manager._plugin_skill_failures)
        self.assertSetEqual({'test.gone.inflight'},
                            self.skill_manager._plugin_skill_unload_pending)

    def test_one_package_can_own_every_loaded_skill(self):
        """A distribution may expose several skill entry points, so uninstalling one
        package can legitimately empty discovery with several skills loaded.

        Counting loaded skills read that as a hiccup and kept every one of them
        registered; what the installed packages declare says it was a real removal."""
        self.skill_manager.plugin_skills = {}
        loaders = [self._tracked_loader(f'bundle.skill.{n}') for n in ('one', 'two', 'three')]

        with patch(self.mock_package + 'find_skill_plugins', return_value={}), self._declared():
            removed = self.skill_manager._unload_undiscoverable_plugin_skills()

        self.assertCountEqual(['bundle.skill.one', 'bundle.skill.two', 'bundle.skill.three'],
                              removed)
        self.assertDictEqual({}, self.skill_manager.plugin_skills)
        for loader in loaders:
            loader.instance.shutdown.assert_called_once_with()

    def test_unreadable_entry_point_metadata_unloads_nothing(self):
        """`_declared_skill_plugins` returning None is "cannot tell", and that must not
        read as "nothing is installed" and shut every skill down."""
        self.skill_manager.plugin_skills = {}
        loader = self._tracked_loader('test.kept.skill')

        with patch(self.mock_package + 'find_skill_plugins', return_value={}), \
                patch.object(self.skill_manager, '_declared_skill_plugins', return_value=None):
            removed = self.skill_manager._unload_undiscoverable_plugin_skills()

        self.assertEqual([], removed)
        self.assertIn('test.kept.skill', self.skill_manager.plugin_skills)
        loader.instance.shutdown.assert_not_called()

    def test_an_abandoned_load_is_never_announced_as_loaded(self):
        """`mycroft.skill.loaded` says a skill is available. A load the uninstall
        abandoned is shut down and never tracked, so it was never available."""
        skill_id = 'test.announced.skill'
        self.skill_manager.plugin_skills = {}
        self.skill_manager._plugin_skill_unload_pending = {skill_id}
        self.skill_manager._loading_plugin_skills = {skill_id}
        self.skill_manager.bus.message_types = []

        mock_loader = Mock(spec=SkillLoader)
        mock_loader.skill_id = skill_id
        mock_loader.instance = Mock()
        mock_loader.load.return_value = True
        self.skill_manager._get_plugin_skill_loader = Mock(return_value=mock_loader)

        self.assertIsNone(self.skill_manager._load_plugin_skill(skill_id, Mock(), reserved=True))

        self.assertNotIn('mycroft.skill.loaded', self.skill_manager.bus.message_types)
        self.assertNotIn(skill_id, self.skill_manager.plugin_skills)
        mock_loader.instance.shutdown.assert_called_once_with()

    def test_a_completed_load_is_announced(self):
        """The counterpart: a load nothing abandoned still announces itself."""
        skill_id = 'test.normal.skill'
        self.skill_manager.plugin_skills = {}
        self.skill_manager._plugin_skill_unload_pending = set()
        self.skill_manager._loading_plugin_skills = {skill_id}
        self.skill_manager.bus.message_types = []

        mock_loader = Mock(spec=SkillLoader)
        mock_loader.skill_id = skill_id
        mock_loader.instance = Mock()
        mock_loader.load.return_value = True
        self.skill_manager._get_plugin_skill_loader = Mock(return_value=mock_loader)

        self.skill_manager._load_plugin_skill(skill_id, Mock(), reserved=True)

        self.assertIn('mycroft.skill.loaded', self.skill_manager.bus.message_types)
        self.assertIn(skill_id, self.skill_manager.plugin_skills)
        mock_loader.instance.shutdown.assert_not_called()

    def test_uninstall_complete_keeps_everything_when_discovery_fails(self):
        """A discovery error must not read as "every package is gone"."""
        self.skill_manager.plugin_skills = {}
        loader = self._tracked_loader('test.kept.skill')

        with patch(self.mock_package + 'find_skill_plugins', side_effect=RuntimeError("boom")):
            self.skill_manager.handle_uninstall_complete(Message('ovos.skills.uninstall.complete'))

        self.assertIn('test.kept.skill', self.skill_manager.plugin_skills)
        loader.instance.shutdown.assert_not_called()
        self.log_mock.exception.assert_called_once()


class TestDeferredLoadingConfigFlag(TestCase):
    """Test suite for the optional deferred loading config flag."""

    mock_package = 'ovos_core.skill_manager.'

    def setUp(self):
        SessionManager.bus = None
        self.message_bus_mock = MessageBusMock()
        self._mock_log()

    def tearDown(self):
        SessionManager.bus = None

    def _mock_log(self):
        log_patch = patch(self.mock_package + 'LOG')
        self.addCleanup(log_patch.stop)
        self.log_mock = log_patch.start()

    def test_deferred_loading_disabled_by_default(self):
        """Test that deferred loading is disabled by default (use_deferred_loading: false)."""
        config = mock_config()
        config['skills']['use_deferred_loading'] = False  # Explicitly set to False
        with patch.dict(Configuration._Configuration__patch, config):
            Configuration._invalidate_cache()
            skill_manager = SkillManager(self.message_bus_mock)
            self.addCleanup(skill_manager.shutdown)
            self.assertFalse(skill_manager._use_deferred_loading)

    def test_deferred_loading_enabled_via_config(self):
        """Test that deferred loading can be enabled via config."""
        config = mock_config()
        config['skills']['use_deferred_loading'] = True
        with patch.dict(Configuration._Configuration__patch, config):
            Configuration._invalidate_cache()
            skill_manager = SkillManager(self.message_bus_mock)
            self.addCleanup(skill_manager.shutdown)
            self.assertTrue(skill_manager._use_deferred_loading)

    def test_connectivity_handlers_not_registered_when_deferred_loading_disabled(self):
        """Test that connectivity event handlers are NOT registered when deferred loading is disabled."""
        config = mock_config()
        config['skills']['use_deferred_loading'] = False  # Explicitly set to False
        with patch.dict(Configuration._Configuration__patch, config):
            Configuration._invalidate_cache()
            skill_manager = SkillManager(self.message_bus_mock)
            self.addCleanup(skill_manager.shutdown)

            # When deferred loading is disabled, connectivity handlers should not be registered
            expected_handlers = [
                'skillmanager.list',
                'skillmanager.deactivate',
                'skillmanager.keep',
                'skillmanager.activate',
                'skillmanager.rescan',
                'ovos.skills.install.complete',
                'ovos.pip.install.complete',
                'ovos.skills.uninstall.complete',
                'ovos.pip.uninstall.complete',
                'mycroft.skills.is_alive',
                'mycroft.skills.is_ready',
                'mycroft.skills.all_loaded',
                'recognizer_loop:record_begin',
                'recognizer_loop:record_end',
                'recognizer_loop:audio_output_start',
                'recognizer_loop:audio_output_end',
                LEGACY_SESSION_SYNC,
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
            Configuration._invalidate_cache()
            skill_manager = SkillManager(self.message_bus_mock)
            self.addCleanup(skill_manager.shutdown)

        # When deferred loading is enabled, connectivity handlers should be registered
        expected_handlers = [
            'skillmanager.list',
            'skillmanager.deactivate',
            'skillmanager.keep',
            'skillmanager.activate',
            'skillmanager.rescan',
            'ovos.skills.install.complete',
            'ovos.pip.install.complete',
            'ovos.skills.uninstall.complete',
            'ovos.pip.uninstall.complete',
            'mycroft.network.connected',
            'mycroft.internet.connected',
            'mycroft.gui.available',
            'mycroft.network.disconnected',
            'mycroft.internet.disconnected',
            'mycroft.gui.unavailable',
            'mycroft.skills.is_alive',
            'mycroft.skills.is_ready',
            'mycroft.skills.all_loaded',
            'recognizer_loop:record_begin',
            'recognizer_loop:record_end',
            'recognizer_loop:audio_output_start',
            'recognizer_loop:audio_output_end',
            LEGACY_SESSION_SYNC,
        ]

        self.assertListEqual(expected_handlers, self.message_bus_mock.event_handlers)

    @patch('ovos_core.skill_manager.find_skill_plugins')
    def test_load_plugin_skills_no_gating_when_deferred_loading_disabled(self, mock_find):
        """Test that load_plugin_skills does not gate when deferred loading is disabled."""
        config = mock_config()
        config['skills']['use_deferred_loading'] = False  # Explicitly set to False
        with patch.dict(Configuration._Configuration__patch, config):
            Configuration._invalidate_cache()
            skill_manager = SkillManager(self.message_bus_mock)
            self.addCleanup(skill_manager.shutdown)

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
            skill_manager._load_plugin_skill.assert_called_once_with('test.skill', mock_plugin, reserved=True)
            self.assertTrue(result)

    @patch('ovos_core.skill_manager.find_skill_plugins')
    def test_load_plugin_skills_gating_when_deferred_loading_enabled(self, mock_find):
        """Test that load_plugin_skills DOES gate on network/internet when enabled."""
        config = mock_config()
        config['skills']['use_deferred_loading'] = True
        with patch.dict(Configuration._Configuration__patch, config):
            Configuration._invalidate_cache()
            skill_manager = SkillManager(self.message_bus_mock)
            self.addCleanup(skill_manager.shutdown)

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
        config = mock_config()
        config['skills']['use_deferred_loading'] = False  # Explicitly set to False
        with patch.dict(Configuration._Configuration__patch, config):
            Configuration._invalidate_cache()
            skill_manager = SkillManager(self.message_bus_mock)
            self.addCleanup(skill_manager.shutdown)

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
            Configuration._invalidate_cache()
            skill_manager = SkillManager(self.message_bus_mock)
            self.addCleanup(skill_manager.shutdown)

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


@patch.dict(Configuration._Configuration__patch, mock_config())
class TestSkillManagerSessionManagerBus(TestCase):
    """
    Regression test: SkillManager must wire SessionManager.connect_to_bus()
    even when the intent service is disabled in this process (the default,
    and the documented --disable-intent-service CLI path). Without this,
    SessionManager.bus stays None in skills-only processes and
    speak(wait=True)/SessionManager.wait_while_speaking silently no-op.
    Mirrors the sibling fix/test in ovos-workshop#526 (SkillContainer).
    """

    def setUp(self):
        SessionManager.bus = None

    def tearDown(self):
        SessionManager.bus = None

    def test_connect_to_bus_with_intent_service_disabled(self):
        bus = MessageBusMock()
        SkillManager(bus, enable_intent_service=False, enable_file_watcher=False)
        self.assertIsNotNone(SessionManager.bus)
        self.assertIs(SessionManager.bus, bus)

    def test_connect_to_bus_exactly_once_with_intent_service_enabled(self):
        """
        Regression test: in the monolith (enable_intent_service=True),
        SkillManager.__init__ connects SessionManager to the bus before
        constructing IntentService, and IntentService.__init__ used to call
        SessionManager.connect_to_bus() unconditionally. Same bus object on
        both call sites means every standard monolith boot registered all
        five SessionManager bus handlers twice. Assert exactly one
        SessionManager-owned handler per topic is registered, regardless of
        which subsystem connects first.

        Counted by handler owner, not by topic: OVOS-SESSION-2 §2.7 defines
        no topic on which any participant pushes a session at another, so
        IntentService itself owns no ``ovos.session.sync`` subscriber -- the
        only listener on that topic is ovos-bus-client's own retired
        pre-spec shim.
        """
        bus = MessageBusMock()
        SkillManager(bus, enable_intent_service=True, enable_file_watcher=False)
        self.assertIsNotNone(SessionManager.bus)
        self.assertIs(SessionManager.bus, bus)
        for topic in (
            "recognizer_loop:record_begin",
            "recognizer_loop:record_end",
            "recognizer_loop:audio_output_start",
            "recognizer_loop:audio_output_end",
            LEGACY_SESSION_SYNC,
        ):
            owned = [h for t, h in bus.handlers
                     if t == topic
                     and getattr(h, "__self__", None) is SessionManager]
            self.assertEqual(
                len(owned), 1,
                f"expected exactly one SessionManager handler for {topic}, "
                f"got {len(owned)}"
            )

