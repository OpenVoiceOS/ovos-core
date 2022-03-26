"""
NOTE: this is dead code! do not use!
This file is only present to ensure backwards compatibility
in case someone is importing from here
This is only meant for 3rd party code expecting ovos-core
to be a drop in replacement for mycroft-core
"""

from mycroft.api import is_paired
from mycroft.enclosure.api import EnclosureAPI
from ovos_utils.log import LOG


RASPBERRY_PI_PLATFORMS = ('mycroft_mark_1', 'picroft', 'mycroft_mark_2pi')


def skill_is_blacklisted(skill):
    """DEPRECATED: do not use, method only for api backwards compatibility
    Logs a warning and returns False
    """
    # this is a internal msm helper
    # it should have been private
    # cant remove to keep api compatibility
    # nothing in the wild should be using this
    LOG.warning("skill_is_blacklisted is an internal method and has been deprecated. Stop using it!")
    return False


class DevicePrimer:
    """DEPRECATED: this class has been fully deprecated, stop using it!
    Only here to provide public api compatibility but it does absolutely nothing!
    """

    def __init__(self, message_bus_client, config=None):
        self.bus = message_bus_client
        self.platform = "unknown"
        self.enclosure = EnclosureAPI(self.bus)
        self.backend_down = False

    @property
    def is_paired(self):
        return is_paired()

    def prepare_device(self):
        """Internet dependent updates of various aspects of the device."""
        LOG.warning("DevicePrimer has been deprecated!")

