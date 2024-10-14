#!/usr/bin/env python3
from setuptools import setup

# skill_id=package_name:SkillClass
PLUGIN_ENTRY_POINT = 'ovos-tskill-fakewiki.openvoiceos=ovos_tskill_fakewiki:FakeWikiSkill'

setup(
    # this is the package name that goes on pip
    name='ovos-tskill-fakewiki',
    version='0.0.1',
    description='this is a OVOS test skill for the common query framework',
    url='https://github.com/OpenVoiceOS/ovos-core',
    author='JarbasAi',
    author_email='jarbasai@mailfence.com',
    license='Apache-2.0',
    package_dir={"ovos_tskill_fakewiki": ""},
    package_data={'ovos_tskill_fakewiki': ['locale/*']},
    packages=['ovos_tskill_fakewiki'],
    include_package_data=True,
    install_requires=["ovos-workshop"],
    keywords='ovos skill plugin',
    entry_points={'ovos.plugin.skill': PLUGIN_ENTRY_POINT}
)
