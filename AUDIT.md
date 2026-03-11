
# ovos-core — Audit Report

## Documentation Status
- [ ] AGENTS.md Header Format
- [x] QUICK_FACTS.md (Moved from docs/)
- [x] FAQ.md (Moved from docs/)
- [x] MAINTENANCE_REPORT.md
- [x] AUDIT.md
- [x] SUGGESTIONS.md
- [x] docs/index.md

## Technical Debt & Issues
- **Dependency Bloat**: The `pyproject.toml` contains an extensive list of dependencies and optional extras, making the package heavy and difficult to maintain.
- **Service Bundling**: Multiple standalone services (intent, skill installer, etc.) are bundled in a single repo, increasing complexity.
- **Pipeline Complexity**: The intent pipeline is highly configurable but also highly complex, leading to potential "configuration hell" for users.
- **Legacy Compatibility**: High amount of "glue code" to maintain compatibility with Mycroft skills and legacy messagebus events.

## Code Quality Issues (Fixed in 2026-03-08 review)
- **Bare `except:` clauses** (5 instances): `transformers.py:56,116,203`, `intent_services/service.py:165,483` — fixed to `except Exception:`.
- **Typo `validate_constrainsts`** in `skill_installer.py` — fixed to `validate_constraints` (method + 2 call sites).
- **Missing return type hints** across `skill_manager.py` (all 35 methods), `skill_installer.py`, `transformers.py` — all added.
- **Missing docstrings** on `SkillsStore` methods — added.

## Known Open Issues (Tracked in SUGGESTIONS.md)
- **S-001**: `_unload_on_network_disconnect/internet_disconnect/gui_disconnect` are stub methods — no implementation.
- **S-002**: `handle_uninstall_skill` always returns "not implemented".
- **S-003**: `validate_skill` only checks GitHub URL prefix; no structural skill validation.
- **S-006**: `send_skill_list`, `activate_skill`, `deactivate_skill`, `deactivate_except` do not track external/Hivemind skills.

## Next Steps
- Audit the `optional-dependencies` list to see if some skills-essential can be decoupled (see S-004).
- Consider adding `ruff E722` lint rule to CI to prevent bare `except:` regressions (see S-005).
