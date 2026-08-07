"""Low-overhead, fixed-cardinality runtime latency histograms."""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from functools import wraps
from threading import Lock
from typing import Any, ParamSpec, TypeVar

DEFAULT_BUCKETS_MS = (
    1.0,
    2.5,
    5.0,
    10.0,
    25.0,
    50.0,
    100.0,
    250.0,
    500.0,
    1_000.0,
    2_500.0,
    5_000.0,
    10_000.0,
    30_000.0,
)

P = ParamSpec("P")
R = TypeVar("R")


class _LatencyMeasurement:
    """A pausable, single-observation histogram measurement."""

    def __init__(self, histogram: "LatencyHistogram") -> None:
        self._histogram = histogram
        self._started = time.monotonic()
        self._elapsed_ms = 0.0
        self._running = True
        self._finished = False

    def pause(self) -> None:
        """Exclude subsequent time until :meth:`resume` is called."""
        if self._running and not self._finished:
            self._elapsed_ms += (time.monotonic() - self._started) * 1_000
            self._running = False

    def resume(self) -> None:
        """Resume measuring after a pause."""
        if not self._running and not self._finished:
            self._started = time.monotonic()
            self._running = True

    def finish(self) -> None:
        """Observe accumulated active time exactly once."""
        if self._finished:
            return
        self.pause()
        self._finished = True
        self._histogram.observe_ms(self._elapsed_ms)


class LatencyHistogram:
    """Thread-safe cumulative latency histogram with fixed buckets."""

    def __init__(self, name: str, *,
                 buckets_ms: Iterable[float] = DEFAULT_BUCKETS_MS) -> None:
        self.name = name
        self._bounds = tuple(sorted(float(value) for value in buckets_ms))
        self._buckets = [0] * len(self._bounds)
        self._count = 0
        self._sum_ms = 0.0
        self._lock = Lock()

    def observe_ms(self, elapsed_ms: float) -> None:
        """Record one finite, non-negative duration in milliseconds."""
        value = float(elapsed_ms)
        if not math.isfinite(value):
            raise ValueError("elapsed_ms must be finite")
        value = max(0.0, value)
        with self._lock:
            self._count += 1
            self._sum_ms += value
            for index, bound in enumerate(self._bounds):
                if value <= bound:
                    self._buckets[index] += 1

    @contextmanager
    def measure(self) -> Iterator[_LatencyMeasurement]:
        """Observe active enclosed time, including exceptional exits."""
        measurement = _LatencyMeasurement(self)
        try:
            yield measurement
        finally:
            measurement.finish()

    def timed(self, function: Callable[P, R]) -> Callable[P, R]:
        """Decorate a synchronous function with this histogram."""
        @wraps(function)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            with self.measure():
                return function(*args, **kwargs)

        return wrapped

    def snapshot(self) -> Mapping[str, Any]:
        """Return an immutable, JSON-friendly cumulative snapshot."""
        with self._lock:
            buckets = {
                f"le_{bound:g}": count
                for bound, count in zip(
                    self._bounds, self._buckets, strict=True
                )
            }
            buckets["inf"] = self._count
            return {
                "name": self.name,
                "count": self._count,
                "sum_ms": self._sum_ms,
                "buckets": buckets,
            }


UTTERANCE_DISPATCH = LatencyHistogram("ovos_utterance_dispatch_ms")
UTTERANCE_PREPROCESS = LatencyHistogram("ovos_utterance_preprocess_ms")
INTENT_MATCHING = LatencyHistogram("ovos_intent_matching_ms")
INTENT_PIPELINE_BUILD = LatencyHistogram("ovos_intent_pipeline_build_ms")
SKILL_SELECTION = LatencyHistogram("ovos_skill_selection_ms")
INTENT_DISPATCH = LatencyHistogram("ovos_intent_dispatch_ms")
INTENT_HANDLER_SCHEDULE = LatencyHistogram(
    "ovos_intent_handler_schedule_ms"
)
UTTERANCE_FINALIZE = LatencyHistogram("ovos_utterance_finalize_ms")

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
_PIPELINE_PREFIXES = (
    ("ovos-stop-pipeline", "stop"),
    ("ovos-converse-pipeline", "converse"),
    ("ovos-padatious-pipeline", "padatious"),
    ("ovos-padacioso-pipeline", "padacioso"),
    ("ovos-adapt-pipeline", "adapt"),
    ("ovos-common-query-pipeline", "common_query"),
    ("ovos-ocp-pipeline", "ocp"),
    ("ovos-m2v-pipeline", "m2v"),
    ("ovos-fallback-pipeline", "fallback"),
)


def pipeline_matching_histogram(pipeline_id: str) -> LatencyHistogram:
    """Return the fixed-cardinality histogram for ``pipeline_id``."""
    normalized = str(pipeline_id).lower().replace("_", "-")
    family = next(
        (family for prefix, family in _PIPELINE_PREFIXES
         if normalized.startswith(prefix)),
        "other",
    )
    return PIPELINE_MATCHING[family]


def performance_histograms() -> Mapping[str, Mapping[str, Any]]:
    """Return the process-local Core runtime histograms."""
    return {
        histogram.name: histogram.snapshot()
        for histogram in (
            UTTERANCE_DISPATCH,
            UTTERANCE_PREPROCESS,
            INTENT_MATCHING,
            INTENT_PIPELINE_BUILD,
            SKILL_SELECTION,
            INTENT_DISPATCH,
            INTENT_HANDLER_SCHEDULE,
            UTTERANCE_FINALIZE,
            *PIPELINE_MATCHING.values(),
        )
    }
