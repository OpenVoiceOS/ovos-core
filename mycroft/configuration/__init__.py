# backwards compat - moved to own python package
from ovos_config.config import Configuration, LocalConf, RemoteConf
from ovos_config.locale import set_default_lf_lang, setup_locale, \
    set_default_tz, set_default_lang, get_default_tz, get_default_lang, \
    get_config_tz, get_primary_lang_code, load_languages, load_language
from ovos_config.locations import SYSTEM_CONFIG, USER_CONFIG, DEFAULT_CONFIG, \
    get_xdg_config_locations
from ovos_config.meta import get_ovos_config
