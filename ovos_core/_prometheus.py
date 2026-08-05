"""Dependency-free Prometheus exposition for one OVOS runtime process."""

from __future__ import annotations

import math
import os
import re
from collections.abc import Callable, Mapping, Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import metadata
from threading import Thread
from typing import Any

from ovos_utils.log import LOG

from ovos_core._metrics import performance_histograms

METRIC_ENTRYPOINT_GROUP = "ovos.performance.metrics"
_PROMETHEUS_NAME = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]*")
HistogramCollector = Callable[[], Mapping[str, Mapping[str, object]]]


def load_metric_collectors() -> tuple[tuple[str, HistogramCollector], ...]:
    """Load Core and installed plugin collectors once at process startup."""
    collectors: list[tuple[str, HistogramCollector]] = [
        ("core", performance_histograms),
    ]
    discovered = metadata.entry_points()
    if hasattr(discovered, "select"):
        entry_points = discovered.select(group=METRIC_ENTRYPOINT_GROUP)
    else:  # pragma: no cover - Python 3.9 compatibility path
        entry_points = discovered.get(METRIC_ENTRYPOINT_GROUP, ())
    entry_points = sorted(
        entry_points,
        key=lambda entry_point: (entry_point.name, entry_point.value),
    )
    for entry_point in entry_points:
        collector = entry_point.load()
        if not callable(collector):
            raise TypeError(
                f"metrics entry point {entry_point.name!r} is not callable"
            )
        collectors.append((entry_point.name, collector))
    return tuple(collectors)


def collect_histograms(
    collectors: Sequence[tuple[str, HistogramCollector]],
) -> dict[str, Mapping[str, object]]:
    """Collect a snapshot and reject duplicate or malformed metric names."""
    histograms: dict[str, Mapping[str, object]] = {}
    for collector_name, collector in collectors:
        snapshots = collector()
        if not isinstance(snapshots, Mapping):
            raise TypeError(
                f"metrics collector {collector_name!r} returned a non-mapping"
            )
        for metric_name, snapshot in snapshots.items():
            if metric_name in histograms:
                raise ValueError(f"duplicate performance metric {metric_name!r}")
            if not isinstance(snapshot, Mapping):
                raise TypeError(
                    f"performance metric {metric_name!r} is not a mapping"
                )
            histograms[str(metric_name)] = snapshot
    return histograms


def _number(value: Any, field: str, metric_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{metric_name}.{field} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{metric_name}.{field} must be finite and non-negative")
    return parsed


def _count(value: Any, field: str, metric_name: str) -> int:
    parsed = _number(value, field, metric_name)
    if not parsed.is_integer():
        raise ValueError(f"{metric_name}.{field} must be an integer")
    return int(parsed)


def _metric_name(metric_name: str) -> str:
    exported = (
        f"{metric_name[:-3]}_seconds"
        if metric_name.endswith("_ms")
        else metric_name
    )
    if not _PROMETHEUS_NAME.fullmatch(exported):
        raise ValueError(f"invalid Prometheus metric name {exported!r}")
    return exported


def render_prometheus(
    histograms: Mapping[str, Mapping[str, object]],
) -> str:
    """Render cumulative millisecond snapshots as Prometheus histograms."""
    lines: list[str] = []
    for metric_name in sorted(histograms):
        snapshot = histograms[metric_name]
        exported = _metric_name(metric_name)
        buckets = snapshot.get("buckets")
        if not isinstance(buckets, Mapping):
            raise TypeError(f"{metric_name}.buckets must be a mapping")
        count = _count(snapshot.get("count"), "count", metric_name)
        sum_seconds = _number(
            snapshot.get("sum_ms"), "sum_ms", metric_name
        ) / 1_000
        finite: list[tuple[float, int]] = []
        infinity_count: int | None = None
        for bucket_name, raw_count in buckets.items():
            bucket_count = _count(raw_count, str(bucket_name), metric_name)
            if bucket_name == "inf":
                infinity_count = bucket_count
                continue
            if not str(bucket_name).startswith("le_"):
                raise ValueError(
                    f"unexpected bucket {bucket_name!r} in {metric_name}"
                )
            bound_ms = float(str(bucket_name)[3:])
            if not math.isfinite(bound_ms) or bound_ms < 0:
                raise ValueError(f"invalid bucket bound in {metric_name}")
            finite.append((bound_ms, bucket_count))
        finite.sort(key=lambda item: item[0])
        cumulative = [bucket_count for _, bucket_count in finite]
        if cumulative != sorted(cumulative):
            raise ValueError(f"non-cumulative buckets in {metric_name}")
        if cumulative and cumulative[-1] > count:
            raise ValueError(f"bucket exceeds count in {metric_name}")
        if infinity_count != count:
            raise ValueError(
                f"{metric_name} infinity bucket does not equal count"
            )
        lines.extend((
            f"# HELP {exported} Process-local latency observed by {metric_name}.",
            f"# TYPE {exported} histogram",
        ))
        for bound_ms, bucket_count in finite:
            lines.append(
                f'{exported}_bucket{{le="{bound_ms / 1_000:g}"}} '
                f"{bucket_count}"
            )
        lines.extend((
            f'{exported}_bucket{{le="+Inf"}} {count}',
            f"{exported}_sum {sum_seconds:g}",
            f"{exported}_count {count}",
        ))
    return "\n".join(lines) + "\n"


def _handler(
    collectors: Sequence[tuple[str, HistogramCollector]],
) -> type[BaseHTTPRequestHandler]:
    class MetricsHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/metrics":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                payload = render_prometheus(collect_histograms(collectors))
            except Exception:
                LOG.exception("OVOS runtime metrics scrape failed")
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
                return
            encoded = payload.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header(
                "Content-Type",
                "text/plain; version=0.0.4; charset=utf-8",
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, _format: str, *args: object) -> None:
            return

    return MetricsHandler


def metrics_enabled() -> bool:
    """Return whether the explicitly opt-in runtime endpoint is enabled."""
    return os.getenv("OVOS_METRICS_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }


def start_metrics_server() -> ThreadingHTTPServer | None:
    """Start a daemon metrics listener when explicitly enabled."""
    if not metrics_enabled():
        return None
    host = os.getenv("OVOS_METRICS_HOST", "127.0.0.1")
    raw_port = os.getenv("OVOS_METRICS_PORT", "9474")
    try:
        port = int(raw_port)
    except ValueError as error:
        raise ValueError("OVOS_METRICS_PORT must be an integer") from error
    if not 0 <= port <= 65_535:
        raise ValueError("OVOS_METRICS_PORT must be between 0 and 65535")
    collectors = load_metric_collectors()
    server = ThreadingHTTPServer((host, port), _handler(collectors))
    Thread(
        target=server.serve_forever,
        name="ovos-runtime-metrics",
        daemon=True,
    ).start()
    LOG.info(
        "OVOS runtime metrics listener started on %s:%s",
        host,
        server.server_address[1],
    )
    return server


def stop_metrics_server(server: ThreadingHTTPServer | None) -> None:
    """Stop and close a runtime metrics listener, if one was started."""
    if server is None:
        return
    server.shutdown()
    server.server_close()
