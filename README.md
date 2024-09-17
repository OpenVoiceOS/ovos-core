[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE.md)
![Unit Tests](https://github.com/OpenVoiceOS/ovos-core/actions/workflows/unit_tests.yml/badge.svg)
[![codecov](https://codecov.io/gh/OpenVoiceOS/ovos-core/branch/dev/graph/badge.svg?token=CS7WJH4PO2)](https://codecov.io/gh/OpenVoiceOS/ovos-core)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](http://makeapullrequest.com)
[![Chat](https://img.shields.io/matrix/openvoiceos-general:matrix.org)](https://matrix.to/#/#OpenVoiceOS-general:matrix.org)
[![GitHub Discussions](https://img.shields.io/github/discussions/OpenVoiceOS/OpenVoiceOS?label=OVOS%20Discussions)](https://github.com/OpenVoiceOS/OpenVoiceOS/discussions)

# OVOS-core

[OpenVoiceOS](https://openvoiceos.org/) is an open source platform for smart speakers and other voice-centric devices.

[Mycroft](https://mycroft.ai) was a hackable, open source voice assistant by the now defunct MycroftAI. OpenVoiceOS continues that work and ovos-core (this repo) is the central component.

All Mycroft Skills and Plugins should work normally with OVOS-core, with the exception of Common Play and other media-related skills. Other Mycroft-based assistants are also believed, but not guaranteed, to be compatible.

The biggest difference between OVOS-core and Mycroft-core is that OVOS-core is fully modular. Furthermore, common
components have been repackaged as plugins. That means it isn't just a great assistant on its own, but also a pretty
small library!

## Table of Contents

- [Installing OVOS](#installing-ovos)
- [Skills](#skills)
- [Getting Involved](#getting-involved)
- [Links](#links)

## Installing OVOS

If you have an existing system that you would like to install OVOS on, we strongly suggest the [ovos-installer](https://github.com/OpenVoiceOS/ovos-installer) to install OVOS and its dependencies. The full assistant requires several repositories and the installer makes it easy to install them all at once.

If you would like to install OVOS on a Raspberry Pi, we suggest using the [RaspOVOS](https://github.com/OpenVoiceOS/RaspOVOS) image. This image is based on Raspberry Pi OS and includes OVOS and its dependencies running in a "headless" mode (no GUI). It is designed and optimized for a Raspberry Pi 3B, so on a 4 or higher its performance is even better.

If you would like to install OVOS on embedded hardware, we suggest using [ovos-buildroot](https://github.com/OpenVoiceOS/ovos-buildroot). This is a buildroot configuration that can be used to build a custom Linux distribution for embedded hardware. It includes OVOS and its dependencies, and is designed to be as small and efficient as possible.

You can find detailed documentation over at the [community-docs](https://openvoiceos.github.io/community-docs) or [ovos-technical-manual](https://openvoiceos.github.io/ovos-technical-manual)

This repo can be installed standalone via `pip install ovos-core`, which will install the bare minimum components common to all services. This is useful for developers who want to build their own custom voice assistant. For more details, [please see the community docs](https://openvoiceos.github.io/community-docs/042-install_ovos_core/).

## Skills

OVOS is nothing without skills. There are a handful of default skills, but [most need to be installed explicitly](https://openvoiceos.github.io/community-docs/080-ht_skills/). OVOS skills are all pip-installable, and can be found on [PyPI](https://pypi.org/) or by [browsing the OVOS organization on GitHub](https://github.com/orgs/OpenVoiceOS/repositories?language=&q=skill&sort=&type=all). Most classic Mycroft skills will also work on OVOS.

Please share your own interesting work!

## Getting Involved

This is an open source project. We would love your help. We have prepared a [contributing](.github/CONTRIBUTING.md)
guide to help you get started.

The easiest way for anyone to contribute is to help with translations! You can help without any programming knowledge via the [translation portal](https://gitlocalize.com/users/OpenVoiceOS)

If this is your first PR, or you're not sure where to get started,
say hi in [OpenVoiceOS Chat](https://matrix.to/#/!XFpdtmgyCoPDxOMPpH:matrix.org?via=matrix.org) and a team member would
be happy to mentor you.
Join the [Discussions](https://github.com/OpenVoiceOS/OpenVoiceOS/discussions) for questions and answers.

## Credits

The OpenVoiceOS team thanks the following entities (in addition to MycroftAI) for making certain code and/or
manpower resources available to us:

- [NeonGecko](https://neon.ai)
- [KDE](https://kde.org) / [Blue Systems](https://blue-systems.com/)

## Links

* [Community Documentation](https://openvoiceos.github.io/community-docs)
* [ovos-technical-manual](https://openvoiceos.github.io/ovos-technical-manual)
* [Release Notes](https://github.com/OpenVoiceOS/ovos-core/releases)
* [OpenVoiceOS Chat](https://matrix.to/#/!XFpdtmgyCoPDxOMPpH:matrix.org?via=matrix.org)
* [OpenVoiceOS Website](https://openvoiceos.com/)
* [Open Conversational AI Forums](https://community.openconversational.ai/)  (previously mycroft forums)
