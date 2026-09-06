"""A skill (de)registering mid-round must not break fallback matching.

``registered_fallbacks`` is written by the bus handlers for
``ovos.skills.fallback.register`` / ``.deregister``, which run on the bus
thread, while ``_collect_fallback_skills`` and ``_fallback_range`` read it
on the utterance thread. Reading the live dict raises ``RuntimeError:
dictionary changed size during iteration`` when a skill loads or unloads at
the wrong moment.
"""
import threading
from collections.abc import MutableMapping

from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.fallback_service import (
    FallbackRange,
    FallbackService,
)


class _MutatingRegistry(MutableMapping):
    """Grows partway *through* the first iteration of it.

    Stands in for the bus thread registering a skill at the exact moment
    the utterance thread is walking the registry. The mutation has to land
    between two yields, not before the first one: a mapping that changes
    size before iteration starts is harmless, and only a change during the
    walk raises "dictionary changed size during iteration".

    Deliberately NOT a ``dict`` subclass. ``dict(some_dict_subclass)`` takes
    a C fast path that never calls the subclass's ``items``/``__iter__``, so
    a dict-derived fixture silently stops exercising anything the moment the
    reader snapshots with ``dict(...)``.

    It stays quiet for ``arm_after_walks`` iterations first. The one walk
    the fix is allowed to make over the live registry is the locked
    snapshot, which a real bus-thread writer cannot interleave with because
    it takes the same lock; every walk after that is a reader, and a reader
    is exactly what must never touch the live mapping. So the fixture
    models a concurrent registration landing during a *reader's* walk:
    unpatched there are two such walks and this raises, patched there are
    none.
    """

    def __init__(self, initial=None, arm_after_walks=1):
        self._data = dict(initial or {})
        self._arm_after_walks = arm_after_walks
        self.iterations = 0
        self.mutated = False

    def _walk(self):
        self.iterations += 1
        armed = self.iterations > self._arm_after_walks and not self.mutated
        # iterate the LIVE dict, not a copy: the copy is what makes the bug
        # survivable, so a fixture that copies here cannot reproduce it
        for index, key in enumerate(self._data):
            yield key
            if armed and index == 0:
                self.mutated = True
                self._data["late-arrival"] = 50

    def __iter__(self):
        return self._walk()

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    def __delitem__(self, key):
        del self._data[key]

    def __len__(self):
        return len(self._data)


def _register(service, skill_id, priority=50):
    service.handle_register_fallback(
        Message("ovos.skills.fallback.register",
                {"skill_id": skill_id, "priority": priority}))


def _service(**config):
    return FallbackService(bus=FakeBus(), config=config)


def _armed_service(count=20):
    service = _service()
    for index in range(count):
        _register(service, f"skill{index}")
    service.registered_fallbacks = _MutatingRegistry(service.registered_fallbacks)
    return service


def _utterance():
    return Message("recognizer_loop:utterance",
                   {"utterances": ["test"], "lang": "en-US"})


# an empty range keeps every skill out of `in_range`, so collection returns
# straight after the registry reads -- the lines under test -- without
# waiting for pongs no skill is here to send
EMPTY_RANGE = FallbackRange(1000, 1001)


def test_registration_during_collection_does_not_raise():
    service = _armed_service()

    assert service._collect_fallback_skills(_utterance(), EMPTY_RANGE) == []
    # exactly one walk over the live registry -- the locked snapshot. Any
    # more means a reader is still reading through it.
    assert service.registered_fallbacks.iterations == 1


def test_registration_during_match_does_not_raise():
    service = _armed_service()

    assert service._fallback_range(["test"], "en-US", _utterance(),
                                   EMPTY_RANGE) is None
    assert service.registered_fallbacks.iterations == 1


def test_selection_ranks_on_the_round_snapshot_not_the_live_registry():
    """A priority change between poll and selection must not reorder the round.

    Two skills acknowledge: skill_a at 50, skill_b at 75. The bus thread then
    re-registers skill_a at 999 while the poll is running. Ranking the round's
    own snapshot still picks skill_a; re-reading the live registry would rank
    skill_b (75) ahead of skill_a (999) and pick skill_b instead.
    """
    service = _service()
    _register(service, "skill_a", priority=50)
    _register(service, "skill_b", priority=75)

    seen = {}

    def poll(message, fb_range=None, registry=None):
        seen["round_registry"] = dict(registry or {})
        # the bus thread re-registers skill_a far out of range, right here
        _register(service, "skill_a", priority=999)
        seen["registry_after"] = dict(service.registered_fallbacks)
        return ["skill_a", "skill_b"]

    service._collect_fallback_skills = poll
    service._fallback_allowed = lambda skill_id: True

    match = service._fallback_range(["test"], "en-US", _utterance(),
                                    FallbackRange(0, 100))

    # the live registry really did move underneath the round
    assert seen["registry_after"]["skill_a"] == 999
    assert seen["round_registry"] == {"skill_a": 50, "skill_b": 75}
    # and the winner is the one the ROUND ranked first
    assert match is not None
    assert match.skill_id == "skill_a"


class _CountingLock:
    """A real lock that records how many times it was entered."""

    def __init__(self):
        self._lock = threading.Lock()
        self.entries = 0

    def __enter__(self):
        self._lock.acquire()
        self.entries += 1  # under the lock, so the count is exact
        return self

    def __exit__(self, *exc):
        self._lock.release()
        return False


def test_every_registry_write_goes_through_the_lock():
    """Both writers must take the lock, not just one of them.

    Each worker only touches its own keys, so the surviving key set is the
    same whether or not the writers lock. Counting acquisitions is what
    makes dropping either writer's lock fail.
    """
    service = _service()
    counting = _CountingLock()
    service._registry_lock = counting

    workers, steps = 8, 50
    start = threading.Barrier(workers + 1)
    errors = []

    def worker(index):
        try:
            start.wait(timeout=5)
            for step in range(steps):
                _register(service, f"worker{index}-{step}")
                service.handle_deregister_fallback(
                    Message("ovos.skills.fallback.deregister",
                            {"skill_id": f"worker{index}-{step}"}))
            _register(service, f"survivor{index}")
        except Exception as error:  # pragma: no cover
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(i,), daemon=True)
               for i in range(workers)]
    for thread in threads:
        thread.start()
    start.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=15)

    assert not errors, f"registry writes raised: {errors[0]!r}"
    # 8 workers x (50 registrations + 50 deregistrations + 1 survivor)
    assert counting.entries == workers * (2 * steps + 1)
    assert {f"survivor{i}" for i in range(workers)} <= set(service.registered_fallbacks)
    assert len(service.registered_fallbacks) == workers


def test_snapshot_is_a_copy_not_the_live_registry():
    service = _service()
    _register(service, "skill1")

    snapshot = service._fallback_registry_snapshot()
    _register(service, "skill2")

    assert "skill1" in snapshot
    assert "skill2" not in snapshot
    assert "skill2" in service.registered_fallbacks


def test_priority_override_still_applies():
    service = _service(fallback_priorities={"skill1": 5})
    _register(service, "skill1", priority=90)
    _register(service, "skill2", priority=90)

    assert service.registered_fallbacks["skill1"] == 5
    assert service.registered_fallbacks["skill2"] == 90


def test_deregister_of_unknown_skill_is_a_noop():
    service = _service()
    service.handle_deregister_fallback(
        Message("ovos.skills.fallback.deregister", {"skill_id": "nope"}))
    assert service.registered_fallbacks == {}
