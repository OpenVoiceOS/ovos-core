[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE.md)
![Unit Tests](https://github.com/OpenVoiceOS/ovos-core/actions/workflows/unit_tests.yml/badge.svg)
[![codecov](https://codecov.io/gh/OpenVoiceOS/ovos-core/branch/dev/graph/badge.svg?token=CS7WJH4PO2)](https://codecov.io/gh/OpenVoiceOS/ovos-core)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)
[![Chat](https://img.shields.io/matrix/openvoiceos-general:matrix.org)](https://matrix.to/#/#OpenVoiceOS-general:matrix.org)
[![GitHub Discussions](https://img.shields.io/github/discussions/OpenVoiceOS/OpenVoiceOS?label=OVOS%20Discussions)](https://github.com/OpenVoiceOS/OpenVoiceOS/discussions)

# OVOS-core

[OpenVoiceOS](https://openvoiceos.org/) is an open source platform for smart speakers and other voice-centric devices.

[Mycroft](https://mycroft.ai) is a hackable, open source voice assistant by MycroftAI. OVOS-core is a
backwards-compatible descendant of [Mycroft-core](https://github.com/MycroftAI/mycroft-core), the central component of
Mycroft. It contains extensions and features not present upstream. All Mycroft Skills and Plugins should work normally
with OVOS-core. Other Mycroft-based assistants are also believed, but not guaranteed, to be compatible.

The biggest difference between OVOS-core and Mycroft-core is that OVOS-core is fully modular. Furthermore, common
components have been repackaged as plugins. That means it isn't just a great assistant on its own, but also a pretty
small library!

Furthermore, it offers a number of cli bindings. The old Mycroft shell scripts still exist, and still work, but that
stuff is now built into the Python program (docs to follow in the form of `--help`, because it's a lot.)

---

**Installing OVOS-core** (NOTE: at this early stage, required system libs are presumed, and your distribution might be a
question mark.)

We suggest you do this in a virtualenv:

`pip install ovos-core[mycroft]`

---

As always, the OpenVoiceOS team thanks the following entities (in addition to MycroftAI) for making certain code and/or
manpower resources available to us which may not have been compatible with our practices before:

- NeonGecko
- KDE
- Blue Systems

## Table of Contents

- [Running Mycroft](#running-mycroft)
- [Skills](#skills)
- [Getting Involved](#getting-involved)
- [Links](#links)

You can find detailed documentation over at the [community-docs](https://openvoiceos.github.io/community-docs) or [ovos-technical-manual](https://openvoiceos.github.io/ovos-technical-manual)

## Skills

Mycroft is nothing without skills. There are a handful of default skills, but most need to be installed explicitly.  
See the [Skill Repo](https://github.com/MycroftAI/mycroft-skills#welcome) to discover skills made by others.  
Please share your own interesting work!

## Getting Involved

This is an open source project. We would love your help. We have prepared a [contributing](.github/CONTRIBUTING.md)
guide to help you get started.

If this is your first PR, or you're not sure where to get started,
say hi in [OpenVoiceOS Chat](https://matrix.to/#/!XFpdtmgyCoPDxOMPpH:matrix.org?via=matrix.org) and a team member would
be happy to mentor you.
Join the [Discussions](https://github.com/OpenVoiceOS/OpenVoiceOS/discussions) for questions and answers.

## Links

* [Community Documentation](https://openvoiceos.github.io/community-docs)
* [ovos-technical-manual](https://openvoiceos.github.io/ovos-technical-manual)
* [Release Notes](https://github.com/OpenVoiceOS/ovos-core/releases)
* [Mycroft Documentation](https://docs.mycroft.ai)
* [Mycroft API Docs](https://mycroft-core.readthedocs.io/en/master/)
* [OpenVoiceOS Chat](https://matrix.to/#/!XFpdtmgyCoPDxOMPpH:matrix.org?via=matrix.org)
* [OpenVoiceOS Website](https://openvoiceos.com/)
* [Mycroft Chat](https://chat.mycroft.ai)
* [Mycroft Forum](https://community.mycroft.ai)
* [Mycroft Blog](https://mycroft.ai/blog)
