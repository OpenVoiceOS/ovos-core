
# Transformer Plugins

Transformers are loaded by `IntentService` and run on every utterance before pipeline matching begins. There are three transformer stages, each backed by a separate plugin type.

## Stages

### 1. UtteranceTransformersService

**Entry point group:** `opm.utterance_transformer`
**Config key:** `utterance_transformers`

Receives the raw utterance list and may rewrite it. Changes are logged as `utterances transformed: X -> Y`. Use cases: spelling correction, canonicalisation, language normalisation.

```python
utterances, context = utterance_transformers.transform(utterances, context)
```

### 2. MetadataTransformersService

**Entry point group:** `opm.metadata_transformer`
**Config key:** `metadata_transformers`

Receives only `message.context` and may enrich it with additional metadata. Does not alter the utterance text. Use cases: speaker identification, emotion detection, tagging detected language.

```python
context = metadata_transformers.transform(context)
```

### 3. IntentTransformersService

**Entry point group:** `opm.intent_transformer`
**Config key:** `intent_transformers`

Runs after a pipeline match is found. Receives and may modify the `IntentHandlerMatch` object before the reply is emitted. Use cases: entity normalisation, confidence adjustment, adding context to the match.

```python
match = intent_transformers.transform(match)
```

## Plugin Priority

Chains run in **ascending priority order** per OVOS-TRANSFORM §4: a plugin
with `priority = 1` runs first (default 50); later plugins see and may
override earlier plugins' output. An explicit `"order"` list in the config
section wins over priorities; loaded plugins absent from the list do not
run.

The runner services themselves are the canonical implementations from
`ovos_plugin_manager.transformer_services` (re-exported by
`ovos_core.transformers`); they also implement the OVOS-TRANSFORM §8.1
cancellation contract: a plugin returning `"canceled": true` +
`"cancel_reason"` stops the chain, and `handle_utterance` terminates the
lifecycle with `ovos.utterance.cancelled` → `ovos.utterance.handled`.
Full contract → [`ovos-plugin-manager/docs/transformers.md`](../../ovos-plugin-manager/docs/transformers.md).

## Enabling / Disabling Plugins

Each plugin is enabled or disabled in `mycroft.conf` under its service config key:

```json
{
  "utterance_transformers": {
    "ovos-utterance-normalizer": {"active": true},
    "my-custom-transformer": {"active": false}
  }
}
```

A plugin not listed in config is not loaded even if installed.

**Split deployments:** shared servers can run some of these chains too.
`ovos-stt-server` runs utterance transformers on transcripts, and `hivemind-core`
runs utterance and metadata transformers for text clients. Enable each plugin
in exactly one place per deployment, or its effect is applied twice.

---

## Cross-References

### Entry point groups
All three transformer types are discovered via `ovos-plugin-manager`:

| Stage | Entry point group | OPM factory function |
|---|---|---|
| Utterance | `opm.utterance_transformer` | `find_utterance_transformer_plugins()` |
| Metadata | `opm.metadata_transformer` | `find_metadata_transformer_plugins()` |
| Intent | `opm.intent_transformer` | `find_intent_transformer_plugins()` |

→ [`ovos-plugin-manager/docs/plugin-types.md`](../../ovos-plugin-manager/docs/plugin-types.md)

### Writing transformer plugins
- Template base classes live in `ovos_plugin_manager.templates` (utterance_transformers, metadata_transformers, intent_transformers).
- Writing guide → [`ovos-plugin-manager/docs/writing-plugins.md`](../../ovos-plugin-manager/docs/writing-plugins.md).

### Listener-level transformers (distinct from these)
`ovos-dinkum-listener` has its own STT-level transformer stage that runs **before** audio is converted to text. These run post-STT but before `recognizer_loop:utterance` is emitted: distinct from the three transformer stages here. See [`ovos-dinkum-listener/docs/transformers.md`](../../ovos-dinkum-listener/docs/transformers.md).

### Audio-level transformers
`ovos-audio` has TTS and dialog transformer stages that run when TTS is synthesised. See [`ovos-audio/docs/transformers.md`](../../ovos-audio/docs/transformers.md).

### IntentHandlerMatch
- `IntentHandlerMatch`: `ovos_plugin_manager.templates.pipeline.IntentHandlerMatch`. Fields: `match_type`, `match_data`, `skill_id`, `utterance`, `updated_session`. Used by `IntentTransformersService`. See [`ovos-plugin-manager/docs/plugin-types.md`](../../ovos-plugin-manager/docs/plugin-types.md).

---
[← Pipeline](pipeline.md) · [Home](index.md) · [Next →](converse-fallback.md)
