"""OVOS-READY-1: a boot-readiness gate for the utterance lifecycle.

While the orchestrator is not yet ready, an utterance must not enter the
pipeline loop at all -- a pipeline's bounded match call (OVOS-PIPELINE-1
``4.4``) can legally exceed its bound from boot contention alone, get
declined as designed, and fall through to the next pipeline. For a mid-
conversation utterance (a bare "yes") that can match an unrelated literal
entity instead of continuing the conversation it belonged to. See
OpenVoiceOS/ovos-core#1027 and the OVOS-READY-1 proposal
(OpenVoiceOS/architecture#285).

CORRECTION (see the timeline posted on #1027): "ready" cannot mean
``IntentService.status`` reaching ``ProcessState.READY`` alone -- that
was already true for the entire window the reported bug lives in, while
padatious was still "compiling in background, serving last compiled
state" (a *stale* state on a fresh process, not a usable one). "Ready"
here means every pipeline plugin that reports a warm/cold transition
(``ovos.pipeline.warm_state``) has reported warm; a plugin that never
reports one counts as warm by default, so this never blocks on a signal
that cannot exist.

This module holds the short, localized "still starting" dialog, the
pipeline warm-state tracker, and the one function that decides whether
to speak the dialog instead of matching.
"""
from typing import Dict, Optional

#: must match the literal every pipeline plugin emits on
#: (OpenVoiceOS/ovos-padatious-pipeline-plugin#179 is the first producer)
PIPELINE_WARM_STATE = "ovos.pipeline.warm_state"

#: lang-prefix (first two letters of a BCP-47 code) -> a short, spoken
#: "the assistant is still starting" sentence. Falls back to English for any
#: prefix not listed here. Reviewed for the languages the Thalovant fleet
#: serves (OpenVoiceOS/ovos-core#1027); a wider upstream release would want
#: this reviewed per-locale rather than per-prefix.
STILL_STARTING_DIALOG = {
    "en": "I'm still starting up. Give me a few more seconds.",
    "fr": "Je démarre encore. Laissez-moi quelques secondes de plus.",
    "es": "Todavía estoy iniciando. Dame unos segundos más.",
    "de": "Ich starte noch. Gib mir noch ein paar Sekunden.",
    "nl": "Ik ben nog aan het opstarten. Geef me nog een paar seconden.",
    "ca": "Encara estic arrencant. Dona'm uns segons més.",
    "it": "Mi sto ancora avviando. Dammi qualche altro secondo.",
    "pt": "Ainda estou a iniciar. Dê-me mais alguns segundos.",
    "gl": "Aínda estou arrincando. Dáme uns segundos máis.",
    "eu": "Oraindik abiarazten ari naiz. Eman iezadazu segundo batzuk gehiago.",
    "hi": "मैं अभी भी शुरू हो रहा हूँ। मुझे कुछ और सेकंड दें।",
}


def still_starting_dialog(lang: Optional[str]) -> str:
    """The "still starting" sentence for ``lang``, by its two-letter prefix,
    falling back to English for an unlisted or missing language."""
    prefix = (lang or "en").split("-")[0].lower()
    return STILL_STARTING_DIALOG.get(prefix, STILL_STARTING_DIALOG["en"])


def is_ready(status) -> bool:
    """True once ``status`` (an ``ovos_utils.process_utils.ProcessStatus``)
    has reached ``READY``. A thin wrapper around ``check_ready()`` (called
    with no message, so nothing is emitted). This is a floor, not the
    whole gate: a process that has not even started obviously is not
    ready, but reaching ``READY`` is not sufficient on its own (see the
    module docstring) -- ``PipelineWarmTracker.all_warm()`` is the other
    half."""
    return bool(status.check_ready())


class PipelineWarmTracker:
    """Aggregates every pipeline plugin's own warm/cold transition
    (``ovos.pipeline.warm_state``, ``{pipeline_id, warm}``) into one
    "every configured pipeline that can report is warm" answer.

    A pipeline that never emits this message is never added to the
    tracked map at all, so it can never block ``all_warm()`` -- a plugin
    without a warm signal counts as warm, per the OVOS-READY-1 proposal.
    """

    def __init__(self, bus):
        self._warm: Dict[str, bool] = {}
        bus.on(PIPELINE_WARM_STATE, self._on_warm_state)

    def _on_warm_state(self, message) -> None:
        pipeline_id = message.data.get("pipeline_id")
        warm = message.data.get("warm")
        if pipeline_id is not None and warm is not None:
            self._warm[pipeline_id] = bool(warm)

    def all_warm(self) -> bool:
        """True when every pipeline that has ever reported is currently
        warm. Vacuously true before anything has reported at all -- there
        is nothing to wait on yet, and ``is_ready`` is the floor that
        covers that window regardless."""
        return all(self._warm.values())
