[![GitHub Discussions](https://img.shields.io/github/discussions/OpenVoiceOS/OpenVoiceOS?label=OVOS%20Discussions)](https://github.com/OpenVoiceOS/OpenVoiceOS/discussions)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)
![Unit Tests](https://github.com/OpenVoiceOS/ovos-core/actions/workflows/unit_tests.yml/badge.svg)
[![codecov](https://codecov.io/gh/OpenVoiceOS/ovos-core/branch/dev/graph/badge.svg?token=CS7WJH4PO2)](https://codecov.io/gh/OpenVoiceOS/ovos-core)

# OVOS-core

[OpenVoiceOS](https://openvoiceos.org/) is an open-source platform for smart speakers and other voice-centric devices. `ovos-core` (this repo) is the central component.

---

## Installing OVOS

If you have an existing system, use the [ovos-installer](https://github.com/OpenVoiceOS/ovos-installer) to install OVOS and its dependencies in one step.

For Raspberry Pi users, the [RaspOVOS](https://github.com/OpenVoiceOS/RaspOVOS) image runs in headless mode (no GUI) and targets Raspberry Pi 3B or higher.

For embedded systems, [ovos-buildroot](https://github.com/OpenVoiceOS/ovos-buildroot) builds a custom Linux distribution for minimal setups.

More detailed documentation is available in the [ovos-technical-manual](https://openvoiceos.github.io/ovos-technical-manual) and in [`docs/`](docs/index.md). See [docs/prerelease-quirks.md](docs/prerelease-quirks.md) for what changed since the last stable release.

Developers can install `ovos-core` standalone:

```bash
pip install ovos-core
```

This includes the core components, for custom assistant development.

---

## Skills

OVOS is powered by skills. Some skills come pre-installed; most need to be installed explicitly.

Browse OVOS-compatible skills on [PyPI](https://pypi.org/search/?q=ovos-skill-) or in the [OVOS GitHub organization](https://github.com/orgs/OpenVoiceOS/repositories?language=&q=skill&sort=&type=all).

Most classic Mycroft skills also work on OVOS.

---

## Persona Support

[ovos-persona](https://github.com/OpenVoiceOS/ovos-persona) generates responses when skills fail to handle user input. With Persona you can connect an LLM to `ovos-core`.

**List Personas**

- "What personas are available?"
- "Can you list the personas?"
- "What personas can I use?"

**Activate a Persona**

- "Connect me to {persona}"
- "Enable {persona}"
- "Start a conversation with {persona}"
- "Let me chat with {persona}"

**Stop Conversation**

- "Stop the interaction"
- "Terminate persona"
- "Deactivate Large Language Model"

<details>
  <summary>Creating a Persona: Click to expand</summary>

#### Persona Files

Personas are configured using JSON files. These can be:

1. Provided by plugins (for example, the [OpenAI plugin](https://github.com/OpenVoiceOS/ovos-solver-openai-persona-plugin/pull/12)).
2. Created as user-defined JSON files in `~/.config/ovos_persona`.

Personas rely on [solver plugins](https://openvoiceos.github.io/ovos-technical-manual/solvers/), which try to answer queries in sequence until a response is found.

**Example:** using a local OpenAI-compatible server.

Save this in `~/.config/ovos_persona/salamandra.json`:

```json
{
  "name": "Salamandra",
  "solvers": [
    "ovos-solver-openai-persona-plugin"
  ],
  "ovos-solver-openai-persona-plugin": {
    "api_url": "https://ollama.uoi.io/v1",
    "model": "hdnh2006/salamandra-7b-instruct",
    "key": "sk-xxxx",
    "persona": "helpful, creative, clever, and very friendly."
  }
}
```

The `"Salamandra"` persona is now available. The example above uses a demo server; no uptime is guaranteed.

More details on how to create your personas are in the [OVOS-persona README](https://github.com/OpenVoiceOS/OVOS-persona?tab=readme-ov-file#-configuring-personas).

</details>

<details>
  <summary>Pipeline Configuration: Click to expand</summary>

#### Persona Pipeline

Add the persona pipeline to your `mycroft.conf` after the `_high` pipeline matchers.

```json
{
  "intents": {
      "persona": {"handle_fallback":  true},
      "pipeline": [
          "stop_high",
          "converse",
          "ocp_high",
          "padatious_high",
          "adapt_high",
          "ovos-persona-pipeline-plugin-high",
          "ocp_medium",
          "fallback_high",
          "stop_medium",
          "adapt_medium",
          "padatious_medium",
          "adapt_low",
          "common_qa",
          "fallback_medium",
          "ovos-persona-pipeline-plugin-low",
          "fallback_low"
    ]
  }
}
```

</details>

---

## Getting Involved

OVOS is open source and depends on community contributions. There is a way to contribute as a coder, designer, or translator.

Help translate OVOS into your language through our [Translation Portal](https://gitlocalize.com/users/OpenVoiceOS).

Have questions or need guidance? Say hi in the [OpenVoiceOS Chat](https://matrix.to/#/!XFpdtmgyCoPDxOMPpH:matrix.org?via=matrix.org), and a team member will help.

Join our [Discussions](https://github.com/OpenVoiceOS/OpenVoiceOS/discussions) to ask questions and share ideas.

---

## Credits

The OpenVoiceOS team thanks the following organizations for their support in our early days:

- **Mycroft** was a hackable, open-source voice assistant by the now-defunct MycroftAI. OpenVoiceOS continues that work.
- [NeonGecko](https://neon.ai)
- [KDE](https://kde.org) / [Blue Systems](https://blue-systems.com)

---

## Links

- [Release Notes](https://github.com/OpenVoiceOS/ovos-releases)
- [Technical Manual](https://openvoiceos.github.io/ovos-technical-manual)
- [OpenVoiceOS Chat](https://matrix.to/#/!XFpdtmgyCoPDxOMPpH:matrix.org?via=matrix.org)
- [Website](https://openvoiceos.org)
- [Open Conversational AI Forums](https://community.openconversational.ai/) (previously Mycroft forums)
