# AGENTS.md

`ovos-core` is the skills and intents service of OpenVoiceOS. It runs the intent pipeline, loads and unloads skills, and dispatches converse, fallback and stop.

Other services (audio, GUI, listener, skills) talk to it over the messagebus. They do not import it.

## Map

| Path | Holds |
| :--- | :--- |
| `ovos_core/__main__.py` | The `ovos-core` command, and the `--disable-*` flags of `python -m ovos_core` |
| `ovos_core/skill_manager.py` | `SkillManager`: skill discovery, loading, connectivity gating, unloading |
| `ovos_core/intent_services/service.py` | `IntentService`: transformers, the pipeline loop and the dispatch |
| `ovos_core/intent_services/converse_service.py`, `fallback_service.py`, `stop_service.py` | The converse, fallback and stop pipeline plugins |
| `ovos_core/transformers.py` | The utterance, metadata and intent transformer services |
| `ovos_core/skill_installer.py` | `SkillsStore`: pip install and uninstall over the bus |
| `test/unittests`, `test/end2end` | Unit tests and ovoscope end-to-end tests |
| `docs/` | The documentation. Start at `docs/index.md`. |

## Setup and test

```bash
sudo apt install swig libssl-dev portaudio19-dev libpulse-dev
uv venv
uv pip install --prerelease=allow -e ".[mycroft,plugins,skills-essential,test]"
.venv/bin/pytest test/unittests
.venv/bin/pytest test/end2end
```

The end-to-end tests load real demo skills from the `test` extra. See `docs/testing.md`.

## Rules

- Open pull requests against `dev`, as drafts until CI passes. Never push to `dev` or `master`.
- Use conventional commits. Use `feat:` only for a change that a user or a consumer can see.
- Do not edit `version.py`. CI sets the version from the commit history.
- Pull requests are squash-merged. Do not squash by hand.
- Put an AI disclosure at the top of each PR and issue that an agent writes. Name the exact model and say that no human reviewed the text.
- Use `uv`, not `pip`. Use floor pins with prereleases (`>=X.Y.Za1`) and no tight upper bound. Use no lockfile and no git URL dependency. All metadata is in `pyproject.toml`.
- A regression test fails on the code before the fix and passes after it. A mock returns only a value that the real function can return.
- All tests are in `test/`. Do not make a `tests/` directory.
- A change to the stage order or to the confidence thresholds of the pipeline changes which skill wins for every skill. Treat it as a change to the public API.
- A change in behaviour updates the page in `docs/` that describes it, in the same PR.
- When the behaviour differs from the last stable release, the PR also updates `docs/prerelease-quirks.md`.
