# Install and run
<!-- agent-hint
covers: how to install ovos-core, which extras exist, and which commands start which services
source: pyproject.toml ([project.scripts], [project.optional-dependencies]), ovos_core/__main__.py
generated: no
verify: grep -q 'ovos-skill-installer = "ovos_core.skill_installer:launch_standalone"' pyproject.toml
see: architecture.md
-->

This page tells you how to install `ovos-core` and how to start each of its services.

## Example

```bash
uv venv && uv pip install --prerelease=allow ovos-core ovos-messagebus
ovos-messagebus &
ovos-core
```

```text
INFO - Skills Manager is starting up.
INFO - IntentService is starting up.
INFO - ScheduledEventService started
INFO - IntentService is ready.
INFO - Skills Manager is ready.
INFO - ovos-core is ready! additional skills can now be loaded
```

## Steps

1. Install a complete assistant with the [ovos-installer](https://github.com/OpenVoiceOS/ovos-installer). On a Raspberry Pi 3B or higher, you can use the [RaspOVOS](https://github.com/OpenVoiceOS/RaspOVOS) image. For a minimal embedded system, use [ovos-buildroot](https://github.com/OpenVoiceOS/ovos-buildroot).
2. To develop on `ovos-core` alone, install the package with uv, as in the example.
3. Start `ovos-messagebus` first. Every service connects to it.
4. Start `ovos-core`. It runs the skill manager, the intent service, the skill installer and the event scheduler in one process.
5. Install skills. Find them on [PyPI](https://pypi.org/search/?q=ovos-skill-) or in the [OpenVoiceOS organization](https://github.com/orgs/OpenVoiceOS/repositories?q=skill). The skill manager loads an installed skill without a restart. See [skill-manager.md](skill-manager.md) and [skill-installer.md](skill-installer.md).

## Reference

### Commands

| Command | Module | Starts |
| :--- | :--- | :--- |
| `ovos-core` | `ovos_core.__main__:main` | Skill manager, intent service, skill installer, event scheduler |
| `ovos-intent-service` | `ovos_core.intent_services.service:launch_standalone` | The intent service only, with no skills |
| `ovos-skill-installer` | `ovos_core.skill_installer:launch_standalone` | The skill installer only |

### Flags of `ovos-core`

Each part runs by default. A flag stops one part. The flags work only when you start the service with `python -m ovos_core`. The `ovos-core` command ignores them: [#1045](https://github.com/OpenVoiceOS/ovos-core/issues/1045).

| Flag | Stops |
| :--- | :--- |
| `--disable-intent-service` | The intent service. Use it when `ovos-intent-service` runs in its own process. |
| `--disable-installer` | The skill installer |
| `--disable-event-scheduler` | The bus event scheduler |
| `--disable-skill-api` | The skill bus API: the services that skills give to other skills |
| `--disable-file-watcher` | The watcher that sends `ovos.skills.settings_changed` when the `settings.json` of a skill changes |

### Extras

| Extra | Adds |
| :--- | :--- |
| `mycroft` | PHAL, audio, GUI, messagebus and the dinkum listener: an assistant that listens and speaks |
| `plugins` | Utterance transformers, translation, number and date parsers, and pipeline plugins |
| `skills-essential` | A base set of skills, such as date and time, alerts and the "I do not understand" fallback |
| `skills-<group>` | Skill sets by topic (`extra`, `audio`, `desktop`, `internet`, `gui`, `media`) or by language (`ca`, `pt`, `gl`, `en`) |
| `test` | The test tools, the demo skills and the pipeline plugins that the tests load |

`pyproject.toml` lists each package of each extra. Install an extra with `uv pip install --prerelease=allow "ovos-core[mycroft]"`.

---
[Home](index.md) · [Next →](architecture.md)
