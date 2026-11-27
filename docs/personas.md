# Answer with a persona
<!-- agent-hint
covers: how to add an LLM persona that answers the utterances that no skill handles
source: pyproject.toml (plugins extra: ovos-persona), ovos_core/intent_services/service.py:_PIPELINE_MIGRATION_MAP
generated: no
verify: grep -q '"ovos-persona>=' pyproject.toml && grep -q '"ovos-fallback-pipeline-plugin-low"' ovos_core/intent_services/service.py
see: pipeline.md
-->

A persona is a set of solver plugins that answers a question when no skill matches it. [ovos-persona](https://github.com/OpenVoiceOS/ovos-persona) supplies the persona pipeline plugin. The `plugins` extra installs it.

## Example

Save this file as `~/.config/ovos_persona/salamandra.json`:

```json
{
  "name": "Salamandra",
  "solvers": ["ovos-solver-openai-persona-plugin"],
  "ovos-solver-openai-persona-plugin": {
    "api_url": "https://ollama.uoi.io/v1",
    "model": "hdnh2006/salamandra-7b-instruct",
    "key": "sk-xxxx",
    "persona": "helpful, creative, clever, and very friendly."
  }
}
```

The `api_url` is a demo server with no uptime guarantee. Use the URL of your own OpenAI-compatible server.

## Steps

1. Install a solver plugin, for example `ovos-solver-openai-persona-plugin`. The solvers of a persona try to answer in sequence, until one gives a response. See the [solvers page](https://openvoiceos.github.io/ovos-technical-manual/solvers/) of the manual.
2. Write the persona file in `~/.config/ovos_persona/`, as in the example. A plugin can also supply persona files.
3. Add the persona matchers to `intents.pipeline` in `mycroft.conf`. Put the high matcher after the high matchers of the skills, and the low matcher before the last fallback:

   ```json
   {
     "intents": {
       "persona": {"handle_fallback": true},
       "pipeline": [
         "ovos-stop-pipeline-plugin-high",
         "ovos-converse-pipeline-plugin",
         "ovos-ocp-pipeline-plugin-high",
         "ovos-padatious-pipeline-plugin-high",
         "ovos-adapt-pipeline-plugin-high",
         "ovos-persona-pipeline-plugin-high",
         "ovos-ocp-pipeline-plugin-medium",
         "ovos-fallback-pipeline-plugin-high",
         "ovos-stop-pipeline-plugin-medium",
         "ovos-adapt-pipeline-plugin-medium",
         "ovos-padatious-pipeline-plugin-medium",
         "ovos-adapt-pipeline-plugin-low",
         "ovos-common-query-pipeline-plugin",
         "ovos-fallback-pipeline-plugin-medium",
         "ovos-persona-pipeline-plugin-low",
         "ovos-fallback-pipeline-plugin-low"
       ]
     }
   }
   ```

4. Restart `ovos-core`, then speak to the persona.

## Reference

| You say | Result |
| :--- | :--- |
| "What personas are available?" | The assistant lists the personas |
| "Connect me to Salamandra" | The persona answers the utterances that follow |
| "End the conversation" | The persona stops |

The [ovos-persona README](https://github.com/OpenVoiceOS/ovos-persona) gives all the keys of a persona file.

---
[← Transformers](transformers.md) · [Home](index.md) · [Next →](converse-fallback.md)
