"""Opt-in request-correlated runtime trace events.

The trace stream is intentionally separate from Prometheus metrics: request
identifiers are high-cardinality and therefore belong in structured benchmark
logs, never metric labels.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from typing import Any

from ovos_utils.log import LOG

_LOG = LOG
_TRUE_VALUES = {"1", "true", "yes", "on"}
_DIRECT_ID_KEYS = ("query_id", "request_id", "qa_query_id")
_NESTED_KEYS = ("context", "data", "metadata", "payload")
_MAX_REQUEST_ID_LENGTH = 256
_MAX_SEARCH_NODES = 24


def performance_trace_enabled() -> bool:
    """Return whether request-correlated trace logging is enabled."""
    return os.environ.get(
        "OVOS_PERFORMANCE_TRACE", ""
    ).strip().lower() in _TRUE_VALUES


def message_request_id(message: Any) -> str | None:
    """Extract one bounded explicit request ID from an OVOS message."""
    pending = deque([message])
    visited: set[int] = set()
    searched = 0
    while pending and searched < _MAX_SEARCH_NODES:
        candidate = pending.popleft()
        if candidate is None:
            continue
        identity = id(candidate)
        if identity in visited:
            continue
        visited.add(identity)
        searched += 1

        if isinstance(candidate, dict):
            for key in _DIRECT_ID_KEYS:
                value = candidate.get(key)
                if isinstance(value, str) and value:
                    return value[:_MAX_REQUEST_ID_LENGTH]
            pending.extend(
                candidate.get(key) for key in _NESTED_KEYS
                if key in candidate
            )
            continue

        for key in _DIRECT_ID_KEYS:
            value = getattr(candidate, key, None)
            if isinstance(value, str) and value:
                return value[:_MAX_REQUEST_ID_LENGTH]
        pending.extend(
            getattr(candidate, key, None) for key in _NESTED_KEYS
            if hasattr(candidate, key)
        )
    return None


def trace_performance_stage(
    stage: str,
    *,
    message: Any = None,
    request_id: str | None = None,
    at_unix_ns: int | None = None,
) -> None:
    """Log one timestamped stage for an explicitly correlated request."""
    if not performance_trace_enabled():
        return
    identifier = request_id or message_request_id(message)
    if not identifier:
        return
    event = {
        "at_unix_ns": int(at_unix_ns if at_unix_ns is not None
                          else time.time_ns()),
        "request_id": identifier[:_MAX_REQUEST_ID_LENGTH],
        "stage": str(stage),
    }
    _LOG.info(
        "performance_trace %s",
        json.dumps(event, sort_keys=True, separators=(",", ":")),
    )
