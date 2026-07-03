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
"""Core-resident helpers for OVOS-CONTEXT-1 — intent context.

OVOS-CONTEXT-1 models intent context as a **flat, decaying key/value
map** stored at ``session.intent_context`` (§2).

The authoritative owner of that map is the ``SessionManager`` singleton
(``ovos_bus_client.session.SessionManager``): it carries
``intent_context`` as a first-class, round-tripping field on every
``Session`` and applies the §5.3 ``ovos.session.sync`` entry-by-entry
merge (set + null-delete) itself — see ``SessionManager.handle_session_sync``
/ ``SessionManager.merge_intent_context``. The orchestrator does **not**
subscribe to ``ovos.session.sync`` and does **not** hold a parallel store.

This module is therefore a set of **stateless helpers** the orchestrator
(and any in-process engine) applies to a session's ``intent_context``
map. It owns no state; every function takes the map (or an entry) as an
argument and returns a value or mutates the passed-in dict in place:

- the entry-shape *liveness* predicate (§2);
- the prune-then-decrement decay lifecycle (§4 / §4.1);
- the §2 live-entry cap eviction;
- the §3.1 scope-resolution helper that maps a gating declaration to a
  stored key, the §6 / §6.1 gating predicates, and the §7
  context-supplied slot fill.

Engine-side enforcement of §6 / §6.1 gating inside a matcher (e.g. a
matcher dropping a candidate whose ``requires_context`` is unsatisfied)
belongs to each pipeline plugin, not to this module. What lives here is
the shared, engine-agnostic vocabulary those plugins (and the
orchestrator) consult.
"""
import time
from typing import Any, Dict, List, Optional, Set, Union

from ovos_utils.log import LOG

#: OVOS-CONTEXT-1 §2 — the JSON field, inside the session carrier, that
#: holds the flat intent-context map. First-class on ``Session`` in
#: bus-client (round-trips through serialize/deserialize).
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


# ---------------------------------------------------------------------------
# §4 — decay lifecycle (stateless; operates on a passed-in intent_context map)
# ---------------------------------------------------------------------------

def prune(intent_context: Dict[str, Any],
          now: Optional[float] = None) -> Dict[str, Any]:
    """OVOS-CONTEXT-1 §4 (pre-match) — remove every non-live entry from
    the given map, in place.

    This is the gating snapshot every matcher sees during the upcoming
    match round.

    @param intent_context: the session's flat ``intent_context`` map
        (mutated in place).
    @param now: current Unix time; defaults to ``time.time()``.
    @return: the same (pruned) map.
    """
    if not intent_context:
        return intent_context
    now = time.time() if now is None else now
    dead = [k for k, e in intent_context.items() if not is_live(e, now)]
    for k in dead:
        intent_context.pop(k, None)
    return intent_context


def decrement(intent_context: Dict[str, Any],
              only_keys: Optional[Set[str]] = None) -> Dict[str, Any]:
    """OVOS-CONTEXT-1 §4 (post-match) — decrement ``turns_remaining`` on
    every remaining entry that sets it, whether or not any intent
    matched.

    Per §4.1, an entry written by an ``ovos.session.sync`` emitted
    **mid-dispatch** must not be decremented by the dispatch it was
    written in. The orchestrator captures the key set present at the
    pre-match prune and passes it as ``only_keys`` so freshly-synced keys
    are skipped, landing alive for exactly the next match round.

    @param intent_context: the session's flat ``intent_context`` map
        (mutated in place).
    @param only_keys: if given, decrement only entries whose key is in
        this set (the snapshot present before the match round).
    @return: the same map.
    """
    if not intent_context:
        return intent_context
    for key, entry in intent_context.items():
        if only_keys is not None and key not in only_keys:
            continue  # §4.1 — mid-dispatch sync entry, not decremented
        if not isinstance(entry, dict):
            continue
        turns = entry.get("turns_remaining")
        if turns is not None:
            entry["turns_remaining"] = turns - 1
    return intent_context


def enforce_cap(intent_context: Dict[str, Any],
                max_entries: int = DEFAULT_MAX_ENTRIES,
                now: Optional[float] = None) -> Dict[str, Any]:
    """OVOS-CONTEXT-1 §2 — bound the live entry count of the given map,
    evicting the entry closest to natural expiry when exceeded (smallest
    ``turns_remaining``, then earliest ``expires_at``, then arbitrary).

    @param intent_context: the session's flat ``intent_context`` map
        (mutated in place).
    @param max_entries: the recommended live-entry ceiling.
    @param now: current Unix time; defaults to ``time.time()`` (unused for
        ranking but accepted for call-site symmetry).
    @return: the same map.
    """
    if not intent_context or len(intent_context) <= max_entries:
        return intent_context

    def _expiry_rank(item):
        _, entry = item
        turns = entry.get("turns_remaining") if isinstance(entry, dict) else None
        expires = entry.get("expires_at") if isinstance(entry, dict) else None
        # entries with neither sort last (least eligible for eviction)
        return (turns if turns is not None else float("inf"),
                expires if expires is not None else float("inf"))

    while len(intent_context) > max_entries:
        victim = min(intent_context.items(), key=_expiry_rank)[0]
        intent_context.pop(victim, None)
    return intent_context
