[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE.md)
![Unit Tests](https://github.com/OpenVoiceOS/ovos-core/actions/workflows/unit_tests.yml/badge.svg)
[![codecov](https://codecov.io/gh/OpenVoiceOS/ovos-core/branch/dev/graph/badge.svg?token=CS7WJH4PO2)](https://codecov.io/gh/OpenVoiceOS/ovos-core)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)
[![Chat](https://img.shields.io/matrix/openvoiceos-general:matrix.org)](https://matrix.to/#/#OpenVoiceOS-general:matrix.org)
[![GitHub Discussions](https://img.shields.io/github/discussions/OpenVoiceOS/OpenVoiceOS?label=OVOS%20Discussions)](https://github.com/OpenVoiceOS/OpenVoiceOS/discussions)

# OVOS-core

[OpenVoiceOS](https://openvoiceos.org/) is an open source platform for smart speakers and other voice-centric devices.

[Mycroft](https://mycroft.ai) was a hackable, open source voice assistant by the now defunct MycroftAI. OpenVoiceOS continues that work and ovos-core (this repo) is the central component.

All Mycroft Skills and Plugins should work normally with OVOS-core. Other Mycroft-based assistants are also believed, but not guaranteed, to be compatible.

The biggest difference between OVOS-core and Mycroft-core is that OVOS-core is fully modular. Furthermore, common
components have been repackaged as plugins. That means it isn't just a great assistant on its own, but also a pretty
small library!

## Table of Contents

- [Installing OVOS](#installing-ovos)
- [Skills](#skills)
- [Getting Involved](#getting-involved)
- [Links](#links)


## Installing OVOS

We strongly suggest you use the companion project [ovos-installer](https://github.com/OpenVoiceOS/ovos-installer) to install OVOS, several repositories are needed to get the full assistant running

You can find detailed documentation over at the [community-docs](https://openvoiceos.github.io/community-docs) or [ovos-technical-manual](https://openvoiceos.github.io/ovos-technical-manual)

This repo can be installed standalone via `pip install ovos-core`

## Skills

OVOS is nothing without skills. There are a handful of default skills, but most need to be installed explicitly.  

Please share your own interesting work!

## Getting Involved

This is an open source project. We would love your help. We have prepared a [contributing](.github/CONTRIBUTING.md)
guide to help you get started.

If this is your first PR, or you're not sure where to get started,
say hi in [OpenVoiceOS Chat](https://matrix.to/#/!XFpdtmgyCoPDxOMPpH:matrix.org?via=matrix.org) and a team member would
be happy to mentor you.
Join the [Discussions](https://github.com/OpenVoiceOS/OpenVoiceOS/discussions) for questions and answers.

## Credits

the OpenVoiceOS team thanks the following entities (in addition to MycroftAI) for making certain code and/or
manpower resources available to us:

- NeonGecko
- KDE / Blue Systems

## Links

* [Community Documentation](https://openvoiceos.github.io/community-docs)
* [ovos-technical-manual](https://openvoiceos.github.io/ovos-technical-manual)
* [Release Notes](https://github.com/OpenVoiceOS/ovos-core/releases)
* [OpenVoiceOS Chat](https://matrix.to/#/!XFpdtmgyCoPDxOMPpH:matrix.org?via=matrix.org)
* [OpenVoiceOS Website](https://openvoiceos.com/)
* [Open Conversational AI Forums](https://community.openconversational.ai/)  (previously mycroft forums)
