"""Droppable backward-compatibility shim for the pre-OVOS-STOP-1 dispatch surface.

This whole module is removed in one move — together with its import and the
``self._legacy = _LegacyStopBridge(self)`` wiring in ``StopService`` — once
every skill consumes the spec ``<skill_id>:stop`` and ``ovos.stop`` topics
directly. It holds no place in the STOP-1 spec path.
"""
from typing import Dict, Optional

from ovos_bus_client.handler import HandlerLifecycle
from ovos_bus_client.message import Message
from ovos_spec_tools import SpecMessage
from ovos_utils.log import LOG

from ovos_core.version import VERSION_MAJOR

#: Removal is scheduled for the next major release; derived from version.py so
#: the deprecation notice never goes stale.
_LEGACY_BRIDGE_REMOVAL_VERSION = f"{VERSION_MAJOR + 1}.0.0"


class _LegacyStopBridge:
    """Backward-compatibility shim reproducing the pre-OVOS-STOP-1 dispatch surface.

    STOP-1 dispatches a targeted stop on ``<skill_id>:stop`` and a global stop
    on ``<pipeline_id>:global_stop``. The ovos-spec-tools namespace translator
    bridges ``<skill_id>:stop`` to the legacy ``<skill_id>.stop`` a skill still
    honours; deployments that additionally observe the pre-spec ``stop:global``
    / ``stop:skill`` dispatch topics, or that run without the translator active,
    keep working through this shim.

    It is fully self-contained and holds no place in the spec path: it observes
    the OVOS-PIPELINE-1 §9.2 ``ovos.intent.matched`` notification, re-emits the
    legacy dispatch, and owns the legacy ``stop:global`` / ``stop:skill``
    handlers that fan out to ``mycroft.stop`` and ``<skill_id>.stop``.
    """

    #: Identity the pre-spec dispatch reported for the stop plugin itself.
    LEGACY_SKILL_ID = "stop.openvoiceos"

    def __init__(self, service) -> None:
        self.service = service
        self.bus = service.bus
        self._warned = False
        self.bus.on(SpecMessage.INTENT_MATCHED.value, self._on_intent_matched)
        self.bus.on("stop:global", self.handle_global_stop)
        self.bus.on("stop:skill", self.handle_skill_stop)

    def _forward_legacy(self, message: Message, msg_type: str,
                        data: Optional[Dict] = None) -> Message:
        """Forward *message* onto a legacy *msg_type*, restamping the legacy identity."""
        msg = message.forward(msg_type, data or {})
        msg.context["skill_id"] = self.LEGACY_SKILL_ID
        return msg

    def _on_intent_matched(self, message: Message) -> None:
        """Re-emit the pre-spec dispatch for a STOP-1 Match (§9.2 observer)."""
        if not (message.data.get("pipeline_id") or "").startswith(self.service.pipeline_id):
            return
        intent_name = message.data.get("intent_name") or ""
        if not self._warned:
            self._warned = True
            LOG.warning(
                "Re-emitting the pre-STOP-1 stop:global/stop:skill dispatch for "
                "backward compatibility; this bridge is removed in ovos-core "
                f"{_LEGACY_BRIDGE_REMOVAL_VERSION}. Migrate skills to consume "
                "'<skill_id>:stop' and 'ovos.stop' directly.")
        if intent_name.endswith(":global_stop"):
            self.bus.emit(self._forward_legacy(message, f"{self.LEGACY_SKILL_ID}.activate"))
            self.bus.emit(self._forward_legacy(message, "stop:global"))
        elif intent_name.endswith(":stop"):
            skill_id = message.data.get("skill_id")
            self.bus.emit(self._forward_legacy(message, f"{self.LEGACY_SKILL_ID}.activate"))
            self.bus.emit(self._forward_legacy(message, "stop:skill", {"skill_id": skill_id}))

    def handle_global_stop(self, message: Message) -> None:
        """Legacy ``stop:global`` handler — emit the pre-spec ``mycroft.stop``."""
        with HandlerLifecycle(self.bus, message,
                              skill_id=self.LEGACY_SKILL_ID,
                              data={"name": "StopService.handle_global_stop"}):
            self.bus.emit(message.forward("mycroft.stop"))

    def handle_skill_stop(self, message: Message) -> None:
        """Legacy ``stop:skill`` handler — re-emit the skill-directed ``<skill_id>.stop``."""
        skill_id = message.data["skill_id"]
        with HandlerLifecycle(self.bus, message,
                              skill_id=self.LEGACY_SKILL_ID,
                              data={"name": "StopService.handle_skill_stop"}):
            self.bus.emit(message.reply(f"{skill_id}.stop"))

    def shutdown(self) -> None:
        """Remove the legacy bus listeners registered by this shim."""
        self.bus.remove(SpecMessage.INTENT_MATCHED.value, self._on_intent_matched)
        self.bus.remove("stop:global", self.handle_global_stop)
        self.bus.remove("stop:skill", self.handle_skill_stop)
