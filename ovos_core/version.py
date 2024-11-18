# START_VERSION_BLOCK
VERSION_MAJOR = 0
VERSION_MINOR = 2
VERSION_BUILD = 12
VERSION_ALPHA = 1
# END_VERSION_BLOCK

# for compat with old imports
OVOS_VERSION_MAJOR = VERSION_MAJOR
OVOS_VERSION_MINOR = VERSION_MINOR
OVOS_VERSION_BUILD = VERSION_BUILD
OVOS_VERSION_ALPHA = VERSION_ALPHA

OVOS_VERSION_TUPLE = (VERSION_MAJOR,
                      VERSION_MINOR,
                      VERSION_BUILD)
OVOS_VERSION_STR = '.'.join(map(str, OVOS_VERSION_TUPLE))


class VersionManager:
    @staticmethod
    def get():
        return {"OpenVoiceOSVersion": OVOS_VERSION_STR}


def check_version(version_string):
    """
        Check if current version is equal or higher than the
        version string provided to the function

        Args:
            version_string (string): version string ('Major.Minor.Build')
    """
    version_tuple = tuple(map(int, version_string.split('.')))
    return OVOS_VERSION_TUPLE >= version_tuple
