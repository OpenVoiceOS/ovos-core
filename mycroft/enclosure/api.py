"""
NOTE: this is dead code! do not use!

This file is only present to ensure backwards compatibility
in case someone is importing from here

This is only meant for 3rd party code expecting ovos-core
to be a drop in replacement for mycroft-core

"""
from ovos_bus_client.apis.enclosure import EnclosureAPI as _EAPI
from mycroft.enclosure.display_manager import DisplayManager


class EnclosureAPI(_EAPI):
    def __init__(self, bus, name=""):
        super().__init__(bus, name)
        self.display_manager = DisplayManager(self.skill_id)
