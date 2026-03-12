
# FAQ - ovos-core

## Why does IntentService time out waiting at startup?

If `wait_for_intent_service` raises `RuntimeError: IntentService did not become ready within 300 seconds`, the IntentService process is either not running or not connected to the messagebus. The timeout is configurable via `skills.intent_service_timeout` in `mycroft.conf` (seconds, default 300).

## Why does converse/stop skip a skill that doesn't respond to the ping?

Since 2026-03-12, `_collect_converse_skills` and `_collect_stop_skills` use `can_handle` default `False`. A skill that does not respond to the converse/stop ping within 0.5 s is excluded — it is not assumed to want to handle the utterance. This avoids stale listeners and unexpected behaviour when a skill process is unresponsive.

---

## What is ovos-core?
`ovos-core` is the central component of the OpenVoiceOS platform, responsible for skill management, intent parsing, and orchestration of the voice assistant's features. It is a fork of the original Mycroft AI core.

---

## Running ovos-core

### How do I run ovos-core?
Run the full skill manager (with all subsystems):
```bash
ovos-core
```
Available flags: `--disable-file-watcher`, `--disable-skill-api`, `--disable-intent-service`, `--disable-installer`, `--disable-event-scheduler`.

### How do I run just the IntentService standalone?
```bash
ovos-intent-service
```
This starts only `IntentService` connected to the messagebus, without loading any skills. Useful for debugging pipeline issues.

### How do I run just the skill installer standalone?
```bash
ovos-skill-installer
```
Listens on `ovos.skills.install`, `ovos.pip.install`, etc. without loading skills.

---

## Skills

### How do I install skills?
Enable pip-based installation in `mycroft.conf`:
```json
{"skills": {"installer": {"allow_pip": true}}}
```
Then emit a bus message or use `ovos-skill-installer`. Skills are installed as Python packages via `pip` or `uv` (if available).

### How do I blacklist a skill so it never loads?
Add the skill's `skill_id` to the configuration:
```json
{"skills": {"blacklisted_skills": ["skill-name.author"]}}
```
The skill will be skipped during `load_plugin_skills()` in `SkillManager`.

### Why does ovos-core warn "No installed skills detected"?
This warning from `SkillManager.__init__()` means `find_skill_plugins()` returned no results. Either no OVOS skills are installed in the current Python environment, or skills are running in standalone mode (which is fine — the warning can be ignored in that case).

### How are skills discovered?
Skills are Python packages that register an entry point under the `ovos.plugins.skill` namespace in their `pyproject.toml`. `ovos-plugin-manager` discovers them via `find_skill_plugins()`.

### Can I reload a skill without restarting ovos-core?
Yes. `SkillManager` runs a loop every 30 seconds calling `_load_new_skills()`, which picks up newly installed skills automatically. You can also trigger a reload by emitting `mycroft.skills.train` on the bus.

### How do skills load?
By default, all skills load unconditionally at startup via `SkillManager.run()` → `_load_new_skills()` (`ovos_core/skill_manager.py`). Runtime requirements (`network_before_load`, `internet_before_load`) are ignored by default.

To enable deferred loading (legacy behavior), set `skills.use_deferred_loading: true` in `mycroft.conf`. When enabled, skills with connectivity requirements are held until those conditions are met via bus events (`mycroft.network.connected`, `mycroft.internet.connected`, etc.).

---

## Intent Pipeline

### What are pipeline plugins?
Pipeline plugins implement the `opm.pipeline` entry point and provide intent matching strategies. Each plugin exposes a `match()` method (or `match_high/medium/low` for `ConfidenceMatcherPipeline`). They are loaded by `OVOSPipelineFactory` at startup.

### What pipeline plugins are included?
Core pipeline plugins registered by ovos-core:
- `ovos-converse-pipeline-plugin` — active skill conversation handling
- `ovos-common-query-pipeline-plugin` — CommonQuery skill routing
- `ovos-fallback-pipeline-plugin-{high,medium,low}` — fallback skill tiers
- `ovos-stop-pipeline-plugin-{high,medium,low}` — stop intent handling

Additional plugins (Adapt, Padatious, Padacioso, OCP, etc.) are installed separately.

### How do I configure the pipeline order?
Set `intents.pipeline` in `mycroft.conf` with an ordered list of pipeline plugin IDs:
```json
{"intents": {"pipeline": [
    "ovos-converse-pipeline-plugin",
    "ovos-adapt-pipeline-plugin-high",
    "ovos-padatious-pipeline-plugin-high",
    "ovos-fallback-pipeline-plugin-high"
]}}
```
Utterances are passed to each plugin in order until one matches.

### How does multilingual intent matching work?
Set `intents.multilingual_matching: true` in `mycroft.conf`. If the primary language fails to match, `IntentService.handle_utterance()` will retry all user-configured languages in `get_valid_languages()`.

### How is the language of an utterance determined?
`IntentService.disambiguate_lang()` checks context keys in priority order:
1. `stt_lang` — language used by STT to transcribe
2. `request_lang` — language volunteered by the source (e.g., wake word detector)
3. `detected_lang` — language set by an utterance transformer plugin
4. Default config language

### What are utterance transformers?
Plugins under the `opm.utterance_transformer` entry point that pre-process utterances before intent matching. Configured under `utterance_transformers` in `mycroft.conf`. Loaded by `UtteranceTransformersService` in `ovos_core/transformers.py`.

---

## Performance

### What performance optimizations are in place?
`ovos-core` includes several built-in optimizations:

- **Thread-safe skill loading** — `_plugin_skills_lock` prevents concurrent dict mutation during `_load_plugin_skill()` and `_unload_plugin_skill()` (skill_manager.py:585-603)
- **Safe iteration snapshots** — `send_skill_list()`, `deactivate_skill()`, `activate_skill()`, and `deactivate_except()` snapshot the plugin_skills dict inside the lock before iterating to prevent RuntimeError during concurrent modifications
- **Event-based fallback signaling** — `_collect_fallback_skills()` uses `threading.Event` instead of busy-wait (fallback_service.py:122-125), reducing CPU usage on utterances reaching fallback
- **Reusable stop event** — `wait_for_intent_service()` reuses `self._stop_event` instead of creating temporary Event objects (skill_manager.py:462)
- **Pipeline matcher caching** — `get_pipeline_matcher()` uses module-level constants for migration map and pre-compiled regex (service.py:39-63, 237-238)
- **Deferred thread spawning** — `create_daemon()` for metrics upload is guarded by config check; threads only spawn if `open_data.intent_urls` is configured (service.py:322, 352)
- **Transformer plugin caching** — `UtteranceTransformersService`, `MetadataTransformersService`, and `IntentTransformersService` cache sorted plugins; cache is invalidated on `load_plugins()` (transformers.py)
- **Fast blacklist lookup** — `_logged_skill_warnings` is a set (O(1) lookup) instead of list (skill_manager.py:111)
- **Single blacklist read** — blacklist is read once before the plugin scan loop, not per-skill (skill_manager.py:363)

### How can I measure ovos-core performance?
Use the `Stopwatch` utility from `ovos_utils.metrics` to profile hot paths. Example:
```python
from ovos_utils.metrics import Stopwatch
with Stopwatch("intent_match") as s:
    match = self.intent_plugins.transform(match)
LOG.info(f"Intent transform took {s.total} seconds")
```

### Why does my IntentService seem slow on startup?
Common causes:
- **No internet** — pipeline plugins that require network (e.g., OpenWeatherMap) may timeout. Set their timeout or disable them.
- **Many skills** — each skill loads sequentially by default. Enable deferred loading: `skills.use_deferred_loading: true`
- **Slow utterance transformers** — check that plugins are not making network calls in the critical path. Consider disabling unused ones.

