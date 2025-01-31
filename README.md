[![GitHub Discussions](https://img.shields.io/github/discussions/OpenVoiceOS/OpenVoiceOS?label=OVOS%20Discussions)](https://github.com/OpenVoiceOS/OpenVoiceOS/discussions)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE.md)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)
![Unit Tests](https://github.com/OpenVoiceOS/ovos-core/actions/workflows/unit_tests.yml/badge.svg)
[![codecov](https://codecov.io/gh/OpenVoiceOS/ovos-core/branch/dev/graph/badge.svg?token=CS7WJH4PO2)](https://codecov.io/gh/OpenVoiceOS/ovos-core)

# 🗣️ OVOS-core

🌟 **[OpenVoiceOS](https://openvoiceos.org/)** is an open-source platform for smart speakers and other voice-centric devices. 

> `ovos-core` (this repo) is the central component. 

---

## 🚀 Installing OVOS

🛠️ If you have an existing system, we strongly recommend using the [ovos-installer](https://github.com/OpenVoiceOS/ovos-installer) to install OVOS and its dependencies. This tool simplifies installing everything in one go!  

📦 For Raspberry Pi users, the [RaspOVOS](https://github.com/OpenVoiceOS/RaspOVOS) image is a perfect choice. It runs in a "headless" mode (no GUI) and is optimized for Raspberry Pi 3B or higher. 💨 Enjoy even better performance on newer devices!  

🔧 For embedded systems, check out [ovos-buildroot](https://github.com/OpenVoiceOS/ovos-buildroot) – a custom Linux distribution for minimal and efficient setups. Stay tuned for updates!  

📚 More detailed documentation is available in the [ovos-technical-manual](https://openvoiceos.github.io/ovos-technical-manual).  

🎯 Developers can install `ovos-core` standalone via:  
```bash
pip install ovos-core
```  
This includes the core components, perfect for custom assistant development.

---

## 🎛️ Skills

🌟 OVOS is powered by **skills**!  
While some skills come pre-installed, most need to be installed explicitly.  

🔍 Browse OVOS-compatible skills on [PyPI](https://pypi.org/search/?q=ovos-skill-) or explore the [OVOS GitHub organization](https://github.com/orgs/OpenVoiceOS/repositories?language=&q=skill&sort=&type=all).  

🤔 Did you know most classic **Mycroft skills** also work on OVOS?  

🎉 Feel free to share your creative skills with the community!

---

## 🤖 Persona Support  

[ovos-persona](https://github.com/OpenVoiceOS/ovos-persona) can be used to generate responses when skills fail to handle user input

> 💡 With Persona you can connect a LLM to ovos-core

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
1️⃣ Provided by **plugins** (e.g., [OpenAI plugin](https://github.com/OpenVoiceOS/ovos-solver-openai-persona-plugin/pull/12)).  
2️⃣ Created as **user-defined JSON files** in `~/.config/ovos_persona`.  

Personas rely on [solver plugins](https://openvoiceos.github.io/ovos-technical-manual/solvers/), which attempt to answer queries in sequence until a response is found.  

🛠️ **Example:** Using a local OpenAI-compatible server.  

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

Now the `"Salamandra"` persona should be available, the example above is using a demo server, please note no uptime is guaranteed


More details on how to create your personas [here](https://github.com/OpenVoiceOS/OVOS-persona?tab=readme-ov-file#-configuring-personas)

</details>


<details>
  <summary>Pipeline Configuration: Click to expand</summary>


#### Persona Pipeline

Add the persona pipeline to your mycroft.conf **after** the `_high` pipeline matchers

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

## 🤝 Getting Involved

🌍 OVOS is **open source** and thrives on community contributions. Whether you're a coder, designer, or translator, there's a way to contribute!  

🌐 **Translate!** Help improve OVOS in your language through our [Translation Portal](https://gitlocalize.com/users/OpenVoiceOS).  

🙋‍♂️ Have questions or need guidance? Say hi in the [OpenVoiceOS Chat](https://matrix.to/#/!XFpdtmgyCoPDxOMPpH:matrix.org?via=matrix.org), and a team member will be happy to mentor you.  

💡 Join our [Discussions](https://github.com/OpenVoiceOS/OpenVoiceOS/discussions) to ask questions, share ideas, and learn from the community!

---

## 🏆 Credits

The OpenVoiceOS team extends gratitude to the following organizations for their support in our early days:  
- **Mycroft** was a hackable, open-source voice assistant by the now-defunct MycroftAI. OpenVoiceOS continues that work
- [NeonGecko](https://neon.ai)  
- [KDE](https://kde.org) / [Blue Systems](https://blue-systems.com)  

---

## 🔗 Links

- 🛠️ [Release Notes](https://github.com/OpenVoiceOS/ovos-releases)
- 📘 [Technical Manual](https://openvoiceos.github.io/ovos-technical-manual)  
- 💬 [OpenVoiceOS Chat](https://matrix.to/#/!XFpdtmgyCoPDxOMPpH:matrix.org?via=matrix.org)  
- 🌐 [Website](https://openvoiceos.org)  
- 📣 [Open Conversational AI Forums](https://community.openconversational.ai/) (previously Mycroft forums)
```
