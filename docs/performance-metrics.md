# Runtime Performance Metrics

`ovos-core` can expose process-local, fixed-cardinality Prometheus histograms
for the synchronous utterance path. The endpoint is disabled by default and
binds to loopback unless explicitly configured.

```text
OVOS_METRICS_ENABLED=true
OVOS_METRICS_HOST=127.0.0.1
OVOS_METRICS_PORT=9474
```

Scrape `GET /metrics`. Do not expose this operational endpoint through the
public voice API or WebSocket ingress. The endpoint has no authentication. For
remote scraping, place it behind an authenticating reverse proxy or restrict
access with a network policy. Do not bind it to `0.0.0.0` on an untrusted
network.

## Core stages

| Metric | Boundary |
|---|---|
| `ovos_utterance_dispatch_seconds` | Complete synchronous handling of one `recognizer_loop:utterance` message by `IntentService` |
| `ovos_utterance_preprocess_seconds` | Utterance and metadata transforms, language selection, and session validation before matching |
| `ovos_utterance_transform_seconds` | Utterance and metadata transformer plugin chains |
| `ovos_language_resolution_seconds` | Resolve the request language against the enabled language set |
| `ovos_session_validation_seconds` | Fold and validate the message session before matching |
| `ovos_session_stamp_seconds` | Serialize the validated session back onto the in-process message |
| `ovos_skill_selection_seconds` | Selection loop across the configured intent pipelines |
| `ovos_intent_pipeline_build_seconds` | Resolve the session's configured matcher functions before invoking them |
| `ovos_intent_matching_seconds` | One pipeline matcher invocation; an utterance can produce more than one observation |
| `ovos_intent_matching_{family}_seconds` | One matcher invocation classified into the fixed `stop`, `converse`, `padatious`, `padacioso`, `adapt`, `common_query`, `ocp`, `m2v`, `fallback`, or `other` family |
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

The boundaries are nested: utterance dispatch contains preprocessing,
selection, matched-intent dispatch, and finalization; selection contains
pipeline construction and one or more matcher observations; matched-intent
dispatch contains handler scheduling. Plugin-provided handler observations can
contain further plugin-provided stages. Do not add nested durations as if they
were disjoint stages.

Installed packages can contribute histograms and cumulative counters through the
`ovos.performance.metrics` entry-point group. A collector is a zero-argument
callable returning fixed metric snapshots. Histograms provide `count`,
`sum_ms`, and cumulative `buckets`; counters provide `type: counter` and an
numeric `value`, and their names end in `_total`. Collectors are loaded once at
startup; duplicate or malformed metric names make a scrape fail rather than
silently publishing misleading data.

## Aggregating partitions

Prometheus must scrape every runtime process. Each process publishes its own
counters. Aggregate buckets across all scraped processes before calculating a
percentile:

```promql
histogram_quantile(
  0.95,
  sum by (le) (rate(ovos_utterance_dispatch_seconds_bucket[5m]))
)
```

Use the same query shape for dispatch, matching, selection, dialog rendering,
and weather-service request histograms. Keep process and pod labels for a
second view when checking shard skew:

```promql
histogram_quantile(
  0.95,
  sum by (pod, le) (rate(ovos_utterance_dispatch_seconds_bucket[5m]))
)
```

These histograms are cumulative and reset when the process restarts. They use
no session, client, utterance, or skill labels, avoiding unbounded cardinality
and user-content leakage.

## Request-correlated benchmark traces

Set `OVOS_PERFORMANCE_TRACE=true` only for a controlled benchmark to emit an
opaque request ID and a wall-clock nanosecond timestamp when the intent service
receives an utterance. The structured log record is prefixed with
`performance_trace` and uses the stage `runtime_receive`.

Request IDs are intentionally absent from the Prometheus endpoint. The trace
contains no utterance, skill, client, credential, or session payload and does
not change the message or public bus contract. Join this opt-in event with the
matching Workshop `skill_reply_emit`, listener stages, and client-receipt
timestamp outside the runtime. Cluster nodes must have synchronized clocks
before interpreting cross-process intervals.
