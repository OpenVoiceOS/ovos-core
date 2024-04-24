# backwards compat - moved to own python package
from ovos_config.config import Configuration as _Config
from ovos_config.config import MycroftUserConfig, MycroftDefaultConfig, MycroftSystemConfig, RemoteConf, LocalConf
from ovos_config.locations import OLD_USER_CONFIG, DEFAULT_CONFIG, SYSTEM_CONFIG, REMOTE_CONFIG, USER_CONFIG, WEB_CONFIG_CACHE
from ovos_utils.log import log_deprecation


class Configuration(_Config):
    @classmethod
    def get(cls, *args, **kwargs):
        """
        Backwards-compat `get` method from
        https://github.com/MycroftAI/mycroft-core/blob/dev/mycroft/configuration/config.py
        """
        if not isinstance(cls, Configuration):
            return _Config.get(*args, **kwargs)
