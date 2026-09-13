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

CANONICAL_POLL = {"ovos.fallback.ping", "ovos.fallback.pong"}


def emitted_topics() -> set:
    """Every string literal in the fallback service that names a bus topic."""
    tree = ast.parse(Path(fallback_service.__file__).read_text())
    return {node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value.startswith("ovos.")}


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
        canonical = emitted_topics() & CANONICAL_POLL
        if not canonical:
            self.skipTest("the fallback poll still uses its legacy spelling")
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
        for topic in ("ovos.skills.fallback.ping", "ovos.skills.fallback.pong"):
            self.assertIsNotNone(migration_counterpart(topic), topic)
