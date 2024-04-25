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
        configs = args[0] if len(args) > 0 else kwargs.get("configs", None)
        if configs or isinstance(configs, list):
            log_deprecation("`Configuration.get` now implements `dict.get`",
                            "0.1.0")
            return Configuration.fake_get(*args, **kwargs)

    @staticmethod
    def fake_get(configs=None, cache=True, remote=True):
        """DEPRECATED - use Configuration class instead"""
        # NOTE: this is only called if using the class directly
        # if using an instance (dict object) self._real_get is called instead
        return Configuration.load_config_stack(configs, cache, remote)