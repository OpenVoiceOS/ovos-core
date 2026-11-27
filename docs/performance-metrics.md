# Runtime Performance Metrics

`ovos-core` can expose process-local, fixed-cardinality Prometheus histograms
for the synchronous utterance path. The histogram, the opt-in switch and the
`/metrics` endpoint are shared by every OVOS service and live in
`ovos_utils.metrics` and `ovos_utils.prometheus` (see ovos-utils
`docs/metrics.md`); core registers its own stage collector with them. The
endpoint is disabled by default and binds to loopback unless explicitly
configured.

```text
OVOS_METRICS_ENABLED=true
OVOS_METRICS_HOST=127.0.0.1
OVOS_METRICS_PORT=9474
```

`ovos-core` and `ovos-intent-service` each start the endpoint for their own
process. Scrape `GET /metrics`. The endpoint has no authentication, so do not expose it
publicly. For remote scraping, place it behind an authenticating reverse proxy
or restrict access with a firewall rule. Do not bind it to `0.0.0.0` on an
untrusted network.

## Core stages

| Metric | Boundary |
|---|---|
| `ovos_utterance_dispatch_seconds` | Complete synchronous handling of one `recognizer_loop:utterance` message by `IntentService` |
| `ovos_utterance_preprocess_seconds` | Utterance and metadata transforms and language selection before matching; session validation is measured separately |
| `ovos_utterance_transform_seconds` | Utterance and metadata transformer plugin chains |
| `ovos_language_resolution_seconds` | Resolve the request language against the enabled language set |
| `ovos_session_validation_seconds` | Fold and validate the message session before matching |
| `ovos_session_stamp_seconds` | Serialize the validated session back onto the in-process message |
| `ovos_skill_selection_seconds` | Selection loop across the configured intent pipelines |
| `ovos_intent_pipeline_build_seconds` | Resolve the session's configured matcher functions before invoking them |
| `ovos_intent_matching_seconds` | One bounded pipeline match attempt, including its queue wait; a timed-out attempt records its bound and a declined one records about 0. An utterance can produce more than one observation |
| `ovos_intent_matching_{family}_seconds` | One bounded match attempt classified into the fixed `stop`, `converse`, `padatious`, `padacioso`, `adapt`, `common_query`, `ocp`, `m2v`, `fallback`, or `other` family; a plugin that is not one of these built-ins is `other` |
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
pipeline construction and one or more match attempts; matched-intent
dispatch contains handler scheduling. Plugin-provided handler observations can
contain further plugin-provided stages. Do not add nested durations as if they
were disjoint stages.

Installed packages can contribute histograms and cumulative counters through the
`ovos.performance.metrics` entry-point group. A collector is a zero-argument
callable returning fixed metric snapshots. Histograms provide `count`,
`sum_ms`, and cumulative `buckets`; counters provide `type: counter` and a
numeric `value`, and their names end in `_total`. Collectors are loaded once at
startup; duplicate or malformed metric names make a scrape fail rather than
silently publishing misleading data.

## Aggregating processes

Histograms are process-local, so every OVOS process that exposes metrics has
its own endpoint. Scrape each one, and give processes on the same host their
own `OVOS_METRICS_PORT`. Aggregate buckets across all scraped processes before
calculating a percentile:

```promql
histogram_quantile(
  0.95,
  sum by (le) (rate(ovos_utterance_dispatch_seconds_bucket[5m]))
)
```

Use the same query shape for any histogram listed above. Keep the `instance`
label for a per-process view:

```promql
histogram_quantile(
  0.95,
  sum by (instance, le) (rate(ovos_utterance_dispatch_seconds_bucket[5m]))
)
```

These histograms are cumulative and reset when the process restarts. They use
no session, client, utterance, or skill labels, avoiding unbounded cardinality
and user-content leakage.
