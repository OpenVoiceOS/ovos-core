
# ovos-core Documentation

`ovos-core` is the central service of the OpenVoiceOS platform. It manages skill loading, intent parsing, and routes user utterances to the correct skill handler.

## Contents

| Document | Description |
|---|---|
| [architecture.md](architecture.md) | High-level component overview and startup flow |
| [skill-manager.md](skill-manager.md) | `SkillManager` — skill loading, activation, connectivity gating |
| [intent-service.md](intent-service.md) | `IntentService` — utterance handling and pipeline matching |
| [pipeline.md](pipeline.md) | Pipeline configuration, plugin IDs, and ordering |
| [transformers.md](transformers.md) | Utterance, metadata, and intent transformer plugins |
| [converse-fallback.md](converse-fallback.md) | `ConverseService` and `FallbackService` |
| [skill-installer.md](skill-installer.md) | `SkillsStore` — runtime pip install/uninstall via the bus |
| [bus-events.md](bus-events.md) | MessageBus events reference |
| [spec-conformance.md](spec-conformance.md) | Architecture-spec conformance and the `legacy_namespace` transition |

## Quick Start

```bash
pip install ovos-core
ovos-core           # starts SkillManager + IntentService + installer + scheduler
```

Run only the intent service (no skills):
```bash
ovos-intent-service
```

## Entry Points

| Command | Module |
|---|---|
| `ovos-core` | `ovos_core.__main__:main` |
| `ovos-intent-service` | `ovos_core.intent_services.service:launch_standalone` |
| `ovos-skill-installer` | `ovos_core.skill_installer:launch_standalone` |

---

## Dependencies & Related Packages

`ovos-core` depends on and integrates with the following packages in this workspace:

| Package | Role | Docs |
|---|---|---|
| **ovos-messagebus** | WebSocket message broker that all services connect to | [`ovos-messagebus/docs/index.md`](../../ovos-messagebus/docs/index.md) |
| **ovos-bus-client** | `MessageBusClient`, `Message`, `Session` — the bus API | [`ovos-bus-client/docs/index.md`](../../ovos-bus-client/docs/index.md) |
| **ovos-workshop** | `OVOSSkill`, `FallbackSkill`, `PluginSkillLoader` — skill base classes | [`ovos-workshop/docs/index.md`](../../ovos-workshop/docs/index.md) |
| **ovos-plugin-manager** | Entry point discovery (`find_skill_plugins`, `OVOSPipelineFactory`) | [`ovos-plugin-manager/docs/index.md`](../../ovos-plugin-manager/docs/index.md) |
| **ovos-config** | `Configuration` singleton — reads `mycroft.conf` | [`ovos-config/docs/index.md`](../../ovos-config/docs/index.md) |
| **ovos-utils** | `LOG`, `ProcessStatus`, `FileWatcher`, `is_connected_http` | [`ovos-utils/docs/index.md`](../../ovos-utils/docs/index.md) |
| **ovos-dinkum-listener** | Produces `recognizer_loop:utterance` that `IntentService` consumes | [`ovos-dinkum-listener/docs/index.md`](../../ovos-dinkum-listener/docs/index.md) |
| **ovos-audio** | Consumes `mycroft.audio.play_sound` emitted by `IntentService` | [`ovos-audio/docs/index.md`](../../ovos-audio/docs/index.md) |
| **ovos-PHAL** | Emits connectivity events; responds to `ovos.PHAL.internet_check` | [`ovos-PHAL/docs/index.md`](../../ovos-PHAL/docs/index.md) |
| **ovos-gui** | Consumes GUI template events emitted by skills via `GUIInterface` | [`ovos-gui/docs/index.md`](../../ovos-gui/docs/index.md) |

### Skill-writing guide
If you are **writing a skill**, start with [`ovos-workshop/docs/index.md`](../../ovos-workshop/docs/index.md). Skills register via the `opm.skills` entry point — see [`ovos-plugin-manager/docs/plugin-types.md`](../../ovos-plugin-manager/docs/plugin-types.md).

### Pipeline plugin guide
If you are **writing a pipeline plugin**, see [`ovos-plugin-manager/docs/writing-plugins.md`](../../ovos-plugin-manager/docs/writing-plugins.md) and [`pipeline.md`](pipeline.md).
