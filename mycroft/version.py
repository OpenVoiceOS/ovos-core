from ovos_core.version import OVOS_VERSION_STR, OVOS_VERSION_BUILD, OVOS_VERSION_TUPLE, \
    OVOS_VERSION_ALPHA, VersionManager, check_version

# The following lines are replaced during the release process.
# START_VERSION_BLOCK
CORE_VERSION_MAJOR = 21
CORE_VERSION_MINOR = 2
CORE_VERSION_BUILD = 1

# END_VERSION_BLOCK
CORE_VERSION_TUPLE = (CORE_VERSION_MAJOR,
                      CORE_VERSION_MINOR,
                      CORE_VERSION_BUILD)
CORE_VERSION_STR = '.'.join(map(str, CORE_VERSION_TUPLE))
