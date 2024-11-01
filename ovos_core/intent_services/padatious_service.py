# backwards compat imports
from ovos_padatious.opm import PadatiousMatcher, PadatiousPipeline as PadatiousService
from ovos_utils.log import log_deprecation
log_deprecation("adapt service moved to 'ovos-padatious-pipeline-plugin'. this import is deprecated", "1.0.0")
