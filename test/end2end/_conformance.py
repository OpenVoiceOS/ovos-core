"""Shared helpers for the OVOS architecture-spec conformance suites.

These suites encode the normative *Conformance* clauses of the OVOS formal
specifications (``ovos/org/architecture/ovos-*.md``) as ovoscope end-to-end
assertions against the ovos-core orchestrator.

The leading underscore keeps pytest from collecting this module as a test
file; it only provides capture helpers the ``test_*_conformance.py`` suites
import.

Driver model
------------
The pure-python ``padacioso`` matcher drives intent dispatch. Intents are
registered directly on the bus with :func:`ovoscope.register_padatious_intent`
so no skill packages or native matchers are required. The in-core stop
pipeline drives the stop-cascade clauses. Both are deterministic on a
``FakeBus``.

xfail discipline
----------------
A conformance test asserts the **spec's** topic name / message shape. Where
ovos-core currently emits a legacy ``mycroft.*`` (or colon-shaped) name — the
``mycroft.* -> ovos.*`` migration is pending — the test is decorated
``@pytest.mark.xfail(strict=False, reason=...)`` citing the legacy name and the
spec clause it should meet. It flips to a pass automatically once the impl is
updated. Tests with no xfail assert clauses the orchestrator already satisfies.
"""
import time
from typing import List, Optional

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_config.config import Configuration
from ovos_spec_tools import SpecMessage

# The spec-namespace entry topic the IntentService subscribes to
# (``IntentService.bus.on(SpecMessage.UTTERANCE, ...)``). The conformance
# suites run with ``legacy_namespace=False`` (see :func:`use_spec_namespace`),
# so core handles the utterance natively on this topic — injecting on the
# legacy ``recognizer_loop:utterance`` would never reach the handler.
ENTRY_TOPIC = SpecMessage.UTTERANCE.value  # "ovos.utterance.handle"


def use_spec_namespace():
    """Switch ovos-core to the spec (``ovos.*``) bus namespace.

    The conformance suites assert the spec topic names, so they flip the
    deployment ``legacy_namespace`` config off. Call from ``setUpModule``.
    """
    Configuration()["legacy_namespace"] = False


def reset_namespace():
    """Restore the default legacy bus namespace. Call from ``tearDownModule``."""
    Configuration()["legacy_namespace"] = True

PADACIOSO_HIGH = "ovos-padacioso-pipeline-plugin-high"
STOP_HIGH = "ovos-stop-pipeline-plugin-high"


def utterance(text: str, session_id: str, pipeline: List[str],
              lang: str = "en-US", **session_fields) -> Message:
    """Build a ``recognizer_loop:utterance`` entry message for one session."""
    sess = Session(session_id)
    sess.lang = lang
    sess.pipeline = pipeline
    for key, value in session_fields.items():
        setattr(sess, key, value)
    return Message(ENTRY_TOPIC,
                   {"utterances": [text], "lang": lang},
                   {"session": sess.serialize(), "source": "A", "destination": "B"})


def capture(mc, message: Message, timeout: float = 5.0) -> List[Message]:
    """Emit ``message`` and return every bus Message seen within ``timeout``.

    Subscribes to the FakeBus catch-all so the full ordered sequence — entry,
    activation, dispatch, terminal events — is captured regardless of which
    clause a given test inspects.
    """
    recs: List[Message] = []

    def _rec(serialized):
        try:
            recs.append(Message.deserialize(serialized)
                        if isinstance(serialized, str) else serialized)
        except Exception:
            pass

    mc.bus.on("message", _rec)
    try:
        mc.bus.emit(message)
        time.sleep(timeout)
    finally:
        mc.bus.remove("message", _rec)
    return recs


def types(recs: List[Message]) -> List[str]:
    """The ordered list of ``msg_type`` strings."""
    return [m.msg_type for m in recs]


def first(recs: List[Message], msg_type: str) -> Optional[Message]:
    """First captured Message of ``msg_type``, or ``None``."""
    return next((m for m in recs if m.msg_type == msg_type), None)
