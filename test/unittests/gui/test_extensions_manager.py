from unittest import TestCase, mock
from unittest.mock import patch
from mycroft.gui.extensions import ExtensionsManager
from ..mocks import MessageBusMock
from mycroft.configuration import Configuration
from test.util import base_config

PATCH_MODULE = "mycroft.gui.extensions"

# Add Unit Tests For ExtensionManager

class TestExtensionManager:
    @patch.object(Configuration, 'get')

    def test_extension_manager_activate(self):
        config = base_config()
        config.merge(
            {
                'enclosure': {
                    'extension': 'Generic',
                    'generic': {
                        'homescreen_supported': False
                    }
                }
            })
        mock_get.return_value = config
        config['enclosure']['extension'] = 'Generic'
        config['enclosure']['extension']['generic']['homescreen_supported'] = False
        extension_manager = ExtensionsManager("ExtensionManager", MessageBusMock(), MessageBusMock())
        extension_manager.activate_extension = mock.Mock()
        extension_manager.activate_extension("Generic")
        extension_manager.activate_extension.assert_any_call("Generic")
