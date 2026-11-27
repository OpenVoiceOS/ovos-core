[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
![Unit Tests](https://github.com/OpenVoiceOS/ovos-core/actions/workflows/build_tests.yml/badge.svg)
[![codecov](https://codecov.io/gh/OpenVoiceOS/ovos-core/branch/dev/graph/badge.svg?token=CS7WJH4PO2)](https://codecov.io/gh/OpenVoiceOS/ovos-core)

# ovos-core
<!-- agent-hint
covers: what ovos-core is, how to install it, and where each topic is documented
source: pyproject.toml, ovos_core/__main__.py
generated: no
verify: grep -q 'ovos-core = "ovos_core.__main__:main"' pyproject.toml
see: docs/index.md
-->

`ovos-core` is the skills and intents service of [OpenVoiceOS](https://openvoiceos.org/). It loads the skills, matches each utterance to an intent through an ordered pipeline, and sends the match to the skill that handles it.

## Install

A full assistant needs audio, a listener and a GUI as well. The [ovos-installer](https://github.com/OpenVoiceOS/ovos-installer) and the [RaspOVOS](https://github.com/OpenVoiceOS/RaspOVOS) image install all of them. To install only this service:

```bash
uv pip install --prerelease=allow ovos-core ovos-messagebus
```

## Quickstart

Start the messagebus, then the service:

```bash
ovos-messagebus &
ovos-core
```

```text
INFO - Skills Manager is starting up.
INFO - IntentService is starting up.
INFO - ScheduledEventService started
INFO - IntentService is ready.
INFO - Skills Manager is ready.
```

## Documentation

| Page | What you get there |
| :--- | :--- |
| [docs/index.md](docs/index.md) | The reading order of all pages |
| [docs/install-and-run.md](docs/install-and-run.md) | Install options, extras and the three commands |
| [docs/pipeline.md](docs/pipeline.md) | How to set the order of the intent matchers |
| [docs/personas.md](docs/personas.md) | How to answer with an LLM persona |
| [docs/bus-events.md](docs/bus-events.md) | Each bus message that the service sends or handles |
| [docs/testing.md](docs/testing.md) | How to run the unit and end-to-end tests |

The [technical manual](https://openvoiceos.github.io/ovos-technical-manual) covers the full platform. Ask questions in the [OpenVoiceOS chat](https://matrix.to/#/!XFpdtmgyCoPDxOMPpH:matrix.org?via=matrix.org) or the [discussions](https://github.com/OpenVoiceOS/OpenVoiceOS/discussions). Help translate OVOS on the [translation portal](https://gitlocalize.com/users/OpenVoiceOS).

## Credits

OpenVoiceOS continues the work of Mycroft AI. The team thanks [NeonGecko](https://neon.ai), [KDE](https://kde.org) and [Blue Systems](https://blue-systems.com) for their support.
