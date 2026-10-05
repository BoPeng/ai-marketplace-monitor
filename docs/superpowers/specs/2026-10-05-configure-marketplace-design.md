# Design: AI-assisted `aimm-configure`, starting with marketplaces

**Date:** 2026-10-05 (revised: tool-based architecture)
**Status:** Draft, for review

## Summary

`aimm-configure` configures aimm through a conversation with the user's AI service. The AI acts
only through **tools** that aimm owns: it asks the user with `ask_user`, reads and drafts a section
with section tools (`marketplace_show`, `marketplace_update`, ...), and saves with `save`, which
shows the change and asks the user once before anything is written. A command is a set of
toolkits:

- `aimm-configure marketplace[.NAME]`: the marketplace toolkit, restricted to one section.
- `aimm-configure`: every toolkit; the user says what they want ("limit the search to 20 miles")
  and the AI finds the section and drafts the change. No sub-conversations are entered or left.

The marketplace toolkit is the first one; item, user and notification toolkits follow in later
PRs. The LLM calls go through [Mirascope](https://mirascope.com/docs) behind a small adapter;
aimm owns the tools, validation and writing:

```text
Mirascope helps obtain tool calls.
aimm owns the tools.
aimm owns validation.
aimm owns config writing.
```

| Topic | Decision |
|---|---|
| Unit of composition | Toolkits (tools over one section type plus its playbook); a command is a set of toolkits run by one generic agent loop |
| LLM protocol | Native tool calls via Mirascope; plain-text replies are treated as a message to the user |
| What the LLM sees | Only what tools return: one section at a time (`*_show`), the names it may reference, and section names with their `request` (`list_sections`) |
| Writes | Only `save`; it writes the drafted sections, each in place in the file that defines it, after one confirmation for all of them |
| Items | The marketplace toolkit never changes items: items use marketplace values unless they set their own |
| Start | `aimm-configure marketplace` lists existing marketplaces (with `request` and settings) and asks which to update or whether to create one, before the AI starts |
| Ending | The AI decides (`save`, `finish`); aimm enforces completeness and never drops unsaved changes |

## The pattern for every section type

- **Tools touch one section.** `<type>_update(name, ...)` changes only the draft of
  `[<type>.<name>]`; `save` writes only drafted sections (`commit_sections(only=...)` refuses any
  other difference).
- **The LLM sees only what it asks for.** `<type>_show(name)` returns that section (secrets
  masked) and the names its fields may reference; `list_sections` returns section names and their
  `request`, never contents. With a single-section command the LLM can see only that section.
- **aimm mediates.** `user ⇄ aimm ⇄ LLM`: the LLM never talks to the user except through
  `ask_user` (or a plain-text reply aimm shows); aimm validates every change and decides
  completeness.
- **Playbooks describe a task** (Goal / Subtasks / Completion / Rules), never a script.

## 1. Components

All under `src/ai_marketplace_monitor/configure/` unless noted.

| Module | Role |
|---|---|
| `workspace.py` | `Workspace`: config files, user/system config (re-read after each save), drafts keyed by `(type, name)`, backup dir, UI, session notes; `SectionDraft` |
| `toolkits.py` | `Toolkit` base (section type, config class, field guides, playbook, show/update/check/apply logic), `FieldGuide`, `FieldGroup` from `option(...)` metadata |
| `marketplace.py` | `MarketplaceToolkit`: guides, validation, `missing()`, start menu |
| `tools.py` | `ToolExecutor`: the tool functions (common + per toolkit), independent of Mirascope |
| `agent.py` | the generic agent loop over a `ModelSession` (adapter interface); turn and step limits |
| `mirascope_model.py` | `MirascopeModelSession`: maps an `[ai.*]` section to a Mirascope model, registers custom endpoints, applies timeouts, strips provider-specific history, scrubs errors |
| `playbooks.py`, `playbooks/AGENT.md`, `playbooks/router.md`, `playbooks/marketplace.md` | task playbooks |
| `writer.py` | `commit_sections` (diff, one confirmation, backup, write, re-read check, verify) |
| `flow.py`, `cli.py` | commands: `aimm-configure`, `aimm-configure ai[.NAME]`, `aimm-configure marketplace[.NAME]` |
| `../ai.py` | unchanged for this PR except removing `AIBackend.chat()` (monitor-time `evaluate()` keeps the SDKs) |

## 2. Tools

Every tool returns a JSON-able dict to the LLM; errors are returned (`{"ok": false, "errors":
[...]}`), never raised, so the LLM can correct itself.

**Common tools (every command)**

| Tool | Behavior |
|---|---|
| `ask_user(message)` | aimm shows `message`, reads the user's reply (`/show` prints the drafts, `/quit` ends the session without writing), returns `{"reply": ...}` |
| `list_sections()` | every section type with its existing names and `request`s; types without a toolkit in this command are marked "not configurable here" |
| `save(message)` | for every draft with unsaved changes: requires it complete (`missing()` empty) and valid; shows `message`, each section and the file diff, asks once "Write these changes?"; writes via `commit_sections`. Returns `saved`, `declined` (ask what to change) or errors |
| `finish(message, discard_unsaved=false)` | ends the session; refused while drafts have unsaved changes unless `discard_unsaved` is true (the user chose to discard) |

**Per toolkit (`<type>` = `marketplace` now)**

| Tool | Behavior |
|---|---|
| `<type>_show(name)` | `{exists, request, saved_values, values, unsaved_changes, still_required, can_reference}`; secrets masked |
| `<type>_update(name, values={}, unset=[], request=null)` | applies to a copy of the draft: unknown fields, secrets that are not `${VAR}`, and `${VAR}` in non-secret fields are rejected; values equal to the current one in another form keep the user's form; then the toolkit validates (config class, referenced names, the whole config still loads). Errors leave the draft unchanged |
| `<type>_check(name)` | `{still_required, errors, unsaved_changes}` |

`aimm-configure` also gets `setup_ai()`: runs the scripted AI setup (`aimm-configure ai`) and
returns its outcome.

In a single-section command, `<type>_*` tools accept only the chosen name (one-section rule), and
`list_sections` is not offered.

## 3. The agent loop

```text
start: system = AGENT.md + playbooks of the command's toolkits (+ router.md for aimm-configure)
              + the field tables; first user message = the situation (command, active section)
loop:  reply = model call (timeout 150 s, one automatic retry on 5xx/timeout/connection)
       tool calls   -> execute in order (ask_user waits for the user), feed outputs back
       plain text   -> show it, read the user's reply, feed it back
       finish/quit  -> end
```

- **Limits:** at most 12 consecutive model calls without user input (then aimm asks the user
  directly, "What would you like to do?"); at most 60 model calls per session (then aimm offers to
  save unsaved, complete drafts and stops).
- **Service errors:** shown (key scrubbed); Enter retries the same call, `/quit` ends.
- **Ctrl-C** ends the program without writing.
- `aimm-configure marketplace`: before the loop, aimm lists existing marketplaces (name, item
  count, `request`, settings) and asks which to update or whether to create one (default name
  `facebook`, else asked).

## 4. Model adapter (Mirascope)

`MirascopeModelSession` turns the working `[ai.*]` section into a Mirascope model:

- OpenAI-compatible providers (UnitySVC, OpenAI, DeepSeek, Gemini's OpenAI endpoint, Ollama's
  `/v1`): `llm.register_provider("openai", scope=f"aimm-{name}/", base_url=..., api_key=...)` and
  model `aimm-{name}/{model}`. Custom scopes use the Chat Completions API.
- Anthropic: `register_provider("anthropic", scope=f"aimm-{name}/", api_key=...)`.
- **Timeouts** are applied by aimm (`asyncio.wait_for`), since Mirascope providers accept only
  `api_key` and `base_url`.
- **History:** assistant messages are re-sent without the provider's raw message
  (`raw_message = None`). Verified against UnitySVC's gateway, which rejects the extra
  `reasoning` field Mirascope would otherwise echo back.
- Errors are scrubbed of the key; `llm.TimeoutError`, `ConnectionError`, `ServerError` and 5xx
  are retried once.

Verified live (spike): tool calling works through UnitySVC `/p/llm` (`balanced`, which sometimes
answers in plain text instead of calling a tool) and through a dashscope endpoint with
`qwen3.7-flash`.

Models without tool calling are out of scope; the error is shown and the user can choose another
AI section.

## 5. Playbooks and field guides

Playbooks are markdown with `key: value` frontmatter (`section`, `summary` required). Section
playbooks need `## Goal`, `## Subtasks`, `## Completion` (`## Rules` optional); `## Completion`
names every requirement `missing()` can report (a test checks this). Bundled in
`configure/playbooks/`; house rules from `~/.ai-marketplace-monitor/playbooks/<name>.md` are
appended (they may override `summary` only).

- `AGENT.md` (every command): act only through tools; change a section only with
  `<type>_update`; talk to the user with `ask_user`; save with `save` and end with `finish`;
  secrets only as `${VAR}`; leave defaults unset unless asked; whenever asking what to set or
  change, list the main settings with current values; do not finish with an unanswered question;
  never say something is saved before `save` returns `saved`.
- `router.md` (`aimm-configure`): find what the user wants to change with `list_sections` (match
  by name or `request`), use that type's tools, use `setup_ai` for AI services, and say plainly
  when a section type cannot be configured here yet.
- `marketplace.md`: as before (location from a pasted Facebook URL, never guessed; items are not
  changed here).

### Field guides (marketplace)

Every field gets a guide; the table lists the guidance in short form. `rating`, `availability`,
`delivery_method` and `date_listed` also accept a list of two values, for the first search and for
later searches (see "First and subsequent searches" in the README); guides say so. Accepted values come from
the config classes and must stay in sync with them (tests check enum-valued fields against their
enums).

| Field | Group | Determine | Format / default |
|---|---|---|---|
| `market_type` | OWN | always Facebook | `"facebook"`; default: leave unset |
| `language` | OWN | only when listings are not in English; must match a `[translation.X]` | e.g. `"es"`; default: unset |
| `login_wait_time` | OWN | only if the user mentions slow manual login | seconds, int; default: unset |
| `username`, `password` | OWN, **secret** | never from the LLM; only `${FACEBOOK_USERNAME}` / `${FACEBOOK_PASSWORD}` if the user asks | `${VAR}`; default: unset |
| `enabled` | OWN | only when the user wants to pause this marketplace | bool; default: unset |
| `search_city` | LOCATION | the city slug in the Facebook URL `facebook.com/marketplace/<slug>/`; from the user's city | list of strings, e.g. `["houston"]` |
| `city_name` | LOCATION | display names for the cities, same length as `search_city` | list of strings; default: unset |
| `radius` | LOCATION | search radius around each city, as Facebook's distance filter | list of ints, one per city or one for all |
| `currency` | LOCATION | only when listings use a non-default currency | list of currency codes, e.g. `["USD"]`; default: unset |
| `search_region` | LOCATION | when the user wants a whole country/area; must name a defined region | list of region names, e.g. `["usa"]` |
| `notify` | SHARED | who should be told; names of `[user.*]` sections | list; default: all users (leave unset) |
| `ai` | SHARED | which AI services rate listings; names of `[ai.*]` sections | list; default: all (leave unset) |
| `exclude_sellers` | SHARED | sellers to ignore | list of names; default: unset |
| `seller_locations` | SHARED | only sellers from these places | list of strings; default: unset |
| `availability` | SHARED | in-stock / out-of-stock listings | any of `all`, `in`, `out`; default: unset |
| `condition` | SHARED | acceptable conditions | any of `new`, `used_like_new`, `used_good`, `used_fair` |
| `date_listed` | SHARED | how recent listings must be | one of `0`, `1`, `7`, `30` (days; 0 = any time) |
| `delivery_method` | SHARED | pickup / shipping | one of `local_pick_up`, `shipping`, `all` |
| `category` | SHARED | only if every item is in one category | one `Category` value, e.g. `"vehicles"`; default: unset |
| `sort_by` | SHARED | listing order | one of `suggested`, `new`, `price_ascend`, `price_descend`, `distance_ascend` |
| `min_price`, `max_price` | SHARED | price range for all items (rare at marketplace level) | string, e.g. `"100"` or `"100 USD"`; default: unset |
| `search_interval`, `max_search_interval` | SHARED | how often to search; a maximum makes the interval random in between | duration string, e.g. `"30m"`, `"1h 30m"`, `"1d"` |
| `start_at` | SHARED | fixed search times; overrides `search_interval` | list of `"HH:MM[:SS]"` (daily), `"*:MM[:SS]"` (hourly), `"*:*:SS"` (every minute) |
| `rating` | SHARED | minimum AI rating to notify | list of ints 1–5, e.g. `[4]` |
| `prompt`, `extra_prompt`, `rating_prompt` | SHARED | only when the user asks to change how the AI judges listings | free text; default: unset |

`marketplace_show` also returns the names of `[user.*]`, `[ai.*]`, `[region.*]` and
`[translation.*]` sections, i.e. the values its fields may reference. It receives nothing about
items (not even their names) or any other section's contents.


## 6. Writing

`commit_sections(ui, new_user_cfg, old_user_cfg, files, backup_dir, only=[...])`:

1. Changed sections = those that differ between the old and new user config; anything outside
   `only` is refused.
2. Each is edited key by key with tomlkit in the last file that defines it (new sections go to the
   last config file); comments, order and other sections are kept.
3. One diff preview for all files, one "Write these changes?".
4. **After confirmation, each target file is re-read; if it changed since the preview, nothing is
   written** and the user is told to try again.
5. Back up (mode 0600), write, reload and check each section reads back as written.

## 7. Normalize changes (prerequisite)

`push_down` keeps a marketplace's shared options when the marketplace has no items (defaults for
future items). `Config.from_dicts`, `expand()` and `normalize()` take `partial=True`, which skips
the check that `[marketplace]`, `[user]` and `[item]` exist; aimm-configure uses it to validate a
config that is still being built. Empty section groups are dropped.

## Errors

| Situation | Behavior |
|---|---|
| No usable AI | `aimm-configure`: offer AI setup; section commands: tell the user to run `aimm-configure ai`, exit 1 |
| Config unreadable | message, exit 1 |
| Model call fails | scrubbed message; Enter retries, `/quit` ends |
| Tool argument errors / validation errors | returned to the LLM |
| Write declined | `save` returns `declined`; the conversation continues |
| File changed during confirmation | nothing written; `save` returns an error |
| `/quit`, Ctrl-C | nothing written; exit 0 |

## Testing

- Toolkit: guide coverage, groups from metadata, enum formats, validation (bad values, unknown
  names, `search_city` format, `city_name` only with a new city), `missing()`, apply never changes
  items, `${VAR}` in non-secret fields rejected and never expanded.
- Tools (executor, no LLM): show/update/check results; update errors leave the draft unchanged;
  `save` refuses incomplete drafts, previews once, writes only drafted sections, returns
  `declined`; `finish` refuses with unsaved changes; single-section restriction.
- Agent loop with a fake `ModelSession` (scripted tool calls): ask_user returns control to the
  UI; plain-text replies; limits; service errors and retry; `/quit`.
- Writer: in-place edits, `only`, file changed during confirmation, override by a later file.
- Adapter: `[ai.*]` sections map to the right provider registration and model id (mocked); history
  stripping; timeouts; error scrubbing.
- Live (manual): `aimm-configure marketplace` and `aimm-configure` with UnitySVC and the dashscope
  endpoint.

## Documentation

`docs/usage.rst` (`aimm-configure` and `aimm-configure marketplace`), CHANGELOG under Unreleased.
