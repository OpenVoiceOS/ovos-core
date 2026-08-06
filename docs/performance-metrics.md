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
| `ovos_skill_selection_seconds` | Selection loop across the configured intent pipelines |
| `ovos_intent_matching_seconds` | One pipeline matcher invocation; an utterance can produce more than one observation |

The boundaries are nested: dispatch contains selection, selection contains one
or more matcher observations, and plugin-provided handler observations can
contain further plugin-provided stages. Do not add these durations as if they
were disjoint stages.

Installed packages can contribute histograms through the
`ovos.performance.metrics` entry-point group. A collector is a zero-argument
callable returning the same fixed histogram snapshot shape as
`ovos_core._metrics.performance_histograms`. Collectors are loaded once at
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
