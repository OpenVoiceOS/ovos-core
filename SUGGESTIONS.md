
# ovos-core — Suggestions

This file documents proposed improvements, refactors, and feature enhancements for human developers to evaluate.

---

## [S-001] Implement skill unloading on connectivity loss [PARTIALLY ADDRESSED]

**Status**: Partially addressed (2026-03-11) — Deferred skill loading is now optional via `skills.use_deferred_loading` config flag (default: `false`). By default, all skills load unconditionally at startup, avoiding the state machine complexity. When enabled, the improved deferred loading behavior from PR #749 is used, but unload stubs (`_unload_on_network_disconnect`, etc.) remain unimplemented.

**Current Behavior**:
- **Default** (`use_deferred_loading: false`): All skills load at startup, regardless of network/internet/GUI state.
- **Opt-in** (`use_deferred_loading: true`): Skills with `network_before_load` or `internet_before_load` defer loading until bus events signal connectivity. Includes PR #749's improvements: thread-safe deferred load queue, prevents duplicate loads during startup race conditions.

**Rationale**: The default behavior is simpler and more robust. Deferred loading can break skills into invalid states (loaded but unable to function). Skills should handle runtime conditions in their own `initialize()` or `shutdown()` methods rather than relying on external state machines.

**TODO**: If `use_deferred_loading: true`, implement the three unload methods to unload skills when their runtime requirements are no longer met.

**Reference**: `ovos_core/skill_manager.py:121-126` (config flag), `_define_message_bus_events()`, `run()`, `load_plugin_skills()`.

---

## [S-002] Implement skill uninstall via bus API

**Problem/Opportunity**: `handle_uninstall_skill()` in `skill_installer.py` always returns a "not implemented" error. The `ovos.skills.uninstall` bus event is wired up but non-functional.

**Proposed Solution**: Implement `pip_uninstall([package])` call inside `handle_uninstall_skill`, using the existing `pip_uninstall` method. Optionally derive the package name from the skill's entry point metadata.

**Estimated Impact**: Medium — unblocks skill lifecycle management from remote clients and Hivemind.

**Reference**: `ovos_core/skill_installer.py:223-234`

---

## [S-003] Strengthen skill URL validation in SkillsStore

**Problem/Opportunity**: `validate_skill()` only checks for `https://github.com/` prefix. Three TODOs indicate missing checks: (1) whether the skill uses `setup.py`, (2) whether it uses `OVOSSkill` vs legacy `MycroftSkill`, (3) whether it uses legacy `CommonPlay`. Installing incompatible skills leads to silent failures.

**Proposed Solution**: Use the GitHub API to fetch `pyproject.toml`/`setup.py` from the repo and validate the skill class. Consider adding a compatibility score or warning system rather than hard-blocking.

**Estimated Impact**: Medium — improves install-time feedback and avoids loading broken skills.

**Reference**: `ovos_core/skill_installer.py:192-199`

---

## [S-004] Decouple standalone services into separate packages

**Problem/Opportunity**: `ovos-core` bundles multiple independent services — IntentService, SkillsStore, EventScheduler — each with their own `launch_standalone()` entry point. This increases install weight and makes individual service updates coupled to core releases.

**Proposed Solution**: Extract `IntentService` and `SkillsStore` into their own lightweight packages (`ovos-intent-service`, `ovos-skills-store`). `ovos-core` becomes a thin orchestrator that depends on them. Already partially reflected in the existing CLI entry points.

**Estimated Impact**: High (long-term) — reduces dependency bloat, enables independent versioning, improves modularity.

**Reference**: `pyproject.toml` extras, `ovos_core/__main__.py`, `AUDIT.md` technical debt section.

---

## [S-005] Replace bare `except:` patterns with typed exception handling

**Problem/Opportunity**: Bare `except:` blocks (catching `BaseException`, including `KeyboardInterrupt` and `SystemExit`) were found in `transformers.py` and `intent_services/service.py`. While these have been fixed to `except Exception:` in this review cycle, the pattern should be prevented from recurring.

**Proposed Solution**: Add a `flake8` or `ruff` rule (`E722` — do not use bare `except`) to the CI lint step to prevent regressions. Consider adding `ruff` to the dev dependencies.

**Estimated Impact**: Low effort, high value — enforces code quality automatically.

**Reference**: `ovos_core/transformers.py`, `ovos_core/intent_services/service.py`

---

## [S-006] Track external (standalone/Hivemind) skills in SkillManager

**Problem/Opportunity**: Four TODOs in `skill_manager.py` note that `send_skill_list`, `deactivate_skill`, `deactivate_except`, and `activate_skill` only operate on `self.plugin_skills` and do not account for `OVOSAbstractApp` or Hivemind-connected skills.

**Proposed Solution**: Introduce a secondary registry (e.g., `self.external_skills: Dict[str, SkillState]`) populated by bus messages from standalone apps announcing their presence. Merge this registry in the skill list/activate/deactivate handlers.

**Estimated Impact**: Medium — required for full skill lifecycle visibility in multi-device/Hivemind setups.

**Reference**: `ovos_core/skill_manager.py:539, 554, 568, 582`

---

## [S-007] Performance Optimizations [ADDRESSED 2026-03-11]

**Status**: Fully addressed (2026-03-11) — All identified race conditions and per-utterance overhead sources have been optimized.

**Optimizations Implemented**:
1. **Race Condition Fixes** (Priority 1):
   - Added `_plugin_skills_lock` guard to `_unload_plugin_skill()` (skill_manager.py:585-603)
   - Snapshot `plugin_skills` dict in `send_skill_list()`, `deactivate_skill()`, `activate_skill()`, `deactivate_except()` to prevent RuntimeError during concurrent modification
   - Replaced busy-wait loop with `threading.Event` in `_collect_fallback_skills()` (fallback_service.py:122-125)

2. **Per-Utterance Overhead** (Priority 2):
   - Reuse `self._stop_event` instead of creating throwaway Event objects in `wait_for_intent_service()` (skill_manager.py:462)
   - Moved `migration_map` dict and regex pattern to module-level constants (service.py:39-63), eliminating rebuild on every pipeline stage
   - Guard `create_daemon()` calls with config check to skip thread creation when metrics disabled (service.py:322, 352)

3. **Minor Optimizations** (Priority 3):
   - Changed `_logged_skill_warnings` from list to set for O(1) lookup (skill_manager.py:111)
   - Cache sorted plugins in `UtteranceTransformersService`, `MetadataTransformersService`, `IntentTransformersService` (transformers.py)
   - Read `blacklist` once before plugin scan loop (skill_manager.py:363)

**Reference**: MAINTENANCE_REPORT.md, AUDIT.md (Race Conditions section), FAQ.md (Performance section), commit `4274a52a09`.

