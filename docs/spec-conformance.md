# Spec Conformance

`ovos-core` is being brought into conformance with the formal
[OpenVoiceOS architecture specifications](https://github.com/OpenVoiceOS/architecture).
The bus-facing contracts of the intent and stop pipelines follow
**OVOS-PIPELINE-1**, **OVOS-STOP-1**, and **OVOS-INTENT-4**.

During the transition the orchestrator speaks **one** of two bus
namespaces, selected deployment-wide by the `legacy_namespace`
configuration key (default `True`). Subscribers listen on **both**
namespaces, so only one message is ever emitted and no consumer
receives duplicates.

```json
{ "legacy_namespace": true }
```

| Concern | Legacy topic (`legacy_namespace: true`) | Spec topic (`legacy_namespace: false`) | Spec |
|---|---|---|---|
| Utterance entry | `recognizer_loop:utterance` | `ovos.utterance.handle` | PIPELINE-1 §9.1 |
| Intent matched | *(none)* | `ovos.intent.matched` | PIPELINE-1 §9.2 |
| No match | `complete_intent_failure` | `ovos.intent.unmatched` | PIPELINE-1 §9.3 |
| Handler start / complete / error | *(none)* | `ovos.intent.handler.start` / `.complete` / `.error` | PIPELINE-1 §8 |
| Universal end-marker | `ovos.utterance.handled` | `ovos.utterance.handled` | PIPELINE-1 §9.5 |
| Global stop broadcast | `mycroft.stop` | `ovos.stop` | STOP-1 §5.3 |
| Stoppability query | `<skill_id>.stop.ping` (per skill) | `ovos.stop.ping` (broadcast) | STOP-1 §4.2 |
| Stoppability reply | `skill.stop.pong` | `ovos.stop.pong` | STOP-1 §4.2 |

The universal end-marker `ovos.utterance.handled` is emitted **exactly
once per entry-topic Message on every terminal path** — a successful
match, a no-match, and a stop all terminate with one and only one
end-marker (PIPELINE-1 §9.5).

## Conformance tests

Spec conformance is asserted end-to-end against a real (in-process)
orchestrator under [`ovoscope`](https://github.com/OpenVoiceOS/ovoscope):

| Suite | Spec |
|---|---|
| `test/end2end/test_pipeline1_conformance.py` | OVOS-PIPELINE-1 |
| `test/end2end/test_stop1_conformance.py` | OVOS-STOP-1 |
| `test/end2end/test_intent4_conformance.py` | OVOS-INTENT-4 |

Each suite exercises the spec namespace (`legacy_namespace: false`).
Behaviours that the implementation does not yet emit are marked
`xfail` citing the legacy topic, so the suite tracks remaining
conformance work without going red.

```bash
pytest test/end2end/test_pipeline1_conformance.py \
       test/end2end/test_stop1_conformance.py \
       test/end2end/test_intent4_conformance.py
```
