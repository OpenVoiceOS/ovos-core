# Prerelease quirks
<!-- agent-hint
covers: the behaviours of a dev alpha that differ from the last stable release, and what to do about each one
source: ovos_core/intent_services/stop_service_legacy.py, ovos_core/skill_installer.py:FAILURE_DETAIL_CHARS, ovos_core/skill_manager.py:PLUGIN_SKILL_RETRY_MAX_SECONDS
generated: no
verify: python3 docs/check_page.py docs/prerelease-quirks.md && grep -q 'FAILURE_DETAIL_CHARS = 2000' ovos_core/skill_installer.py && { grep -v '^verify:' docs/prerelease-quirks.md | grep -qF 'last 2000 characters'; } && grep -q 'PLUGIN_SKILL_RETRY_MAX_SECONDS = 15 \* 60' ovos_core/skill_manager.py && { grep -v '^verify:' docs/prerelease-quirks.md | grep -qF 'maximum of 15 minutes'; }
see: index.md
-->

This page lists the behaviours of a `dev` alpha that differ from the last stable release. Read it before you report a bug on an alpha. `CHANGELOG.md` lists each change by version.

## Stop

The stop pipeline sends a targeted stop on `<skill_id>:stop` and a global stop on `<pipeline_id>:global_stop`. Neither message activates a skill.

A listener that waits for `mycroft.stop` or `<skill_id>.stop` still gets them. `_LegacyStopBridge` in `ovos_core/intent_services/stop_service_legacy.py` sends them again on those topics. Move a listener to the spec topics: the bridge is a compatibility layer.

## Pipeline

- `pipeline_id` in `ovos.intent.matched` is the bare plugin ID, for example `ovos-adapt-pipeline-plugin`. It is not the matcher ID with a `-high`, `-medium` or `-low` suffix. A consumer that compares it with a matcher ID must remove the suffix first.
- An entry in `session.blacklisted_pipelines` names a plugin. It blocks all confidence tiers of that plugin, in the short form (`adapt_high`) and in the full form (`ovos-adapt-pipeline-plugin-high`).

## Converse, fallback and stop polls

- Converse sends one `ovos.converse.ping` for each round, with no skill ID, and also the ping to each skill.
- A pong whose `utterance_id` or session does not match the open round is discarded. A late answer cannot win a later round.

## Sessions

- `ovos-core` does not handle `ovos.session.sync`. `ovos-bus-client` (`>=2.11.13a1`) folds that message for the default session.
- When an utterance arrives, a field that its session omits keeps the stored value. A field that is present replaces the stored value. Intent context that a device declares on one utterance stays for the next one.

## Skills

- A skill installed over the bus loads when the installer sends `ovos.skills.install.complete`. It does not wait for the 30 s scan. `skillmanager.rescan` runs the same pass on request.
- A skill uninstalled over the bus unloads when the installer sends `ovos.skills.uninstall.complete`. A restart is not necessary.
- Each `.failed` reply of the installer has a `detail` field with the last 2000 characters of the pip output. The `error` field does not change.
- A plugin skill that fails to load is tried again after 30 s. The wait doubles after each failure, to a maximum of 15 minutes. A successful load resets it.

## Metrics and telemetry

- The latency histograms are off by default. `OVOS_METRICS_ENABLED=true` turns them on. See [performance-metrics.md](performance-metrics.md).
- When `open_data.intent_urls` is set, the intent upload also sends `pipeline` (the matcher IDs of the session, joined with `|`) and `core_version`. A collector that refuses unknown keys must accept these two.

---
[← Testing](testing.md) · [Home](index.md)
