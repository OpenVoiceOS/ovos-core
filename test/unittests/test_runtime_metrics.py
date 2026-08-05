"""Tests for the opt-in process-local OVOS runtime metrics endpoint."""

from urllib.request import urlopen

import pytest

from ovos_core._metrics import LatencyHistogram
from ovos_core._prometheus import (
    collect_histograms,
    load_metric_collectors,
    render_prometheus,
    start_metrics_server,
    stop_metrics_server,
)


def test_histogram_observes_exceptional_blocks():
    histogram = LatencyHistogram("test_stage_ms", buckets_ms=(10, 50))

    with pytest.raises(RuntimeError), histogram.measure():
        raise RuntimeError("expected")

    snapshot = histogram.snapshot()
    assert snapshot["count"] == 1
    assert snapshot["buckets"]["inf"] == 1


def test_histogram_rejects_non_finite_observations():
    histogram = LatencyHistogram("test_stage_ms")

    with pytest.raises(ValueError, match="must be finite"):
        histogram.observe_ms(float("nan"))


def test_prometheus_renderer_converts_milliseconds_to_seconds():
    payload = render_prometheus({
        "test_stage_ms": {
            "count": 1,
            "sum_ms": 125.0,
            "buckets": {"le_100": 0, "le_250": 1, "inf": 1},
        },
    })

    assert 'test_stage_seconds_bucket{le="0.1"} 0' in payload
    assert 'test_stage_seconds_bucket{le="0.25"} 1' in payload
    assert "test_stage_seconds_sum 0.125" in payload
    assert "test_stage_seconds_count 1" in payload


def test_collectors_reject_duplicate_metric_names():
    collector = lambda: {  # noqa: E731
        "duplicate_ms": {
            "count": 0,
            "sum_ms": 0,
            "buckets": {"inf": 0},
        },
    }

    with pytest.raises(ValueError, match="duplicate performance metric"):
        collect_histograms((("first", collector), ("second", collector)))


def test_plugin_metric_collectors_are_loaded_in_stable_order(monkeypatch):
    def plugin_collector():
        return {}

    class EntryPoint:
        def __init__(self, name, value):
            self.name = name
            self.value = value

        def load(self):
            return plugin_collector

    class EntryPoints(list):
        def select(self, *, group):
            assert group == "ovos.performance.metrics"
            return self

    monkeypatch.setattr(
        "ovos_core._prometheus.metadata.entry_points",
        lambda: EntryPoints((
            EntryPoint("weather", "weather:metrics"),
            EntryPoint("workshop", "workshop:metrics"),
        )),
    )

    collectors = load_metric_collectors()

    assert [name for name, _collector in collectors] == [
        "core", "weather", "workshop",
    ]


def test_opt_in_metrics_endpoint(monkeypatch):
    monkeypatch.setenv("OVOS_METRICS_ENABLED", "true")
    monkeypatch.setenv("OVOS_METRICS_HOST", "127.0.0.1")
    monkeypatch.setenv("OVOS_METRICS_PORT", "0")
    server = start_metrics_server()
    assert server is not None
    try:
        with urlopen(  # noqa: S310 - loopback test server only
            f"http://127.0.0.1:{server.server_address[1]}/metrics",
            timeout=2,
        ) as response:
            payload = response.read().decode()
        assert response.status == 200
        assert "ovos_utterance_dispatch_seconds" in payload
        assert "ovos_intent_matching_seconds" in payload
        assert "ovos_skill_selection_seconds" in payload
    finally:
        stop_metrics_server(server)
