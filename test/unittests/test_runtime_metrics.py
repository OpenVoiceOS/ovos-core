"""Tests for the opt-in process-local OVOS runtime metrics endpoint."""

from urllib.request import urlopen

import pytest

from ovos_core._metrics import (
    PIPELINE_MATCHING,
    LatencyHistogram,
    pipeline_matching_histogram,
)
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


def test_histogram_measurement_can_exclude_nested_work(monkeypatch):
    clock = iter((10.0, 10.1))
    monkeypatch.setattr("ovos_core._metrics.time.monotonic", lambda: next(clock))
    histogram = LatencyHistogram("test_stage_ms")

    with histogram.measure() as measurement:
        measurement.pause()

    snapshot = histogram.snapshot()
    assert snapshot["count"] == 1
    assert snapshot["sum_ms"] == pytest.approx(100.0)


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


def test_prometheus_renderer_supports_counters():
    payload = render_prometheus({
        "test_cache_hit_total": {"type": "counter", "value": 7},
    })

    assert "# TYPE test_cache_hit_total counter" in payload
    assert "test_cache_hit_total 7" in payload


def test_prometheus_renderer_rejects_malformed_counters():
    with pytest.raises(ValueError, match="must end with '_total'"):
        render_prometheus({
            "test_cache_hit": {"type": "counter", "value": 1},
        })


@pytest.mark.parametrize(
    ("pipeline_id", "family"),
    (
        ("ovos-stop-pipeline-plugin-high", "stop"),
        ("ovos-converse-pipeline-plugin", "converse"),
        ("ovos-padatious-pipeline-plugin-high", "padatious"),
        ("ovos-padatious-pipeline-plugin-low", "padatious"),
        ("ovos-common-query-pipeline-plugin", "common_query"),
        ("ovos-m2v-pipeline-high", "m2v"),
        ("third-party-matcher-high", "other"),
    ),
)
def test_pipeline_histogram_uses_fixed_families(pipeline_id, family):
    assert pipeline_matching_histogram(pipeline_id) is PIPELINE_MATCHING[family]


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


def test_renderer_rejects_exported_metric_name_collisions():
    snapshot = {
        "count": 0,
        "sum_ms": 0,
        "buckets": {"inf": 0},
    }

    with pytest.raises(ValueError, match="both export as"):
        render_prometheus({
            "duplicate_ms": snapshot,
            "duplicate_seconds": snapshot,
        })


def test_prometheus_renderer_preserves_sum_precision():
    payload = render_prometheus({
        "test_stage_ms": {
            "count": 1,
            "sum_ms": 1_000_000_000.125,
            "buckets": {"inf": 1},
        },
    })

    assert "test_stage_seconds_sum 1000000.000125" in payload


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
