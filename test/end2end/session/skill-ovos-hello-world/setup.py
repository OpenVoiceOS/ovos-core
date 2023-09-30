#!/usr/bin/env python3
from setuptools import setup
from os import walk, path

URL = "https://github.com/OpenVoiceOS/skill-ovos-hello-world"
SKILL_CLAZZ = "HelloWorldSkill"  # needs to match __init__.py class name

# below derived from github url to ensure standard skill_id
SKILL_AUTHOR, SKILL_NAME = URL.split(".com/")[-1].split("/")
SKILL_PKG = SKILL_NAME.lower().replace('-', '_')
PLUGIN_ENTRY_POINT = f'{SKILL_NAME.lower()}.{SKILL_AUTHOR.lower()}={SKILL_PKG}:{SKILL_CLAZZ}'
# skill_id=package_name:SkillClass


def find_resource_files():
    resource_base_dirs = ("locale", "ui", "vocab", "dialog", "regex", "skill")
    base_dir = path.dirname(__file__)
    package_data = ["*.json"]
    for res in resource_base_dirs:
        if path.isdir(path.join(base_dir, res)):
            for (directory, _, files) in walk(path.join(base_dir, res)):
                if files:
                    package_data.append(
                        path.join(directory.replace(base_dir, "").lstrip('/'),
                                  '*'))
    return package_data


setup(
    name="ovos-skill-hello-world",
    version="0.0.0",
    long_description="test",
    description='OVOS hello world skill plugin',
    author_email='jarbasai@mailfence.com',
    license='Apache-2.0',
    package_dir={SKILL_PKG: ""},
    package_data={SKILL_PKG: find_resource_files()},
    packages=[SKILL_PKG],
    include_package_data=True,
    keywords='ovos skill plugin',
    entry_points={'ovos.plugin.skill': PLUGIN_ENTRY_POINT}
)
