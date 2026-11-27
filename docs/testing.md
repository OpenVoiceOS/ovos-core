# Run the tests
<!-- agent-hint
covers: how to run the unit tests and the end-to-end tests, locally and on CI
source: .github/workflows/build_tests.yml, .github/workflows/ovoscope.yml, pyproject.toml (test extra)
generated: no
verify: grep -q "test_path: 'test/unittests'" .github/workflows/build_tests.yml && grep -q 'test_path: "test/end2end/"' .github/workflows/ovoscope.yml
see: index.md
-->

This page tells you how to run the two test suites of `ovos-core`: the unit tests and the end-to-end tests.

## Example

```bash
sudo apt install swig libssl-dev portaudio19-dev libpulse-dev
uv venv
uv pip install --prerelease=allow -e ".[mycroft,plugins,skills-essential,test]"
.venv/bin/pytest test/unittests
.venv/bin/pytest test/end2end
```

## Steps

1. Install the system packages. The audio and crypto dependencies build from source.
2. Install the package with the extras that CI uses. The `test` extra installs demo skills (`ovos-skill-hello-world`, `ovos-skill-parrot`, `ovos-skill-count`, `ovos-skill-fallback-unknown`) the Adapt, Padatious and m2v pipeline plugins, ovoscope, the cancel transformer, and the listener with the ggwave transformer for the data-over-sound install test. The end-to-end tests load these skills for real.
3. Run the unit tests in `test/unittests`.
4. Run the end-to-end tests in `test/end2end`. They use [ovoscope](https://github.com/TigreGotico/ovoscope): each test sends an utterance on a bus in the test process and compares the messages that come back with a list.
5. To see which bus messages the tests observed, add `--ovoscope-bus-cov`.

## Reference

### CI

| Workflow | Runs | Extras | On |
| :--- | :--- | :--- | :--- |
| `build_tests.yml` | `test/unittests` | `mycroft,plugins,skills-essential,test` | Push to `dev` and `master`, pull request to `dev` |
| `ovoscope.yml` | `test/end2end/`, with bus coverage | `test` | Push to `dev`, pull request to `dev` |

### Rules for a test

- A regression test fails on the code before the fix and passes after it.
- All tests are in `test/`. There is no `tests/` directory.
- A test that replaces a function with a mock gives it only a value that the real function can return.

---
[← Performance metrics](performance-metrics.md) · [Home](index.md) · [Next →](prerelease-quirks.md)
