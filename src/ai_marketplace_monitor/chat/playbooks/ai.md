---
section: ai
summary: Choose and configure the AI service aimm uses to rate listings and to chat.
check: probe
---
# AI playbook

An `[ai.<name>]` section configures one AI service. If `provider` is omitted, the section
name is the provider (`[ai.openai]` uses OpenAI). How each field is derived is listed in
the field guide that follows this playbook.

## Choosing a provider

- **UnitySVC** (recommended): one `UNITYSVC_API_KEY` from https://unitysvc.com works for
  the AI and, as the SMTP password for `smtp.svcpass.com:587`, for email notifications.
  The tier picks a capability level; UnitySVC chooses the underlying model and fails over
  automatically when a provider has trouble.
- **OpenAI** / **Anthropic**: direct access with `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`.
- **Ollama**: runs models on the user's own machine; no key and no cost, but needs a
  capable computer and a pulled model.
- **DeepSeek** / **Gemini**: also supported; configure them by hand.

## When the AI check fails

- "Set the environment variable X": the key is not set in the shell that runs aimm.
  `export X=<key>` (and add it to the shell profile), then run aimm again.
- "Key rejected": the key is wrong, expired, or for another service.
- "Can't reach …": no network, a wrong `base_url`, or Ollama is not running.
- "Model … isn't available": fix `model`; the message lists what is available.
- "request failed: …": usually billing or quota; the provider's text says which.
