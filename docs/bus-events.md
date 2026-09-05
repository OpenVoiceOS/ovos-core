
# MessageBus Events Reference

All events use the OVOS `Message` format: `{type, data, context}`.

---

## Utterance / Intent Flow

| Event | Direction | Description |
|---|---|---|
| `recognizer_loop:utterance` | listener → core | User utterance, triggers intent pipeline |
| `add_context` | skill → core | Add a context entity to the session |
| `remove_context` | skill → core | Remove a named context entity |
| `clear_context` | skill → core | Clear all context entities |
| `ovos.utterance.cancelled` | core → * | Utterance was cancelled (cancel word detected) |
| `ovos.utterance.handled` | core → * | Utterance processing complete (match or failure) |
| `complete_intent_failure` | core → * | No pipeline stage could handle the utterance |

## Intent Service API

| Event | Direction | Description |
|---|---|---|
| `intent.service.intent.get` | * → core | Query the pipeline for an intent without triggering it |
| `intent.service.intent.reply` | core → * | Response to `intent.service.intent.get` |
| `intent.service.pipelines.reload` | * → core | Reload all pipeline plugins |
| `intent.service.skills.activate` | skill → core | Mark a skill as active in the session |
| `intent.service.skills.deactivate` | skill → core | Remove a skill from the active list |
| `intent.service.active_skills.get` | * → core | Query the current active skill list |
| `mycroft.intents.is_ready` | * → core | Health-check: is IntentService ready? |
| `ovos.intent.list` | * → core | Query the intent manifest (INTENT-4 §10); optional filters `skill_id`, `lang`, `session_id`; `include_definitions: true` attaches each row's registration payload |
| `ovos.intent.list.response` | core → * | Response to `ovos.intent.list`: `{ok, intents: [{skill_id, intent_name, lang, method, enabled, session_id[, definition]}]}` |
| `ovos.intent.describe` | * → core | Fetch the registration payload(s) behind one intent: `skill_id`, `intent_name`, `lang` (optional `method`) |
| `ovos.intent.describe.response` | core → * | Response to `ovos.intent.describe`: `{ok, definitions: [{method, definition}]}` or `{ok: false, error}` |

## Skill Manager

| Event | Direction | Description |
|---|---|---|
| `mycroft.skills.initialized` | core → * | All startup skills loaded, manager ready |
| `mycroft.skills.train` | core → * | Request pipeline intent training |
| `mycroft.skills.trained` | * → core | Training complete |
| `mycroft.skill.loaded` | core → * | A skill was successfully loaded |
| `mycroft.skills.list` | core → * | Response to `skillmanager.list` |
| `mycroft.skills.error` | core → * | Some skills failed to load on startup |
| `skillmanager.list` | * → core | Request list of loaded skills |
| `skillmanager.activate` | * → core | Activate (load) a skill by ID |
| `skillmanager.deactivate` | * → core | Deactivate (unload) a skill by ID |
| `skillmanager.keep` | * → core | Deactivate all skills except one |
| `ovos.skills.settings_changed` | core → * | A skill's `settings.json` file changed |

## Converse

| Event | Direction | Description |
|---|---|---|
| `converse:skill` | * → core | Route an utterance to a specific skill's converse handler |
| `{skill_id}.converse.request` | core → skill | Ask a skill to handle converse |
| `skill.converse.get_response.enable` | skill → core | Lock converse to this skill (during `get_response`) |
| `skill.converse.get_response.disable` | skill → core | Release converse lock |

## Fallback

| Event | Direction | Description |
|---|---|---|
| `ovos.skills.fallback.register` | skill → core | Register as a fallback skill with a priority |
| `ovos.skills.fallback.deregister` | skill → core | Deregister from fallback |

## Skill Installer

| Event | Direction | Description |
|---|---|---|
| `ovos.skills.install` | * → core | Install skill packages via pip |
| `ovos.skills.install.complete` | core → * | Install succeeded |
| `ovos.skills.install.failed` | core → * | Install failed |
| `ovos.skills.uninstall` | * → core | Uninstall skill packages |
| `ovos.skills.uninstall.complete` | core → * | Uninstall succeeded |
| `ovos.skills.uninstall.failed` | core → * | Uninstall failed |
| `ovos.pip.install` | * → core | Install arbitrary pip packages |
| `ovos.pip.uninstall` | * → core | Uninstall arbitrary pip packages |

## Connectivity / Network

| Event | Direction | Description |
|---|---|---|
| `mycroft.network.connected` | PHAL → * | Local network is available |
| `mycroft.internet.connected` | PHAL → * | Internet is reachable |
| `mycroft.network.disconnected` | PHAL → * | Network lost |
| `mycroft.internet.disconnected` | PHAL → * | Internet lost |
| `mycroft.gui.available` | GUI → * | GUI client connected |
| `mycroft.gui.unavailable` | GUI → * | GUI client disconnected |
| `ovos.PHAL.internet_check` | core → PHAL | Query current network/internet status |

## Audio

| Event | Direction | Description |
|---|---|---|
| `mycroft.audio.play_sound` | core → audio | Play a sound file by URI |

## Skill Activation (per-skill)

| Event | Direction | Description |
|---|---|---|
| `{skill_id}.activate` | core → skill | Skill has been activated in the session |

---

## Cross-References

### Message format
All events use the OVOS `Message` format. See **`ovos-bus-client`** for the full `Message` API: fields, routing methods (`reply`, `forward`, `response`), and `dig_for_message`:
→ [`ovos-bus-client/docs/message.md`](../../ovos-bus-client/docs/message.md)

### Session serialisation
Every reply message carries the current `Session` serialised under `context.session`. Skills and pipeline plugins can read/modify the session from the message context. See:
→ [`ovos-bus-client/docs/session.md`](../../ovos-bus-client/docs/session.md)

### `recognizer_loop:utterance`: upstream source
This event is produced by **`ovos-dinkum-listener`** at the end of the STT pipeline. Its `data` contains `utterances` (list) and its `context` carries `stt_lang`, `session`, and any listener-level transformer additions. See:
→ [`ovos-dinkum-listener/docs/voice-loop.md`](../../ovos-dinkum-listener/docs/voice-loop.md)

### `mycroft.audio.play_sound`: downstream consumer
Consumed by **`ovos-audio`**. The `uri` field can be a file path or URL. See:
→ [`ovos-audio/docs/audio-service.md`](../../ovos-audio/docs/audio-service.md)

### Connectivity events: upstream source
`mycroft.network.connected`, `mycroft.internet.connected`, etc. are produced by the connectivity PHAL plugin. The `ovos.PHAL.internet_check` request/response pattern is described in:
→ [`ovos-PHAL/docs/index.md`](../../ovos-PHAL/docs/index.md)

### GUI events
GUI-related bus events (`mycroft.gui.available`, `mycroft.gui.unavailable`, `gui.page.show`, etc.) are documented in the GUI service:
→ [`ovos-gui/docs/bus-protocol.md`](../../ovos-gui/docs/bus-protocol.md)

### Skill-side events
Skills emit and handle many additional events not listed here (intent handlers, `get_response`, OCP media, etc.). See:
→ [`ovos-workshop/docs/decorators.md`](../../ovos-workshop/docs/decorators.md)
→ [`ovos-workshop/docs/ovos-skill.md`](../../ovos-workshop/docs/ovos-skill.md)

---
[← Skill Installer](skill-installer.md) · [Home](index.md)
