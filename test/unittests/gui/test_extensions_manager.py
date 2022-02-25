from unittest import TestCase, mock
from mycroft.gui.extensions import ExtensionsManager
from ..mocks import MessageBusMock

PATCH_MODULE = "mycroft.gui.extensions"

# Add Unit Tests For ExtensionManager

class TestExtensionManager:

    def test_extension_manager_activate(self):
        extension_manager = ExtensionsManager("ExtensionManager", MessageBusMock(), MessageBusMock())
        extension_manager.activate_extension = mock.Mock()
        extension_manager.activate_extension("SmartSpeaker")
        extension_manager.activate_extension.assert_any_call("SmartSpeaker")
