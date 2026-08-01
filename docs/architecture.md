
# Architecture

## Component Map

```
ovos-messagebus  (WebSocket pub/sub)
      │
      ├── ovos-core  (this repo)
      │     ├── SkillManager          - loads/unloads skill plugins
      │     ├── IntentService         - routes utterances through the pipeline
      │     │     ├── UtteranceTransformersService
      │     │     ├── MetadataTransformersService
      │     │     ├── IntentTransformersService
      │     │     └── Pipeline plugins (Adapt, Padatious, Converse, Fallback, …)
      │     ├── SkillsStore           - runtime pip install/uninstall
      │     └── EventScheduler        - timed bus events
      │
      ├── ovos-dinkum-listener  - STT / wake-word → recognizer_loop:utterance
      ├── ovos-audio            - TTS playback
      ├── ovos-gui              - GUI layer
      └── ovos-PHAL             - hardware/platform plugins
```

## Startup Flow (`ovos-core`)

1. Connect to MessageBus (`MessageBusClient.run_in_thread`)
2. Instantiate `SkillManager` (daemon thread)
   - Optionally starts `IntentService`, `SkillsStore`, `EventScheduler`
3. `SkillManager.run()`:
   a. Wait for `IntentService` to report ready (`mycroft.intents.is_ready`)
   b. Load offline skills (`_load_on_startup`)
   c. Query PHAL for network/internet status → load network/internet skills
   d. Emit `mycroft.skills.initialized`
   e. Loop every 30 s: scan for newly installed skills, call watchdog
4. On exit: unload all skills gracefully, shutdown subsystems

## Subsystem Enable Flags

`SkillManager.__init__` and `main()` accept boolean flags to opt out of subsystems:

| Flag | Subsystem |
|---|---|
| `enable_intent_service` | `IntentService` |
| `enable_installer` | `SkillsStore` |
| `enable_event_scheduler` | `EventScheduler` |
| `enable_skill_api` | `SkillApi.connect_bus` |
| `enable_file_watcher` | Settings file watcher |

CLI equivalents: `--disable-intent-service`, `--disable-installer`, etc.

## Process Status States

Each subsystem publishes its state to the bus via `ProcessStatus`:

```
started → alive → ready → stopping
```

`IntentService` emits `mycroft.intents.is_ready` when it reaches the `ready` state.

---

## Integration Testing

ovos-core's own end-to-end tests live at `test/end2end/` and use **ovoscope**: the OVOS
end-to-end testing framework. Each test spins up a `MiniCroft` (a `SkillManager` subclass backed
by `FakeBus`) with a specific set of skill plugins and asserts on the full bus message sequence
produced by a test utterance.

```
ovos-core/test/end2end/
├── test_adapt.py         # Adapt intent pipeline: match, blacklist, intent blacklist
└── ...                   # additional pipeline tests
```

What the tests cover:

- Intent pipeline routing (`ovos-adapt-pipeline-plugin`, `ovos-padatious-pipeline-plugin`)
- Session-level skill blacklisting (`session.blacklisted_skills`)
- Session-level intent blacklisting (`session.blacklisted_intents`)
- Message ordering and routing context propagation

These tests are the canonical reference for how ovoscope should be used in any OVOS repo.

See [ovoscope/docs/usage-guide.md](../../ovoscope/docs/usage-guide.md) for the full tutorial.

---

## Cross-References

| Component | Package | Documentation |
|---|---|---|
| **MessageBus server** | `ovos-messagebus` | [`ovos-messagebus/docs/server.md`](../../ovos-messagebus/docs/server.md): WebSocket Tornado broker, host/port/SSL config |
| **`MessageBusClient`** | `ovos-bus-client` | [`ovos-bus-client/docs/client.md`](../../ovos-bus-client/docs/client.md): connect, emit, on, `wait_for_response` |
| **`Message`** | `ovos-bus-client` | [`ovos-bus-client/docs/message.md`](../../ovos-bus-client/docs/message.md): structure, routing, context keys |
| **`ProcessStatus`** | `ovos-utils` | [`ovos-utils/docs/process-utils.md`](../../ovos-utils/docs/process-utils.md): state machine, callbacks |
| **`Configuration`** | `ovos-config` | [`ovos-config/docs/configuration.md`](../../ovos-config/docs/configuration.md): config stack, `mycroft.conf` location |
| **`ovos-dinkum-listener`** | `ovos-dinkum-listener` | [`ovos-dinkum-listener/docs/index.md`](../../ovos-dinkum-listener/docs/index.md): produces `recognizer_loop:utterance` |
| **`ovos-audio`** | `ovos-audio` | [`ovos-audio/docs/index.md`](../../ovos-audio/docs/index.md): TTS playback, `mycroft.audio.play_sound` |
| **`ovos-gui`** | `ovos-gui` | [`ovos-gui/docs/architecture.md`](../../ovos-gui/docs/architecture.md): GUI adapter plugin system, site_id routing |
| **`ovos-PHAL`** | `ovos-PHAL` | [`ovos-PHAL/docs/index.md`](../../ovos-PHAL/docs/index.md): connectivity events, `ovos.PHAL.internet_check` |

---
[Home](index.md) · [Next →](skill-manager.md)
