# SkillManager
<!-- agent-hint
covers: how SkillManager finds, loads, gates and unloads skills
source: ovos_core/skill_manager.py:SkillManager
generated: no
verify: python3 docs/check_page.py docs/skill-manager.md opm.skills
see: intent-service.md
-->

**Module:** `ovos_core.skill_manager.SkillManager`

`SkillManager` is a daemon `Thread` that owns the full lifecycle of skill plugins: discovery, loading, connectivity-gating, and graceful shutdown.

## Skill Discovery

Skills are Python packages that register themselves via the `opm.skills` entry point group. `ovos-plugin-manager` discovers them with `find_skill_plugins()`, which returns a `{skill_id: SkillClass}` dict.

```python
from ovos_plugin_manager.skills import find_skill_plugins
plugins = find_skill_plugins()
```

## Connectivity Gating

By default, the skill manager loads all skills at startup, with no gate. Set `skills.use_deferred_loading` to `true` in `mycroft.conf` to load each skill only when the network, internet or GUI that its `RuntimeRequirements` declare is available:

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

The skill manager does not load a skill whose ID is in `skills.blacklisted_skills` in `mycroft.conf`. To remove a skill for all users, uninstall it.

## Startup checks

- When no skill is installed, the log shows `No installed skills detected!`. Ignore it when the skills run in their own process. Otherwise, install skills.
- The skill manager waits for the intent service before it loads skills. After `skills.intent_service_timeout` seconds (default 300), it raises `RuntimeError: IntentService did not become ready within 300 seconds`.

## Intent Training

After new skills are loaded, the manager requests pipeline re-training:

```
mycroft.skills.train  →  (pipeline plugins train)
```

The request has no reply. The manager does not wait for the training to finish.

## Loading After an Install

The periodic scan is not the only way a newly installed skill gets loaded. `SkillsStore` reloads `ovos-plugin-manager` before it reports a completed install, so the manager runs the same discovery pass as soon as it sees that report:

```
ovos.skills.install.complete  →  _load_new_skills()
ovos.pip.install.complete     →  _load_new_skills()
```

A caller that wants to drive this explicitly sends `skillmanager.rescan`; the response names what that pass loaded, so a caller can tell a fresh load from a pass that loaded nothing:

```
skillmanager.rescan  →  skillmanager.rescan.response  {"loaded": ["skill-id", ...]}
```

Both paths apply the same connectivity gating as the scan, and both wait until the manager is ready: before the startup load has run, they do nothing and leave the new skill to that load. The 30 s scan remains the backstop.

## Unloading After an Uninstall

`SkillsStore` reloads `ovos-plugin-manager` before it reports a completed uninstall, so `find_skill_plugins()` no longer returns the removed package. On that report the manager compares the loaded plugin skills with what is still discoverable and shuts down every one that is gone:

```
ovos.skills.uninstall.complete  →  _unload_undiscoverable_plugin_skills()
ovos.pip.uninstall.complete     →  _unload_undiscoverable_plugin_skills()
```

The unloaded id is also dropped from the load-retry bookkeeping, so a later reinstall loads again on the next pass. Discovery is not trusted unconditionally: if it raises, nothing is unloaded and no bookkeeping is cleared.

`find_skill_plugins()` reports what it could *import* and swallows the error when an import fails, so a skill whose package is present but whose import broke is missing from the result in exactly the same way as an uninstalled one. What the installed packages still *declare* separates those two, and it is read from entry point metadata without importing anything, so it is read on every pass and the two sets are used together: a skill is gone only when it is neither importable nor declared. Unloading on an import failure would shut a still-installed skill down and discard its loader, and the next pass would load it again.

Metadata that cannot be read at all is "cannot tell", and nothing is unloaded. When nothing imports but entry points are still declared, every skill is kept and a warning is logged.

Counting loaded skills cannot answer this, because one distribution may expose several skill entry points: uninstalling a single package can legitimately empty discovery with several skills loaded.

The removal list and the loader instances behind it are taken under the same lock, and each shutdown runs outside it, so a replacement loaded for one of those ids by an overlapping pass is never the one shut down.

A skill still inside `loader.load()` when the report lands is not tracked yet, so the pass has no loader to detach for it. It records the verdict against that id instead, and the load honours it on the way out: the loader is shut down and never tracked, rather than the finished load reviving a package that is already gone. Such a load is never announced on `mycroft.skill.loaded` either, since it was never available. The verdict is spent on the one load it was recorded against, so a reinstall that reserves the id afresh loads normally. `skillmanager.deactivate` only silences a skill; this is what removes it.

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
| `skillmanager.rescan` | `handle_rescan_request` |
| `ovos.skills.install.complete` | `handle_install_complete` |
| `ovos.pip.install.complete` | `handle_install_complete` |
| `ovos.skills.uninstall.complete` | `handle_uninstall_complete` |
| `ovos.pip.uninstall.complete` | `handle_uninstall_complete` |
| `mycroft.network.connected` | `handle_network_connected` |
| `mycroft.internet.connected` | `handle_internet_connected` |
| `mycroft.gui.available` | `handle_gui_connected` |
| `mycroft.network.disconnected` | `handle_network_disconnected` |
| `mycroft.internet.disconnected` | `handle_internet_disconnected` |
| `mycroft.gui.unavailable` | `handle_gui_disconnected` |

---

## Cross-References

### Skill discovery & loading
- **`find_skill_plugins()`**: `ovos_plugin_manager.skills.find_skill_plugins` → [`ovos-plugin-manager/docs/plugin-types.md`](https://github.com/OpenVoiceOS/ovos-plugin-manager/blob/dev/docs/plugin-types.md). Entry point group: `opm.skills`.
- **`PluginSkillLoader`**: `ovos_workshop.skill_launcher.PluginSkillLoader` → [`ovos-workshop/docs/skill-launcher.md`](https://github.com/OpenVoiceOS/ovos-workshop/blob/dev/docs/skill-launcher.md). Handles load, hot-reload, and settings watching for a single skill.
- **`RuntimeRequirements`**: declared by each skill class to specify `network_before_load`, `internet_before_load`, `requires_gui`. Defined in `ovos-workshop` → [`ovos-workshop/docs/ovos-skill.md`](https://github.com/OpenVoiceOS/ovos-workshop/blob/dev/docs/ovos-skill.md).

### Writing skills
- Skill base classes (`OVOSSkill`, `FallbackSkill`, `ConversationalSkill`) → [`ovos-workshop/docs/skill-classes.md`](https://github.com/OpenVoiceOS/ovos-workshop/blob/dev/docs/skill-classes.md).
- Skill resource files (vocab, dialog, locale) → [`ovos-workshop/docs/resource-files.md`](https://github.com/OpenVoiceOS/ovos-workshop/blob/dev/docs/resource-files.md).
- Skill settings & settings.json → [`ovos-workshop/docs/settings.md`](https://github.com/OpenVoiceOS/ovos-workshop/blob/dev/docs/settings.md).

### Bus & session
- **`MessageBusClient`**: `ovos_bus_client.client.MessageBusClient` → [`ovos-bus-client/docs/client.md`](https://github.com/OpenVoiceOS/ovos-bus-client/blob/dev/docs/client.md).
- **Shared vs. isolated bus connections**: `websocket.shared_connection` in `mycroft.conf`. See [`ovos-config/docs/configuration.md`](https://github.com/OpenVoiceOS/ovos-config).

### Connectivity detection
- **`ovos.PHAL.internet_check`**: emitted by `SkillManager._sync_skill_loading_state()`, answered by the connectivity PHAL plugin → [`ovos-PHAL/docs/index.md`](https://github.com/OpenVoiceOS/ovos-PHAL).
- **`is_connected_http()`**: fallback from `ovos_utils.network_utils` → [`ovos-utils/docs/utilities.md`](https://github.com/OpenVoiceOS/ovos-utils/blob/dev/docs/utilities.md).

### Settings file watcher
- **`FileWatcher`**: `ovos_utils.file_utils.FileWatcher` → [`ovos-utils/docs/utilities.md`](https://github.com/OpenVoiceOS/ovos-utils/blob/dev/docs/utilities.md).

### Full bus events list
See [`bus-events.md`](bus-events.md) for the complete SkillManager event reference.

---
[← Architecture](architecture.md) · [Home](index.md) · [Next →](intent-service.md)
