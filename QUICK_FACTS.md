
# Quick Facts - ovos-core

The spiritual successor to Mycroft AI, OVOS is flexible voice assistant software that can be run almost anywhere!

| Feature | Details |
|---------|---------|
| Package Name | `ovos-core` |
| Version | `2.1.2a2` |
| License | Apache-2.0 |
| Repository | [OpenVoiceOS/ovos-core](https://github.com/OpenVoiceOS/ovos-core) |
| Python Support | >=3.9 |

## Entry Points

### Scripts
- `ovos-core`: `ovos_core.__main__:main`
- `ovos-intent-service`: `ovos_core.intent_services.service:launch_standalone`
- `ovos-skill-installer`: `ovos_core.skill_installer:launch_standalone`

### Pipeline Plugins (`opm.pipeline`)
- `ovos-converse-pipeline-plugin`: `ovos_core.intent_services.converse_service:ConverseService`
- `ovos-fallback-pipeline-plugin`: `ovos_core.intent_services.fallback_service:FallbackService`
- `ovos-stop-pipeline-plugin`: `ovos_core.intent_services.stop_service:StopService`
