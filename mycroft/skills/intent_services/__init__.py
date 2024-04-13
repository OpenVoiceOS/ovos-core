from ovos_core.intent_services import AdaptService,\
    ConverseService, \
    CommonQAService, \
    FallbackService, \
    PadaciosoService
from ovos_core.intent_services import IntentMatch
from mycroft.skills.intent_services.adapt_service import AdaptIntent, IntentBuilder, Intent

try:
    from ovos_core.intent_services.padatious_service import PadatiousService, PadatiousMatcher
except ImportError:
    from ovos_utils.log import LOG
    LOG.warning("padatious not installed")
    from ovos_core.intent_services.padacioso_service import PadaciosoService as PadatiousService
