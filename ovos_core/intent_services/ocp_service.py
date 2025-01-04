# backwards compat imports
from ocp_pipeline.opm import OCPPipelineMatcher, OCPFeaturizer, OCPPlayerProxy
from ovos_utils.log import log_deprecation
log_deprecation("adapt service moved to 'ovos-ocp-pipeline-plugin'. this import is deprecated", "1.0.0")

import warnings

warnings.warn(
    "adapt service moved to 'ovos-ocp-pipeline-plugin'",
    DeprecationWarning,
    stacklevel=2,
)