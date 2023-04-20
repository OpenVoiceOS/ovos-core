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

    loader = SkillLoader(bus, str(skill_directory))

    # TODO: un-mock these when they are more testable
    loader._load_skill_source = Mock(
        return_value=Mock()
    )
    loader._check_for_first_run = Mock()

    def test_skill_already_loaded(self):
        """The loader should take to action for an already loaded skill."""
        bus.msgs = []
        self.loader.instance = Mock
        self.loader.instance.reload_skill = True
        self.loader.loaded = True
        self.loader.last_loaded = time() + ONE_MINUTE

        self.assertFalse(self.loader.reload_needed())

    def test_skill_reloading_blocked(self):
        """The loader should skip reloads for skill that doesn't allow it."""
        bus.msgs = []
        self.loader.instance = Mock()
        self.loader.instance.reload_skill = False
        self.loader.active = True
        self.loader.loaded = True
        self.assertFalse(self.loader.reload_needed())

    def test_skill_reloading_deactivated(self):
        """The loader should skip reloads for skill that aren't active."""
        bus.msgs = []
        self.loader.instance = Mock()
        self.loader.name = "MySkill"
        self.loader.instance.reload_skill = True
        self.loader.active = False
        self.loader.loaded = False
        self.assertFalse(self.loader.reload_needed())

    def test_skill_reload(self):
        bus.msgs = []
        """Test reloading a skill that was modified."""
        self.loader.instance = Mock()
        self.loader.loaded = True
        self.loader.load_attempted = False
        self.loader.last_loaded = 10
        self.loader.instance.reload_skill = True
        self.loader.instance.name = "MySkill"
        self.loader.skill_id = 'test_skill'

        # Mock to return a known (Mock) skill instance
        real_create_skill_instance = self.loader._create_skill_instance

        def _update_skill_instance(*args, **kwargs):
            self.loader.instance = Mock()
            self.loader.loaded = True
            self.loader.last_loaded = 100
            self.loader.skill_id = 'test_skill'
            self.loader.instance.name = "MySkill"
            return True

        self.loader._create_skill_instance = _update_skill_instance

        self.loader.reload()

        self.assertTrue(self.loader.load_attempted)
        self.assertTrue(self.loader.loaded)

        self.assertListEqual(
            ['mycroft.skills.shutdown', 'mycroft.skills.loaded'],
            [m["type"] for m in bus.msgs]
        )
        self.loader._create_skill_instance = real_create_skill_instance

    def test_skill_load(self):
        bus.msgs = []

        self.loader.instance = None
        self.loader.loaded = False
        self.loader.last_loaded = 0

        # Mock to return a known (Mock) skill instance
        real_create_skill_instance = self.loader._create_skill_instance

        def _update_skill_instance(*args, **kwargs):
            self.loader.instance = Mock()
            self.loader.loaded = True
            self.loader.last_loaded = 100
            self.loader.skill_id = 'test_skill'
            self.loader.instance.name = "MySkill"
            return True

        self.loader._create_skill_instance = _update_skill_instance

        self.loader.load()

        self.assertTrue(self.loader.load_attempted)
        self.assertTrue(self.loader.loaded)

        self.assertListEqual(
            ['mycroft.skills.loaded'],
            [m["type"] for m in bus.msgs]
        )
        self.loader._create_skill_instance = real_create_skill_instance

    def test_reload_modified(self):
        bus.msgs = []
        self.loader.last_modified = 0
        self.loader.reload = Mock()

        self.loader._handle_filechange()
        self.loader.reload.assert_called_once_with()
        self.assertNotEqual(self.loader.last_modified, 0)

    def test_skill_load_blacklisted(self):
        """Skill should not be loaded if it is blacklisted"""
        self.loader.instance = Mock()
        self.loader.loaded = False
        self.loader.last_loaded = 0
        self.loader.skill_id = 'test_skill'
        self.loader.name = "MySkill"
        bus.msgs = []
        config = dict(self.loader.config)
        config['skills']['blacklisted_skills'] = ['test_skill']
        self.loader.config = config
        self.assertEqual(self.loader.config['skills']['blacklisted_skills'],
                         ['test_skill'])
        self.loader.skill_id = 'test_skill'

        self.loader.load()

        self.assertTrue(self.loader.load_attempted)
        self.assertFalse(self.loader.loaded)

        self.assertListEqual(
            ['mycroft.skills.loading_failure'],
            [m["type"] for m in bus.msgs]
        )

        self.loader.config['skills']['blacklisted_skills'].remove('test_skill')
