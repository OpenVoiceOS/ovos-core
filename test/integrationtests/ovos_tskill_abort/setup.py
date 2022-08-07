#!/usr/bin/env python3
from setuptools import setup

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
    package_data={'ovos_tskill_abort': ['locale/*']},
    packages=['ovos_tskill_abort'],
    include_package_data=True,
    install_requires=["ovos-workshop"],
    keywords='ovos skill plugin',
    entry_points={'ovos.plugin.skill': PLUGIN_ENTRY_POINT}
)
