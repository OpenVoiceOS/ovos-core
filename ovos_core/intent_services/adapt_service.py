# backwards compat import
from ovos_adapt.opm import AdaptPipeline as AdaptService
from ovos_utils.log import log_deprecation
log_deprecation("adapt service moved to 'ovos-adapt-pipeline-plugin'. this import is deprecated", "1.0.0")
