"""Regression tests: the post-load training request must not block boot.

After loading new skills, the skill manager emits ``mycroft.skills.train``
so that engines with a deferred training step (e.g. padatious) can train.
The request is fire-and-forget: no reply topic is part of the spec, a single
responder could not speak for every loaded pipeline, and most engines train
at registration time — so ``_load_new_skills`` must complete promptly and
without logging a training-timeout error even when nothing answers.
"""

import time
from threading import Event
from unittest import TestCase
from unittest.mock import Mock, patch

from ovos_utils.fakebus import FakeBus

from ovos_core.skill_manager import SkillManager


class TestTrainRequestNonBlocking(TestCase):
    def _make_manager(self, bus):
        manager = SkillManager.__new__(SkillManager)
        manager.bus = bus
        manager._use_deferred_loading = False
        manager._gui_event = Event()
        manager._gui_event.set()  # skip the is_gui_connected bus round-trip
        manager.load_plugin_skills = Mock(return_value=True)
        return manager

    def test_train_request_emitted_after_load(self):
        bus = FakeBus()
        train_requests = []
        bus.on("mycroft.skills.train", train_requests.append)
        manager = self._make_manager(bus)

        manager._load_new_skills(network=True, internet=True, gui=False)

        self.assertEqual(len(train_requests), 1)

    def test_completes_promptly_without_any_responder(self):
        bus = FakeBus()
        manager = self._make_manager(bus)

        start = time.monotonic()
        with patch("ovos_core.skill_manager.LOG") as mock_log:
            manager._load_new_skills(network=True, internet=True, gui=False)
        elapsed = time.monotonic() - start

        # No blocking wait on a reply nobody is required to send.
        self.assertLess(elapsed, 1.0)
        for call in mock_log.error.call_args_list:
            self.assertNotIn("timed out", str(call))
        mock_log.exception.assert_not_called()

    def test_no_train_request_when_nothing_loaded(self):
        bus = FakeBus()
        train_requests = []
        bus.on("mycroft.skills.train", train_requests.append)
        manager = self._make_manager(bus)
        manager.load_plugin_skills = Mock(return_value=False)

        manager._load_new_skills(network=True, internet=True, gui=False)

        self.assertEqual(train_requests, [])
