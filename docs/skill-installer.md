
# Skill Installer (SkillsStore)

**Module:** `ovos_core.skill_installer.SkillsStore`

`SkillsStore` provides runtime skill and package management via the MessageBus. It is enabled by default in `ovos-core` but can be disabled with `--disable-installer`.

## pip Backend

`SkillsStore` uses `uv pip` if `uv` is on `$PATH` (default in raspOVOS); otherwise falls back to `pip`. A named lock (`ovos_pip.lock`) prevents concurrent installs.

```python
SkillsStore.UV = shutil.which("uv")  # None if not available
```

## Constraints

All installs use a constraints file to avoid dependency conflicts. The default constraints file is fetched from:

```
https://raw.githubusercontent.com/OpenVoiceOS/ovos-releases/refs/heads/main/constraints-stable.txt
```

A custom URL can be set in config under `skills.installer.constraints`.

## Configuration

```json
{
  "skills": {
    "installer": {
      "constraints": "https://...",
      "sounds": {
        "pip_error": "snd/error.mp3",
        "pip_success": "snd/acknowledge.mp3"
      }
    }
  }
}
```

Pip installs can be disabled entirely by not enabling the installer subsystem (default in `--disable-installer` mode).

## Bus Events

### Install a skill

```
ovos.skills.install
  data: {
    "packages": ["ovos-skill-foo"],   # pip package names or URLs
    "constraints": "https://..."      # optional override
  }
  → ovos.skills.install.complete  (success)
  → ovos.skills.install.failed    (error)
```

### Uninstall a skill

```
ovos.skills.uninstall
  data: {"packages": ["ovos-skill-foo"]}
  → ovos.skills.uninstall.complete
  → ovos.skills.uninstall.failed
```

### Install arbitrary Python packages

```
ovos.pip.install
  data: {"packages": ["some-lib>=1.0"]}
```

### Uninstall arbitrary Python packages

```
ovos.pip.uninstall
  data: {"packages": ["some-lib"]}
```

After a successful skill install, `ovos-plugin-manager`'s entry point cache is reloaded so the new skill is discovered on the next `SkillManager` scan cycle (every 30 s).

## Error Types

| `InstallError` | Meaning |
|---|---|
| `DISABLED` | pip disabled in config |
| `PIP_ERROR` | subprocess returned non-zero |
| `BAD_URL` | URL validation failed |
| `NO_PKGS` | empty package list |

---

## Cross-References

### Constraints file source
Default constraints are served from **`ovos-releases`** — the workspace repo that manages stable/testing/alpha constraint channels. See [`ovos-releases`](../../ovos-releases) for the constraints file format. Custom constraints can point to any HTTP URL or local path (`skills.installer.constraints` in `mycroft.conf`).

### Entry point cache reload
After a successful install, `ovos_plugin_manager` is reloaded via `importlib.reload(ovos_plugin_manager)` to pick up new entry points. The `SkillManager` scan loop (every 30 s) then discovers and loads the new skill. See [`ovos-plugin-manager/docs/index.md`](../../ovos-plugin-manager/docs/index.md).

### `uv` acceleration
`uv` is a fast pip-compatible installer. It is the default in **raspOVOS**. If `uv` is on `$PATH`, `SkillsStore.UV` is set and `uv pip install` is used instead of `pip`. See the [uv documentation](https://github.com/astral-sh/uv) for setup.

### Configuration
Config is read from `mycroft.conf` via `ovos_config.config.Configuration` → [`ovos-config/docs/configuration.md`](../../ovos-config/docs/configuration.md).

### Security note
`validate_skill()` currently only checks for the `https://github.com/` prefix. See [`SUGGESTIONS.md`](../SUGGESTIONS.md) entry S-003 for the proposed full validation (class compatibility, legacy Mycroft checks).

### Full bus events list
See [`bus-events.md`](bus-events.md) for the complete SkillsStore event reference.
