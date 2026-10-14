"""OVOS-READY-1: the "still starting" reply and the load tracking behind it."""
from typing import Callable, Optional, Set

from ovos_bus_client.message import Message

#: a pipeline plugin that loads in the background announces both of these
PIPELINE_LOADING = "ovos.pipeline.loading"
PIPELINE_LOADED = "ovos.pipeline.loaded"

#: emitted once by the skill manager when its first load is done
SKILLS_INITIALIZED = "mycroft.skills.initialized"
SKILLS_IS_READY = "mycroft.skills.is_ready"
SKILLS_IS_READY_RESPONSE = "mycroft.skills.is_ready.response"

#: lang prefix -> "still starting" sentence; an unlisted prefix has none
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


class LoadTracker:
    """Tracks which pipelines are still loading and whether the skill
    manager's first load is done.

    ``answering`` opens once, when the first skill load is done and no
    pipeline is loading, and never closes: a skill installed or a pipeline
    retrained later does not stop the service answering.
    """

    def __init__(self, bus, skills_required: bool = True,
                 on_pipelines_loaded: Optional[Callable[[], None]] = None):
        self.bus = bus
        self._loading: Set[str] = set()
        self._skills_loaded = not skills_required
        self._answering = False
        self._on_pipelines_loaded = on_pipelines_loaded
        bus.on(PIPELINE_LOADING, self._on_loading)
        bus.on(PIPELINE_LOADED, self._on_loaded)
        bus.on(SKILLS_INITIALIZED, self._on_skills_initialized)
        bus.on(SKILLS_IS_READY_RESPONSE, self._on_skills_is_ready)

    def ask_skills(self) -> None:
        """Ask once, for a skill manager that finished before this service
        started and so will not emit ``SKILLS_INITIALIZED`` again."""
        self.bus.emit(Message(SKILLS_IS_READY))

    @property
    def pipelines_loading(self) -> bool:
        return bool(self._loading)

    @property
    def answering(self) -> bool:
        self._update()
        return self._answering

    def _update(self) -> None:
        if self._skills_loaded and not self._loading:
            self._answering = True

    def _on_loading(self, message) -> None:
        self._loading.add(message.data["pipeline_id"])

    def _on_loaded(self, message) -> None:
        self._loading.discard(message.data["pipeline_id"])
        self._update()
        if not self._loading and self._on_pipelines_loaded:
            self._on_pipelines_loaded()

    def _on_skills_initialized(self, message=None) -> None:
        self._skills_loaded = True
        self._update()

    def _on_skills_is_ready(self, message) -> None:
        if message.data.get("status"):
            self._on_skills_initialized()
