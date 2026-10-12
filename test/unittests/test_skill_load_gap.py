"""Nothing between "IntentService is ready" and the first skill load may wait
on a reply that is not needed.

Measured on a runtime with 18 skills and no GUI: the first load started 3.6-5 s
after the intent service reported ready. ``_load_new_skills`` asked the bus
whether a GUI was connected (a 3 s ``gui.status.request`` timeout) for a value
no load decision reads, and ``wait_for_intent_service`` asked the in-process
intent service over the bus, sleeping a second after every miss.
"""
import time
from threading import Event
from unittest import TestCase
from unittest.mock import Mock, patch

from ovos_utils.fakebus import FakeBus
from ovos_utils.process_utils import ProcessState

from ovos_core.skill_manager import SkillManager


def _manager():
    manager = SkillManager.__new__(SkillManager)
    manager.bus = FakeBus()
    manager._use_deferred_loading = False
    manager._gui_event = Event()
    manager._stop_event = Event()
    manager.config = {"skills": {}}
    return manager


class TestNoGuiProbeBeforeLoading(TestCase):
    def test_load_pass_does_not_ask_for_the_gui(self):
        manager = _manager()
        manager._load_untracked_plugin_skills = Mock(return_value=[])
        with patch("ovos_core.skill_manager.is_gui_connected") as probe:
            manager._load_new_skills()
        probe.assert_not_called()


class TestVersionsReadOncePerPass(TestCase):
    def test_one_metadata_scan_for_many_skills(self):
        manager = _manager()
        manager._distribution_versions = {}
        manager._network_event = Event()
        manager._connected_event = Event()
        manager._logged_skill_warnings = set()
        manager._should_retry_plugin_skill = Mock(return_value=True)
        manager._is_plugin_skill_tracked = Mock(return_value=False)
        manager._reserve_plugin_skill_load = Mock(return_value=True)
        loader = Mock()
        loader.runtime_requirements.network_before_load = False
        loader.runtime_requirements.internet_before_load = False
        manager._get_plugin_skill_loader = Mock(return_value=loader)
        manager._load_plugin_skill = Mock(return_value=loader)
        plugins = {f"skill-{i}": Mock() for i in range(5)}
        scan = Mock(return_value={"skill-1": "1.0"})
        with patch("ovos_core.skill_manager.find_skill_plugins", return_value=plugins), \
                patch.object(SkillManager, "blacklist", []), \
                patch.object(SkillManager, "_declared_skill_versions", staticmethod(scan)):
            loaded = manager._load_untracked_plugin_skills(network=True, internet=True)
        self.assertEqual(len(loaded), 5)
        self.assertEqual(scan.call_count, 1)
        versions = {c.args[0]: c.kwargs["version"]
                    for c in manager._load_plugin_skill.call_args_list}
        self.assertEqual(versions["skill-1"], "1.0")
        self.assertIsNone(versions["skill-0"])


class TestInProcessIntentServiceWait(TestCase):
    def test_ready_in_process_service_returns_without_the_bus(self):
        manager = _manager()
        manager.intents = Mock()
        manager.intents.status.state = ProcessState.READY
        manager.bus = Mock()
        manager.wait_for_intent_service()
        manager.bus.wait_for_response.assert_not_called()

    def test_waits_for_the_in_process_service_to_become_ready(self):
        manager = _manager()
        manager.intents = Mock()
        manager.intents.status.state = ProcessState.ALIVE
        manager.bus = Mock()

        def become_ready(timeout=None):
            manager.intents.status.state = ProcessState.READY
            return False

        manager._stop_event = Mock()
        manager._stop_event.is_set.return_value = False
        manager._stop_event.wait.side_effect = become_ready
        start = time.monotonic()
        manager.wait_for_intent_service()
        self.assertLess(time.monotonic() - start, 1.0)
        manager._stop_event.wait.assert_called_once_with(0.05)
        manager.bus.wait_for_response.assert_not_called()

    def test_without_an_in_process_service_asks_the_bus(self):
        manager = _manager()
        manager.intents = None
        manager.bus = Mock()
        manager.bus.wait_for_response.return_value = Mock(data={"status": True})
        manager.wait_for_intent_service()
        manager.bus.wait_for_response.assert_called_once()
