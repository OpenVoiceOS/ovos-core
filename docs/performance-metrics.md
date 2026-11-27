# Performance metrics
<!-- agent-hint
covers: how to turn on the latency histograms and read them
source: ovos_core/_metrics.py, ovos_core/intent_services/service.py
generated: no
verify: python3 docs/check_page.py docs/performance-metrics.md ovos.performance.metrics recognizer_loop:utterance && for m in $(grep -o '^| `ovos_[a-z_]*_seconds`' docs/performance-metrics.md | grep -o 'ovos_[a-z_]*' | sed 's/_seconds$//'); do grep -q "\"${m}_ms\"" ovos_core/_metrics.py || exit 1; done
see: testing.md
-->

`ovos-core` can record a Prometheus latency histogram for each stage of the utterance path. This page tells you how to turn them on and how to read them.

The histogram type, the switch and the `/metrics` endpoint are in `ovos_utils.metrics` and `ovos_utils.prometheus`. All OVOS services use them. `ovos-core` adds its own stage collector. The endpoint is off by default. It binds to the loopback address unless you set a host.

```text
OVOS_METRICS_ENABLED=true
OVOS_METRICS_HOST=127.0.0.1
OVOS_METRICS_PORT=9474
```

`ovos-core` and `ovos-intent-service` each start the endpoint for their own process. Scrape `GET /metrics`.

The endpoint has no authentication. Do not bind it to `0.0.0.0` on a network that you do not trust. For a remote scrape, put it behind a reverse proxy that authenticates, or limit access with a firewall rule.

## Core stages

| Metric | Boundary |
|---|---|
| `ovos_utterance_dispatch_seconds` | Complete synchronous handling of one `recognizer_loop:utterance` message by `IntentService` |
| `ovos_utterance_preprocess_seconds` | Utterance and metadata transforms and language selection before matching; session validation has its own histogram |
| `ovos_utterance_transform_seconds` | Utterance and metadata transformer plugin chains |
| `ovos_language_resolution_seconds` | Resolve the request language against the enabled language set |
| `ovos_session_validation_seconds` | Fold and validate the message session before matching |
| `ovos_session_stamp_seconds` | Serialize the validated session back onto the in-process message |
| `ovos_skill_selection_seconds` | Selection loop across the configured intent pipelines |
| `ovos_intent_pipeline_build_seconds` | Resolve the session's configured matcher functions before invoking them |
| `ovos_intent_matching_seconds` | One bounded pipeline match attempt, including its queue wait. A timed-out attempt records its bound. A declined attempt records about 0. One utterance can give more than one observation |
| `ovos_intent_matching_{family}_seconds` | One bounded match attempt classified into the fixed `stop`, `converse`, `padatious`, `padacioso`, `adapt`, `common_query`, `ocp`, `m2v`, `fallback`, or `other` family. A plugin outside these families is `other` |
| `ovos_intent_dispatch_seconds` | Post-match transformation, activation, lifecycle emission, and handler scheduling for a matched utterance |
| `ovos_intent_transform_seconds` | Intent transformer plugin chain after a successful match |
| `ovos_intent_activation_seconds` | Update active-handler state and emit the selected skill activation event |
| `ovos_intent_matched_emit_seconds` | Build and emit the public intent-matched notification |
| `ovos_intent_handler_schedule_seconds` | Register the in-flight lifecycle and emit handler-start plus the selected skill dispatch |
| `ovos_handler_timeout_arm_seconds` | Register the in-flight dispatch and arm its bounded timeout |
| `ovos_handler_start_emit_seconds` | Emit the handler-start lifecycle event |
| `ovos_handler_dispatch_emit_seconds` | Emit the selected skill dispatch message |
| `ovos_utterance_finalize_seconds` | Session synchronization and per-utterance deactivation cleanup after selection |
| `ovos_converse_prepare_seconds` | Normalize the language and inspect session response-mode candidates inside the converse matcher |
| `ovos_converse_poll_seconds` | Prune stale converse owners and collect their bounded capability replies |
| `ovos_converse_policy_seconds` | Apply blacklist and converse policy checks to the owners that accepted a poll |

The stages are nested. Do not add the durations of nested stages:

- Utterance dispatch contains preprocessing, selection, matched-intent dispatch and finalization.
- Selection contains the pipeline build and one or more match attempts.
- Matched-intent dispatch contains the handler scheduling.
- A plugin can record more stages inside its own handler.

An installed package can add histograms and counters through the `ovos.performance.metrics` entry-point group. A collector is a callable with no arguments that returns metric snapshots:

- A histogram gives `count`, `sum_ms` and cumulative `buckets`.
- A counter gives `type: counter` and a numeric `value`. Its name ends in `_total`.

The service loads the collectors once, at startup. A duplicate or malformed metric name makes the scrape fail.

## Aggregating processes

Each process has its own histograms and its own endpoint. Scrape each endpoint. Give each process on one host its own `OVOS_METRICS_PORT`. Add the buckets of all processes before you calculate a percentile:

```promql
histogram_quantile(
  0.95,
  sum by (le) (rate(ovos_utterance_dispatch_seconds_bucket[5m]))
)
```

The same query works for each histogram in the table. To see each process, keep the `instance` label:

```promql
histogram_quantile(
  0.95,
  sum by (instance, le) (rate(ovos_utterance_dispatch_seconds_bucket[5m]))
)
```

The histograms are cumulative. They reset when the process restarts. They have no session, client, utterance or skill labels, so the number of series stays fixed and no user text goes into a metric.

---
[← Bus events](bus-events.md) · [Home](index.md) · [Next →](testing.md)
