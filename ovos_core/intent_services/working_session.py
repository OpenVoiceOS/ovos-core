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
from copy import deepcopy
from threading import RLock
from typing import Dict, Optional

from ovos_bus_client.message import Message
from ovos_bus_client.session import Session
from ovos_utils.log import LOG

#: An utterance whose dispatch never reaches a terminal is never closed, so the
#: oldest round is evicted once this many are open at once. Reaching the bound
#: means terminals are going missing; the eviction only stops that leaking.
_MAX_OPEN_ROUNDS = 32

_LOCK = RLock()
_OPEN_ROUNDS: "OrderedDict[str, Session]" = OrderedDict()
#: intent-context entries the round's pre-match prune removed, per open
#: round, as key -> the entry the prune dropped.
_PRUNED_ENTRIES: "OrderedDict[str, Dict[str, dict]]" = OrderedDict()


def raw_session_id(message: Message) -> Optional[str]:
    """The ``session_id`` a Message's raw ``context.session`` carrier names,
    without folding it through :class:`Session` (OVOS-SESSION-1 §2.5).

    A missing/``None`` carrier is the default session (§2.1/§3.1). A carrier
    that is present but not a JSON object is malformed: this returns ``None``
    instead of raising or substituting the default session's identity, so a
    correlation lookup keyed on it is dropped rather than misrouted. Use for
    call sites that only need the id for correlation (dispatch tracking,
    manifest scoping) — not for reading session content, which goes through
    ``SessionManager``/``Session`` and its own ``MalformedSession`` handling.
    """
    session = message.context.get("session")
    if session is None:
        return "default"
    if not isinstance(session, dict):
        LOG.error(f"OVOS-SESSION-1 §2.5: malformed session carrier on "
                  f"{message.msg_type} (got {type(session).__name__}, "
                  f"expected object); dropping")
        return None
    return session.get("session_id", "default")


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
            evicted, _ = _OPEN_ROUNDS.popitem(last=False)
            _PRUNED_ENTRIES.pop(evicted, None)


def record_pruned(message: Message, entries: Dict[str, dict]) -> None:
    """Record the intent-context entries this round's pre-match prune removed.

    OVOS-SESSION-2 §2.6 makes the round's decay authoritative over what a
    handler carries back: an entry the prune dropped stays dropped even when
    the handler's copy of the session predates the prune and still holds it.
    The dropped *entry* is kept, not just its key, so that a handler re-arming
    the same key with a fresh entry is told apart from one echoing the stale
    one — only the echo is beaten by the decay.
    """
    uid = _utterance_id(message)
    if not uid:
        return
    with _LOCK:
        _PRUNED_ENTRIES[uid] = deepcopy(entries)


def pruned_entries(message: Optional[Message]) -> Dict[str, dict]:
    """The intent-context entries this round's pre-match prune removed."""
    uid = _utterance_id(message)
    if not uid:
        return {}
    with _LOCK:
        return deepcopy(_PRUNED_ENTRIES.get(uid) or {})


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
        _PRUNED_ENTRIES.pop(uid, None)
        return _OPEN_ROUNDS.pop(uid, None)
