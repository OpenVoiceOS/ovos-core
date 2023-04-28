# Copyright 2019 Mycroft AI Inc.
#
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
"""Unit tests for the SkillLoader class."""
import json
import unittest
from pathlib import Path
from time import time
from unittest.mock import Mock

from mycroft.skills.mycroft_skill.mycroft_skill import MycroftSkill
from mycroft.skills.skill_loader import SkillLoader
from ovos_utils import classproperty
from ovos_utils.messagebus import FakeBus
from ovos_utils.process_utils import RuntimeRequirements

ONE_MINUTE = 60


class OfflineSkill(MycroftSkill):
    @classproperty
    def runtime_requirements(self):
        return RuntimeRequirements(internet_before_load=False,
                                   network_before_load=False,
                                   requires_internet=False,
                                   requires_network=False,
                                   no_internet_fallback=True,
                                   no_network_fallback=True)


class LANSkill(MycroftSkill):
    @classproperty
    def runtime_requirements(self):
        scans_on_init = True
        return RuntimeRequirements(internet_before_load=False,
                                   network_before_load=scans_on_init,
                                   requires_internet=False,
                                   requires_network=True,
                                   no_internet_fallback=True,
                                   no_network_fallback=False)


class TestSkillNetwork(unittest.TestCase):

    def test_class_property(self):
        self.assertEqual(OfflineSkill.runtime_requirements,
                         RuntimeRequirements(internet_before_load=False,
                                             network_before_load=False,
                                             requires_internet=False,
                                             requires_network=False,
                                             no_internet_fallback=True,
                                             no_network_fallback=True)
                         )
        self.assertEqual(LANSkill.runtime_requirements,
                         RuntimeRequirements(internet_before_load=False,
                                             network_before_load=True,
                                             requires_internet=False,
                                             requires_network=True,
                                             no_internet_fallback=True,
                                             no_network_fallback=False)
                         )
        self.assertEqual(MycroftSkill.runtime_requirements,
                         RuntimeRequirements()
                         )


msgs = []
bus = FakeBus()
bus.msgs = []


def _handle(msg):
    global bus
    bus.msgs.append(json.loads(msg))


bus.on("message", _handle)


class TestSkillLoader(unittest.TestCase):
    skill_directory = Path('/tmp/test_skill')
    skill_directory.mkdir(exist_ok=True)
    for file_name in ('__init__.py', 'bar.py', '.foobar', 'bar.pyc'):
        skill_directory.joinpath(file_name).touch()

    def test_skill_already_loaded(self):
        """The loader should take to action for an already loaded skill."""
        bus.msgs = []
        loader = SkillLoader(bus, str(self.skill_directory))
        loader.instance = Mock
        loader.instance.reload_skill = True
        loader.loaded = True
        loader.last_loaded = time() + ONE_MINUTE

        self.assertFalse(loader.reload_needed())

    def test_skill_reloading_blocked(self):
        """The loader should skip reloads for skill that doesn't allow it."""
        bus.msgs = []
        loader = SkillLoader(bus, str(self.skill_directory))
        loader.instance = Mock()
        loader.instance.reload_skill = False
        loader.active = True
        loader.loaded = True

        self.assertFalse(loader.reload_needed())

    def test_skill_reloading_deactivated(self):
        """The loader should skip reloads for skill that aren't active."""
        bus.msgs = []
        loader = SkillLoader(bus, str(self.skill_directory))
        loader.instance = Mock()
        loader.name = "MySkill"
        loader.instance.reload_skill = True
        loader.active = False
        loader.loaded = False

        self.assertFalse(loader.reload_needed())

    def test_skill_reload(self):
        """Test reloading a skill that was modified."""
        bus.msgs = []
        loader = SkillLoader(bus, str(self.skill_directory))
        loader.instance = Mock()
        loader.loaded = True
        loader.load_attempted = False
        loader.last_loaded = 10
        loader.instance.reload_skill = True
        loader.instance.name = "MySkill"
        loader.skill_id = 'test_skill'

        # Mock to return a known (Mock) skill instance
        real_create_skill_instance = loader._create_skill_instance

        def _update_skill_instance(*args, **kwargs):
            loader.instance = Mock()
            loader.loaded = True
            loader.load_attempted = True
            loader.last_loaded = 100
            loader.skill_id = 'test_skill'
            loader.instance.name = "MySkill"
            return True

        loader._create_skill_instance = _update_skill_instance

        loader.reload()

        self.assertTrue(loader.load_attempted)
        self.assertTrue(loader.loaded)

        self.assertListEqual(
            ['mycroft.skills.shutdown', 'mycroft.skills.loaded'],
            [m["type"] for m in bus.msgs]
        )
        loader._create_skill_instance = real_create_skill_instance

    def test_skill_load(self):
        loader = SkillLoader(bus, str(self.skill_directory))
        bus.msgs = []
        loader.instance = None
        loader.loaded = False
        loader.last_loaded = 0

        # Mock to return a known (Mock) skill instance
        real_create_skill_instance = loader._create_skill_instance

        def _update_skill_instance(*args, **kwargs):
            loader.instance = Mock()
            loader.loaded = True
            loader.last_loaded = 100
            loader.skill_id = 'test_skill'
            loader.instance.name = "MySkill"
            return True

        loader._create_skill_instance = _update_skill_instance

        loader.load()

        self.assertTrue(loader.load_attempted)
        self.assertTrue(loader.loaded)

        self.assertListEqual(
            ['mycroft.skills.loaded'],
            [m["type"] for m in bus.msgs]
        )
        loader._create_skill_instance = real_create_skill_instance

    def test_reload_modified(self):
        loader = SkillLoader(bus, str(self.skill_directory))
        bus.msgs = []
        loader.last_modified = 0
        loader.reload = Mock()

        loader._handle_filechange()
        loader.reload.assert_called_once_with()
        self.assertNotEqual(loader.last_modified, 0)

    def test_skill_load_blacklisted(self):
        """Skill should not be loaded if it is blacklisted"""
        loader = SkillLoader(bus, str(self.skill_directory))
        loader.instance = Mock()
        loader.loaded = False
        loader.last_loaded = 0
        loader.skill_id = 'test_skill'
        loader.name = "MySkill"
        bus.msgs = []

        config = dict(loader.config)
        config['skills']['blacklisted_skills'] = ['test_skill']
        loader.config = config
        self.assertEqual(loader.config['skills']['blacklisted_skills'],
                         ['test_skill'])
        loader.skill_id = 'test_skill'

        loader.load()

        self.assertTrue(loader.load_attempted)
        self.assertFalse(loader.loaded)

        self.assertListEqual(
            ['mycroft.skills.loading_failure'],
            [m["type"] for m in bus.msgs]
        )

        loader.config['skills']['blacklisted_skills'].remove('test_skill')
