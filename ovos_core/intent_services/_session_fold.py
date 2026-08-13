"""Shared fold-order helper for pipeline plugins.

Mirrors ``IntentService._registry_session_for_context_write`` (#857,
``ovos_core/intent_services/service.py``) and
``ConverseService._registry_session_for_write`` (#858,
``ovos_core/intent_services/converse_service.py``) for INCIDENTAL session
writes in ``stop_service.py`` that have no wire echo. Kept as its own small
module (rather than importing one plugin's private static method from
another) so ``stop_service.py``/``fallback_service.py`` don't reach into
``converse_service.py``'s internals; delete only if/when all three call-site
families are consolidated together.

FOLD-ORDER CONTRACT (read this before adding a new call site):

``SessionManager.get(message)`` is NEVER a pure read. It always folds the
incoming message's session snapshot onto the live registry entry
(``SessionManager._store`` -> ``Session.update_from``, full
serialize/deserialize replace, for every session id including
``"default"``) and returns THAT live object. So every call is a write of
the message's declared state onto the registry, whether or not the caller
goes on to mutate anything itself.

That fold is *correct and required* at two kinds of site:
  1. True lifecycle entry - the first fold for this message in this
     pipeline turn. SESSION-2 last-writer-wins: the client's
     freshly-declared fields (lang, blacklist, client-side (de)activations)
     must apply here.
  2. Any site that stamps the resolved session back onto the wire via
     ``message.context["session"] = session.serialize()`` - bypassing the
     fold there would silently discard the client's own declarations from
     the outgoing message.

The fold is *wrong* (and this helper exists to avoid it) only for an
INCIDENTAL write with no wire echo, where a STALE message (one that
predates state written to the registry earlier in the same session's
lifecycle - by this same pipeline stage OR an earlier one in the same
turn, e.g. converse's skill activation/deactivation) would otherwise wipe
that state via the full-replace fold before this handler's own write lands.

RESIDUAL (not fixed by this helper, tracked as a known gap, same as #858):
a case-2 wire-echo site elsewhere still full-replaces the registry entry
when it folds, so a write this helper protects only survives until the
next stale wire-echo call for that session.

Resolution: resolve session_id off the message and, if the registry already
holds a live entry for it, mutate that object directly - no fold. Fall back
to ``SessionManager.get(message)`` (today's behavior) only when no registry
entry exists yet, e.g. out-of-registry/test callers or a message with no
session context.
"""
from typing import Optional

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager, Session


def registry_session_for_write(message: Optional[Message]) -> Session:
    """Resolve the live registry session to mutate for an incidental write
    that has no wire echo. See module docstring for the full fold-order
    contract."""
    session_data = message.context.get("session") if message and message.context else None
    session_id = session_data.get("session_id") if isinstance(session_data, dict) else None
    if session_id and session_id in SessionManager.sessions:
        return SessionManager.sessions[session_id]
    return SessionManager.get(message)
