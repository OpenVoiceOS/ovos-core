"""End-to-end suite config: keep the §8.3 handler-timeout backstop short.

The orchestrator (``IntentService``) blocks on each matched handler's §8 terminal
before emitting the §9.5 ``ovos.utterance.handled`` end-marker. In production the
backstop is 5 minutes (``DEFAULT_HANDLER_TIMEOUT``); in this suite every handler
reports within a second — or is explicitly stopped — so a long backstop only buys a
slow hang if a done-signal is ever dropped. Pin it low so such a regression fails
fast (a few seconds) instead of stalling the whole run.
"""
import ovos_core.intent_services.service as _service

#: seconds — generous vs. the sub-second e2e handlers, tiny vs. the 300s default
_service.DEFAULT_HANDLER_TIMEOUT = 10
