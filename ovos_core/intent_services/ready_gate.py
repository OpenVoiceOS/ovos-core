"""OVOS-READY-1: a boot-readiness gate for the utterance lifecycle.

While the orchestrator is not yet ready (``IntentService.status`` has not
reached ``ProcessState.READY``), an utterance must not enter the pipeline
loop at all -- a pipeline's bounded match call (OVOS-PIPELINE-1 ``4.4``)
can legally exceed its bound from boot contention alone, get declined as
designed, and fall through to the next pipeline. For a mid-conversation
utterance (a bare "yes") that can match an unrelated literal entity instead
of continuing the conversation it belonged to. See OpenVoiceOS/ovos-core#1027
and the OVOS-READY-1 proposal (OpenVoiceOS/architecture#285).

This module holds the short, localized "still starting" dialog and the one
function that decides whether to speak it instead of matching.
"""
from typing import Optional

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
    with no message, so nothing is emitted) so the gate's call site reads
    as a readiness check, and so it has one place to widen later
    (OVOS-READY-1 ``2`` describes an aggregate across every pipeline
    plugin, not just this process's own ``ProcessState``)."""
    return bool(status.check_ready())
