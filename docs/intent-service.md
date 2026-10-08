
# IntentService

**Module:** `ovos_core.intent_services.service.IntentService`

`IntentService` is the utterance router. It receives `recognizer_loop:utterance` messages from the listener and walks the configured pipeline until a skill claims the utterance.

## Utterance Handling Flow

```
recognizer_loop:utterance
  │
  ├── UtteranceTransformersService.transform()   # may rewrite utterance text
  ├── MetadataTransformersService.transform()    # may enrich context
  ├── disambiguate_lang()                        # pick the best language
  ├── _validate_session()                        # get/create Session
  │
  └── for each pipeline stage (in order):
        match_func(utterances, lang, message)
          ├── match found → _emit_match_message() → skill intent handler
          └── no match   → next stage
              (all stages fail) → send_complete_intent_failure()
```

## Language Disambiguation

Language is chosen by priority from message context keys:

1. `stt_lang`: language used by STT to transcribe
2. `request_lang`: volunteered by the source (e.g. wake word)
3. `detected_lang`: detected by a transformer plugin
4. Config default / `message.data["lang"]`

The chosen language is validated against `valid_langs` from config using `langcodes.closest_match` (max distance 10). Invalid tags fall through to the next candidate.

## Multilingual Matching

When `intents.multilingual_matching` is `true` in config, if the primary language produces no match, all other configured languages are tried in order.

## Session Management

Each utterance is associated with a `Session`. The default session expires and is reset automatically. Non-default sessions (e.g. from HiveMind clients) are updated but not reset. Session state (active skills, pipeline, blacklists) is serialised into every reply message under `context.session`.

## Intent Match Emission

When a pipeline stage returns a match (`IntentHandlerMatch`):

1. `IntentTransformersService.transform(match)`: post-process the match
2. Build a reply message with `match.match_type` as the message type
3. Activate the skill in the session (`sess.activate_skill(skill_id)`)
   - Skipped if the skill called `self.deactivate()` during this turn
4. Emit `{skill_id}.activate` for the skill's callback
5. Emit the reply: the skill's intent handler receives it

## Intent Query API

External tools can query the pipeline without triggering a skill:

```
intent.service.intent.get  {utterance: "...", lang: "..."}
  → intent.service.intent.reply  {intent: {...} | null, utterance: "..."}
```

## Context Management

| Event | Effect |
|---|---|
| `add_context` | Inject entity into legacy frame-based session context |
| `remove_context` | Remove named context entity (legacy frames) |
| `clear_context` | Clear all context entities (legacy frames) |
| `ovos.session.sync` | OVOS-CONTEXT-1 §5.3 — handled by `SessionManager.handle_session_sync`, which merges `session.intent_context` entry-by-entry. `IntentService` does not subscribe to this event |

### OVOS-CONTEXT-1 intent context

The orchestrator implements the flat, decaying `session.intent_context`
key/value store defined by **OVOS-CONTEXT-1**. `SessionManager` owns the
map (carries it on every `Session`, applies the §5.3 `ovos.session.sync`
merge); `IntentService` applies the §4 decay lifecycle each match round
and provides the §6/§6.1 gating + §7 slot-fill as an orchestrator backstop
— matcher plugins are expected to apply these themselves via the shared
`ovos_spec_tools.context` helpers.

## Open Data / Metrics Upload

If `open_data.intent_urls` is configured, intent match results (utterance, intent type, lang, match data) are `POST`ed to each URL in a background thread. This is opt-in and has no default server.

## Bus Events Handled

`IntentService` itself subscribes to:

| Event | Handler |
|---|---|
| `recognizer_loop:utterance` | `handle_utterance` |
| `add_context` | `handle_add_context` |
| `remove_context` | `handle_remove_context` |
| `clear_context` | `handle_clear_context` |
| `intent.service.intent.get` | `handle_get_intent` |
| `intent.service.skills.deactivate` | `_handle_deactivate` |
| `intent.service.pipelines.reload` | `handle_reload_pipelines` |

`ovos.session.sync` is handled by `SessionManager.handle_session_sync` (bus-client), not by `IntentService` — see [Context Management](#context-management) above.

---

## Cross-References

### Upstream: who produces `recognizer_loop:utterance`
- **`ovos-dinkum-listener`**: the voice input daemon. Runs the wakeword → STT pipeline and emits `recognizer_loop:utterance`. See [`ovos-dinkum-listener/docs/voice-loop.md`](../../ovos-dinkum-listener/docs/voice-loop.md) for the FSM states and [`ovos-dinkum-listener/docs/transformers.md`](../../ovos-dinkum-listener/docs/transformers.md) for STT-level transformers (distinct from the intent-level transformers here).

### Sessions
- **`Session`**: `ovos_bus_client.session.Session` → [`ovos-bus-client/docs/session.md`](../../ovos-bus-client/docs/session.md). Stores `active_skills`, `pipeline`, `context`, `lang`, `site_id`, `blacklisted_skills`, `blacklisted_intents`.
- **`SessionManager`**: `ovos_bus_client.session.SessionManager` → same file. Singleton registry; `SessionManager.get(message)` resolves the session from message context.
- **`IntentContextManager`**: `ovos_bus_client.session.IntentContextManager` → used by the Adapt pipeline for entity context injection via `add_context` / `remove_context` events.

### Pipeline plugins
- **`OVOSPipelineFactory`**: `ovos_plugin_manager.pipeline.OVOSPipelineFactory` → [`ovos-plugin-manager/docs/plugin-types.md`](../../ovos-plugin-manager/docs/plugin-types.md). Discovers and loads all `opm.pipeline` entry points.
- **`ConfidenceMatcherPipeline`** / **`PipelinePlugin`**: base classes in `ovos_plugin_manager.templates.pipeline`. Plugins extending `ConfidenceMatcherPipeline` must implement `match_high`, `match_medium`, `match_low`.
- Pipeline configuration and stage names → [`pipeline.md`](pipeline.md).

### Transformer plugins
- Three transformer stages run before pipeline matching → [`transformers.md`](transformers.md).
- Entry point groups: `opm.utterance_transformer`, `opm.metadata_transformer`, `opm.intent_transformer` → [`ovos-plugin-manager/docs/plugin-types.md`](../../ovos-plugin-manager/docs/plugin-types.md).

### Language handling
- **`get_valid_languages()`**: `ovos_config.locale.get_valid_languages` → [`ovos-config/docs/configuration.md`](../../ovos-config/docs/configuration.md). Returns the list of enabled languages from `mycroft.conf`.
- **`langcodes.closest_match`**: third-party `langcodes` library; used in `disambiguate_lang()` to validate language tags against enabled languages.

### Metrics / Open Data
- **`ovos-opendata-server`**: optional companion server for intent metrics collection. Configure `open_data.intent_urls` in `mycroft.conf` to enable upload. See [`ovos-opendata-server`](../../ovos-opendata-server) repo.

### Full bus events list
See [`bus-events.md`](bus-events.md) for the complete IntentService event reference.

---
[← Skill Manager](skill-manager.md) · [Home](index.md) · [Next →](pipeline.md)
