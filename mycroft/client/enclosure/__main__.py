"""
NOTE: this is dead code! do not use!

This file is only present to ensure backwards compatibility
in case someone is importing from here

This is only meant for 3rd party code expecting ovos-core
to be a drop in replacement for mycroft-core

"""
from ovos_utils.log import init_service_logger
from mycroft.deprecated.enclosure.main import *

if __name__ == "__main__":
    init_service_logger("enclosure")
    main()
