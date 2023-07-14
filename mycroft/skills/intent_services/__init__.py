from ovos_core.intent_services import AdaptService,\
    ConverseService,\
    CommonQAService, \
    FallbackService, \
    PadaciosoService, \
    PadatiousService
from ovos_core.intent_services import IntentMatch
from mycroft.skills.intent_services.adapt_service import AdaptIntent, IntentBuilder, Intent

try:  # TODO -remove backwards compat import, before 0.0.8, ovos_core module didnt make it into a stable release yet!
    from ovos_core.intent_services import PadatiousMatcher
except ImportError:
    from ovos_utils.log import LOG
    LOG.warning("padatious not installed")
