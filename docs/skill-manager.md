
# SkillManager

**Module:** `ovos_core.skill_manager.SkillManager`

`SkillManager` is a daemon `Thread` that owns the full lifecycle of skill plugins: discovery, loading, connectivity-gating, and graceful shutdown.

## Skill Discovery

Skills are Python packages that register themselves via the `opm.skills` entry point group. `ovos-plugin-manager` discovers them with `find_skill_plugins()`, which returns a `{skill_id: SkillClass}` dict.

```python
from ovos_plugin_manager.skills import find_skill_plugins
plugins = find_skill_plugins()
```

## Connectivity Gating

Skills declare their runtime requirements (network/internet/GUI) in their `RuntimeRequirements`. The skill manager only loads a skill when those requirements are met:

| Event | Action |
|---|---|
| Startup (offline) | Load skills with no network/internet requirement |
| `mycroft.network.connected` | Load skills requiring network |
| `mycroft.internet.connected` | Load skills requiring internet |
| `mycroft.gui.available` | Load skills requiring GUI |

Network/internet state is queried from PHAL at startup via `ovos.PHAL.internet_check`; falls back to a direct HTTP check if PHAL is unavailable.

## Loading a Skill

```
find_skill_plugins()
  → _get_plugin_skill_loader(skill_id, skill_class)
    → PluginSkillLoader.load(skill_class)
      → mycroft.skill.loaded (bus event)
```

Each skill gets its own bus connection when `websocket.shared_connection` is `false` in config (isolation from BusBricker-style attacks).

## Blacklisting

Skills listed in `skills.blacklisted_skills` in `mycroft.conf` are skipped at load time. The recommended approach is to uninstall unwanted skills rather than blacklist them.

## Intent Training

After new skills are loaded, the manager requests pipeline re-training:

```
mycroft.skills.train  →  (pipeline plugins train)  →  mycroft.skills.trained
```

Training has a 60-second timeout. On failure, an error is logged but the manager continues.

## Settings File Watcher

When enabled, a `FileWatcher` monitors `~/.config/ovos/skills/*/settings.json`. Any change emits:

```
ovos.skills.settings_changed  {skill_id: "..."}
```

## Bus Events Handled

| Event | Handler |
|---|---|
| `skillmanager.list` | `send_skill_list` |
| `skillmanager.activate` | `activate_skill` |
| `skillmanager.deactivate` | `deactivate_skill` |
| `skillmanager.keep` | `deactivate_except` |
| `mycroft.network.connected` | `handle_network_connected` |
| `mycroft.internet.connected` | `handle_internet_connected` |
| `mycroft.gui.available` | `handle_gui_connected` |
| `mycroft.network.disconnected` | `handle_network_disconnected` |
| `mycroft.internet.disconnected` | `handle_internet_disconnected` |
| `mycroft.gui.unavailable` | `handle_gui_disconnected` |

---

## Cross-References

### Skill discovery & loading
- **`find_skill_plugins()`**: `ovos_plugin_manager.skills.find_skill_plugins` → [`ovos-plugin-manager/docs/plugin-types.md`](../../ovos-plugin-manager/docs/plugin-types.md). Entry point group: `opm.skills`.
- **`PluginSkillLoader`**: `ovos_workshop.skill_launcher.PluginSkillLoader` → [`ovos-workshop/docs/skill-launcher.md`](../../ovos-workshop/docs/skill-launcher.md). Handles load, hot-reload, and settings watching for a single skill.
- **`RuntimeRequirements`**: declared by each skill class to specify `network_before_load`, `internet_before_load`, `requires_gui`. Defined in `ovos-workshop` → [`ovos-workshop/docs/ovos-skill.md`](../../ovos-workshop/docs/ovos-skill.md).

### Writing skills
- Skill base classes (`OVOSSkill`, `FallbackSkill`, `ConversationalSkill`) → [`ovos-workshop/docs/skill-classes.md`](../../ovos-workshop/docs/skill-classes.md).
- Skill resource files (vocab, dialog, locale) → [`ovos-workshop/docs/resource-files.md`](../../ovos-workshop/docs/resource-files.md).
- Skill settings & settings.json → [`ovos-workshop/docs/settings.md`](../../ovos-workshop/docs/settings.md).

### Bus & session
- **`MessageBusClient`**: `ovos_bus_client.client.MessageBusClient` → [`ovos-bus-client/docs/client.md`](../../ovos-bus-client/docs/client.md).
- **Shared vs. isolated bus connections**: `websocket.shared_connection` in `mycroft.conf`. See [`ovos-config/docs/configuration.md`](../../ovos-config/docs/configuration.md).

### Connectivity detection
- **`ovos.PHAL.internet_check`**: emitted by `SkillManager._sync_skill_loading_state()`, answered by the connectivity PHAL plugin → [`ovos-PHAL/docs/index.md`](../../ovos-PHAL/docs/index.md).
- **`is_connected_http()`**: fallback from `ovos_utils.network_utils` → [`ovos-utils/docs/utilities.md`](../../ovos-utils/docs/utilities.md).

### Settings file watcher
- **`FileWatcher`**: `ovos_utils.file_utils.FileWatcher` → [`ovos-utils/docs/utilities.md`](../../ovos-utils/docs/utilities.md).

### Full bus events list
See [`bus-events.md`](bus-events.md) for the complete SkillManager event reference.

---
[← Architecture](architecture.md) · [Home](index.md) · [Next →](intent-service.md)
