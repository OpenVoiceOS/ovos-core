"""OVOS-INTENT-4 conformance suite.

Encodes the normative *Conformance* clauses (§11) and the registration bus
surface (§4) of OVOS-INTENT-4 (``ovos/org/architecture/ovos-intent-4.md``) as
ovoscope end-to-end assertions against the ovos-core orchestrator.

INTENT-4 defines a fixed set of registration topics under ``ovos.intent.*`` /
``ovos.entity.*`` and an orchestrator-served introspection manifest
(``ovos.intent.list`` / ``ovos.intent.describe``). ovos-core does not yet expose
this bus contract — intent registration is in-process / plugin-specific
(``padatious:register_intent``) and introspection is the legacy
``intent.service.intent.get``. This suite therefore asserts the spec topics
directly: the §2 fire-and-forget rule already holds (green); the registration,
deregistration and introspection topics are pending (xfail) and flip to passing
once the contract lands. The xfail discipline is described in ``_conformance.py``.

Coverage map (clause -> status against current ovos-core):
- §2   registrations are fire-and-forget (no ack / no .response) .. green
- §5   ``ovos.intent.register.keyword`` makes an intent matchable . xfail
- §6   ``ovos.intent.register.template`` makes an intent matchable . xfail
- §7   ``ovos.entity.register`` value-set hint ................... xfail
- §8.2 ``ovos.intent.deregister`` removes an intent .............. xfail
- §8.3 ``ovos.entity.deregister`` removes an entity .............. xfail
- §8.4 ``ovos.skill.deregister`` removes a whole skill ........... xfail
- §8.5 ``ovos.intent.disable`` suppresses an intent .............. xfail
- §8.5 ``ovos.intent.enable`` re-arms a disabled intent .......... xfail
- §10.1 ``ovos.intent.list`` introspection responds ............. xfail
- §10.2 ``ovos.intent.describe`` introspection responds ......... xfail
"""
import time
from unittest import TestCase

import pytest
from ovos_bus_client.message import Message
from ovos_utils.log import LOG

from ovoscope import (
    get_minicroft,
    register_padatious_entity,
    register_padatious_intent,
)

from ._conformance import PADACIOSO_HIGH, capture, types, utterance

KEYWORD_INTENT = "intent4.skill:lights_off"
KEYWORD_SKILL, KEYWORD_NAME = KEYWORD_INTENT.split(":")
KEYWORD_SAMPLES = ["turn off the lights", "switch off the lights", "lights off please"]

ENTITY_NAME = "intent4.skill:color"
ENTITY_SAMPLES = ["red", "green", "blue"]

_MC = None

TEMPLATE_INTENT = "intent4.skill:lights_on"
TEMPLATE_SKILL, TEMPLATE_NAME = TEMPLATE_INTENT.split(":")
TEMPLATE_SAMPLES = ["turn on the lights", "switch on the lights", "lights on please"]


def setUpModule():
    global _MC
    LOG.set_level("CRITICAL")
    _MC = get_minicroft([])
    time.sleep(1)


def tearDownModule():
    if _MC is not None:
        _MC.stop()


def _register_template(topic: str, intent: str, samples):
    """Emit a §6 template-registration payload on the given topic."""
    skill_id, intent_name = intent.split(":")
    _MC.bus.emit(Message(topic, {
        "skill_id": skill_id,
        "intent_name": intent_name,
        "lang": "en-US",
        "samples": samples,
    }, {"skill_id": skill_id}))
    time.sleep(1.5)


# ─────────────────────────────────────────────────────────────────────────────
# §2 — Registrations are fire-and-forget
# ─────────────────────────────────────────────────────────────────────────────

class TestSec2FireAndForget(TestCase):
    """§2: registration is broadcast and fire-and-forget — there is no
    ``.response`` reply, no acknowledgement, and no error event."""

    def test_no_ack_for_registration(self):
        """Emitting a registration produces no ``.response`` / ack on the bus (§2)."""
        recs = capture(
            _MC,
            Message("ovos.intent.register.template", {
                "skill_id": TEMPLATE_SKILL,
                "intent_name": TEMPLATE_NAME,
                "lang": "en-US",
                "samples": TEMPLATE_SAMPLES,
            }, {"skill_id": TEMPLATE_SKILL}),
            2.0,
        )
        acks = [t for t in types(recs)
                if t.endswith(".response") or t == "ovos.intent.register.template.response"]
        self.assertEqual(acks, [], f"unexpected acknowledgement(s): {acks}")


# ─────────────────────────────────────────────────────────────────────────────
# §6 / §8 — Registration and deregistration bus contract
# ─────────────────────────────────────────────────────────────────────────────

class TestSec6TemplateRegistration(TestCase):
    """§6: a template intent registered on ``ovos.intent.register.template``
    becomes matchable; a match dispatches ``<skill_id>:<intent_name>``."""

    @pytest.mark.xfail(strict=False,
                       reason="ovos-core consumes registrations via the legacy "
                              "'padatious:register_intent'; INTENT-4 §6 defines "
                              "'ovos.intent.register.template'")
    def test_spec_topic_registration_is_matchable(self):
        """Registering via the spec topic makes the intent matchable (§6)."""
        _register_template("ovos.intent.register.template", TEMPLATE_INTENT, TEMPLATE_SAMPLES)
        recs = capture(
            _MC,
            utterance("turn on the lights", "i4-tmpl", [PADACIOSO_HIGH]),
            3.0,
        )
        self.assertIn(TEMPLATE_INTENT, types(recs))


class TestSec82Deregister(TestCase):
    """§8.2: ``ovos.intent.deregister`` removes one intent so it no longer
    matches."""

    @pytest.mark.xfail(strict=False,
                       reason="ovos-core does not consume 'ovos.intent.deregister'; "
                              "INTENT-4 §8.2")
    def test_spec_deregister_removes_intent(self):
        """After a spec-topic deregister, the intent must no longer match (§8.2)."""
        # register via the working mechanism so there is something to remove
        register_padatious_intent(_MC.bus, TEMPLATE_INTENT, TEMPLATE_SAMPLES)
        time.sleep(1.5)
        _MC.bus.emit(Message("ovos.intent.deregister", {
            "skill_id": TEMPLATE_SKILL, "intent_name": TEMPLATE_NAME, "lang": "en-US",
        }, {"skill_id": TEMPLATE_SKILL}))
        time.sleep(1.5)
        recs = capture(
            _MC,
            utterance("turn on the lights", "i4-dereg", [PADACIOSO_HIGH]),
            3.0,
        )
        self.assertNotIn(TEMPLATE_INTENT, types(recs))


class TestSec85Disable(TestCase):
    """§8.5: ``ovos.intent.disable`` temporarily suppresses an intent without
    removing its definition."""

    @pytest.mark.xfail(strict=False,
                       reason="ovos-core does not consume 'ovos.intent.disable'; "
                              "INTENT-4 §8.5")
    def test_spec_disable_suppresses_intent(self):
        """A disabled intent is excluded from match candidacy (§8.5)."""
        register_padatious_intent(_MC.bus, TEMPLATE_INTENT, TEMPLATE_SAMPLES)
        time.sleep(1.5)
        _MC.bus.emit(Message("ovos.intent.disable", {
            "skill_id": TEMPLATE_SKILL, "intent_name": TEMPLATE_NAME, "lang": "en-US",
        }, {"skill_id": TEMPLATE_SKILL}))
        time.sleep(1.5)
        recs = capture(
            _MC,
            utterance("turn on the lights", "i4-disable", [PADACIOSO_HIGH]),
            3.0,
        )
        self.assertNotIn(TEMPLATE_INTENT, types(recs))


# ─────────────────────────────────────────────────────────────────────────────
# §5 — Keyword-intent registration
# ─────────────────────────────────────────────────────────────────────────────

class TestSec5KeywordRegistration(TestCase):
    """§5: a keyword intent registered on ``ovos.intent.register.keyword``
    becomes matchable; a match dispatches ``<skill_id>:<intent_name>``."""

    @pytest.mark.xfail(strict=False,
                       reason="ovos-core consumes keyword registration via the legacy "
                              "'padatious:register_intent'/'register_intent'; INTENT-4 "
                              "§5 defines 'ovos.intent.register.keyword'")
    def test_spec_keyword_registration_is_matchable(self):
        """Registering via the spec keyword topic makes the intent matchable (§5)."""
        _MC.bus.emit(Message("ovos.intent.register.keyword", {
            "skill_id": KEYWORD_SKILL,
            "intent_name": KEYWORD_NAME,
            "lang": "en-US",
            "samples": KEYWORD_SAMPLES,
        }, {"skill_id": KEYWORD_SKILL}))
        time.sleep(1.5)
        recs = capture(
            _MC,
            utterance("turn off the lights", "i4-kw", [PADACIOSO_HIGH]),
            3.0,
        )
        self.assertIn(KEYWORD_INTENT, types(recs))


# ─────────────────────────────────────────────────────────────────────────────
# §7 — Entity (value-set) registration
# ─────────────────────────────────────────────────────────────────────────────

class TestSec7EntityRegistration(TestCase):
    """§7: ``ovos.entity.register`` registers a value-set hint that the matcher
    can resolve as a named slot. Registration is fire-and-forget (§2)."""

    @pytest.mark.xfail(strict=False,
                       reason="ovos-core consumes entity registration via the legacy "
                              "'padatious:register_entity'/'register_vocab'; INTENT-4 "
                              "§7 defines 'ovos.entity.register'")
    def test_spec_entity_registration_no_ack(self):
        """Emitting an entity registration on the spec topic produces no ack and is
        accepted by an INTENT-4 consumer (§7, §2)."""
        recs = capture(_MC, Message("ovos.entity.register", {
            "skill_id": ENTITY_NAME.split(":")[0],
            "name": ENTITY_NAME,
            "lang": "en-US",
            "samples": ENTITY_SAMPLES,
        }, {"skill_id": ENTITY_NAME.split(":")[0]}), 2.0)
        acks = [t for t in types(recs) if t.endswith(".response")]
        self.assertEqual(acks, [], f"unexpected acknowledgement(s): {acks}")
        # an INTENT-4 consumer must not reject a well-formed entity payload
        self.assertNotIn("ovos.entity.register.error", types(recs))


# ─────────────────────────────────────────────────────────────────────────────
# §8.3 / §8.4 — Entity and whole-skill deregistration
# ─────────────────────────────────────────────────────────────────────────────

class TestSec83EntityDeregister(TestCase):
    """§8.3: ``ovos.entity.deregister`` removes one entity value-set hint."""

    @pytest.mark.xfail(strict=False,
                       reason="ovos-core does not consume 'ovos.entity.deregister'; "
                              "INTENT-4 §8.3")
    def test_spec_entity_deregister_no_error(self):
        """A spec-topic entity deregister is consumed without an error event (§8.3)."""
        register_padatious_entity(_MC.bus, ENTITY_NAME, ENTITY_SAMPLES)
        time.sleep(1.0)
        recs = capture(_MC, Message("ovos.entity.deregister", {
            "skill_id": ENTITY_NAME.split(":")[0],
            "name": ENTITY_NAME, "lang": "en-US",
        }, {"skill_id": ENTITY_NAME.split(":")[0]}), 2.0)
        self.assertNotIn("ovos.entity.deregister.error", types(recs))


class TestSec84SkillDeregister(TestCase):
    """§8.4: ``ovos.skill.deregister`` removes every intent and entity registered
    under one ``skill_id`` in a single broadcast."""

    @pytest.mark.xfail(strict=False,
                       reason="ovos-core removes a skill's registrations via the legacy "
                              "'detach_skill'; INTENT-4 §8.4 defines 'ovos.skill.deregister'")
    def test_spec_skill_deregister_removes_all_intents(self):
        """After a spec-topic skill deregister, none of the skill's intents match (§8.4)."""
        register_padatious_intent(_MC.bus, KEYWORD_INTENT, KEYWORD_SAMPLES)
        time.sleep(1.5)
        _MC.bus.emit(Message("ovos.skill.deregister", {
            "skill_id": KEYWORD_SKILL,
        }, {"skill_id": KEYWORD_SKILL}))
        time.sleep(1.5)
        recs = capture(
            _MC,
            utterance("turn off the lights", "i4-skilldereg", [PADACIOSO_HIGH]),
            3.0,
        )
        self.assertNotIn(KEYWORD_INTENT, types(recs))


# ─────────────────────────────────────────────────────────────────────────────
# §8.5 — Enable re-arms a disabled intent
# ─────────────────────────────────────────────────────────────────────────────

class TestSec85Enable(TestCase):
    """§8.5: ``ovos.intent.enable`` re-arms an intent previously suppressed by
    ``ovos.intent.disable``, restoring its match candidacy."""

    @pytest.mark.xfail(strict=False,
                       reason="ovos-core does not consume 'ovos.intent.disable'/"
                              "'ovos.intent.enable'; INTENT-4 §8.5")
    def test_spec_enable_rearms_intent(self):
        """A disabled-then-enabled intent matches again (§8.5)."""
        register_padatious_intent(_MC.bus, KEYWORD_INTENT, KEYWORD_SAMPLES)
        time.sleep(1.5)
        _MC.bus.emit(Message("ovos.intent.disable", {
            "skill_id": KEYWORD_SKILL, "intent_name": KEYWORD_NAME, "lang": "en-US",
        }, {"skill_id": KEYWORD_SKILL}))
        time.sleep(1.0)
        _MC.bus.emit(Message("ovos.intent.enable", {
            "skill_id": KEYWORD_SKILL, "intent_name": KEYWORD_NAME, "lang": "en-US",
        }, {"skill_id": KEYWORD_SKILL}))
        time.sleep(1.0)
        recs = capture(
            _MC,
            utterance("turn off the lights", "i4-enable", [PADACIOSO_HIGH]),
            3.0,
        )
        self.assertIn(KEYWORD_INTENT, types(recs))


# ─────────────────────────────────────────────────────────────────────────────
# §10 — Orchestrator-owned introspection manifest
# ─────────────────────────────────────────────────────────────────────────────

class TestSec10Introspection(TestCase):
    """§10 / §11: the orchestrator MUST serve ``ovos.intent.list`` and
    ``ovos.intent.describe`` against its passive registration manifest."""

    @pytest.mark.xfail(strict=False,
                       reason="ovos-core serves the legacy 'intent.service.intent.get'; "
                              "INTENT-4 §10.1 defines 'ovos.intent.list'")
    def test_intent_list_responds(self):
        """A query on ``ovos.intent.list`` yields an ``ovos.intent.list.response`` (§10.1)."""
        recs = capture(_MC, Message("ovos.intent.list", {}, {"source": "A"}), 2.0)
        self.assertIn("ovos.intent.list.response", types(recs))

    @pytest.mark.xfail(strict=False,
                       reason="ovos-core does not serve 'ovos.intent.describe'; "
                              "INTENT-4 §10.2")
    def test_intent_describe_responds(self):
        """A query on ``ovos.intent.describe`` yields an
        ``ovos.intent.describe.response`` (§10.2)."""
        recs = capture(_MC, Message("ovos.intent.describe", {
            "skill_id": TEMPLATE_SKILL, "intent_name": TEMPLATE_NAME, "lang": "en-US",
        }, {"source": "A"}), 2.0)
        self.assertIn("ovos.intent.describe.response", types(recs))
