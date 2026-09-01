# Prerelease quirks

This file lists everything that changed or broke since the last stable
release, `2.1.1`. It is version-stamped and newest first. If you install an
alpha of `ovos-core`, read this before you file a bug: the behavior you
are seeing may be documented here already.

This file resets at the next stable release. At that point its contents
become upgrade notes for the `2.1.1 -> next-stable` jump, and a new, empty
quirks log starts.

## #905 (alpha of 2026-09-01)

`SkillManager._load_plugin_skill`'s `finally` block only tracked a plugin
skill in `self.plugin_skills` once a `PluginSkillLoader` instance existed;
if `_get_plugin_skill_loader`/`.load()` raised before that instance was
bound, the skill was left out of `plugin_skills` while the in-flight marker
was still cleared, so the next periodic scan (`load_plugin_skills`, every
30s) saw it as "never attempted" and reloaded it from scratch — reinstating
the skill and re-registering its intents on every scan, indefinitely.
Failed loads are now tracked separately with an exponential backoff (30s,
capped at 15 minutes) before a retry is attempted again; a successful load
clears the backoff. Separately, `load_plugin_skills` set `loaded_new = True`
on every load *attempt* rather than on confirmed success, so a skill stuck
in the retry loop above also re-triggered the `mycroft.skills.train`
broadcast on every scan; `loaded_new` now reflects the actual load result.

## 3.0.7a5

`main()` now closes the messagebus client and joins its receiver thread,
with a bounded timeout, before returning on shutdown. Without this, the
daemon thread spawned by `bus.run_in_thread()` could still be dispatching a
buffered inbound frame onto `bus.emitter`'s `ThreadPoolExecutor` after the
interpreter started tearing down, raising `RuntimeError: cannot schedule
new futures after shutdown` from a background thread and leaving the
process hung until SIGKILL.

Known quirk: this narrows the race but does not fully close it. If the bus
client is caught inside its reconnect backoff (transport error -> sleep ->
recreate the websocket -> recurse) at shutdown time, `bus.close()` on every
`ovos-bus-client` release up to and including `2.8.5a1` has no effect on
that recursion, so the receiver thread can outlive the bounded join.
Fixed on the `ovos-bus-client` side in
[OpenVoiceOS/ovos-bus-client#295](https://github.com/OpenVoiceOS/ovos-bus-client/pull/295);
until that fix is released and the floor pin bumped here, a service
restart that lands mid-reconnect can still hang past the join timeout.

## 3.0 major (breaking, from #802)

`ovos-core` moved to a 3.0 major version. The stop pipeline's dispatch
shape changed: `#802` (OVOS-STOP-1) makes the pipeline dispatch a targeted
stop on `<skill_id>:stop` and a global stop on `<pipeline_id>:global_stop`,
both suppressing skill activation, instead of the pre-spec
`stop:global`/`stop:skill` topics. The pre-spec surface is kept alive by a
separable legacy bridge, `_LegacyStopBridge`
(`ovos_core/intent_services/stop_service_legacy.py`), which re-emits onto
`mycroft.stop` / `<skill_id>.stop` for old listeners. This bridge is a
compat shim, not a permanent feature: it is slated for removal at the next
major version.

## #854 (alpha of 2026-08-14)

`session.blacklisted_pipelines` matched blacklist entries and `session.pipeline`
matcher ids as literal strings, so a legacy short id (`adapt_high`) never
matched the canonical suffixed matcher it maps to (`ovos-adapt-pipeline-plugin-high`),
and a confidence-suffixed entry (either spelling) only denied that one tier,
leaving the plugin's other tiers invokable. Per OVOS-PIPELINE-1 §3/§5.2 a
blacklist entry names the plugin, not a matcher variant of it: denying it
denies every confidence tier, whichever spelling — legacy or canonical,
suffixed or bare — the entry uses. Both the blacklist and the matcher id are
now normalized to a bare plugin id before comparison.

## #689 (alpha of 2026-08-31)

The open-data intent-metrics upload (`IntentService._upload_match_data`,
gated behind the opt-in `open_data.intent_urls` config, off by default) now
carries `pipeline` (the session's pipe-joined matcher-id list) and
`core_version` (`OVOS_VERSION_STR`) alongside the existing fields. This is
an HTTP telemetry payload to a user-configured endpoint, not a bus message;
existing collectors that only read the fields they expect are unaffected,
but anyone parsing the payload strictly (e.g. rejecting unknown keys) needs
to accept the two new ones.

## #868 (alpha of 2026-08-14)

`handle_add_context`/`handle_remove_context`/`handle_clear_context` did a
copy-modify-assign on `Session.intent_context` outside the context lock
that `Session.set_intent_context`/`remove_intent_context` use. A concurrent
skill-side registry write (ovos-workshop's registry-first
`set_context`/`remove_context`, >= 9.3.13a1) landing between the snapshot
read and the write-back was silently lost. Fixed by wrapping each handler's
read-modify-write in the same lock.

## #865 (alpha of 2026-08-14)

`add_context`/`remove_context` are documented and tested as legacy-compat
paths, with idempotency proven by test.

## #863 (alpha of 2026-08-14)

Converse gained a broadcast contest poll (OVOS-CONVERSE-1 §4.2):
`ConverseService` emits one `ovos.converse.ping` per round on the static
spec topic, carrying no candidate identity, alongside the existing
per-skill pings (kept for compat since no released `ovos-workshop` binds
the broadcast topic yet). See `docs/converse-fallback.md`.

## #862 (alpha of 2026-08-14)

Extended the utterance_id/session round-correlation guard from #859
(converse's `handle_ack`) to fallback's `ovos.skills.fallback.pong`
collector and stop's `skill.stop.pong` collector: a pong whose
`utterance_id` or session does not match the currently open poll round is
now discarded, closing a class of bug where a late answer from a stale
round could win the wrong round. A round with no `utterance_id` still
stands down (V0 back-compat). `ovos-common-query-pipeline-plugin`'s
phrase-string correlation is a separate repo and was not touched here.

## #859 (alpha of 2026-08-14)

Stamps `context.utterance_id` at pipeline lifecycle entry
(PIPELINE-1 §9.1.1), the field #862 later correlates poll rounds against.

## #858 (alpha of 2026-08-14)

`SessionManager.get(message)` always folds the incoming message's session
snapshot onto the live registry entry before returning it — never a pure
read. Converse write paths were split: a true lifecycle entry point (and
any site that stamps the resolved session back onto the wire, like
`activate_skill`/`deactivate_skill`) keeps the real fold, since SESSION-2
last-writer-wins needs the client's declared fields to apply. An incidental
write with no wire echo (`get_response.enable`/`disable`) now bypasses the
fold, so a stale message arriving after registry state was already written
cannot wipe it out via full-replace.

**Pending, not yet merged:** #864 mirrors this same registry-first
resolution fix for the stop pipeline's write paths.

## #857 / #856 / #855 (alpha of 2026-08-14)

Registry-first session-handling cleanup: `add_context` mirrors under the
resolved private key when the producer names it (#857); manifest mutations
read the context session and `describe` spans sessions and self-identifies
entries (#856); `SessionManager` connects to the bus exactly once
regardless of construction order (#855).

## #786 (alpha of 2026-08-13/14)

Added OVOS-CONTEXT-1: orchestrator-resident intent context with decay,
session.sync merge, and slot-fill.

## Pending, not yet merged

- **#864** — mirrors #858's registry-first session resolution fix for the
  stop pipeline's write paths.
- **#879** — "kill queued deprecation-warning hot-path reads": swaps
  remaining legacy `Session`-view call sites for their non-warning
  equivalents. Open, not yet in `dev`.

## Older changes (2.x alphas, since 2.1.1)

- `#845` / `#788` / `#785` — transformer chains now conform to
  OVOS-TRANSFORM-1 ascending §4 chain ordering; the orchestrator owns the
  PIPELINE-1 §8 trio and §9 utterance-terminal events.
- `#832` — pipeline plugins can be blacklisted at load time and per
  session.
- `#829` — package names are canonicalized before the protected-package
  check in the skill installer.
- `#825` — e2e intent-name expectations updated for the OVOS-INTENT-2
  lowercase rename.
- `#822` — dropped the deprecated bus-client `EnclosureAPI` import from
  `skill_manager`.
- `#816` — boot no longer blocks on a pipeline training reply.
- `#810` — malformed intent-service locale templates are repaired instead
  of failing resource load.
- `#804` — `set_context` mirrors into OVOS-CONTEXT-1's `intent_context`.
- `#798` — orchestrator manifest (`IntentManifest`), INTENT-4 §10.
- `#778` — PIPELINE-1 §6.2 required_slots backstop and §7.3 reserved-name
  suppression.
- `#775` / `#767` / `#766` / `#779` — dependency floors widened to
  `ovos-bus-client` 2.x and `ovos-workshop` 8.x/9.x; single-sourced from
  `pyproject.toml`.
- `#773` — `intent.service.intent.get` accepts an `exclude_pipeline`
  filter.
- `#763` / `#754` — language matching migrated to `ovos-spec-tools`; bare
  lang-code locale directories renamed to canonical form.
- `#750` — deferred skill loading is now opt-in via a config flag.
- `#744` — duplicate skill loads during rescans are prevented.
- `#742` — skill-dependency install fix.
