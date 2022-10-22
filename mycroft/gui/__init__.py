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
""" Interface for interacting with the Mycroft gui qml viewer. """

from ovos_config.config import Configuration

from ovos_utils.gui import GUIInterface


class SkillGUI(GUIInterface):
    """SkillGUI - Interface to the Graphical User Interface

    Values set in this class are synced to the GUI, accessible within QML
    via the built-in sessionData mechanism.  For example, in Python you can
    write in a skill:
        self.gui['temp'] = 33
        self.gui.show_page('Weather.qml')
    Then in the Weather.qml you'd access the temp via code such as:
        text: sessionData.time
    """

    def __init__(self, skill):
        self.skill = skill
        super().__init__(skill.skill_id, config=Configuration())

    @property
    def bus(self):
        return self.skill.bus

    @property
    def skill_id(self):
        return self.skill.skill_id

    def setup_default_handlers(self):
        """Sets the handlers for the default messages."""
        msg_type = self.build_message_type('set')
        self.skill.add_event(msg_type, self.gui_set)

    def register_handler(self, event, handler):
        """Register a handler for GUI events.

        When using the triggerEvent method from Qt
        triggerEvent("event", {"data": "cool"})

        Args:
            event (str):    event to catch
            handler:        function to handle the event
        """
        msg_type = self.build_message_type(event)
        self.skill.add_event(msg_type, handler)

    def _pages2uri(self, page_names):
        # Convert pages to full reference
        page_urls = []
        for name in page_names:
            page = self.skill._resources.locate_qml_file(name)
            if page:
                if self.remote_url:
                    page_urls.append(self.remote_url + "/" + page)
                elif page.startswith("file://"):
                    page_urls.append(page)
                else:
                    page_urls.append("file://" + page)
            else:
                raise FileNotFoundError(f"Unable to find page: {name}")

        return page_urls

    def shutdown(self):
        """Shutdown gui interface.

        Clear pages loaded through this interface and remove the skill
        reference to make ref counting warning more precise.
        """
        self.release()
        self.skill = None
