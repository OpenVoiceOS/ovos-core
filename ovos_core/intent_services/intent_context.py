# Copyright 2024 OpenVoiceOS
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Core-resident implementation of OVOS-CONTEXT-1 — intent context.

OVOS-CONTEXT-1 replaces the legacy frame-based ``IntentContextManager``
(``ovos_bus_client.session.IntentContextManager``) with a **flat,
decaying key/value map** stored at ``session.intent_context`` (§2).

This module is the orchestrator-resident half of the spec. It owns:

- the entry shape and the *liveness* predicate (§2);
- the prune-then-decrement decay lifecycle (§4);
- the ``ovos.session.sync`` entry-by-entry merge (§5.3);
- the §3.1 scope-resolution helper that maps a gating declaration to a
  stored key, the §6 / §6.1 gating predicates, and the §7
  context-supplied slot fill — provided here as pure functions so any
  in-process engine (and core's own match post-processing) can apply
  them identically.

The *engine-side* enforcement of §6 / §6.1 gating inside a matcher (e.g.
the Adapt matcher dropping a candidate whose ``requires_context`` is
unsatisfied) is **out of scope for this module** — it belongs to each
pipeline plugin and is tracked as a follow-up. What lives here is the
shared, engine-agnostic vocabulary those plugins (and the orchestrator)
consult.

Storage note: ``session.intent_context`` is a plain JSON object carried
inside the OVOS-SESSION-1 carrier (``Message.context.session``). The
legacy ``ovos_bus_client.session.Session`` object does not yet expose it
as a first-class attribute and drops it on round-trip, so the
orchestrator maintains the working map keyed by ``session_id`` and
stamps it back onto the serialized session it emits. See
``IntentContextStore`` and the wiring in ``service.py``.
"""
import time
from typing import Any, Dict, List, Optional, Union

from ovos_utils.log import LOG

#: OVOS-CONTEXT-1 §2 — the JSON path, inside the session carrier, that
#: holds the flat intent-context map. Stamped onto / read from the
#: serialized session dict (``message.context["session"][_FIELD]``).
INTENT_CONTEXT_FIELD = "intent_context"

#: OVOS-CONTEXT-1 §2 / OVOS-MSG-1 §2.1.1 — the single load-bearing
#: separator between a private entry's owner and its sub-key. A prefixed
#: (private) key contains exactly one ``:``; a bare (shared) key none.
SCOPE_SEPARATOR = ":"

#: OVOS-CONTEXT-1 §2 — the recommended maximum live entry count an
#: orchestrator SHOULD enforce, evicting the entry closest to natural
#: expiry when exceeded.
DEFAULT_MAX_ENTRIES = 1024


def is_live(entry: Dict[str, Any], now: Optional[float] = None) -> bool:
    """OVOS-CONTEXT-1 §2 liveness predicate.

    An entry is **live** iff both of:

    - ``turns_remaining`` is unset, ``null``, or strictly greater than 0;
    - ``expires_at`` is unset, ``null``, or strictly greater than the
      current Unix time.

    @param entry: a context entry object (``value`` plus optional
        ``expires_at`` / ``turns_remaining``).
    @param now: current Unix time; defaults to ``time.time()``.
    @return: True if the entry is live.
    """
    if not isinstance(entry, dict):
        return False
    now = time.time() if now is None else now

    turns = entry.get("turns_remaining")
    if turns is not None and not turns > 0:
        return False

    expires = entry.get("expires_at")
    if expires is not None and not expires > now:
        return False

    return True


def resolve_key(key: str, scope: str, owner_id: Optional[str]) -> Optional[str]:
    """OVOS-CONTEXT-1 §3.1 — map a gating declaration to a stored key.

    - ``scope == "private"`` resolves to ``<owner_id>:<key>``; shared
      entries with the same key do **not** satisfy a private gate.
    - ``scope == "shared"`` resolves to the bare ``<key>``; private
      entries with the same name do **not** satisfy a shared gate.

    @param key: the caller-chosen sub-key (unprefixed).
    @param scope: ``"private"`` or ``"shared"``.
    @param owner_id: the declaring intent's ``skill_id`` / ``pipeline_id``;
        required for private scope.
    @return: the stored key, or None if a private lookup has no owner.
    """
    if scope == "shared":
        return key
    # private (the safe default)
    if not owner_id:
        return None
    return f"{owner_id}{SCOPE_SEPARATOR}{key}"


def normalize_declaration(entry: Union[str, Dict[str, Any]]) -> Optional[Dict[str, str]]:
    """OVOS-CONTEXT-1 §6 — normalize one ``requires_context`` /
    ``excludes_context`` entry to ``{key, scope}``.

    A bare string is interpreted as ``{key: <string>, scope: "private"}``
    — the safe default (§6). A mapping may set an explicit ``scope``.

    @param entry: a bare key string or a ``{key, scope}`` mapping.
    @return: a normalized ``{key, scope}`` dict, or None if malformed.
    """
    if isinstance(entry, str):
        return {"key": entry, "scope": "private"}
    if isinstance(entry, dict) and entry.get("key"):
        scope = entry.get("scope", "private")
        if scope not in ("private", "shared"):
            LOG.warning(f"invalid context scope '{scope}', defaulting to private")
            scope = "private"
        return {"key": entry["key"], "scope": scope}
    LOG.warning(f"malformed context declaration: {entry!r}")
    return None


def gate_satisfied(intent_context: Dict[str, Any],
                   requires: Optional[List[Union[str, Dict]]],
                   excludes: Optional[List[Union[str, Dict]]],
                   owner_id: Optional[str],
                   now: Optional[float] = None) -> bool:
    """OVOS-CONTEXT-1 §6 / §6.1 — evaluate the positive and negative
    gating contracts against a (post-decay, §4) context snapshot.

    A match is permitted iff **every** ``requires_context`` key resolves
    to a live entry **and** **no** ``excludes_context`` key resolves to a
    live entry, each resolved per §3.1.

    @param intent_context: the flat ``session.intent_context`` map.
    @param requires: ``requires_context`` declarations, or None/empty.
    @param excludes: ``excludes_context`` declarations, or None/empty.
    @param owner_id: the declaring intent's ``skill_id`` / ``pipeline_id``.
    @param now: current Unix time; defaults to ``time.time()``.
    @return: True if the gate permits the match.
    """
    intent_context = intent_context or {}
    now = time.time() if now is None else now

    for decl in (requires or []):
        norm = normalize_declaration(decl)
        if norm is None:
            return False  # malformed declaration can never be satisfied
        stored = resolve_key(norm["key"], norm["scope"], owner_id)
        entry = intent_context.get(stored) if stored else None
        if entry is None or not is_live(entry, now):
            return False

    for decl in (excludes or []):
        norm = normalize_declaration(decl)
        if norm is None:
            continue
        stored = resolve_key(norm["key"], norm["scope"], owner_id)
        entry = intent_context.get(stored) if stored else None
        if entry is not None and is_live(entry, now):
            return False

    return True


def context_supplied_slots(intent_context: Dict[str, Any],
                           requires: Optional[List[Union[str, Dict]]],
                           slot_names: List[str],
                           owner_id: Optional[str],
                           filled_slots: Optional[Dict[str, Any]] = None,
                           now: Optional[float] = None) -> Dict[str, Any]:
    """OVOS-CONTEXT-1 §7 — the context-supplied slot rule.

    When a ``requires_context`` key ``k`` **also names a slot** of the
    intent definition, and the §3.1-selected entry's ``value`` is
    non-null, and the utterance did **not** itself fill slot ``k``,
    populate ``Match.slots[k]`` from that value (keyed by ``k``,
    unprefixed). Utterance-produced values always win — context is a
    fallback, not an override.

    @param intent_context: the flat ``session.intent_context`` map.
    @param requires: the intent's ``requires_context`` declarations.
    @param slot_names: the slot / vocabulary names of the intent
        definition.
    @param owner_id: the declaring intent's ``skill_id`` / ``pipeline_id``.
    @param filled_slots: slots the utterance itself produced (these win).
    @param now: current Unix time; defaults to ``time.time()``.
    @return: a mapping of slot-name -> context-supplied value (only the
        slots this rule fills; empty if none apply).
    """
    intent_context = intent_context or {}
    filled_slots = filled_slots or {}
    slot_names = set(slot_names or [])
    now = time.time() if now is None else now
    supplied: Dict[str, Any] = {}

    for decl in (requires or []):
        norm = normalize_declaration(decl)
        if norm is None:
            continue
        key = norm["key"]
        if key not in slot_names:
            continue  # gated only, §7 does not apply
        if filled_slots.get(key) not in (None, ""):
            continue  # utterance-produced value wins
        stored = resolve_key(key, norm["scope"], owner_id)
        entry = intent_context.get(stored) if stored else None
        if entry is None or not is_live(entry, now):
            continue
        value = entry.get("value")
        if value is None:
            continue  # flag-context has no value to supply
        supplied[key] = value

    return supplied


class IntentContextStore:
    """Orchestrator-resident store of ``session.intent_context`` maps.

    Holds the authoritative flat context map for each session, applies
    the §4 decay lifecycle (prune before a match round, decrement after),
    and the §5.3 ``ovos.session.sync`` entry-by-entry merge.

    The legacy ``ovos_bus_client.session.Session`` object does not carry
    ``intent_context`` and drops it on (de)serialization, so the
    orchestrator is the source of truth: it reads the inbound snapshot
    off the wire, reconciles it with what it already holds, and stamps
    the working map back onto the serialized session it emits.
    """

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES):
        # session_id -> {key: entry}
        self._maps: Dict[str, Dict[str, Any]] = {}
        self.max_entries = max_entries

    def get(self, session_id: str) -> Dict[str, Any]:
        """Return the (mutable) working map for a session, creating it
        empty if absent."""
        return self._maps.setdefault(session_id, {})

    def set(self, session_id: str, intent_context: Dict[str, Any]) -> None:
        """Replace the working map for a session wholesale.

        Used when adopting an inbound snapshot for an unseen session
        (the carrier is replayable, OVOS-CONTEXT-1 §9).
        """
        self._maps[session_id] = dict(intent_context or {})

    def adopt_inbound(self, session_id: str,
                      inbound: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Reconcile a wire-carried ``intent_context`` snapshot for a
        session the orchestrator has not seen before.

        On ordinary Messages ``session.intent_context`` is **read-only**
        (§8): the orchestrator keeps its own working copy. But sessions
        are replayable carriers (§9) — when an utterance arrives for a
        session id we hold no map for, the inbound snapshot is the only
        state available, so we adopt it. For a session we already track,
        the inbound snapshot is ignored (the §5 pathways are the only
        writers).

        @return: the working map for the session.
        """
        if session_id not in self._maps:
            self._maps[session_id] = dict(inbound or {})
        return self._maps[session_id]

    def prune(self, session_id: str, now: Optional[float] = None) -> Dict[str, Any]:
        """OVOS-CONTEXT-1 §4 (pre-match) — remove every non-live entry.

        This is the gating snapshot every matcher sees during the
        upcoming match round.

        @return: the pruned working map.
        """
        now = time.time() if now is None else now
        ctx = self.get(session_id)
        dead = [k for k, e in ctx.items() if not is_live(e, now)]
        for k in dead:
            ctx.pop(k, None)
        return ctx

    def decrement(self, session_id: str,
                  only_keys: Optional[set] = None) -> Dict[str, Any]:
        """OVOS-CONTEXT-1 §4 (post-match) — decrement ``turns_remaining``
        on every remaining entry that sets it, whether or not any intent
        matched.

        Per §4.1, an entry written by an ``ovos.session.sync`` emitted
        **mid-dispatch** must not be decremented by the dispatch it was
        written in. The orchestrator captures the key set present at the
        pre-match prune and passes it as ``only_keys`` so freshly-synced
        keys are skipped, landing alive for exactly the next match round.

        @param only_keys: if given, decrement only entries whose key is in
            this set (the snapshot present before the match round).
        @return: the working map.
        """
        ctx = self.get(session_id)
        for key, entry in ctx.items():
            if only_keys is not None and key not in only_keys:
                continue  # §4.1 — mid-dispatch sync entry, not decremented
            turns = entry.get("turns_remaining")
            if turns is not None:
                entry["turns_remaining"] = turns - 1
        return ctx

    def merge_sync(self, session_id: str,
                   payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """OVOS-CONTEXT-1 §5.3 — apply an ``ovos.session.sync``
        ``intent_context`` payload **entry-by-entry**:

        - a key mapping to an entry object **sets or replaces** that key;
        - a key mapping to JSON ``null`` **removes** that key;
        - keys absent from the payload are left unchanged.

        Concurrent handlers writing disjoint keys therefore do not
        overwrite each other.

        @return: the merged working map.
        """
        ctx = self.get(session_id)
        if not payload:
            return ctx
        for key, entry in payload.items():
            if entry is None:
                ctx.pop(key, None)
            elif isinstance(entry, dict):
                ctx[key] = entry
            else:
                LOG.warning(f"ignoring malformed intent_context entry "
                            f"for key '{key}': {entry!r}")
        self._enforce_cap(session_id)
        return ctx

    def _enforce_cap(self, session_id: str, now: Optional[float] = None) -> None:
        """OVOS-CONTEXT-1 §2 — bound the live entry count, evicting the
        entry closest to natural expiry when exceeded (smallest
        ``turns_remaining``, then earliest ``expires_at``, then
        arbitrary)."""
        ctx = self.get(session_id)
        if len(ctx) <= self.max_entries:
            return
        now = time.time() if now is None else now

        def _expiry_rank(item):
            _, entry = item
            turns = entry.get("turns_remaining")
            expires = entry.get("expires_at")
            # entries with neither sort last (least eligible for eviction)
            return (turns if turns is not None else float("inf"),
                    expires if expires is not None else float("inf"))

        while len(ctx) > self.max_entries:
            victim = min(ctx.items(), key=_expiry_rank)[0]
            ctx.pop(victim, None)

    def discard(self, session_id: str) -> None:
        """Drop the working map for a session (e.g. on reset)."""
        self._maps.pop(session_id, None)
