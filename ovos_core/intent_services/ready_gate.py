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

SECOND HALF (measured on a canary): warm pipelines are still not enough. A
hub whose padatious was warm at ~80 s kept loading skills until ~125 s, and
an utterance in that gap ("yes", in the middle of a game whose skill was not
registered yet) still reached an unrelated skill. The orchestrator is ready
to answer when every pipeline is warm AND the skills it will route to are
registered. The signal for the second half is the one the skill manager
already emits when its first load is done, ``mycroft.skills.initialized``.
It is latched: only the FIRST load counts, so a skill installed, upgraded or
reloaded afterwards never turns a ready system back into a not-ready one
(the manager emits the event once, and the latch would ignore a repeat).

This module holds the short, localized "still starting" dialog, the
pipeline warm-state tracker, and the one function that decides whether
to speak the dialog instead of matching.
"""
from typing import Dict, Optional

from ovos_bus_client.message import Message

#: must match the literal every pipeline plugin emits on
#: (OpenVoiceOS/ovos-padatious-pipeline-plugin#179 is the first producer)
PIPELINE_WARM_STATE = "ovos.pipeline.warm_state"

#: emitted once by the skill manager when its first load is done
SKILLS_INITIALIZED = "mycroft.skills.initialized"
#: the skill manager's own status query (ProcessStatus ``is_ready``) and the
#: reply type; used once at startup for an intent service that came up after
#: the skill manager had already finished loading
SKILLS_IS_READY = "mycroft.skills.is_ready"
SKILLS_IS_READY_RESPONSE = "mycroft.skills.is_ready.response"

#: lang-prefix (first two letters of a BCP-47 code) -> a short, spoken
#: "the assistant is still starting" sentence. A prefix not listed here has NO
#: dialog (OVOS-READY-1 section 3: never a dialog in the wrong language);
#: the caller plays the error sound instead. Reviewed for the languages the Thalovant fleet
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


#: the non-verbal reply OVOS-READY-1 section 3 requires when there is no
#: dialog in the session's language
ERROR_SOUND_URI = "snd/error.mp3"
PLAY_SOUND = "mycroft.audio.play_sound"


def still_starting_dialog(lang: Optional[str]) -> Optional[str]:
    """The "still starting" sentence for ``lang``, by its two-letter prefix,
    or None for an unlisted or missing language -- never another
    language's dialog (OVOS-READY-1 section 3)."""
    if not lang:
        return None
    return STILL_STARTING_DIALOG.get(lang.split("-")[0].lower())


def response_dialog(message_lang: Optional[str], output_lang: Optional[str]):
    """``(dialog, lang)`` in the language OVOS-SESSION-1 section 3.2.3 says a
    response is rendered in: ``output_lang`` when the session sets it, else
    the language resolved for the utterance. When ``output_lang`` is set but
    has no dialog here, the input-side language is the fallback section 3.2.3
    allows. ``(None, None)`` when neither has one: the caller plays the
    error sound, never a dialog in some other language."""
    for lang in (output_lang, message_lang):
        dialog = still_starting_dialog(lang)
        if dialog is not None:
            return dialog, lang
    return None, None


def is_ready(status) -> bool:
    """True once ``status`` (an ``ovos_utils.process_utils.ProcessStatus``)
    has reached ``READY``. A thin wrapper around ``check_ready()`` (called
    with no message, so nothing is emitted). This is a floor, not the
    whole gate: a process that has not even started obviously is not
    ready, but reaching ``READY`` is not sufficient on its own (see the
    module docstring) -- ``ReadinessTracker.ready()`` is the other
    half."""
    return bool(status.check_ready())


class ReadinessTracker:
    """The one aggregate behind "the orchestrator is ready to answer":
    every pipeline that reports a warm/cold transition
    (``ovos.pipeline.warm_state``, ``{pipeline_id, warm}``) is warm, AND the
    skill manager has finished its first load.

    A pipeline that never emits a warm report is never added to the tracked
    map, so it can never block ``all_warm()`` -- a plugin without a warm
    signal counts as warm, per the OVOS-READY-1 proposal.

    The skills half is a latch. ``mycroft.skills.initialized`` is emitted once
    after the first load; from then on ``skills_loaded`` stays True, so a
    skill that is installed or reloaded later cannot flip the system back to
    not ready. Registration of that one later skill is the skill manager's
    business, not a reason to refuse every utterance.
    """

    def __init__(self, bus, skills_required: bool = True):
        self._warm: Dict[str, bool] = {}
        self._skills_loaded = False
        #: False for a deployment with no skill manager on the bus at all
        #: (an intent service used on its own), where nothing would ever
        #: signal a first load and the gate would decline for good
        self._skills_required = skills_required
        self.bus = bus
        bus.on(PIPELINE_WARM_STATE, self._on_warm_state)
        bus.on(SKILLS_INITIALIZED, self._on_skills_initialized)
        bus.on(SKILLS_IS_READY_RESPONSE, self._on_skills_is_ready)

    def ask_skills(self) -> None:
        """Ask the skill manager once whether it is already done. Covers an
        intent service that starts after the skill manager finished loading
        and so never heard ``mycroft.skills.initialized``. Not a poll and not
        a timer: nobody answering just leaves the latch to the event."""
        self.bus.emit(Message(SKILLS_IS_READY))

    def _on_warm_state(self, message) -> None:
        pipeline_id = message.data.get("pipeline_id")
        warm = message.data.get("warm")
        if pipeline_id is not None and warm is not None:
            self._warm[pipeline_id] = bool(warm)

    def _on_skills_initialized(self, message=None) -> None:
        self._skills_loaded = True

    def _on_skills_is_ready(self, message) -> None:
        if message.data.get("status"):
            self._skills_loaded = True

    @property
    def skills_loaded(self) -> bool:
        return self._skills_loaded

    def all_warm(self) -> bool:
        """True when every pipeline that has ever reported is currently
        warm. Vacuously true before anything has reported at all -- there
        is nothing to wait on yet, and ``is_ready`` is the floor that
        covers that window regardless."""
        return all(self._warm.values())

    def ready(self) -> bool:
        """Every pipeline warm and, where skills are required, the first
        skill load done."""
        return ((not self._skills_required or self._skills_loaded)
                and self.all_warm())
