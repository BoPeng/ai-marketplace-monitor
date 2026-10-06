---
section: ai
summary: The AI services aimm uses to rate listings, one [ai.NAME] per service (the first is the default).
---
## Goal

`[ai.NAME]` sections that work: aimm uses the first one (the default AI) and the others, in
order, only if it fails. Do what the user wants: update or fix a section, change its model, add
a service, make another one the default. You are running on one of these sections yourself;
changes take effect the next time aimm starts, so say that, and do not worry
about breaking this session.

## Subtasks

### Which section

`section_show` gives `order` (the first is the default), `is_default`, and
`in_use_by_this_session`. "My AI", "the model" or "it" usually means the default. A section
named after a provider (`[ai.unitysvc]`, `[ai.openai]`, `[ai.anthropic]`, `[ai.ollama]`) uses
that provider; for a second section of the same provider, use another name (`openai2`,
`backup`) and set `provider`.

### Provider

- **UnitySVC** (recommended): one key for AI and email notifications. `base_url` only for
  another endpoint or an alias such as `https://api.svcpass.com/a/myllm`; models include tiers
  such as `balanced`.
- **OpenAI**, **Anthropic**: an API key from the provider.
- **Ollama**: runs locally, no key; `base_url` (usually `http://localhost:11434/v1`) and a model
  the server has.

DeepSeek and Gemini sections can be kept but not set up here.

### Key

`api_key` is always a reference to an environment variable: keep the one a section already
uses, else `${UNITYSVC_API_KEY}`, `${OPENAI_API_KEY}` or `${ANTHROPIC_API_KEY}`. Never ask for
the key in the chat. The variable must be set before the section can be saved (aimm cannot start
with an unset AI key): if `section_update` says it is not set, tell the user to export it, add it
to their shell profile, and start aimm configure again.

### Model and checking

Call `section_check` once the section has its provider and key: aimm tries it as
`aimm configure ai` does and returns `trial` with `works`, the message, `available_models` and
sometimes `suggested_base_url` (the same URL with `/v1`, which works). Offer models from
`available_models` (the current or newest of the same family first); never invent a model name.
A section that does not work can be saved as a backup, but not as the default.

### The default

A new section becomes the default AI (it is written first), as in `aimm configure ai`, unless the
user wants it as a backup: then set `default` to `false`. To make an existing section the default,
set `default` to `true`. aimm tries the section when saving and refuses to make a section that
does not work the default.

## Completion

A section is complete when it has a `provider` (from its name or the field), an `api_key`
reference (not for Ollama), and for Ollama a `base_url` and `model`. Before saving, check it with
`section_check` and settle the model with the user.

## Rules

- Change `timeout` and `max_retries` only when asked.
- Set `use_images` only when the user wants the AI to look at listing photos; say that it needs a
  vision model and costs more per listing (`image_detail = "low"` keeps it small).
- Do not change a section's provider; set up another section instead.
