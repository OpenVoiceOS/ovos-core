
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

All transformer services load plugins ordered by `priority` (higher number = called first). A priority-1 plugin is last to run and wins over all others — its changes are final.

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
`ovos-dinkum-listener` has its own STT-level transformer stage that runs **before** audio is converted to text. These run post-STT but before `recognizer_loop:utterance` is emitted — distinct from the three transformer stages here. See [`ovos-dinkum-listener/docs/transformers.md`](../../ovos-dinkum-listener/docs/transformers.md).

### Audio-level transformers
`ovos-audio` has TTS and dialog transformer stages that run when TTS is synthesised. See [`ovos-audio/docs/transformers.md`](../../ovos-audio/docs/transformers.md).

### IntentHandlerMatch
- `IntentHandlerMatch` — `ovos_plugin_manager.templates.pipeline.IntentHandlerMatch`. Fields: `match_type`, `match_data`, `skill_id`, `utterance`, `updated_session`. Used by `IntentTransformersService`. See [`ovos-plugin-manager/docs/plugin-types.md`](../../ovos-plugin-manager/docs/plugin-types.md).
