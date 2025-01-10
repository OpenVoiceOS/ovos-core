from ovos_commonqa.opm import Query, CommonQAService
from ovos_utils.log import log_deprecation
log_deprecation("adapt service moved to 'ovos-common-query-pipeline-plugin'. this import is deprecated", "1.0.0")

import warnings

warnings.warn(
    "adapt service moved to 'ovos-common-query-pipeline-plugin'",
    DeprecationWarning,
    stacklevel=2,
)