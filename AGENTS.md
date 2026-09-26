# AGENTS.md

Conventions for AI coding agents (internal and community) working in this
repository.

## What this repo is

`ovos-core` is the central skills-and-intents runtime of OpenVoiceOS. It owns
the intent pipeline, skill loading and lifecycle, and the fallback/converse
dispatch that decides which skill handles an utterance.

It depends on `ovos-bus-client` for messagebus transport, `ovos-config` for
configuration, `ovos-plugin-manager` for discovering STT/TTS/pipeline
plugins, and `ovos-workshop` for the skill base classes it loads. Everything
else in an OVOS install (audio, GUI, listener, individual skills) talks to
this process over the bus rather than importing it directly.

## Ground rules

- Work on a feature branch. Never push to `dev` or `master` directly.
- Open pull requests against `dev` as **drafts** until CI is green and the
  change is ready for review.
- One commit per PR. Squash before pushing if history accumulates.

- Use conventional commit prefixes (`fix:`, `feat:`, `refactor:`, `docs:`,
  `test:`, `chore:`). Reserve `feat:` for changes a user or downstream
  consumer can actually observe.

- Never hand-edit `version.py`. CI computes and bumps the version from
  conventional commit history.

- Every PR description and issue you write or edit carries an AI-authorship
  disclosure at the top, naming the exact model used, and states the text is
  not human-reviewed.

## Dependencies

- Use `uv`, never `pip`, for installing and resolving dependencies.

- Pin floors only, and always allow prereleases: `>=X.Y.Za1`.
  `ovos-core`'s runtime deps (`ovos-utils`, `ovos_bus_client`,
  `ovos-plugin-manager`, `ovos-config`, `ovos-workshop`, `ovos-spec-tools`)
  already follow this pattern in `pyproject.toml`. Match it, and do not add
  a tight upper bound.

- Never add a lockfile.
- All dependency and metadata declarations live in `pyproject.toml`.

- Never install a dependency from a git URL. Publish an alpha to PyPI and
  depend on that.

- The `test` extra pulls in a full runnable stack (a listener, several
  demo skills, a padatious/adapt pipeline plugin, `ovoscope`) because the
  test suite exercises real end-to-end skill loading, not just mocks.

## Testing

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e ".[test,mycroft]"
pytest test/
```

The suite under `test/` includes end-to-end skill-loading and intent-pipeline
tests that install and run real demo skills (`ovos-skill-hello-world`,
`ovos-skill-parrot`, `ovos-skill-count`, `ovos-skill-fallback-unknown`), so
the `test` extra alone is not enough for every test module. Check which
extras a failing test needs before assuming it's broken.

A regression test for a bug must be shown to fail against the code before the
fix and pass after it. A test that passes against unfixed code proves
nothing and does not satisfy this gate.

## Docs discipline

Any change that touches observable behavior updates `README.md` and the
relevant file under `docs/` (`architecture.md`, `pipeline.md`,
`intent-service.md`, `bus-events.md`, `converse-fallback.md`,
`skill-manager.md`, `skill-installer.md`, `transformers.md`) in the same PR.

Also add a version-stamped entry at the top of `docs/prerelease-quirks.md`
describing the change (create the file if it does not exist yet), newest
entry first.

## Repo-specific notes

- The pipeline stage order and matcher confidence handling in
  `ovos_core/intent_services` determine which skill wins a given utterance.
  Changing match-confidence thresholds or stage ordering is a behavior
  change for every skill in the ecosystem, not a local fix. Treat it with
  the same care as a public API change.

- `test/` (singular) is the one test directory. Do not create a parallel
  `tests/` directory.

- The `mycroft` optional-dependency group pulls in PHAL, audio, GUI, plus the
  dinkum listener. Installing it is what makes a locally-built assistant
  actually speak and listen, and several higher-level tests assume it is
  present.
