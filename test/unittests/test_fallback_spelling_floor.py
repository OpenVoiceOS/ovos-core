"""The fallback poll may only switch to its canonical spelling once the
declared ovos-spec-tools floor can build the legacy wire twin.

OVOS-FALLBACK-1 §6.1 names the poll pair `ovos.fallback.ping` and
`ovos.fallback.pong`. Every shipped FallbackSkill subscribes to the legacy
`ovos.skills.fallback.ping` alone, so once this service emits the canonical
spelling the only thing that still reaches those skills is the legacy twin that
ovos-bus-client puts on the wire. That twin is built from the migration map in
*this* process's ovos-spec-tools, so a floor below the release carrying the
FALLBACK-1 renames means no twin, no answer, and nothing in the logs.
"""
import ast
import unittest
from importlib.metadata import requires
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

import ovos_core.intent_services.fallback_service as fallback_service

# The first ovos-spec-tools release whose migration map carries the four
# OVOS-FALLBACK-1 renames.
MAP_FLOOR = Version("1.12.0a1")

# The poll pair as OVOS-FALLBACK-1 section 6.1 spells it, written out here
# rather than read from ovos-spec-tools, so the expectation does not come
# from the code under test.
CANONICAL_POLL = {"ovos.fallback.ping", "ovos.fallback.pong"}
LEGACY_POLL = {"ovos.skills.fallback.ping", "ovos.skills.fallback.pong"}

# The ovos-spec-tools SpecMessage members that carry the canonical poll pair.
# A switch written as SpecMessage.FALLBACK_PING, SpecMessage["FALLBACK_PING"]
# or getattr(SpecMessage, "FALLBACK_PING") instead of a string literal is the
# same switch, and it needs the same floor. SpecMessage("ovos.fallback.ping")
# is already caught as a string literal.
CANONICAL_POLL_MEMBERS = {"FALLBACK_PING": "ovos.fallback.ping",
                          "FALLBACK_PONG": "ovos.fallback.pong"}


def emitted_topics() -> set:
    """Every bus topic the fallback service names: string literals that start
    with "ovos.", and FALLBACK_PING / FALLBACK_PONG member uses (attribute,
    subscript or getattr name) counted as the canonical topic they carry."""
    tree = ast.parse(Path(fallback_service.__file__).read_text())
    topics = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("ovos."):
                topics.add(node.value)
            elif node.value in CANONICAL_POLL_MEMBERS:
                topics.add(CANONICAL_POLL_MEMBERS[node.value])
        elif isinstance(node, ast.Attribute) and node.attr in CANONICAL_POLL_MEMBERS:
            topics.add(CANONICAL_POLL_MEMBERS[node.attr])
    return topics


def declared_floor() -> Version:
    for raw in requires("ovos-core") or []:
        req = Requirement(raw)
        if req.name != "ovos-spec-tools":
            continue
        floors = [Version(s.version) for s in req.specifier if s.operator == ">="]
        if floors:
            return max(floors)
    raise AssertionError("ovos-core does not declare ovos-spec-tools")


class TestFallbackSpellingFloor(unittest.TestCase):
    def test_canonical_poll_requires_the_mapping_floor(self):
        topics = emitted_topics()
        canonical = topics & CANONICAL_POLL
        if not canonical:
            # No canonical spelling yet: the service must still name the
            # legacy pair every shipped FallbackSkill answers, or the poll
            # has no answer at all.
            self.assertTrue(
                LEGACY_POLL <= topics,
                f"the fallback service names neither poll spelling: {sorted(topics)}")
            return
        self.assertGreaterEqual(
            declared_floor(), MAP_FLOOR,
            f"{sorted(canonical)} is emitted, so the legacy twin has to be "
            f"built here, which needs ovos-spec-tools>={MAP_FLOOR}")

    def test_the_floor_release_maps_the_poll_pair(self):
        """MAP_FLOOR is a claim about a published release; hold it to it."""
        from ovos_spec_tools import migration_counterpart
        from ovos_spec_tools.version import VERSION_MAJOR, VERSION_MINOR, \
            VERSION_BUILD, VERSION_ALPHA
        installed = Version(f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_BUILD}"
                            + (f"a{VERSION_ALPHA}" if VERSION_ALPHA else ""))
        if installed < MAP_FLOOR:
            self.skipTest(f"installed ovos-spec-tools {installed} predates the floor")
        expected = {"ovos.skills.fallback.ping": "ovos.fallback.ping",
                    "ovos.skills.fallback.pong": "ovos.fallback.pong"}
        for legacy, canonical in expected.items():
            self.assertEqual(migration_counterpart(legacy), canonical, legacy)
