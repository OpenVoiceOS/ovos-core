"""The session an utterance is being processed on, for as long as that utterance lasts.

OVOS-SESSION-2 §2.2 lets the orchestrator keep a transient cache of the
session it is currently processing and forbids anything from treating such a
cache as durable state. This module is that cache, and the whole of it.

The working session is registered when an utterance enters the lifecycle
(OVOS-PIPELINE-1 §6) and dropped when the lifecycle terminates. It is keyed on
the §9.1.1 ``utterance_id``, which every Message derived from the utterance
carries, so a handler frame or a legacy context write arriving mid-round finds
the same object the pipeline is working on, and nothing survives its round.

Named sessions are why this exists. The orchestrator holds no state for them
between utterances (§2.2), so ``SessionManager.sessions`` never contains one
and a lookup there answers ``None``; the round's session lives here instead.
For the default session the working session *is* the store (§5), so a lookup
here and ``SessionManager.get_default_session()`` return the same object and
either answer is correct.

A message with no ``utterance_id`` belongs to no lifecycle. There is no
working session for it — per §2.6 an out-of-lifecycle write has nowhere
legitimate to land — and callers get ``None``.
"""
from collections import OrderedDict
from threading import RLock
from typing import Optional

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session

#: An utterance whose dispatch never reaches a terminal is never closed, so the
#: oldest round is evicted once this many are open at once. Reaching the bound
#: means terminals are going missing; the eviction only stops that leaking.
_MAX_OPEN_ROUNDS = 32

_LOCK = RLock()
_OPEN_ROUNDS: "OrderedDict[str, Session]" = OrderedDict()


def _utterance_id(message: Optional[Message]) -> Optional[str]:
    ctx = getattr(message, "context", None) or {}
    return ctx.get("utterance_id")


def open_round(message: Message, session: Session) -> None:
    """Register ``session`` as the working session of ``message``'s lifecycle."""
    uid = _utterance_id(message)
    if not uid:
        return
    with _LOCK:
        _OPEN_ROUNDS[uid] = session
        _OPEN_ROUNDS.move_to_end(uid)
        while len(_OPEN_ROUNDS) > _MAX_OPEN_ROUNDS:
            _OPEN_ROUNDS.popitem(last=False)


def working_session(message: Optional[Message]) -> Optional[Session]:
    """The working session of ``message``'s lifecycle, if one is open."""
    uid = _utterance_id(message)
    if not uid:
        return None
    with _LOCK:
        return _OPEN_ROUNDS.get(uid)


def close_round(message: Optional[Message]) -> Optional[Session]:
    """Drop and return the working session of ``message``'s lifecycle."""
    uid = _utterance_id(message)
    if not uid:
        return None
    with _LOCK:
        return _OPEN_ROUNDS.pop(uid, None)
