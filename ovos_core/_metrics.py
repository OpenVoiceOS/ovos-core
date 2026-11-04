"""Fixed-cardinality latency histograms for the utterance path.

The histogram, the opt-in switch and the Prometheus endpoint are shared by
every OVOS service and live in :mod:`ovos_utils.metrics` and
:mod:`ovos_utils.prometheus`; this module only names the stages core times.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ovos_utils.metrics import LatencyHistogram

UTTERANCE_DISPATCH = LatencyHistogram("ovos_utterance_dispatch_ms")
UTTERANCE_PREPROCESS = LatencyHistogram("ovos_utterance_preprocess_ms")
UTTERANCE_TRANSFORM = LatencyHistogram("ovos_utterance_transform_ms")
LANGUAGE_RESOLUTION = LatencyHistogram("ovos_language_resolution_ms")
SESSION_VALIDATION = LatencyHistogram("ovos_session_validation_ms")
SESSION_STAMP = LatencyHistogram("ovos_session_stamp_ms")
INTENT_MATCHING = LatencyHistogram("ovos_intent_matching_ms")
INTENT_PIPELINE_BUILD = LatencyHistogram("ovos_intent_pipeline_build_ms")
SKILL_SELECTION = LatencyHistogram("ovos_skill_selection_ms")
INTENT_DISPATCH = LatencyHistogram("ovos_intent_dispatch_ms")
INTENT_TRANSFORM = LatencyHistogram("ovos_intent_transform_ms")
INTENT_ACTIVATION = LatencyHistogram("ovos_intent_activation_ms")
INTENT_MATCHED_EMIT = LatencyHistogram("ovos_intent_matched_emit_ms")
INTENT_HANDLER_SCHEDULE = LatencyHistogram(
    "ovos_intent_handler_schedule_ms"
)
HANDLER_TIMEOUT_ARM = LatencyHistogram("ovos_handler_timeout_arm_ms")
HANDLER_START_EMIT = LatencyHistogram("ovos_handler_start_emit_ms")
HANDLER_DISPATCH_EMIT = LatencyHistogram("ovos_handler_dispatch_emit_ms")
UTTERANCE_FINALIZE = LatencyHistogram("ovos_utterance_finalize_ms")
CONVERSE_PREPARE = LatencyHistogram("ovos_converse_prepare_ms")
CONVERSE_POLL = LatencyHistogram("ovos_converse_poll_ms")
CONVERSE_POLICY = LatencyHistogram("ovos_converse_policy_ms")

# Pipeline identifiers are session-selectable, so they must never become raw
# metric names or labels.  These families cover the built-in matchers while an
# explicit ``other`` bucket keeps third-party plugins observable without
# unbounded cardinality.
_PIPELINE_FAMILIES = (
    "stop",
    "converse",
    "padatious",
    "padacioso",
    "adapt",
    "common_query",
    "ocp",
    "m2v",
    "fallback",
    "other",
)
PIPELINE_MATCHING = {
    family: LatencyHistogram(f"ovos_intent_matching_{family}_ms")
    for family in _PIPELINE_FAMILIES
}
_PIPELINE_TIER = re.compile(r"-(high|medium|low)$")
# Exact ids, so a third-party plugin named after a built-in stays in ``other``.
_PIPELINE_FAMILY_BY_ID = {
    "ovos-stop-pipeline-plugin": "stop",
    "ovos-converse-pipeline-plugin": "converse",
    "ovos-padatious-pipeline-plugin": "padatious",
    "ovos-padacioso-pipeline-plugin": "padacioso",
    "ovos-adapt-pipeline-plugin": "adapt",
    "ovos-common-query-pipeline-plugin": "common_query",
    "ovos-ocp-pipeline-plugin": "ocp",
    "ovos-ocp-pipeline-plugin-legacy": "ocp",
    "ovos-m2v-pipeline": "m2v",
    "ovos-fallback-pipeline-plugin": "fallback",
}


def pipeline_matching_histogram(pipeline_id: str) -> LatencyHistogram:
    """Return the fixed-cardinality histogram for ``pipeline_id``.

    Callers pass the migrated id: a legacy id such as ``adapt_high`` is
    ``other`` here.
    """
    plugin_id = _PIPELINE_TIER.sub("", str(pipeline_id))
    return PIPELINE_MATCHING[_PIPELINE_FAMILY_BY_ID.get(plugin_id, "other")]


def performance_histograms() -> Mapping[str, Mapping[str, Any]]:
    """Return the process-local Core runtime histograms."""
    return {
        histogram.name: histogram.snapshot()
        for histogram in (
            UTTERANCE_DISPATCH,
            UTTERANCE_PREPROCESS,
            UTTERANCE_TRANSFORM,
            LANGUAGE_RESOLUTION,
            SESSION_VALIDATION,
            SESSION_STAMP,
            INTENT_MATCHING,
            INTENT_PIPELINE_BUILD,
            SKILL_SELECTION,
            INTENT_DISPATCH,
            INTENT_TRANSFORM,
            INTENT_ACTIVATION,
            INTENT_MATCHED_EMIT,
            INTENT_HANDLER_SCHEDULE,
            HANDLER_TIMEOUT_ARM,
            HANDLER_START_EMIT,
            HANDLER_DISPATCH_EMIT,
            UTTERANCE_FINALIZE,
            CONVERSE_PREPARE,
            CONVERSE_POLL,
            CONVERSE_POLICY,
            *PIPELINE_MATCHING.values(),
        )
    }
