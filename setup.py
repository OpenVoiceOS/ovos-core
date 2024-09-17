# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import os
import os.path

from setuptools import setup, find_packages

BASEDIR = os.path.abspath(os.path.dirname(__file__))


def get_version():
    """ Find the version of ovos-core"""
    version = None
    version_file = os.path.join(BASEDIR, 'ovos_core', 'version.py')
    major, minor, build, alpha = (0, 0, 0, 0)
    with open(version_file) as f:
        for line in f:
            if 'VERSION_MAJOR' in line:
                major = line.split('=')[1].strip()
            elif 'VERSION_MINOR' in line:
                minor = line.split('=')[1].strip()
            elif 'VERSION_BUILD' in line:
                build = line.split('=')[1].strip()
            elif 'VERSION_ALPHA' in line:
                alpha = line.split('=')[1].strip()

            if ((major and minor and build and alpha) or
                    '# END_VERSION_BLOCK' in line):
                break
    version = f"{major}.{minor}.{build}"
    if int(alpha):
        version += f"a{alpha}"
    return version


def required(requirements_file):
    """ Read requirements file and remove comments and empty lines. """
    with open(os.path.join(BASEDIR, requirements_file), 'r') as f:
        requirements = f.read().splitlines()
        if 'MYCROFT_LOOSE_REQUIREMENTS' in os.environ:
            print('USING LOOSE REQUIREMENTS!')
            requirements = [r.replace('==', '>=').replace('~=', '>=') for r in requirements]
        return [pkg for pkg in requirements
                if pkg.strip() and not pkg.startswith("#")]


with open(os.path.join(BASEDIR, "README.md"), "r") as f:
    long_description = f.read()


setup(
    name='ovos-core',
    version=get_version(),
    license='Apache-2.0',
    url='https://github.com/OpenVoiceOS/ovos-core',
    description='The spiritual successor to Mycroft AI, OVOS is flexible voice assistant software that can be run almost anywhere!',
    long_description=long_description,
    long_description_content_type="text/markdown",
    install_requires=required('requirements/requirements.txt'),
    extras_require={
        'mycroft': required('requirements/mycroft.txt'),
        'lgpl': required('requirements/lgpl.txt'),
        'deprecated': required('requirements/extra-deprecated.txt'),
        'plugins': required('requirements/plugins.txt'),
        'skills-essential': required('requirements/skills-essential.txt'),
        'skills-audio': required('requirements/skills-audio.txt'),
        'skills-desktop': required('requirements/skills-desktop.txt'),
        'skills-internet': required('requirements/skills-internet.txt'),
        'skills-gui': required('requirements/skills-gui.txt'),
        'skills-media': required('requirements/skills-media.txt')
    },
    packages=find_packages(include=['mycroft*']) + find_packages(include=['ovos_core*']),
    include_package_data=True,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: Apache Software License",
    ],
    entry_points={
        'console_scripts': [
            'ovos-core=ovos_core.__main__:main',
            # TODO - remove below console_scripts in 0.1.0 (backwards compat)
            'mycroft-speech-client=mycroft.listener.__main__:main',
            'mycroft-messagebus=mycroft.messagebus.service.__main__:main',
            'mycroft-skills=mycroft.skills.__main__:main',
            'mycroft-audio=mycroft.audio.__main__:main',
            'mycroft-echo-observer=mycroft.messagebus.client.ws:echo',
            'mycroft-audio-test=mycroft.util.audio_test:main',
            'mycroft-enclosure-client=ovos_PHAL.__main__:main',
            'mycroft-cli-client=mycroft.client.text.__main__:main',
            'mycroft-gui-service=mycroft.gui.__main__:main'
        ]
    }
)
