
# Converse and Fallback Services

Both services are pipeline plugins shipped inside `ovos-core` and registered via its own entry points.

---

## ConverseService

**Module:** `ovos_core.intent_services.converse_service.ConverseService`
**Pipeline plugin ID:** `ovos-converse-pipeline-plugin`
**Stage name:** `converse`

Converse allows active skills to intercept utterances before general intent matching. A skill is "active" if it recently handled an utterance. Active skills are stored in the `Session` object.

### How It Works

1. `converse` stage is hit in the pipeline
2. `ConverseService.match()` iterates active skills in priority order
3. For each skill, emits `{skill_id}.converse.request` and waits for a response
4. If the skill returns `True`, the utterance is consumed
5. If not, the next active skill is tried

### Converse Modes

Controlled by `ConverseMode` and `ConverseActivationMode` from `ovos-workshop`:

- **ConverseMode** — restricts which skills may participate in converse
- **ConverseActivationMode** — controls when a skill becomes active (e.g. only when it handled the last utterance)

### `get_response` Support

During `skill.get_response`, the skill temporarily holds the converse channel:
- `skill.converse.get_response.enable` → lock converse to this skill
- `skill.converse.get_response.disable` → release lock

### Bus Events Handled

| Event | Handler |
|---|---|
| `intent.service.skills.activate` | `handle_activate_skill_request` |
| `intent.service.skills.deactivate` | `handle_deactivate_skill_request` |
| `intent.service.active_skills.get` | `handle_get_active_skills` |
| `skill.converse.get_response.enable` | `handle_get_response_enable` |
| `skill.converse.get_response.disable` | `handle_get_response_disable` |
| `converse:skill` | `handle_converse` |

### Broadcast Contest Poll (OVOS-CONVERSE-1 §4.2)

Alongside the sequential per-skill `{skill_id}.converse.request` above,
`ConverseService` also emits one broadcast `ovos.converse.ping` per round on
the static spec topic. It carries no candidate identity — the session
already names the active skills — and every active skill answers on the
shared pong topic. The legacy per-skill pings still go out alongside it: no
released `ovos-workshop` vintage binds the broadcast topic yet, so dropping
the legacy leg would silence every skill in the field. Each poll round is
correlated by `utterance_id` and session, so a late pong from a stale round
is discarded instead of winning the wrong round.

---

## FallbackService

**Module:** `ovos_core.intent_services.fallback_service.FallbackService`
**Pipeline plugin ID:** `ovos-fallback-pipeline-plugin`
**Stage names:** `fallback_high`, `fallback_medium`, `fallback_low`

Fallback skills handle utterances that nothing else could match. They register with a priority number (lower = higher priority).

### How It Works

1. A fallback stage is hit in the pipeline
2. `FallbackService.match_high/medium/low()` filters registered fallbacks by priority range
3. For each fallback skill (sorted by priority), emits a converse-style request
4. First skill that returns `True` wins

### Priority Ranges

| Stage | Priority range |
|---|---|
| `fallback_high` | 0–49 |
| `fallback_medium` | 50–89 |
| `fallback_low` | 90–100+ |

Priority overrides can be set in config:

```json
{
  "skills": {
    "fallbacks": {
      "fallback_priorities": {
        "my-skill-id": 10
      }
    }
  }
}
```

### FallbackMode

Controlled by `FallbackMode` from `ovos-workshop`:
- Restricts which skills are allowed to act as fallbacks (e.g. skill owner, anyone, or disabled)

### Bus Events Handled

| Event | Handler |
|---|---|
| `ovos.skills.fallback.register` | `handle_register_fallback` |
| `ovos.skills.fallback.deregister` | `handle_deregister_fallback` |

---

## StopService

**Module:** `ovos_core.intent_services.stop_service.StopService`
**Pipeline plugin ID:** `ovos-stop-pipeline-plugin`
**Stage names:** `stop_high`, `stop_medium`, `stop_low`

Handles "stop" / "cancel" utterances. Active skills are asked to handle the stop request in priority order. Configured under `skills.stop` in `mycroft.conf`.

---

## Cross-References

### Skill base classes for converse and fallback
Skills that participate in converse or fallback inherit from special base classes in `ovos-workshop`:

| Class | Module | Docs |
|---|---|---|
| `ConversationalSkill` | `ovos_workshop.skills` | [`ovos-workshop/docs/skill-classes.md`](../../ovos-workshop/docs/skill-classes.md) |
| `FallbackSkill` | `ovos_workshop.skills` | [`ovos-workshop/docs/skill-classes.md`](../../ovos-workshop/docs/skill-classes.md) |
| `OVOSSkill` (base, has `self.converse()`) | `ovos_workshop.skills.ovos` | [`ovos-workshop/docs/ovos-skill.md`](../../ovos-workshop/docs/ovos-skill.md) |

### Mode enums (ovos-workshop)
`ConverseMode`, `ConverseActivationMode`, and `FallbackMode` control who can participate and when. Defined in `ovos_workshop.skills.common_query_skill` and `ovos_workshop.skills` respectively → [`ovos-workshop/docs/permissions.md`](../../ovos-workshop/docs/permissions.md).

### Session & active skills
Active skills are tracked in `Session.active_skills` — `ovos_bus_client.session.Session`. The converse service reads and updates this list via `sess.activate_skill()` / `sess.deactivate_skill()`. See [`ovos-bus-client/docs/session.md`](../../ovos-bus-client/docs/session.md).

### Intent decorators for converse
Skills declare converse handlers with `@converse_handler` from `ovos-workshop` → [`ovos-workshop/docs/decorators.md`](../../ovos-workshop/docs/decorators.md).

### Full bus events list
See [`bus-events.md`](bus-events.md) for the Converse and Fallback event reference.

---
[← Transformers](transformers.md) · [Home](index.md) · [Next →](skill-installer.md)
