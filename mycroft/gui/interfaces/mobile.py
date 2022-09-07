from ovos_utils.gui import GUIInterface

class MobileExtensionGuiInterface(GUIInterface):
    def __init__(self, bus, homescreen_manager) -> None:
        super(MobileExtensionGuiInterface, self).__init__(
            skill_id="MobileExtension.GuiInterface")
        self.bus = bus
        self.homescreen_manager = homescreen_manager

        # Initiate Bind
        self.bind()

    def bind(self):
        super().set_bus(self.bus)
        self.register_handler("mycroft.device.show.idle",
                              self.handle_show_homescreen)
        self.register_handler('mycroft.gui.screen.close',
                                  self.handle_show_homescreen)

    def handle_show_homescreen(self, message):
        self.homescreen_manager.show_homescreen()
