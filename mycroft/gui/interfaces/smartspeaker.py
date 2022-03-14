import os
import subprocess
import time
import socket
import secrets
import string
from ovos_utils.gui import GUIInterface


class SmartSpeakerExtensionGuiInterface(GUIInterface):
    def __init__(self, bus, homescreen_manager) -> None:
        super(SmartSpeakerExtensionGuiInterface, self).__init__(
            skill_id="SmartSpeakerExtension.GuiInterface")
        self.bus = bus
        self.homescreen_manager = homescreen_manager

        # Dashboard Specific
        self.dash_running = None
        alphabet = string.ascii_letters + string.digits
        self.dash_secret = ''.join(secrets.choice(alphabet) for i in range(5))

        # Initiate Bind
        self.bind()

    def bind(self):
        super().set_bus(self.bus)

        self.bus.on("mycroft.device.settings", self.handle_device_settings)
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

    def handle_device_settings(self, message):
        """ Display device settings page. """
        self["state"] = "settings/settingspage"
        self.show_page("SYSTEM_AdditionalSettings.qml")

    def handle_device_homescreen_settings(self, message):
        """
        display homescreen settings page
        """
        screens = self.homescreen_manager.homescreens
        self["idleScreenList"] = {"screenBlob": screens}
        self["selectedScreen"] = self.homescreen_manager.get_active_homescreen()
        self["state"] = "settings/homescreen_settings"
        self.show_page("SYSTEM_AdditionalSettings.qml")

    def handle_device_ssh_settings(self, message):
        """
        display ssh settings page
        """
        self["state"] = "settings/ssh_settings"
        self.show_page("SYSTEM_AdditionalSettings.qml")

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

    def handle_device_dashboard_status_check(self):
        build_status_check_call = "systemctl --user is-active --quiet ovos-dashboard@'{0}'.service".format(
            self.dash_secret)
        status = os.system(build_status_check_call)

    def handle_device_developer_enable_dash(self, message):
        os.environ["SIMPLELOGIN_USERNAME"] = "OVOS"
        os.environ["SIMPLELOGIN_PASSWORD"] = self.dash_secret
        build_call = "systemctl --user start ovos-dashboard@'{0}'.service".format(
            self.dash_secret)
        call_dash = subprocess.Popen([build_call], shell=True)
        time.sleep(3)
        build_status_check_call = "systemctl --user is-active --quiet ovos-dashboard@'{0}'.service".format(
            self.dash_secret)
        status = os.system(build_status_check_call)

        if status == 0:
            self.dash_running = True
        else:
            self.dash_running = False

        if self.dash_running:
            self["dashboard_enabled"] = self.dash_running
            self["dashboard_url"] = "https://{0}:5000".format(
                self._get_local_ip())
            self["dashboard_user"] = "OVOS"
            self["dashboard_password"] = self.dash_secret

    def handle_device_developer_disable_dash(self, message):
        build_call = "systemctl --user stop ovos-dashboard@'{0}'.service".format(
            self.dash_secret)
        subprocess.Popen([build_call], shell=True)
        time.sleep(3)
        build_status_check_call = "systemctl --user is-active --quiet ovos-dashboard@'{0}'.service".format(
            self.dash_secret)
        status = os.system(build_status_check_call)

        if status == 0:
            self.dash_running = True
        else:
            self.dash_running = False

        if not self.dash_running:
            self["dashboard_enabled"] = self.dash_running
            self["dashboard_url"] = ""
            self["dashboard_user"] = ""
            self["dashboard_password"] = ""

    def handle_device_dashboard_status_check(self):
        build_status_check_call = "systemctl --user is-active --quiet ovos-dashboard@'{0}'.service".format(
            self.dash_secret)
        status = os.system(build_status_check_call)

        if status == 0:
            self.dash_running = True
        else:
            self.dash_running = False

        if self.dash_running:
            self["dashboard_enabled"] = self.dash_running
            self["dashboard_url"] = "https://{0}:5000".format(
                self._get_local_ip())
            self["dashboard_user"] = "OVOS"
            self["dashboard_password"] = self.dash_secret

    def _get_local_ip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
