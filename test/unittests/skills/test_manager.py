import unittest
from unittest.mock import MagicMock, patch

from ovos_bus_client.message import Message

from ovos_core.skill_manager import SkillManager


class TestSkillManager(unittest.TestCase):

    def setUp(self):
        self.bus = MagicMock()
        self.skill_manager = SkillManager(self.bus)

    def test_blacklist_property(self):
        blacklist = self.skill_manager.blacklist
        self.assertIsInstance(blacklist, list)

    @patch('ovos_core.skill_manager.LOG')
    def test_handle_settings_file_change(self, mock_log):
        path = '/some/path/skills/settings.json'
        self.skill_manager._handle_settings_file_change(path)
        self.bus.emit.assert_called_once_with(Message("ovos.skills.settings_changed", {"skill_id": "skills"}))
        mock_log.info.assert_called_once_with(f"skill settings.json change detected for skills")

    @patch('ovos_core.skill_manager.is_paired', side_effect=[False, True])
    def test_handle_check_device_readiness(self, mock_is_paired):
        self.skill_manager.is_device_ready = MagicMock(return_value=True)
        self.skill_manager.handle_check_device_readiness(Message(""))
        self.bus.emit.assert_called_once_with(Message('mycroft.ready'))

    @patch('ovos_core.skill_manager.find_skill_plugins', return_value={'mock_plugin': 'path/to/mock_plugin'})
    def test_load_plugin_skills(self, mock_find_skill_plugins):
        self.skill_manager._load_plugin_skill = MagicMock(return_value=True)
        self.skill_manager.load_plugin_skills(network=True, internet=True)
        self.assertTrue(self.skill_manager._load_plugin_skill.called)
        mock_find_skill_plugins.assert_called_once()

    @patch('ovos_core.skill_manager.is_gui_connected', return_value=True)
    def test_handle_gui_connected(self, mock_is_gui_connected):
        self.skill_manager._allow_state_reloads = True
        self.skill_manager._gui_event.clear()
        self.skill_manager._load_new_skills = MagicMock()
        self.skill_manager.handle_gui_connected(Message("", data={"permanent": False}))
        self.assertTrue(self.skill_manager._gui_event.is_set())
        self.assertTrue(self.skill_manager._load_new_skills.called)

    @patch('ovos_core.skill_manager.is_gui_connected', return_value=False)
    def test_handle_gui_disconnected(self, mock_is_gui_connected):
        self.skill_manager._allow_state_reloads = True
        self.skill_manager._gui_event.set()
        self.skill_manager._unload_on_gui_disconnect = MagicMock()
        self.skill_manager.handle_gui_disconnected(Message(""))
        self.assertFalse(self.skill_manager._gui_event.is_set())
        self.assertTrue(self.skill_manager._unload_on_gui_disconnect.called)

    @patch('ovos_core.skill_manager.is_connected', return_value=True)
    def test_handle_internet_connected(self, mock_is_connected):
        self.skill_manager._connected_event.clear()
        self.skill_manager._network_event.clear()
        self.skill_manager._network_loaded.set()
        self.skill_manager._load_on_internet = MagicMock()
        self.skill_manager.handle_internet_connected(Message(""))
        self.assertTrue(self.skill_manager._connected_event.is_set())
        self.assertTrue(self.skill_manager._network_loaded.is_set())
        self.assertTrue(self.skill_manager._load_on_internet.called)

    @patch('ovos_core.skill_manager.is_connected', return_value=False)
    def test_handle_internet_disconnected(self, mock_is_connected):
        self.skill_manager._allow_state_reloads = True
        self.skill_manager._connected_event.set()
        self.skill_manager._internet_loaded.set()
        self.skill_manager._unload_on_internet_disconnect = MagicMock()
        self.skill_manager.handle_internet_disconnected(Message(""))
        self.assertFalse(self.skill_manager._connected_event.is_set())
        self.assertTrue(self.skill_manager._unload_on_internet_disconnect.called)

    @patch('ovos_core.skill_manager.is_connected', return_value=True)
    def test_handle_network_connected(self, mock_is_connected):
        self.skill_manager._network_event.clear()
        self.skill_manager._load_on_network = MagicMock()
        self.skill_manager.handle_network_connected(Message(""))
        self.assertTrue(self.skill_manager._network_event.is_set())
        self.assertTrue(self.skill_manager._load_on_network.called)

    @patch('ovos_core.skill_manager.is_connected', return_value=False)
    def test_handle_network_disconnected(self, mock_is_connected):
        self.skill_manager._allow_state_reloads = True
        self.skill_manager._network_event.set()
        self.skill_manager._unload_on_network_disconnect = MagicMock()
        self.skill_manager.handle_network_disconnected(Message(""))
        self.assertFalse(self.skill_manager._network_event.is_set())
        self.assertTrue(self.skill_manager._unload_on_network_disconnect.called)


if __name__ == '__main__':
    unittest.main()
