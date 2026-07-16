"""Intent matching must survive the loss of pipeline-plugin compiled state.

Registration broadcasts are load-time announcements (OVOS-INTENT-4 §10): a
matcher (re)constructed after a skill loaded has missed them and matches
nothing until they are replayed. Two live scenarios exercise this end to end,
against a REAL ovos-messagebus (FakeBus cannot model a websocket drop):

- ``intent.service.pipelines.reload`` rebuilds every pipeline plugin with
  empty engines; the orchestrator must repopulate them from its passive
  registration registry (OVOS-INTENT-4 §10) so previously matching
  utterances keep matching.
- restarting the messagebus process drops and re-opens every client
  websocket; after the automatic reconnect, previously matching utterances
  must keep matching (the orchestrator rebuilds the matchers from its
  registry on the client's ``open`` event, so even a matcher that lost
  state while disconnected recovers).
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from threading import Event

from ovos_bus_client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

from ovos_core.intent_services.service import IntentService

SKILL_ID = "ovos-skill-hello-world.openvoiceos"
HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


class TestMatchingSurvivesMatcherStateLoss(unittest.TestCase):
    """Full stack on a real messagebus: intent service + a real skill."""

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        xdg = tempfile.mkdtemp(prefix="ovos-bus-restart-")
        os.makedirs(f"{xdg}/mycroft", exist_ok=True)
        with open(f"{xdg}/mycroft/mycroft.conf", "w") as f:
            json.dump({"websocket": {"host": HOST, "port": cls.port}}, f)
        cls.env = dict(os.environ, XDG_CONFIG_HOME=xdg)

        cls.bus_proc = cls._start_bus()

        cls.core_bus = MessageBusClient(host=HOST, port=cls.port)
        cls.core_bus.run_in_thread()
        assert cls.core_bus.connected_event.wait(10)

        cls.service = IntentService(cls.core_bus)
        cls._wait_for(lambda: cls.service.pipeline_plugins,
                      "pipeline plugins never loaded")

        from ovos_workshop.skill_launcher import (PluginSkillLoader,
                                                  find_skill_plugins)
        plugins = find_skill_plugins()
        assert SKILL_ID in plugins, f"{SKILL_ID} not installed"
        cls.skill_loader = PluginSkillLoader(cls.core_bus, SKILL_ID)
        assert cls.skill_loader.load(plugins[SKILL_ID])

        # a second client plays the role of an external utterance source
        cls.probe = MessageBusClient(host=HOST, port=cls.port)
        cls.probe.run_in_thread()
        assert cls.probe.connected_event.wait(10)

    @classmethod
    def tearDownClass(cls):
        # tear everything down while the bus is still up, then close the
        # clients before stopping the bus: emitting on a disconnected client
        # blocks its emitter worker until a reconnect, hanging the runner
        time.sleep(2)
        if cls.core_bus.connected_event.is_set():
            try:
                cls.skill_loader.unload()
                cls.service.shutdown()
            except Exception:
                pass
        for client in (cls.core_bus, cls.probe):
            try:
                client.close()
            except Exception:
                pass
            # a client emit issued while the websocket was down parks its
            # emitter worker in _send() on connected_event with no timeout;
            # release those workers or interpreter shutdown joins them forever
            client.connected_event.set()
        cls.bus_proc.terminate()
        cls.bus_proc.wait()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @classmethod
    def _start_bus(cls):
        log = tempfile.NamedTemporaryFile(mode="w", prefix="ovos-bus-",
                                          suffix=".log", delete=False)
        proc = subprocess.Popen([sys.executable, "-m", "ovos_messagebus"],
                                env=cls.env, stdout=log,
                                stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                socket.create_connection((HOST, cls.port), timeout=0.2).close()
                return proc
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("ovos-messagebus did not start")

    @staticmethod
    def _wait_for(predicate, error, timeout=15):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.2)
        raise AssertionError(error)

    def _utterance_matches(self, timeout=10) -> bool:
        """Send 'hello world' and report whether the skill's intent matched."""
        matched = Event()
        unmatched = Event()

        def on_matched(message):
            if message.data.get("skill_id") == SKILL_ID:
                matched.set()

        def on_unmatched(message):
            unmatched.set()

        self.probe.on("ovos.intent.matched", on_matched)
        self.probe.on("ovos.intent.unmatched", on_unmatched)
        try:
            session = Session()
            session.lang = "en-US"
            session.pipeline = ["ovos-adapt-pipeline-plugin-high"]
            self.probe.emit(
                Message("recognizer_loop:utterance",
                        {"utterances": ["hello world"], "lang": "en-US"},
                        {"session": session.serialize()}))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if matched.is_set():
                    return True
                if unmatched.is_set():
                    return False
                time.sleep(0.1)
            return False
        finally:
            self.probe.remove("ovos.intent.matched", on_matched)
            self.probe.remove("ovos.intent.unmatched", on_unmatched)

    # ------------------------------------------------------------------
    # single sequential scenario: load -> pipeline reload -> bus restart
    # (one test method so the phases cannot be reordered by the runner)
    # ------------------------------------------------------------------
    def test_matching_survives_state_loss(self):
        # initial registration
        self._wait_for(self._utterance_matches,
                       "intent never matched after initial registration",
                       timeout=30)

        # pipeline plugins rebuilt with empty engines; the orchestrator must
        # repopulate them from its registration registry
        adapt_id = "ovos-adapt-pipeline-plugin"
        old_plugin = self.service.pipeline_plugins.get(adapt_id)
        self.assertIsNotNone(old_plugin)
        self.probe.emit(Message("intent.service.pipelines.reload"))
        self._wait_for(
            lambda: self.service.pipeline_plugins.get(adapt_id)
            is not old_plugin,
            "pipeline plugins were never reloaded", timeout=30)
        self._wait_for(self._utterance_matches,
                       "intent lost after pipeline plugins reloaded",
                       timeout=60)

        # messagebus process restart -> websocket drop + auto reconnect
        type(self).bus_proc.terminate()
        type(self).bus_proc.wait()
        time.sleep(2)
        type(self).bus_proc = self._start_bus()

        self._wait_for(lambda: (self.core_bus.connected_event.is_set() and
                                self.probe.connected_event.is_set()),
                       "bus clients never reconnected", timeout=120)
        self.assertIsNone(type(self).bus_proc.poll(),
                          "restarted messagebus process died")
        self._wait_for(self._utterance_matches,
                       "intent lost after messagebus restart",
                       timeout=60)


if __name__ == "__main__":
    unittest.main()
