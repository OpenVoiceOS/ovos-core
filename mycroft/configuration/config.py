# backwards compat - moved to own python package
from ovos_config.config import Configuration as _Config
from ovos_config.config import MycroftUserConfig, MycroftDefaultConfig, MycroftSystemConfig, RemoteConf, LocalConf
from ovos_config.locations import OLD_USER_CONFIG, DEFAULT_CONFIG, SYSTEM_CONFIG, REMOTE_CONFIG, USER_CONFIG, WEB_CONFIG_CACHE
from ovos_utils.log import log_deprecation


class Configuration(_Config):
    def __init__(self):
        _Config.__init__(self)
        self.get = self.patched_get

    @staticmethod
    def patched_get(*args, **kwargs):
        """
        Backwards-compat `get` method from
        https://github.com/MycroftAI/mycroft-core/blob/dev/mycroft/configuration/config.py
        """
        configs = args[0] if len(args) > 0 else kwargs.get("configs", None)
        if configs or isinstance(configs, list):
            log_deprecation("`Configuration.get` now implements `dict.get`",
                            "0.1.0")
            cache = args[1] if len(args) > 1 else kwargs.get("cache", True)
            remote = args[2] if len(args) > 2 else kwargs.get("remote", True)
            return Configuration.load_config_stack(configs, cache, remote)
        return Configuration._real_get(*args, **kwargs)
