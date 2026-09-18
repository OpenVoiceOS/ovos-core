
# Intent Pipeline

The pipeline is an ordered list of matchers. Each utterance is passed to matchers in sequence until one returns a match.

## Configuration

The pipeline is configured per-session. The default comes from `mycroft.conf`:

```json
{
  "intents": {
    "pipeline": [
      "stop_high",
      "converse",
      "ocp_high",
      "padatious_high",
      "adapt_high",
      "ocp_medium",
      "fallback_high",
      "stop_medium",
      "adapt_medium",
      "padatious_medium",
      "adapt_low",
      "common_qa",
      "fallback_medium",
      "fallback_low"
    ]
  }
}
```

Pipeline stages are also configurable per-`Session`, allowing HiveMind clients or individual users to have different pipelines.

## Plugin IDs and Stage Names

Pipeline plugins are loaded by `OVOSPipelineFactory` from the `opm.pipeline` entry point group. Each plugin ID maps to one or more stage names:

| Stage name(s) | Plugin ID | Matcher type |
|---|---|---|
| `converse` | `ovos-converse-pipeline-plugin` | `PipelinePlugin` |
| `common_qa` | `ovos-common-query-pipeline-plugin` | `PipelinePlugin` |
| `fallback_high/medium/low` | `ovos-fallback-pipeline-plugin` | `ConfidenceMatcherPipeline` |
| `stop_high/medium/low` | `ovos-stop-pipeline-plugin` | `ConfidenceMatcherPipeline` |
| `adapt_high/medium/low` | `ovos-adapt-pipeline-plugin` | `ConfidenceMatcherPipeline` |
| `padatious_high/medium/low` | `ovos-padatious-pipeline-plugin` | `ConfidenceMatcherPipeline` |
| `padacioso_high/medium/low` | `ovos-padacioso-pipeline-plugin` | `ConfidenceMatcherPipeline` |
| `ocp_high/medium/low/legacy` | `ovos-ocp-pipeline-plugin` | `ConfidenceMatcherPipeline` |

Plugins that implement `ConfidenceMatcherPipeline` expose `match_high`, `match_medium`, and `match_low` methods; the stage suffix selects which one is called.

## Plugin Resolution

`IntentService.get_pipeline_matcher(matcher_id)` resolves a stage name:

1. Apply legacy name migration map (e.g. `"converse"` → `"ovos-converse-pipeline-plugin"`)
2. Strip `-high`/`-medium`/`-low` suffix to get the plugin base ID
3. Look up the loaded plugin in `self.pipeline_plugins`
4. Return the appropriate method (`match`, `match_high`, `match_medium`, or `match_low`)

Unloaded or unknown plugins are skipped with a warning: they do not cause startup failures.

## Reloading

Send `intent.service.pipelines.reload` on the bus to trigger a fresh scan and load of all installed pipeline plugins. This is done automatically at `IntentService` startup.

## Built-in Pipeline Plugins (this repo)

`ovos-core` ships three pipeline plugins registered via its own `pyproject.toml`:

- `ovos-converse-pipeline-plugin` → `ConverseService` (see [`converse-fallback.md`](converse-fallback.md))
- `ovos-fallback-pipeline-plugin` → `FallbackService` (high/medium/low)
- `ovos-stop-pipeline-plugin` → `StopService` (high/medium/low)

All other pipeline plugins (`adapt`, `padatious`, `ocp`, etc.) come from separate packages.

---

## Cross-References

### Plugin framework
- **`OVOSPipelineFactory`**: `ovos_plugin_manager.pipeline.OVOSPipelineFactory` → [`ovos-plugin-manager/docs/plugin-types.md`](../../ovos-plugin-manager/docs/plugin-types.md). Scans the `opm.pipeline` entry point group and instantiates each plugin with a `bus` connection.
- **`ConfidenceMatcherPipeline`** / **`PipelinePlugin`**: base templates in `ovos_plugin_manager.templates.pipeline`. Writing a new pipeline plugin: [`ovos-plugin-manager/docs/writing-plugins.md`](../../ovos-plugin-manager/docs/writing-plugins.md).

### Per-session pipeline
- The pipeline list is stored on the **`Session`** object: `ovos_bus_client.session.Session.pipeline`. Each HiveMind client or remote session can have an independent pipeline. See [`ovos-bus-client/docs/session.md`](../../ovos-bus-client/docs/session.md).

### External pipeline plugins (separate packages)
| Plugin | Package | Notes |
|---|---|---|
| `ovos-adapt-pipeline-plugin` | `ovos-adapt` | Keyword/entity intent matching |
| `ovos-padatious-pipeline-plugin` | `ovos-padatious` | ML intent matching (Padatious) |
| `ovos-padacioso-pipeline-plugin` | `ovos-padacioso` | Regex+Padatious hybrid |
| `ovos-ocp-pipeline-plugin` | `ovos-ocp` | OCP media player pipeline |
| `ovos-common-query-pipeline-plugin` | `ovos-workshop` | `CommonQuerySkill` routing |
| `ovos-persona-pipeline-plugin` | `ovos-persona` | LLM persona / chatbot routing; see [`ovos-persona`](../../ovos-persona) |

### Converse & Fallback detail
→ [`converse-fallback.md`](converse-fallback.md)

---
[← Intent Service](intent-service.md) · [Home](index.md) · [Next →](transformers.md)
