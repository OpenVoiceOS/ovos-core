#!/usr/bin/env python3
from setuptools import setup
from os import getenv, path, walk


def find_resource_files():
    resource_base_dirs = ("locale", "ui", "vocab", "dialog", "regex")
    base_dir = path.dirname(__file__)
    package_data = ["skill.json"]
    for res in resource_base_dirs:
        if path.isdir(path.join(base_dir, res)):
            for (directory, _, files) in walk(path.join(base_dir, res)):
                if files:
                    package_data.append(
                        path.join(directory.replace(base_dir, "").lstrip('/'),
                                  '*'))
    return package_data


# skill_id=package_name:SkillClass
PLUGIN_ENTRY_POINT = 'ovos-tskill-abort.openvoiceos=ovos_tskill_abort:TestAbortSkill'

setup(
    # this is the package name that goes on pip
    name='ovos-tskill-abort',
    version='0.0.1',
    description='this is a OVOS test skill for the killable_intents decorator',
    url='https://github.com/OpenVoiceOS/skill-abort-test',
    author='JarbasAi',
    author_email='jarbasai@mailfence.com',
    license='Apache-2.0',
    package_dir={"ovos_tskill_abort": ""},
    package_data={'ovos_tskill_abort': find_resource_files()},
    packages=['ovos_tskill_abort'],
    include_package_data=True,
    install_requires=["ovos-workshop"],
    keywords='ovos skill plugin',
    entry_points={'ovos.plugin.skill': PLUGIN_ENTRY_POINT}
)
