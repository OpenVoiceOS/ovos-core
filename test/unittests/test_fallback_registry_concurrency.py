"""A skill (de)registering mid-round must not break fallback matching.

``registered_fallbacks`` is written by the bus handlers for
``ovos.skills.fallback.register`` / ``.deregister``, which run on the bus
thread, while ``_collect_fallback_skills`` and ``_fallback_range`` read it
on the utterance thread. Reading the live dict raises ``RuntimeError:
dictionary changed size during iteration`` when a skill loads or unloads at
the wrong moment.
"""
from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

from ovos_core.intent_services.fallback_service import (
    FallbackRange,
    FallbackService,
)


class _MutatingRegistry(dict):
    """Grows partway *through* the first iteration of it.

    Stands in for the bus thread registering a skill at the exact moment
    the utterance thread is walking the registry. The mutation has to land
    between two yields, not before the first one: a dict that changes size
    before iteration starts is harmless, and only a change during the walk
    raises "dictionary changed size during iteration".
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.armed = True

    def _walk(self):
        armed = self.armed
        self.armed = False
        for index, key in enumerate(dict.__iter__(self)):
            yield key
            if armed and index == 0:
                dict.__setitem__(self, "late-arrival", 50)

    def items(self):
        return ((key, dict.__getitem__(self, key)) for key in self._walk())

    def __iter__(self):
        return self._walk()


def _register(service, skill_id, priority=50):
    service.handle_register_fallback(
        Message("ovos.skills.fallback.register",
                {"skill_id": skill_id, "priority": priority}))


def _service(**config):
    return FallbackService(bus=FakeBus(), config=config)


def test_registration_during_collection_does_not_raise():
    service = _service()
    for index in range(20):
        _register(service, f"skill{index}")
    service.registered_fallbacks = _MutatingRegistry(service.registered_fallbacks)

    message = Message("recognizer_loop:utterance",
                      {"utterances": ["test"], "lang": "en-US"})
    # an empty range keeps every skill out of `in_range`, so this returns
    # straight after the registry reads -- the lines under test -- without
    # waiting for pongs no skill is here to send
    result = service._collect_fallback_skills(message, FallbackRange(1000, 1001))

    assert result == []


def test_registration_during_match_does_not_raise():
    service = _service()
    for index in range(20):
        _register(service, f"skill{index}")
    service.registered_fallbacks = _MutatingRegistry(service.registered_fallbacks)

    message = Message("recognizer_loop:utterance",
                      {"utterances": ["test"], "lang": "en-US"})
    assert service._fallback_range(["test"], "en-US", message,
                                   FallbackRange(1000, 1001)) is None


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
