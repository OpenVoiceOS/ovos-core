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
    def measure(self) -> Iterator[None]:
        """Observe the enclosed block, including exceptional exits."""
        started = time.monotonic()
        try:
            yield
        finally:
            self.observe_ms((time.monotonic() - started) * 1_000)

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
                for bound, count in zip(self._bounds, self._buckets)
            }
            buckets["inf"] = self._count
            return {
                "name": self.name,
                "count": self._count,
                "sum_ms": self._sum_ms,
                "buckets": buckets,
            }


UTTERANCE_DISPATCH = LatencyHistogram("ovos_utterance_dispatch_ms")
INTENT_MATCHING = LatencyHistogram("ovos_intent_matching_ms")
SKILL_SELECTION = LatencyHistogram("ovos_skill_selection_ms")


def performance_histograms() -> Mapping[str, Mapping[str, Any]]:
    """Return the process-local Core runtime histograms."""
    return {
        histogram.name: histogram.snapshot()
        for histogram in (
            UTTERANCE_DISPATCH,
            INTENT_MATCHING,
            SKILL_SELECTION,
        )
    }
