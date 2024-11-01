# backwards compat imports
from padacioso.opm import PadaciosoPipeline as PadaciosoService, PadaciosoIntent
from padacioso import IntentContainer as FallbackIntentContainer
from ovos_utils.log import log_deprecation
log_deprecation("adapt service moved to 'padacioso.opm'. this import is deprecated", "1.0.0")
