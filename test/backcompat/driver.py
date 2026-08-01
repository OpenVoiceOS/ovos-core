"""Shared plumbing for the mixed-version back-compat matrix.

The driver process **is** the core side of a combo: it runs under the core
venv, so ``ovos-core`` / ``ovos-padatious`` / ``ovos-bus-client`` here are the
versions that combo pins. The skill side lives in a separate venv and is
reached only over a real websocket, which is what makes two package sets
observable at once.

Nothing in this module mocks the bus. A real ``ovos-messagebus`` is started on
a free port and both sides connect to it.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from threading import Event
from typing import Optional

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message

SKILL_ID = "backcompat.mixed.test"
INTENT_FILE = "food.order.intent"
LEGACY_TOPIC = f"{SKILL_ID}:{INTENT_FILE}"
CANONICAL_TOPIC = f"{SKILL_ID}:food.order"

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_SCRIPT = os.path.join(HERE, "skill_process.py")

#: How long to wait for the skill venv to import workshop and register. A cold
#: interpreter plus resource loading is slow; this is not a latency assertion.
SKILL_BOOT_TIMEOUT = 120
#: How long to wait for a handler to answer once the dispatch is on the wire.
#: Generous on purpose — a short window would turn CI jitter into a fake
#: "compat is broken" result, and this suite must only fail for real reasons.
DISPATCH_TIMEOUT = 10


def free_port() -> int:
    """Grab a port the messagebus can own for one test run."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def core_canonicalizes() -> bool:
    """Whether the core-side stack folds the suffixed intent id at registration.

    This is the single behaviour that decides which topic a combo puts on the
    wire, and it lives in the padatious **pipeline plugin**, not in ovos-core:
    ``ovos-core`` forwards ``match.match_type`` verbatim
    (``IntentService._dispatch_match``), so the spelling is whatever the engine
    registry holds.

    ``ovos-padatious >= 2.0.1a1`` folds ``<skill_id>:<file>.intent`` onto
    ``<skill_id>:<file>`` inside ``register_intent``, so every match is
    canonical by construction. Older releases keep whatever the skill sent.

    The probe is the real symbol rather than a version string, so the matrix
    keeps telling the truth if the fold ever moves or is reverted.
    """
    import ovos_padatious.opm as opm
    return hasattr(opm, "_dealias_intent_name")


def dispatch_topic_for(registered_name: str) -> str:
    """The topic this core stack would dispatch for ``registered_name``."""
    if not core_canonicalizes():
        return registered_name
    import ovos_padatious.opm as opm
    return opm._dealias_intent_name(registered_name)


def make_shared_config(port: int) -> str:
    """Write a throwaway ``mycroft.conf`` pinning the bus to ``port``.

    Neither the bus server nor the client reads a port from the environment,
    and both venvs must agree on one. An ``XDG_CONFIG_HOME`` pointed at this
    directory is the one knob that reaches every process regardless of which
    venv it runs in, and it keeps the run off the developer's real bus.
    """
    root = tempfile.mkdtemp(prefix="backcompat-xdg-")
    conf_dir = os.path.join(root, "mycroft")
    os.makedirs(conf_dir)
    with open(os.path.join(conf_dir, "mycroft.conf"), "w") as f:
        json.dump({"websocket": {"host": "127.0.0.1", "port": port,
                                 "route": "/core", "ssl": False}}, f)
    return root


class BusServer:
    """A real ``ovos-messagebus`` on a private port."""

    def __init__(self):
        self.port = free_port()
        self.xdg = make_shared_config(self.port)
        env = dict(os.environ, XDG_CONFIG_HOME=self.xdg)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "ovos_messagebus"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env)
        self._wait_until_accepting()

    def _wait_until_accepting(self, timeout: int = 60):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(
                    "messagebus died during startup:\n"
                    + (self.proc.stdout.read() if self.proc.stdout else ""))
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", self.port)) == 0:
                    return
            time.sleep(0.25)
        raise RuntimeError(f"messagebus never accepted on port {self.port}")

    def client(self) -> MessageBusClient:
        bus = MessageBusClient(host="127.0.0.1", port=self.port, route="/core")
        bus.run_in_thread()
        if not bus.connected_event.wait(30):
            raise RuntimeError("driver could not connect to the messagebus")
        return bus

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class SkillProcess:
    """The other venv's skill, as a child process on the same bus.

    ``emit_legacy`` is threaded through as an environment flag because the
    kill-switch control needs to turn the compat bridge off in the **skill**
    process, where bus-client#271's mirror runs — not in the driver.
    """

    def __init__(self, python: str, xdg: str, emit_legacy: bool = True,
                 blanket: bool = False):
        env = dict(os.environ,
                   XDG_CONFIG_HOME=xdg,
                   OVOS_BUS_EMIT_LEGACY=str(emit_legacy).lower(),
                   OVOS_BUS_INTENT_REEMIT_BLANKET=str(blanket).lower(),
                   BACKCOMPAT_SKILL_ID=SKILL_ID,
                   PYTHONUNBUFFERED="1")
        self.lines = []
        self.bound_topics = []
        #: versions resolved inside the skill venv, reported by the child
        self.versions = {}
        self.proc = subprocess.Popen(
            [python, SKILL_SCRIPT],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env)
        self._wait_ready()

    def _wait_ready(self):
        deadline = time.time() + SKILL_BOOT_TIMEOUT
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                if self.proc.poll() is not None:
                    raise RuntimeError(
                        "skill process died before registering:\n" + self.log)
                continue
            self.lines.append(line.rstrip())
            if line.startswith("BOUND_TOPICS "):
                self.bound_topics = json.loads(line[len("BOUND_TOPICS "):])
            if line.startswith("VERSIONS "):
                self.versions = json.loads(line[len("VERSIONS "):])
            if line.startswith("SKILL_READY"):
                return
        raise RuntimeError(f"skill process never reported ready:\n{self.log}")

    @property
    def log(self) -> str:
        return "\n".join(self.lines)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()


class Capture:
    """Collect messages seen on a topic, with a wait-for-first helper.

    ``token`` narrows the capture to one dispatch. The bus is shared by the
    whole module and a handler's answer can land after the test that triggered
    it has moved on, so counting everything that ever appeared on a topic would
    charge one test for another test's traffic — and a duplicate-firing check
    has to be able to tell those apart.
    """

    def __init__(self, bus: MessageBusClient, topic: str,
                 token: Optional[str] = None):
        self.bus = bus
        self.topic = topic
        self.token = token
        self.messages = []
        self._seen = Event()
        bus.on(topic, self._handle)

    def _matches(self, message: Message) -> bool:
        if self.token is None:
            return True
        data = message.data or {}
        # the marker echoes the dispatch payload under "data"; the dispatch
        # itself carries the token at the top level
        return (data.get("token") == self.token
                or (data.get("data") or {}).get("token") == self.token)

    def _handle(self, message: Message):
        if not self._matches(message):
            return
        self.messages.append(message)
        self._seen.set()

    def wait(self, timeout: float = DISPATCH_TIMEOUT) -> bool:
        return self._seen.wait(timeout)

    def close(self):
        self.bus.remove(self.topic, self._handle)


def dispatch(bus: MessageBusClient, topic: str, **data) -> str:
    """Emit an intent dispatch the way ``IntentService._dispatch_match`` does.

    Returns the correlation token stamped into the payload so a capture can
    attribute the answer to this dispatch and no other.
    """
    token = uuid.uuid4().hex
    bus.emit(Message(topic, dict(data, token=token),
                     {"session": {"session_id": f"backcompat-{token[:8]}"}}))
    return token
