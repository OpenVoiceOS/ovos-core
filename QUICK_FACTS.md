
# Quick Facts - ovos-core

The spiritual successor to Mycroft AI, OVOS is flexible voice assistant software that can be run almost anywhere!

| Feature | Details |
|---------|---------|
| Package Name | `ovos-core` |
| Version | `2.1.4a1` |
| License | Apache-2.0 |
| Repository | [OpenVoiceOS/ovos-core](https://github.com/OpenVoiceOS/ovos-core) |
| Python Support | >=3.10 |

## Testing & CI

| Feature | Details |
|---------|---------|
| Unit Tests | `test/unittests/` — run via `build_tests.yml` workflow |
| End-to-End Tests | `test/end2end/` — run via `ovoscope.yml` workflow using ovoscope framework |
| Coverage Report | `coverage.yml` workflow — deploys to GitHub Pages |
| License Check | `license_tests.yml` workflow — checks for copyleft violations |
| Security Audit | `pipaudit.yml` workflow — scans for known CVEs |
| Locale Build | `locale_check.yml` workflow — verifies locale files are packaged |
| Sync Translations | `sync_translations.yml` workflow — syncs gitlocalize translation commits |
| Type Check | `type_check.yml` workflow — mypy static type checking |
| Docs Check | `docs_check.yml` workflow — validates required docs files |
| Repo Health | `repo_health.yml` workflow — required files + version block validation |
| Release Preview | `release_preview.yml` workflow — predicts next version from PR |

### Workflows

| Workflow | Purpose |
|----------|---------|
| `build_tests.yml` | Build/install/test matrix across Python versions (unit tests) |
| `ovoscope.yml` | End-to-end skill tests with bus coverage report |
| `coverage.yml` | Pytest coverage with HTML report deployment |
| `license_tests.yml` | Dependency license compliance check |
| `pipaudit.yml` | Security vulnerability scan |
| `locale_check.yml` | Locale build verification (pyproject.toml + SOURCES.txt) |
| `sync_translations.yml` | Gitlocalize translation commit sync |
| `type_check.yml` | Mypy type checking with PR comment |
| `docs_check.yml` | Required docs files validation |
| `repo_health.yml` | Required files check + first-time contributor greeting |
| `release_preview.yml` | Next version prediction from PR labels/title |
| `release_workflow.yml` | Alpha release on PR merge to `dev` |
| `publish_stable.yml` | Stable release on PR merge to `master` |

## Entry Points

### Scripts
- `ovos-core`: `ovos_core.__main__:main`
- `ovos-intent-service`: `ovos_core.intent_services.service:launch_standalone`
- `ovos-skill-installer`: `ovos_core.skill_installer:launch_standalone`

### Pipeline Plugins (`opm.pipeline`)
- `ovos-converse-pipeline-plugin`: `ovos_core.intent_services.converse_service:ConverseService`
- `ovos-fallback-pipeline-plugin`: `ovos_core.intent_services.fallback_service:FallbackService`
- `ovos-stop-pipeline-plugin`: `ovos_core.intent_services.stop_service:StopService`
