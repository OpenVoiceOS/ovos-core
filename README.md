[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE.md) 
![Unit Tests](https://github.com/OpenVoiceOS/ovos-core/actions/workflows/build_tests.yml/badge.svg)
[![codecov](https://codecov.io/gh/OpenVoiceOS/ovos-core/branch/dev/graph/badge.svg?token=CS7WJH4PO2)](https://codecov.io/gh/OpenVoiceOS/ovos-core)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)
[![Chat](https://img.shields.io/matrix/openvoiceos-general:matrix.org)](https://matrix.to/#/#OpenVoiceOS-general:matrix.org)
[![GitHub Discussions](https://img.shields.io/github/discussions/OpenVoiceOS/OpenVoiceOS?label=OVOS%20Discussions)](https://github.com/OpenVoiceOS/OpenVoiceOS/discussions)

# OVOS-core
[OpenVoiceOS](https://openvoiceos.com/) is an open source platform for smart speakers and other voice-centric devices.

[Mycroft](https://mycroft.ai) is a hackable, open source voice assistant by MycroftAI. OVOS-core is a backwards-compatible descendant of [Mycroft-core](https://github.com/MycroftAI/mycroft-core), the central component of Mycroft. It contains extensions and features not present upstream. All Mycroft Skills and Plugins should work normally with OVOS-core. Other Mycroft-based assistants are also believed, but not guaranteed, to be compatible.

The biggest difference between OVOS-core and Mycroft-core is that OVOS-core is fully modular. Furthermore, common components have been repackaged as plugins. That means it isn't just a great assistant on its own, but also a pretty small library!

Furthermore, it offers a number of cli bindings. The old Mycroft shell scripts still exist, and still work, but that stuff is now built into the Python program (docs to follow in the form of `--help`, because it's a lot.)

---

**Installing OVOS-core** (NOTE: at this early stage, required system libs are presumed, and your distribution might be a question mark.)

We suggest you do this in a virtualenv:

`pip install ovos-core[audio-backend,mark1,stt,tts,skills_minimal,skills,default_skills,enclosure,bus,all]`

---

As always, the OpenVoiceOS team thanks the following entities (in addition to MycroftAI) for making certain code and/or manpower resources available to us which may not have been compatible with our practices before:

  - NeonGecko
  - HelloChatterbox
  - KDE (via Blue Systems)

**For now, the rest of this document is part of the README from Mycroft-core.**

## Table of Contents

- [Running Mycroft](#running-mycroft)
- [Using Mycroft](#using-mycroft)
  * [*Home* Device and Account Manager](#home-device-and-account-manager)
  * [Skills](#skills)
- [Behind the scenes](#behind-the-scenes)
  * [Pairing Information](#pairing-information)
  * [Configuration](#configuration)
  * [Using Mycroft Without Home](#using-mycroft-without-home)
  * [API Key Services](#api-key-services)
  * [Using Mycroft behind a proxy](#using-mycroft-behind-a-proxy)
    + [Using Mycroft behind a proxy without authentication](#using-mycroft-behind-a-proxy-without-authentication)
    + [Using Mycroft behind an authenticated proxy](#using-mycroft-behind-an-authenticated-proxy)
- [Getting Involved](#getting-involved)
- [Links](#links)

## Running Mycroft

Mycroft provides `start-mycroft.sh` to perform common tasks. **Note**: MycroftAI's `dev_setup.sh` does not exist in OVOS-core.

Assuming you installed mycroft-core in your home directory, run:
- `cd ~/mycroft-core`
- `./start-mycroft.sh debug`

The "debug" command will start the background services (microphone listener, skill, messagebus, and audio subsystems) as well as bringing up a text-based Command Line Interface (CLI) you can use to interact with Mycroft and see the contents of the various logs. Alternatively you can run `./start-mycroft.sh all` to begin the services without the command line interface.  Later you can bring up the CLI using `./start-mycroft.sh cli`.

The background services can be stopped as a group with:
- `./stop-mycroft.sh`

## Using Mycroft

### *Home* Device and Account Manager
Mycroft AI, Inc. maintains a device and account management system known as Mycroft Home. Developers may sign up at: https://home.mycroft.ai

By default, mycroft-core  is configured to use Home. By saying "Hey Mycroft, pair my device" (or any other request verbal request) you will be informed that your device needs to be paired. Mycroft will speak a 6-digit code which you can enter into the pairing page within the [Mycroft Home site](https://home.mycroft.ai).

Once paired, your unit will use Mycroft API keys for services such as Speech-to-Text (STT), weather and various other skills.

### Skills

Mycroft is nothing without skills.  There are a handful of default skills that are downloaded automatically to your `/opt/mycroft/skills` directory, but most need to be installed explicitly.  See the [Skill Repo](https://github.com/MycroftAI/mycroft-skills#welcome) to discover skills made by others.  Please share your own interesting work!

## Behind the scenes

### Pairing Information
Pairing information generated by registering with Home is stored in:
`~/.config/mycroft/identity/identity2.json` <b><-- DO NOT SHARE THIS WITH OTHERS!</b>

### Configuration
Mycroft's configuration consists of 4 possible locations:
- `mycroft-core/mycroft/configuration/mycroft.conf`(Defaults)
- [Mycroft Home](https://home.mycroft.ai) (Remote)
- `/etc/mycroft/mycroft.conf` (Machine)
- `$XDG_CONFIG_DIR/mycroft/mycroft.conf` (which is by default `$HOME/.config/mycroft/mycroft.conf`) (USER)

When the configuration loader starts, it looks in these locations in this order, and loads ALL configurations. Keys that exist in multiple configuration files will be overridden by the last file to contain the value. This process results in a minimal amount being written for a specific device and user, without modifying default distribution files.

### Using Mycroft Without Home

If you do not wish to use the Mycroft Home service, before starting Mycroft for the first time, create `$HOME/.config/mycroft/mycroft.conf` with the following contents:

```
{
  "skills": {
    "blacklisted_skills": [
      "mycroft-configuration.mycroftai",
      "mycroft-pairing.mycroftai"
    ]
  }
}
```

### API Key Services

The Mycroft backend provides access to a range of API keys for specific services. Without pairing with the Mycroft backend, you will need to add your own API keys, install a different Skill or Plugin to perform that function, or not have access to that functionality.

These are the keys currently used in Mycroft Core through the Mycroft backend:

- [STT API, Google STT, Google Cloud Speech](http://www.chromium.org/developers/how-tos/api-keys)
  - [A range of STT services](https://mycroft-ai.gitbook.io/docs/using-mycroft-ai/customizations/stt-engine) are available for use with Mycroft.
- [Weather Skill API, OpenWeatherMap](http://openweathermap.org/api)
- [Wolfram-Alpha Skill](http://products.wolframalpha.com/api/)


### Using Mycroft behind a proxy

Many schools, universities and workplaces run a `proxy` on their network. If you need to type in a username and password to access the external internet, then you are likely behind a `proxy`.

If you plan to use Mycroft behind a proxy, then you will need to do an additional configuration step.

_NOTE: In order to complete this step, you will need to know the `hostname` and `port` for the proxy server. Your network administrator will be able to provide these details. Your network administrator may want information on what type of traffic Mycroft will be using. We use `https` traffic on port `443`, primarily for accessing ReST-based APIs._

#### Using Mycroft behind a proxy without authentication

If you are using Mycroft behind a proxy without authentication, add the following environment variables, changing the `proxy_hostname.com` and `proxy_port` for the values for your network. These commands are executed from the Linux command line interface (CLI).

```bash
$ export http_proxy=http://proxy_hostname.com:proxy_port
$ export https_port=http://proxy_hostname.com:proxy_port
$ export no_proxy="localhost,127.0.0.1,localaddress,.localdomain.com,0.0.0.0,::1"
```

#### Using Mycroft behind an authenticated proxy

If  you are behind a proxy which requires authentication, add the following environment variables, changing the `proxy_hostname.com` and `proxy_port` for the values for your network. These commands are executed from the Linux command line interface (CLI).

```bash
$ export http_proxy=http://user:password@proxy_hostname.com:proxy_port
$ export https_port=http://user:password@proxy_hostname.com:proxy_port
$ export no_proxy="localhost,127.0.0.1,localaddress,.localdomain.com,0.0.0.0,::1"
```

## Getting Involved

This is an open source project. We would love your help. We have prepared a [contributing](.github/CONTRIBUTING.md) guide to help you get started.

If this is your first PR, or you're not sure where to get started,
say hi in [Mycroft Chat](https://chat.mycroft.ai/) and a team member would be happy to mentor you.
Join the [Mycroft Forum](https://community.mycroft.ai/) for questions and answers.

## Links
* [Creating a Skill](https://mycroft-ai.gitbook.io/docs/skill-development/your-first-skill)
* [Documentation](https://docs.mycroft.ai)
* [Skill Writer API Docs](https://mycroft-core.readthedocs.io/en/master/)
* [Release Notes](https://github.com/MycroftAI/mycroft-core/releases)
* [Mycroft Chat](https://chat.mycroft.ai)
* [Mycroft Forum](https://community.mycroft.ai)
* [Mycroft Blog](https://mycroft.ai/blog)
