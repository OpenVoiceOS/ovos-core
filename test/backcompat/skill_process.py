"""Standalone skill process for the mixed-version back-compat matrix.

Runs in the **skill venv** (its own ``ovos-workshop`` + whatever
``ovos-bus-client`` that workshop's dependency floor resolves to), never in the
venv the test driver runs in. That separation is the whole point: the two
package sets have to be able to differ, which one process cannot do.

The script builds a throwaway skill directory with a single
``food.order.intent`` resource, brings up an ``OVOSSkill`` against the real
websocket bus, and registers the intent through ``register_intent_file`` — the
exact call whose topic spelling changed across workshop releases.

When the handler runs it emits two things:

* ``backcompat.skill.handled`` — a precise marker carrying the topic that
  actually fired, so the driver can tell the canonical dispatch from the
  suffixed twin and count firings (a double-fire is a failure, not a pass);
* a normal ``speak`` — the realistic "the skill answered" signal.

``SKILL_READY`` on stdout means registration finished and the driver may
dispatch. Everything else on stdout is diagnostic and is echoed by the driver
when an assertion fails.
"""
import json
import os
import sys
import tempfile
import time
from os.path import join

from ovos_bus_client.client import MessageBusClient
from ovos_bus_client.message import Message
from ovos_workshop.skills.ovos import OVOSSkill

SKILL_ID = os.environ.get("BACKCOMPAT_SKILL_ID", "backcompat.mixed.test")
INTENT_FILE = "food.order.intent"

#: Sample lines for the padatious resource. The matcher is never exercised —
#: the driver dispatches the registered topic directly, the way ovos-core's
#: ``_dispatch_match`` forwards ``match.match_type`` verbatim — but
#: ``register_intent_file`` refuses to register a resource it cannot read.
SAMPLES = ["order some tacos", "i am hungry", "grab some food"]


def _dist_version(name: str) -> str:
    from importlib.metadata import version
    return version(name)


def _make_skill_dir() -> str:
    """Lay out the minimal on-disk skill a real workshop install expects."""
    root = tempfile.mkdtemp(prefix="backcompat-skill-")
    locale = join(root, "locale", "en-us")
    os.makedirs(locale)
    with open(join(locale, INTENT_FILE), "w") as f:
        f.write("\n".join(SAMPLES) + "\n")
    return root


class BackCompatSkill(OVOSSkill):
    """One intent, registered the ordinary way.

    Nothing here is version-aware. The skill is written exactly as a skill
    author would write it, and the matrix observes what each workshop release
    does with it.
    """

    def initialize(self):
        self.register_intent_file(INTENT_FILE, self.handle_order)

    def handle_order(self, message: Message):
        self.bus.emit(message.forward(
            "backcompat.skill.handled",
            {"topic": message.msg_type,
             "skill_id": SKILL_ID,
             "data": message.data}))
        self.speak("ordering tacos")


def main():
    bus = MessageBusClient()
    bus.run_in_thread()
    bus.connected_event.wait(30)

    root = _make_skill_dir()
    # Passing ``bus`` runs the full startup (including ``initialize``) inside
    # the constructor, so there is no separate ``_startup`` call to make here.
    BackCompatSkill(skill_id=SKILL_ID, bus=bus, resources_dir=root)

    # Report what this workshop actually bound, so a failing combo says which
    # spellings existed rather than only that nothing fired.
    bound = sorted(t for t in getattr(bus.emitter, "_events", {})
                   if t.startswith(f"{SKILL_ID}:"))
    print("BOUND_TOPICS " + json.dumps(bound), flush=True)

    # The versions actually resolved inside THIS venv, and whether the
    # receive-side compat mirror of ovos-bus-client#271 is present. The driver
    # asserts on these: the repair strategy only works if a container pinned to
    # an old workshop still resolves a client new enough to carry the mirror.
    print("VERSIONS " + json.dumps({
        "ovos_workshop": _dist_version("ovos-workshop"),
        "ovos_bus_client": _dist_version("ovos-bus-client"),
        "has_reemit_hook": hasattr(MessageBusClient, "_reemit_legacy_intent"),
    }), flush=True)
    print("SKILL_READY", flush=True)

    # The client already owns a reader thread from ``run_in_thread`` above;
    # ``run_forever`` would try to open the same socket twice. Park instead and
    # let the driver terminate the process.
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    sys.exit(main())
