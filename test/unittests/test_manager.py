import unittest
from os.path import join, dirname
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

    @patch('ovos_core.skill_manager.find_skill_plugins', return_value={'mock_plugin': 'path/to/mock_plugin'})
    def test_load_plugin_skills(self, mock_find_skill_plugins):
        self.skill_manager._load_plugin_skill = MagicMock(return_value=True)
        self.skill_manager.load_plugin_skills(network=True, internet=True)
        self.assertTrue(self.skill_manager._load_plugin_skill.called)
        mock_find_skill_plugins.assert_called_once()

    def test_handle_gui_connected(self):
        self.skill_manager._allow_state_reloads = True
        self.skill_manager._gui_event.clear()
        self.skill_manager._load_new_skills = MagicMock()
        self.skill_manager.handle_gui_connected(Message("", data={"permanent": False}))
        self.assertTrue(self.skill_manager._gui_event.is_set())
        self.assertTrue(self.skill_manager._load_new_skills.called)

    def test_handle_gui_disconnected(self):
        self.skill_manager._allow_state_reloads = True
        self.skill_manager._gui_event.set()
        self.skill_manager._unload_on_gui_disconnect = MagicMock()
        self.skill_manager.handle_gui_disconnected(Message(""))
        self.assertFalse(self.skill_manager._gui_event.is_set())
        self.assertTrue(self.skill_manager._unload_on_gui_disconnect.called)

    @patch('ovos_core.skill_manager.is_connected_http', return_value=True)
    def test_handle_internet_connected(self, mock_is_connected):
        self.skill_manager._connected_event.clear()
        self.skill_manager._network_event.clear()
        self.skill_manager._network_loaded.set()
        self.skill_manager._load_on_internet = MagicMock()
        self.skill_manager.handle_internet_connected(Message(""))
        self.assertTrue(self.skill_manager._connected_event.is_set())
        self.assertTrue(self.skill_manager._network_loaded.is_set())
        self.assertTrue(self.skill_manager._load_on_internet.called)

    @patch('ovos_core.skill_manager.is_connected_http', return_value=False)
    def test_handle_internet_disconnected(self, mock_is_connected):
        self.skill_manager._allow_state_reloads = True
        self.skill_manager._connected_event.set()
        self.skill_manager._internet_loaded.set()
        self.skill_manager._unload_on_internet_disconnect = MagicMock()
        self.skill_manager.handle_internet_disconnected(Message(""))
        self.assertFalse(self.skill_manager._connected_event.is_set())
        self.assertTrue(self.skill_manager._unload_on_internet_disconnect.called)

    @patch('ovos_core.skill_manager.is_connected_http', return_value=True)
    def test_handle_network_connected(self, mock_is_connected):
        self.skill_manager._network_event.clear()
        self.skill_manager._load_on_network = MagicMock()
        self.skill_manager.handle_network_connected(Message(""))
        self.assertTrue(self.skill_manager._network_event.is_set())
        self.assertTrue(self.skill_manager._load_on_network.called)

    @patch('ovos_core.skill_manager.is_connected_http', return_value=False)
    def test_handle_network_disconnected(self, mock_is_connected):
        self.skill_manager._allow_state_reloads = True
        self.skill_manager._network_event.set()
        self.skill_manager._unload_on_network_disconnect = MagicMock()
        self.skill_manager.handle_network_disconnected(Message(""))
        self.assertFalse(self.skill_manager._network_event.is_set())
        self.assertTrue(self.skill_manager._unload_on_network_disconnect.called)

    @patch('ovos_core.skill_manager.is_connected_http', return_value=True)
    def test_sync_skill_loading_state_no_phal_plugin(self, mock_is_connected):
        self.bus.wait_for_response.side_effect = [
            None,
            Message("gui.status.request.response",
                    data={"connected": True, "permanent": True})
        ]

        self.skill_manager._gui_event.clear()
        self.skill_manager._connected_event.clear()
        self.skill_manager._network_event.clear()

        self.skill_manager._sync_skill_loading_state()

        self.assertEqual(
            [
                unittest.mock.call(
                    Message("ovos.PHAL.internet_check"),
                    timeout=self.skill_manager._status_query_timeout
                ),
                unittest.mock.call(
                    Message("gui.status.request"),
                    "gui.status.request.response",
                    timeout=self.skill_manager._status_query_timeout
                )
            ],
            self.bus.wait_for_response.call_args_list
        )
        self.assertTrue(self.skill_manager._gui_event.is_set())
        self.assertFalse(self.skill_manager._allow_state_reloads)
        self.assertTrue(self.bus.emit.called)
        self.assertEqual(self.bus.emit.call_args[0][0].msg_type, 'mycroft.internet.connected')
        self.assertEqual(2, self.bus.wait_for_response.call_count)

    def test_sync_skill_loading_state_phal_plugin_no_gui(self):
        self.bus.wait_for_response.side_effect = [
            Message("ovos.PHAL.internet_check", data={"internet_connected": True}),
            None
        ]

        self.skill_manager._gui_event.clear()
        self.skill_manager._connected_event.clear()
        self.skill_manager._network_event.clear()

        self.skill_manager._sync_skill_loading_state()

        self.assertEqual(
            [
                unittest.mock.call(
                    Message("ovos.PHAL.internet_check"),
                    timeout=self.skill_manager._status_query_timeout
                ),
                unittest.mock.call(
                    Message("gui.status.request"),
                    "gui.status.request.response",
                    timeout=self.skill_manager._status_query_timeout
                )
            ],
            self.bus.wait_for_response.call_args_list
        )
        self.assertFalse(self.skill_manager._gui_event.is_set())
        self.assertTrue(self.bus.emit.called)
        self.assertEqual(self.bus.emit.call_args[0][0].msg_type, 'mycroft.internet.connected')

    def test_sync_skill_loading_state_gui_no_internet_but_network(self):
        self.bus.wait_for_response.side_effect = [
            Message("ovos.PHAL.internet_check",
                    data={"internet_connected": False,
                          "network_connected": True}),
            Message("gui.status.request.response", data={"connected": True})
        ]

        self.skill_manager._gui_event.clear()
        self.skill_manager._connected_event.clear()
        self.skill_manager._network_event.clear()

        self.skill_manager._sync_skill_loading_state()

        self.assertEqual(
            [
                unittest.mock.call(
                    Message("ovos.PHAL.internet_check"),
                    timeout=self.skill_manager._status_query_timeout
                ),
                unittest.mock.call(
                    Message("gui.status.request"),
                    "gui.status.request.response",
                    timeout=self.skill_manager._status_query_timeout
                )
            ],
            self.bus.wait_for_response.call_args_list
        )
        self.assertTrue(self.skill_manager._gui_event.is_set())
        self.assertTrue(self.bus.emit.called)
        self.assertEqual(self.bus.emit.call_args[0][0].msg_type, 'mycroft.network.connected')

    def test_load_new_skills_does_not_query_gui_status(self):
        self.skill_manager.load_plugin_skills = MagicMock(return_value=False)
        self.bus.wait_for_response.reset_mock()

        self.skill_manager._load_new_skills(network=False, internet=False)

        self.bus.wait_for_response.assert_not_called()

    @patch('ovos_core.skill_manager.MessageBusClient', autospec=True)
    def test_get_internal_skill_bus_shared_connection(self, mock_MessageBusClient):
        # Set the configuration to use shared_connection=True
        self.skill_manager.config = {'websocket': {'shared_connection': True}}

        # Call the method under test
        result = self.skill_manager._get_internal_skill_bus()

        # Ensure the shared connection is returned
        self.assertEqual(result, self.bus)
        # Ensure that MessageBusClient is not called since shared_connection=True
        self.assertFalse(mock_MessageBusClient.called)

    @patch('ovos_core.skill_manager.MessageBusClient', autospec=True)
    def test_get_internal_skill_bus_not_shared_connection(self, mock_MessageBusClient):
        # Set the configuration to use shared_connection=False
        self.skill_manager.config = {'websocket': {'shared_connection': False}}

        # Call the method under test
        result = self.skill_manager._get_internal_skill_bus()

        # Ensure a new MessageBusClient is created and returned
        mock_MessageBusClient.assert_called_once_with(cache=True)
        self.assertTrue(result.run_in_thread.called)


if __name__ == '__main__':
    unittest.main()
