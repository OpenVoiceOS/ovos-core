"""Tests for core's use of the shared OVOS metrics (ovos_utils.metrics/prometheus).

The histogram, the opt-in switch, the renderer and the endpoint are tested in
ovos-utils; these cover what only core owns: its stage histograms and the
entry point that registers them.
"""

import inspect
import re
import time
from urllib.request import urlopen

import pytest

from ovos_core._metrics import (
    PIPELINE_MATCHING,
    LatencyHistogram,
    performance_histograms,
    pipeline_matching_histogram,
)
from ovos_utils.metrics import reset_metrics_recording_cache
from ovos_utils.prometheus import start_metrics_server, stop_metrics_server


@pytest.mark.parametrize(
    ("pipeline_id", "family"),
    (
        ("ovos-stop-pipeline-plugin-high", "stop"),
        ("ovos-converse-pipeline-plugin", "converse"),
        ("ovos-padatious-pipeline-plugin-high", "padatious"),
        ("ovos-padatious-pipeline-plugin-low", "padatious"),
        ("ovos-common-query-pipeline-plugin", "common_query"),
        ("ovos-m2v-pipeline-high", "m2v"),
        ("ovos-ocp-pipeline-plugin-legacy", "ocp"),
        ("third-party-matcher-high", "other"),
        ("third-party-adapt-wrapper", "other"),
        ("ovos-adapt-pipeline-wrapper", "other"),
        ("ovos_adapt_pipeline_plugin", "other"),
        ("ovos-adapt-pipeline-plugin-wrapper-high", "other"),
    ),
)
def test_pipeline_histogram_uses_fixed_families(pipeline_id, family):
    assert pipeline_matching_histogram(pipeline_id) is PIPELINE_MATCHING[family]


def test_every_migrated_pipeline_id_has_a_built_in_family():
    """A legacy id must not fall into ``other`` once it has been migrated."""
    from ovos_core.intent_services.service import _PIPELINE_MIGRATION_MAP

    for legacy, current in _PIPELINE_MIGRATION_MAP.items():
        assert pipeline_matching_histogram(current) is not PIPELINE_MATCHING["other"], legacy


def test_service_entrypoint_starts_and_stops_the_metrics_server():
    """The scrape endpoint is only useful if the service actually starts it.

    ovos_core.__main__ is the process entry point; without the
    start/stop calls the histograms are collected but nothing ever serves
    them, and the endpoint silently never comes up.
    """
    import inspect

    import ovos_core.__main__ as service_main

    source = inspect.getsource(service_main.main)
    assert "start_metrics_server([(\"core\", performance_histograms)])" in source
    assert "stop_metrics_server(" in source


def test_stage_histograms_wrap_the_bounded_match_call():
    """A bound the utterance waited out is latency it paid.

    OVOS-PIPELINE-1 §4.4 runs each plugin ``match`` through
    ``_call_match_bounded``, which returns ``None`` on timeout and on a
    §6.2 single-flight skip rather than raising. The stage histograms wrap
    that bounded call, not the plugin call inside it, so a slow entry
    records the time the round actually spent on it and a declined entry
    records ~0. Measuring inside the bound would make a timed-out pipeline
    look free.
    """
    import ovos_core.intent_services.service as service

    source = inspect.getsource(service.IntentService.handle_utterance)
    wrapped = re.search(
        r"with \(INTENT_MATCHING\.measure\(\),\s*"
        r"pipeline_matching_histogram\(\s*"
        r"_PIPELINE_MIGRATION_MAP\.get\(pipeline, pipeline\)\s*"
        r"\)\.measure\(\)\):\s*"
        r"match = self\._call_match_bounded\(",
        source,
    )
    assert wrapped, (
        "the stage histograms no longer wrap _call_match_bounded; a timed-out "
        "or declined pipeline entry would be recorded as free"
    )

    histogram = LatencyHistogram("test_bounded_ms", buckets_ms=(10, 50), enabled=lambda: True)
    before = histogram.snapshot()["count"]
    with histogram.measure():
        time.sleep(0.05)
    snapshot = histogram.snapshot()
    assert snapshot["count"] == before + 1
    assert snapshot["sum_ms"] >= 50


@pytest.mark.parametrize(
    "failing_step",
    ("MessageBusClient", "SkillManager", "wait_for_exit_signal"),
)
def test_service_entrypoint_stops_the_listener_when_startup_raises(monkeypatch, failing_step):
    """A raise between start and stop must not leak the bound port.

    The listener is a daemon thread, so it does not keep the interpreter
    alive and nothing else frees the port it holds. The installed wrapper
    exits on an uncaught exception, but an in-process caller can catch one
    and retry ``main`` - and that retry has to be able to bind again.
    """
    import ovos_core.__main__ as service_main

    stopped = []

    class _Boom(RuntimeError):
        pass

    def _fail(*args, **kwargs):
        raise _Boom(failing_step)

    class _Bus:
        def __init__(self, *args, **kwargs):
            self.connected_event = type("E", (), {"wait": lambda self: None})()

        def run_in_thread(self):
            return None

        def close(self):
            pass

    class _Manager:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def shutdown(self):
            pass

    monkeypatch.setattr(service_main, "init_service_logger", lambda *a, **k: None)
    monkeypatch.setattr(service_main, "start_metrics_server", lambda collectors=None: "listener")
    monkeypatch.setattr(service_main, "stop_metrics_server", stopped.append)
    monkeypatch.setattr(service_main, "MessageBusClient", _Bus)
    monkeypatch.setattr(service_main, "SkillManager", _Manager)
    monkeypatch.setattr(service_main, "wait_for_exit_signal", lambda: None)
    monkeypatch.setattr(service_main, failing_step, _fail)

    with pytest.raises(_Boom):
        service_main.main()

    assert stopped == ["listener"], (
        f"a raise in {failing_step} left the metrics listener running; a caller "
        f"that retries main() would fail to bind the port"
    )


@pytest.mark.parametrize(
    "failing_step",
    (None, "MessageBusClient", "IntentService", "wait_for_exit_signal"),
)
def test_standalone_intent_service_serves_and_stops_the_listener(monkeypatch, failing_step):
    """``ovos-intent-service`` records the stages, so it has to serve them too.

    Whatever ends the process, the listener is stopped: nothing else frees the
    port it holds.
    """
    import ovos_bus_client
    import ovos_utils
    import ovos_utils.log
    import ovos_utils.prometheus

    from ovos_core.intent_services import service

    started = []
    stopped = []

    class _Boom(RuntimeError):
        pass

    def _fail(*args, **kwargs):
        raise _Boom(failing_step)

    class _Bus:
        connected_event = type("E", (), {"wait": lambda self: None})()

        def run_in_thread(self):
            return None

    class _Intents:
        def __init__(self, bus):
            pass

        def shutdown(self):
            pass

    def _start(collectors=None):
        started.append(collectors)
        return "listener"

    monkeypatch.setattr(ovos_utils.log, "init_service_logger", lambda *a, **k: None)
    monkeypatch.setattr(ovos_utils.prometheus, "start_metrics_server", _start)
    monkeypatch.setattr(ovos_utils.prometheus, "stop_metrics_server", stopped.append)
    monkeypatch.setattr(ovos_bus_client, "MessageBusClient", _fail if failing_step == "MessageBusClient" else _Bus)
    monkeypatch.setattr(service, "IntentService", _fail if failing_step == "IntentService" else _Intents)
    monkeypatch.setattr(ovos_utils, "wait_for_exit_signal",
                        _fail if failing_step == "wait_for_exit_signal" else (lambda: None))

    if failing_step:
        with pytest.raises(_Boom):
            service.launch_standalone()
    else:
        service.launch_standalone()

    assert [name for name, _ in started[0]] == ["core"]
    assert started[0][0][1] is performance_histograms
    assert stopped == ["listener"]


# --------------------------------------------------------------------------
# A misconfigured opt-in endpoint must not stop the skills service
# --------------------------------------------------------------------------


def test_core_registers_its_stage_histograms_on_the_shared_endpoint(monkeypatch):
    monkeypatch.setenv("OVOS_METRICS_ENABLED", "true")
    monkeypatch.setenv("OVOS_METRICS_HOST", "127.0.0.1")
    monkeypatch.setenv("OVOS_METRICS_PORT", "0")
    reset_metrics_recording_cache()
    server = start_metrics_server([("core", performance_histograms)])
    assert server is not None
    try:
        with urlopen(  # noqa: S310 - loopback test server only
            f"http://127.0.0.1:{server.server_address[1]}/metrics",
            timeout=2,
        ) as response:
            payload = response.read().decode()
        assert response.status == 200
        for stage in (
            "ovos_utterance_dispatch", "ovos_utterance_preprocess",
            "ovos_utterance_transform", "ovos_language_resolution",
            "ovos_session_validation", "ovos_session_stamp",
            "ovos_intent_matching", "ovos_intent_pipeline_build",
            "ovos_skill_selection", "ovos_intent_dispatch",
            "ovos_intent_transform", "ovos_intent_activation",
            "ovos_intent_matched_emit", "ovos_intent_handler_schedule",
            "ovos_handler_timeout_arm", "ovos_handler_start_emit",
            "ovos_handler_dispatch_emit", "ovos_utterance_finalize",
            "ovos_converse_prepare", "ovos_converse_poll",
            "ovos_converse_policy",
        ):
            assert f"{stage}_seconds" in payload, stage
    finally:
        stop_metrics_server(server)
        monkeypatch.delenv("OVOS_METRICS_ENABLED", raising=False)
        reset_metrics_recording_cache()
