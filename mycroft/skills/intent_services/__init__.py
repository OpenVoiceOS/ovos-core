from ovos_core.intent_services.fallback_service import FallbackService
from ovos_core.intent_services.converse_service import ConverseService
from ovos_adapt.opm import AdaptPipeline as AdaptService
from padacioso.opm import PadaciosoPipeline as PadaciosoService
from ovos_commonqa.opm import CommonQAService
from ovos_plugin_manager.templates.pipeline import IntentMatch
from ovos_workshop.intents import Intent as AdaptIntent, IntentBuilder, Intent

try:
    from ovos_padatious.opm import PadatiousPipeline as PadatiousService, PadatiousMatcher
except ImportError:
    from ovos_utils.log import LOG
    LOG.warning("padatious not installed")
    from padacioso.opm import PadaciosoPipeline as PadatiousService
