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
    on ``<pipeline_id>:global_stop``. When the bus's ovos-spec-tools namespace
    translator is active (``modernize``/``emit_legacy``, default ``True`` on
    both ``MessageBusClient`` and ``FakeBus``) it ALREADY bridges both,
    receive-side, onto the legacy topics a skill still honours: ``ovos.stop``
    mirrors onto ``mycroft.stop`` and ``<skill_id>:stop`` mirrors onto
    ``<skill_id>.stop`` — confirmed via
    ``NamespaceTranslator().counterpart_topics(...)``. In that case this bridge
    must NOT ALSO re-emit those two topics: doing so double-delivers to every
    legacy skill's ``stop()`` (executed proof: a handler bound to both
    ``mycroft.stop`` and ``<skill_id>.stop`` saw
    ``['mycroft.stop', 'mycroft.stop']`` for one global stop before this fix).
    When the translator is inactive or absent (deployments still running
    without it), the mirroring above does not happen at all, so this shim's
    own ``mycroft.stop`` / ``<skill_id>.stop`` re-emission is the ONLY thing
    providing that compatibility surface and must still fire —
    :meth:`_legacy_topics_already_bridged` decides which regime applies, once,
    at construction.

    It is fully self-contained and holds no place in the spec path: it observes
    the OVOS-PIPELINE-1 §9.2 ``ovos.intent.matched`` notification and
    unconditionally re-emits the pre-spec ``stop:global`` / ``stop:skill``
    core-internal observer topics — spellings the translator never maps
    (``NamespaceTranslator().is_migrated("stop:global")`` is ``False``, tested
    against the installed ovos-spec-tools), so they always need this shim.
    """

    #: Identity the pre-spec dispatch reported for the stop plugin itself.
    LEGACY_SKILL_ID = "stop.openvoiceos"

    def __init__(self, service) -> None:
        self.service = service
        self.bus = service.bus
        self._warned = False
        #: whether the bus's NamespaceTranslator already mirrors mycroft.stop /
        #: <skill_id>.stop for us — decided once, at construction, since the
        #: translator's config does not change over the bridge's lifetime.
        self._legacy_topics_already_bridged = self._detect_translator_bridging()
        self.bus.on(SpecMessage.INTENT_MATCHED.value, self._on_intent_matched)
        self.bus.on("stop:global", self.handle_global_stop)
        self.bus.on("stop:skill", self.handle_skill_stop)

    def _detect_translator_bridging(self) -> bool:
        """Whether ``self.bus`` already mirrors ``mycroft.stop`` for us.

        ``is_migrated`` is a *structural* check (does this topic pair exist at
        all) and stays True regardless of the ``modernize``/``emit_legacy``
        flags, so it cannot answer this. ``counterpart_topics`` IS flag-aware:
        emitting the spec ``ovos.stop`` only mirrors onto legacy
        ``mycroft.stop`` when ``emit_legacy`` is set — exactly the direction
        this bridge cares about (StopService emits the spec topic; the
        question is whether the translator alone gets it to legacy
        subscribers). Reads the ``NamespaceTranslator`` both
        ``MessageBusClient`` and ``FakeBus`` carry as ``_translator``.
        Defensive: a bus without one (unknown bus implementation) is treated
        as NOT bridging, so this shim falls back to its own re-emission rather
        than silently dropping legacy compatibility.
        """
        translator = getattr(self.bus, "_translator", None)
        counterpart_topics = getattr(translator, "counterpart_topics", None)
        if counterpart_topics is None:
            return False
        return "mycroft.stop" in counterpart_topics(SpecMessage.STOP.value)

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
        """Legacy ``stop:global`` handler — re-emits ``mycroft.stop`` ONLY when
        the translator is not already doing it (see class docstring)."""
        with HandlerLifecycle(self.bus, message,
                              skill_id=self.LEGACY_SKILL_ID,
                              data={"name": "StopService.handle_global_stop"}):
            if not self._legacy_topics_already_bridged:
                self.bus.emit(message.forward("mycroft.stop"))

    def handle_skill_stop(self, message: Message) -> None:
        """Legacy ``stop:skill`` handler — re-emits ``<skill_id>.stop`` ONLY
        when the translator is not already doing it (see class docstring)."""
        skill_id = message.data.get("skill_id")
        if not skill_id:
            LOG.warning("stop:skill received without a skill_id; dropping")
            return
        with HandlerLifecycle(self.bus, message,
                              skill_id=self.LEGACY_SKILL_ID,
                              data={"name": "StopService.handle_skill_stop"}):
            if not self._legacy_topics_already_bridged:
                self.bus.emit(message.reply(f"{skill_id}.stop"))

    def shutdown(self) -> None:
        """Remove the legacy bus listeners registered by this shim."""
        self.bus.remove(SpecMessage.INTENT_MATCHED.value, self._on_intent_matched)
        self.bus.remove("stop:global", self.handle_global_stop)
        self.bus.remove("stop:skill", self.handle_skill_stop)
