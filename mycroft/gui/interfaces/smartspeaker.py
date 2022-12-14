import json
import platform
from os.path import exists, join

from json_database import JsonStorage
from mycroft.messagebus import Message
from mycroft.util.log import LOG
from mycroft.version import OVOS_VERSION_STR
from ovos_utils import network_utils
from ovos_utils.gui import GUIInterface
from ovos_utils.xdg_utils import xdg_config_home


class SmartSpeakerExtensionGuiInterface(GUIInterface):
    def __init__(self, bus, homescreen_manager) -> None:
        super(SmartSpeakerExtensionGuiInterface, self).__init__(
            skill_id="SmartSpeakerExtension.GuiInterface")
        self.bus = bus
        self.homescreen_manager = homescreen_manager
        
        # Paths to find the local display config
        self.display_config_path_local = join(xdg_config_home(), "OvosDisplay.conf")
        self.display_config_path_system = "/etc/xdg/OvosDisplay.conf"
        self.local_display_config = JsonStorage(self.display_config_path_local)
        self.about_page_data = []

        if not exists(self.display_config_path_local):
            self.handle_display_config_load()

        # Initiate Bind
        self.bind()

    def bind(self):
        super().set_bus(self.bus)
        
        self.bus.on("mycroft.device.settings", self.handle_device_settings)
        self.bus.on("ovos.PHAL.dashboard.status.response",
                    self.update_device_dashboard_status)

        self.bus.on("ovos.phal.configuration.provider.get.response",
                    self.display_advanced_config_for_group)
        self.bus.on("ovos.phal.configuration.provider.list.groups.response",
                    self.display_advanced_config_groups)
        self.bus.on("smartspeaker.extension.extend.about",
                    self.extend_about_page_data_from_event)

        self.register_handler("mycroft.device.settings",
                              self.handle_device_settings)
        self.register_handler(
            "mycroft.device.settings.homescreen", self.handle_device_homescreen_settings)
        self.register_handler("mycroft.device.settings.ssh",
                              self.handle_device_ssh_settings)
        self.register_handler(
            "mycroft.device.settings.developer",  self.handle_device_developer_settings)
        self.register_handler("mycroft.device.enable.dash",
                              self.handle_device_developer_enable_dash)
        self.register_handler("mycroft.device.disable.dash",
                              self.handle_device_developer_disable_dash)
        self.register_handler("mycroft.device.show.idle",
                              self.handle_show_homescreen)
        self.register_handler("mycroft.device.settings.customize",
                              self.handle_device_customize_settings)
        self.register_handler("mycroft.device.settings.create.theme",
                              self.handle_device_create_theme)
        self.register_handler("mycroft.device.settings.about.page",
                              self.handle_device_about_page)
        self.register_handler("mycroft.device.settings.display",
                              self.handle_device_display_settings)
        self.register_handler("mycroft.device.settings.factory",
                              self.handle_device_display_factory)
        
        # Display settings      
        self.register_handler("speaker.extension.display.set.wallpaper.rotation",
                              self.handle_display_wallpaper_rotation_config_set)
        self.register_handler("speaker.extension.display.set.auto.dim",
                              self.handle_display_auto_dim_config_set)
        self.register_handler("speaker.extension.display.set.auto.nightmode",
                              self.handle_display_auto_nightmode_config_set)
        
        self.build_initial_about_page_data()

    def handle_device_settings(self, message):
        """ Display device settings page. """
        self["state"] = "settings/settingspage"
        self.show_page("SYSTEM_AdditionalSettings.qml", override_idle=True)

    def handle_device_homescreen_settings(self, message):
        """
        display homescreen settings page
        """
        screens = self.homescreen_manager.homescreens
        self["idleScreenList"] = {"screenBlob": screens}
        self["selectedScreen"] = self.homescreen_manager.get_active_homescreen()
        self["state"] = "settings/homescreen_settings"
        self.show_page("SYSTEM_AdditionalSettings.qml", override_idle=True)

    def handle_device_ssh_settings(self, message):
        """
        display ssh settings page
        """
        self["state"] = "settings/ssh_settings"
        self.show_page("SYSTEM_AdditionalSettings.qml", override_idle=True)

    def handle_set_homescreen(self, message):
        """
        Set the homescreen to the selected screen
        """
        homescreen_id = message.data.get("homescreen_id", "")
        if homescreen_id:
            self.homescreen_manager.set_active_homescreen(homescreen_id)

    def handle_show_homescreen(self, message):
        self.homescreen_manager.show_homescreen()

    def handle_device_developer_settings(self, message):
        self['state'] = 'settings/developer_settings'
        self.handle_get_dash_status()

    def handle_device_developer_enable_dash(self, message):
        self.bus.emit(Message("ovos.PHAL.dashboard.enable"))

    def handle_device_developer_disable_dash(self, message):
        self.bus.emit(Message("ovos.PHAL.dashboard.disable"))

    def update_device_dashboard_status(self, message):
        call_check = message.data.get("status", False)
        dash_security_pass = message.data.get("password", "")
        dash_security_user = message.data.get("username", "")
        dash_url = message.data.get("url", "")
        if call_check:
            self["dashboard_enabled"] = call_check
            self["dashboard_url"] = dash_url
            self["dashboard_user"] = dash_security_user
            self["dashboard_password"] = dash_security_pass
        else:
            self["dashboard_enabled"] = call_check
            self["dashboard_url"] = ""
            self["dashboard_user"] = ""
            self["dashboard_password"] = ""

    def handle_device_customize_settings(self, message):
        self['state'] = 'settings/customize_settings'
        self.show_page("SYSTEM_AdditionalSettings.qml", override_idle=True)

    def handle_device_create_theme(self, message):
        self['state'] = 'settings/customize_theme'
        self.show_page("SYSTEM_AdditionalSettings.qml", override_idle=True)

    def handle_device_display_factory(self, message):
        self['state'] = 'settings/factory_settings'
        self.show_page("SYSTEM_AdditionalSettings.qml", override_idle=True)

    def handle_device_display_settings(self, message):
        LOG.info("Display settings")
        LOG.info(self.local_display_config)
          
        self['state'] = 'settings/display_settings'
        self['display_wallpaper_rotation'] = self.local_display_config.get("wallpaper_rotation", False)
        self['display_auto_dim'] = self.local_display_config.get("auto_dim", False)
        self['display_auto_nightmode'] = self.local_display_config.get("auto_nightmode", False)
        self.show_page("SYSTEM_AdditionalSettings.qml", override_idle=True)

    def handle_device_about_page(self, message):
        # TODO: Move `system_information` generation to util method
        uname_info = platform.uname()
        system_information = {"display_list": self.about_page_data}
        self['state'] = 'settings/about_page'
        self['system_info'] = system_information
        self.show_page("SYSTEM_AdditionalSettings.qml", override_idle=True)

    def handle_display_wallpaper_rotation_config_set(self, message):
        wallpaper_rotation = message.data.get("wallpaper_rotation", False)
        self.local_display_config["wallpaper_rotation"] = wallpaper_rotation
        self.local_display_config.store()
        self.bus.emit(Message("speaker.extension.display.wallpaper.rotation.changed"))

    def handle_display_auto_dim_config_set(self, message):
        auto_dim = message.data.get("auto_dim", False)
        self.local_display_config["auto_dim"] = auto_dim
        self.local_display_config.store()
        self.bus.emit(Message("speaker.extension.display.auto.dim.changed"))

    def handle_display_auto_nightmode_config_set(self, message):
        auto_nightmode = message.data.get("auto_nightmode", False)
        self.local_display_config["auto_nightmode"] = auto_nightmode
        self.local_display_config.store()
        self.bus.emit(Message("speaker.extension.display.auto.nightmode.changed"))

    def handle_display_config_load(self):
        if exists(self.display_config_path_system):
            LOG.info("Loading display config from system")
            with open(self.display_config_path_system, "r") as f:
                writeable_conf = json.load(f)
                self.local_display_config["wallpaper_rotation"] = writeable_conf["wallpaper_rotation"]
                self.local_display_config["auto_dim"] = writeable_conf["auto_dim"]
                self.local_display_config["auto_nightmode"] = writeable_conf["auto_nightmode"]
                self.local_display_config.store()

    def display_advanced_config_for_group(self, message=None):
        group_meta = message.data.get("settingsMetaData")
        group_name = message.data.get("groupName")
        self["groupName"] = group_name
        self["groupConfigurationData"] = group_meta
        self['state'] = 'settings/configuration_generator_display'
        self.show_page("SYSTEM_AdditionalSettings.qml", override_idle=True)

    def display_advanced_config_groups(self, message=None):
        groups_list = message.data.get("groups")
        self["groupList"] = groups_list
        self['state'] = 'settings/configuration_groups_display'
        self.show_page("SYSTEM_AdditionalSettings.qml", override_idle=True)

    def handle_get_dash_status(self):
        self.bus.emit(Message("ovos.PHAL.dashboard.get.status"))
    
    def build_initial_about_page_data(self):
        uname_info = platform.uname()
        self.about_page_data.append({"display_key": "Kernel Version", "display_value": uname_info[2]})
        self.about_page_data.append({"display_key": "Core Version", "display_value": OVOS_VERSION_STR})
        self.about_page_data.append({"display_key": "Python Version", "display_value": platform.python_version()})
        self.about_page_data.append({"display_key": "Local Address", "display_value": network_utils.get_ip()})
        
    def check_about_page_data_contains_key(self, key):
        for item in self.about_page_data:
            if item["display_key"] == key:
                return True
        return False
    
    def add_about_page_data(self, key, value):
        if not self.check_about_page_data_contains_key(key):
            self.about_page_data.append({"display_key": key, "display_value": value})
        else:
            for item in self.about_page_data:
                if item["display_key"] == key:
                    item["display_value"] = value
                    break
    
    def extend_about_page_data_from_event(self, message=None):
        extended_list = message.data.get("display_list")
        for item in extended_list:
            self.add_about_page_data(item["display_key"], item["display_value"])
