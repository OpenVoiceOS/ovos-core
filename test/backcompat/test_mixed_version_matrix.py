"""Mixed-version back-compat matrix: a real bus, two venvs, four combos.

Why this exists
---------------

Every in-process guard in this repo shares one interpreter, so it can only
ever observe one set of package versions. The breakage this suite is about is
*definitionally* cross-version: a skill container frozen months ago talks to a
stack that moved on. That needs two package sets alive at once, which means
two venvs and a real websocket between them.

What moved
----------

OVOS-MSG-1 §2.1.1 builds the per-intent dispatch topic as
``<skill_id>:<intent_name>``. Old ``ovos-workshop`` built it from the
padatious resource **filename**, so the authoring extension leaked onto the
wire as ``<skill_id>:food.order.intent``. Two independent changes then landed:

* ``ovos-padatious >= 2.0.1a1`` folds the suffixed id onto the canonical
  ``<skill_id>:food.order`` at **registration** time, so every match — and
  therefore every dispatch, since ``ovos-core`` forwards ``match.match_type``
  verbatim — is canonical;
* ``ovos-workshop >= 9.3.2a1`` binds the handler to **both** spellings, so a
  skill built against it survives either dispatch.

The interesting cell is the one where those two miss each other: a skill built
against ``ovos-workshop == 9.3.1a2`` binds the suffixed topic **only**, and a
current core dispatches the canonical topic **only**.

The matrix
----------

===================  ==================  =================  ============
combo                skill binds         core dispatches    handler runs
===================  ==================  =================  ============
old skill/old core   suffixed only       suffixed           yes
old skill/new core   suffixed only       canonical          **no**
new skill/old core   both                suffixed           yes
new skill/new core   both                canonical          yes (once)
===================  ==================  =================  ============

Only ``old skill/new core`` is broken, and it is marked
``xfail(strict=True)``. The other three are passing controls: they prove the
harness can see a handler fire at all, so the one red cell is a real finding
and not a broken fixture.

How it gets fixed, and why the fix lands where it does
------------------------------------------------------

The old container does **not** ship an old ``ovos-bus-client``. Its workshop
pin declares a floor, not a ceiling, so a rebuilt container resolves the
current client — this suite asserts that, because the whole repair strategy
depends on it. ``ovos-bus-client#271`` bridges with two stateless rules: the emitter
also sends a marked ``.intent``-suffixed twin frame for every intent topic
(reaches truly frozen old clients over the wire), and a receiver
canonicalizes unmarked suffixed traffic locally. Either way the old
handler runs without the skill changing at all.

That is also why the mirror is receive-side rather than emit-side: the fix has
to execute in the process that owns the stale binding, and only that process
knows what it bound.

Kill-switch role
----------------

These four cells are a gate on the compat train, in both directions:

* the day ``#271`` releases, ``old skill/new core`` starts passing,
  ``strict=True`` turns that into a loud XPASS failure, and the marker comes
  off — the guard is then permanent;
* ``ovos-workshop#500`` removes the suffixed binding, which turns
  ``new skill/old core`` red. That cell must not be deleted to make the PR
  green; it is the signal that the inbound direction (suffixed wire topic →
  canonical local listener) is still missing from the client;
* any PR that drops the compat must flip these deliberately.

Running it
----------

The combo is selected by environment, so one script serves all four CI matrix
entries::

    BACKCOMPAT_COMBO=old-skill/new-core \\
    BACKCOMPAT_SKILL_PYTHON=/path/to/venv_skill_old/bin/python \\
    <core-venv>/bin/pytest test/backcompat/

``test/backcompat/build_venvs.sh`` builds the four venvs with the pins above.
"""
import os
import time
import uuid

import pytest

from ovos_bus_client.message import Message

from .driver import (CANONICAL_TOPIC, LEGACY_TOPIC, SKILL_ID, BusServer,
                     Capture, SkillProcess, core_canonicalizes, dispatch,
                     dispatch_topic_for)

#: What each combo is *supposed* to be, so a silent pin drift (a new workshop
#: release changing what it binds, or the padatious fold being reverted) fails
#: as a wrong-vintage error instead of quietly turning a red cell green.
COMBOS = {
    # combo id            skill binds suffixed only, core canonicalizes, fires
    "old-skill/old-core": (True, False, True),
    "old-skill/new-core": (True, True, False),
    "new-skill/old-core": (False, False, True),
    "new-skill/new-core": (False, True, True),
}

COMBO = os.environ.get("BACKCOMPAT_COMBO", "")
SKILL_PYTHON = os.environ.get("BACKCOMPAT_SKILL_PYTHON", "")

pytestmark = pytest.mark.skipif(
    not COMBO or not SKILL_PYTHON,
    reason="mixed-version matrix needs BACKCOMPAT_COMBO and "
           "BACKCOMPAT_SKILL_PYTHON; see test/backcompat/build_venvs.sh")

#: True only in the one cell the compat train has to repair. Evaluated at
#: import time so the xfail below can be static and strict.
IS_BROKEN_CELL = COMBO == "old-skill/new-core"

_XFAIL_REASON = (
    "old skill container (ovos-workshop==9.3.1a2, suffixed binding only) does "
    "not hear a canonical dispatch; needs the receive-side alias mirror from "
    "ovos-bus-client#271, unreleased. XPASS here means #271 shipped — drop "
    "this marker and keep the guard.")


@pytest.fixture(scope="module")
def stack():
    """One bus and one skill process, shared by the read-only observations."""
    if COMBO not in COMBOS:
        pytest.fail(f"unknown BACKCOMPAT_COMBO {COMBO!r}; "
                    f"expected one of {sorted(COMBOS)}")
    server = BusServer()
    skill = None
    try:
        bus = server.client()
        # Capture registration before the skill exists, so the name the core
        # side would key its engine entry on is observed, never assumed.
        registrations = Capture(bus, "padatious:register_intent")
        skill = SkillProcess(SKILL_PYTHON, server.xdg)
        registrations.wait(30)
        yield server, bus, skill, registrations
    finally:
        if skill is not None:
            skill.stop()
        server.stop()


def _registered_name(registrations) -> str:
    names = [m.data.get("name") for m in registrations.messages
             if str(m.data.get("name", "")).startswith(f"{SKILL_ID}:")]
    assert names, ("the skill never registered an intent with the padatious "
                   "contract; nothing to dispatch")
    return names[0]


def test_pins_are_the_intended_vintage(stack):
    """Fail loudly if either side is not the version this combo assumes.

    Without this, a workshop release that quietly changes what it binds would
    turn the broken cell green and be read as "the compat train landed".
    """
    _server, _bus, skill, _regs = stack
    want_suffixed_only, want_canon, _ = COMBOS[COMBO]

    suffixed_only = skill.bound_topics == [LEGACY_TOPIC]
    assert suffixed_only == want_suffixed_only, (
        f"{COMBO}: expected suffixed-only binding={want_suffixed_only}, but "
        f"the skill venv bound {skill.bound_topics}")
    if not want_suffixed_only:
        assert CANONICAL_TOPIC in skill.bound_topics
    assert core_canonicalizes() == want_canon, (
        f"{COMBO}: expected the core venv to canonicalize at registration="
        f"{want_canon}, got {core_canonicalizes()}")


def test_old_container_resolves_a_current_bus_client(stack):
    """The repair strategy assumes the frozen container gets a modern client.

    ``ovos-workshop``'s dependency floor is a lower bound, so even a pinned
    old workshop resolves today's ``ovos-bus-client``. If that ever stopped
    being true, the receive-side mirror of ``#271`` could not run in the old
    process and the whole compat design would need rethinking — so it is
    asserted rather than assumed.
    """
    _server, _bus, skill, _regs = stack
    client = skill.versions.get("ovos_bus_client", "")
    assert client, f"the skill venv did not report its versions:\n{skill.log}"
    assert int(client.split(".")[0]) >= 2, (
        f"the skill venv resolved ovos-bus-client {client}; the receive-side "
        f"mirror of #271 cannot run there and the compat design does not hold")

    # Recorded, not asserted: this is the switch the xfail above waits for.
    # When it turns True the broken cell starts passing and strict xfail
    # converts that into the loud signal to promote the guard.
    print(f"{COMBO}: skill venv = ovos-workshop "
          f"{skill.versions.get('ovos_workshop')}, ovos-bus-client {client}, "
          f"#271 mirror present={skill.versions.get('has_reemit_hook')}")


def test_core_dispatches_the_topic_this_combo_expects(stack):
    """Positive control on the core half, independent of any handler.

    Proves the dispatch really went out and with which spelling, so a silent
    handler in the broken cell can only mean the handler never heard it.
    """
    _server, bus, _skill, regs = stack
    topic = dispatch_topic_for(_registered_name(regs))
    want = CANONICAL_TOPIC if core_canonicalizes() else LEGACY_TOPIC
    assert topic == want

    seen = Capture(bus, topic)
    try:
        dispatch(bus, topic, food="tacos")
        assert seen.wait(), f"the dispatch on {topic!r} never reached the bus"
    finally:
        seen.close()


@pytest.mark.xfail(IS_BROKEN_CELL, strict=True, reason=_XFAIL_REASON)
def test_the_skill_handler_runs(stack):
    """The contract: a canonical dispatch must reach the skill's handler.

    Emitted exactly the way ``IntentService._dispatch_match`` does — the
    matched topic, forwarded with the utterance data — and observed through
    the marker the skill emits from inside the handler.
    """
    _server, bus, skill, regs = stack
    topic = dispatch_topic_for(_registered_name(regs))

    token = uuid.uuid4().hex
    handled = Capture(bus, "backcompat.skill.handled", token=token)
    spoken = Capture(bus, "speak")
    try:
        bus.emit(Message(topic, {"food": "tacos", "token": token},
                         {"session": {"session_id": "backcompat"}}))
        assert handled.wait(), (
            f"{COMBO}: dispatched {topic!r} but the skill handler never ran.\n"
            f"the skill venv bound: {skill.bound_topics}\n"
            f"skill process log:\n{skill.log}")
        assert handled.messages[0].data["topic"] in (topic, LEGACY_TOPIC)
        assert handled.messages[0].data["data"]["food"] == "tacos"
        assert spoken.wait(), "the handler ran but never spoke"
    finally:
        handled.close()
        spoken.close()


@pytest.mark.xfail(IS_BROKEN_CELL, strict=True, reason=_XFAIL_REASON)
def test_the_handler_runs_exactly_once(stack):
    """A skill bound to both spellings must not answer twice.

    ``new skill/new core`` is where this bites: the skill binds the canonical
    and the suffixed topic, so once the compat mirror of ``#271`` is live the
    same dispatch could reach the same handler down two paths. One utterance,
    one answer.
    """
    _server, bus, skill, regs = stack
    topic = dispatch_topic_for(_registered_name(regs))

    token = uuid.uuid4().hex
    handled = Capture(bus, "backcompat.skill.handled", token=token)
    try:
        bus.emit(Message(topic, {"food": "burritos", "token": token},
                         {"session": {"session_id": "backcompat-once"}}))
        assert handled.wait(), f"{COMBO}: handler never ran for {topic!r}"
        # Keep listening past the first hit: a duplicate arrives late, so an
        # assertion taken the instant the first one lands would never see it.
        time.sleep(3)
        assert len(handled.messages) == 1, (
            f"{COMBO}: one dispatch on {topic!r} produced "
            f"{len(handled.messages)} handler runs "
            f"(skill bound {skill.bound_topics})")
    finally:
        handled.close()


@pytest.mark.skipif(not IS_BROKEN_CELL,
                    reason="the kill switch only has meaning where the "
                           "compat mirror is what makes the handler run")
def test_kill_switch_disables_the_compat_mirror():
    """Inverse control: with ``emit_legacy`` off, the old handler stays silent.

    This is what proves the broken cell above measures the compat bridge and
    not some accident of the fixture. It passes today for the trivial reason
    that no mirror exists; once ``#271`` ships it becomes the real negative
    half of the pair, and a compat-drop PR has to flip the cell above while
    leaving this one green.
    """
    server = BusServer()
    skill = None
    try:
        bus = server.client()
        skill = SkillProcess(SKILL_PYTHON, server.xdg, emit_legacy=False)
        token = uuid.uuid4().hex
        handled = Capture(bus, "backcompat.skill.handled", token=token)
        canonical = Capture(bus, CANONICAL_TOPIC, token=token)
        try:
            bus.emit(Message(CANONICAL_TOPIC, {"food": "tacos", "token": token},
                             {"session": {"session_id": "backcompat-off"}}))
            assert canonical.wait(), "the dispatch never reached the bus"
            assert not handled.wait(5), (
                "the old handler ran with emit_legacy disabled — the compat "
                "mirror is not actually gated by the kill switch")
        finally:
            handled.close()
            canonical.close()
    finally:
        if skill is not None:
            skill.stop()
        server.stop()
