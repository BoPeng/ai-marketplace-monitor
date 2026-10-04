# Design: `aimm --chat` — section assistants, playbooks, AI bootstrap, and plain chat

**Date:** 2026-10-04
**Status:** Approved (brainstorm), pending implementation plan
**Related:** #362 (config normalization, needed later for LLM-driven section edits), #365 (UnitySVC provider)

## Summary

Add `aimm --chat`: interactive, conversation-based configuration for the CLI now and the
web UI next.

The central concept is **"chat to create or revise a section."** Every config section type
has an **assistant** that holds a conversation and produces a **proposal**; one shared
**commit** step previews, confirms, backs up, writes, and verifies every proposal. Each
assistant is backed either by **code** (a hard-coded script) or by a **playbook** — a
Markdown instruction file, like `AGENT.md` / `CLAUDE.md`, that becomes part of the LLM
chat instance. Users can add their own playbooks to extend the bundled ones.

This spec delivers the framework and its first two consumers:

1. The **AI assistant** (scripted): determines which AI to use — the bootstrap — because no
   AI exists yet to drive a conversation.
2. A **plain chat** with the chosen AI, instructed by the playbooks, that can explain the
   user's configuration but not yet change it.

LLM-driven assistants for other sections are later specs; each will mostly be a playbook
plus tests.

## Goals

- A first-time user with no AI configured gets to a working AI with as little friction as
  possible, without ever pasting an API key into aimm or into a config file.
- A user with working AI sections confirms one (or sets up another) in one step.
- Every failure says exactly what to fix.
- The engine is front-end independent: the CLI and the GUI run the same conversations.
- Adding an LLM-driven assistant for another section means writing a playbook, not a new
  write path.

## Non-goals (later specs)

- GUI chat panel (WebSocket front end) and per-section "Chat" buttons.
- `PlaybookAssistant` (LLM-driven proposals), tool calling, and playbooks for item, user,
  notification, marketplace, region, monitor, translation.
- Writing through `normalize()` (#362); this spec writes single sections with `tomlkit`.
- Persisting chat history; `prompt_toolkit` input.

## Architecture

New package `src/ai_marketplace_monitor/chat/`, one file per concern:

| File | Responsibility |
|---|---|
| `messages.py` | Message types the engine sends; JSON-serializable dataclasses |
| `ui.py` | `ChatUI` protocol, `ChatClosed`; `ScriptedChatUI` (canned answers, records messages) |
| `cli_ui.py` | `CLIChatUI`, terminal front end built on `rich` |
| `ai_sections.py` | Read `[ai.*]` sections across config files with ownership |
| `probe.py` | Two-step AI usability check |
| `sections.py` | `SectionRef`, `SectionProposal`, `SectionAssistant`, `ChatContext`, assistant registry |
| `commit.py` | The single write path: preview, confirm, backup, write, verify |
| `playbooks.py` | Playbook format, loader (bundled + user), instruction assembly |
| `playbooks/AGENT.md` | Bundled base playbook (rules for every conversation) |
| `playbooks/ai.md` | Bundled AI playbook (knowledge; the AI flow itself is code) |
| `assistants/ai.py` | `ScriptedAIAssistant` |
| `session.py` | `run_chat(ui, config_files, target)`: orchestration and the plain chat loop |

Supporting changes outside the package:

- `config.py`: `resolve_config_files(config_files) -> List[Path]` — the default
  `~/.ai-marketplace-monitor/config.toml` (if it exists) followed by each `--config` file,
  resolved. `MarketplaceMonitor.__init__` calls it instead of computing the list inline.
  (May conflict trivially with #363, which also edits `config.py`.)
- `ai.py`: `AIBackend.chat(messages: List[Dict[str, str]]) -> str`, implemented by
  `OpenAIBackend` (covers OpenAI, DeepSeek, Gemini, Ollama, UnitySVC) and
  `AnthropicBackend`.
- `cli.py`: `--chat [SECTION]`.
- `pyproject.toml`: new dependency `tomlkit`; package data `chat/playbooks/*.md`.

## Messages and the UI protocol

```python
@dataclass
class Say:
    text: str
    kind: str = "info"        # info | success | warning | error | assistant
    markdown: bool = False

@dataclass
class Option:
    value: str
    label: str
    hint: str = ""

@dataclass
class Choose:
    prompt: str
    options: List[Option]
    default: str | None = None

@dataclass
class AskText:
    prompt: str
    default: str | None = None

@dataclass
class Confirm:
    prompt: str
    default: bool = True

Question = Choose | AskText | Confirm

class ChatClosed(Exception): ...

class ChatUI(Protocol):
    async def say(self, message: Say) -> None: ...
    async def ask(self, question: Question) -> str: ...
```

- Every message type has `to_dict()` (with a `"type"` discriminator) and a
  `message_from_dict()` inverse, so a WebSocket front end can send them as JSON.
- Answers are always strings: the chosen `Option.value` for `Choose`, the typed text for
  `AskText` (empty input returns `default` if set, else `""`), `"yes"`/`"no"` for
  `Confirm`.
- There is no secret-input question type: keys are never typed into aimm.
- A front end raises `ChatClosed` from `ask` when the user leaves (Ctrl-C, Ctrl-D, closed
  socket). The engine lets it propagate; nothing is written.
- `ScriptedChatUI(answers: List[str])` returns answers in order and appends every `Say`
  and question to `.transcript`. Asking past the end of the script raises
  `AssertionError("unexpected question: ...")`.

### `CLIChatUI`

- The constructor raises `RuntimeError("aimm --chat needs an interactive terminal")` when
  stdin is not a TTY; the CLI prints it and exits with code 1.
- `Say` is styled by `kind` (`success` green, `warning` yellow, `error` red); `assistant`
  text is rendered as Markdown when `markdown=True`.
- `Choose`: numbered list (`1) UnitySVC — recommended — one key for the AI and email`),
  then a number prompt; empty input selects `default`; invalid input re-asks.
- `AskText` / `Confirm`: prompt with the default shown.
- Input is read with `asyncio.to_thread(input)`; `KeyboardInterrupt` / `EOFError` →
  `ChatClosed`.

## Sections, assistants, and commit

```python
@dataclass
class SectionRef:
    type: str                 # "ai", "item", "user", ...
    name: str | None          # None = create a new section

@dataclass
class SectionProposal:
    ref: SectionRef           # name filled in
    values: Dict[str, Any]    # the section's raw keys, e.g. {"api_key": "${UNITYSVC_API_KEY}"}
    request: str | None       # one-sentence summary of what the user asked for
    target_file: Path         # where commit writes it

@dataclass
class ChatContext:
    files: List[Path]         # resolve_config_files() result, in read order
    default_file: Path        # ~/.ai-marketplace-monitor/config.toml
    playbooks: PlaybookSet    # loaded once per session

class SectionAssistant(Protocol):
    section_type: str
    async def propose(self, ui: ChatUI, ref: SectionRef, ctx: ChatContext) -> SectionProposal | None: ...
    async def after_commit(self, ui: ChatUI, proposal: SectionProposal, ctx: ChatContext) -> Any: ...

ASSISTANTS: Dict[str, SectionAssistant] = {"ai": ScriptedAIAssistant()}
```

- `propose` holds the conversation and returns a proposal, or `None` if the user quit.
- `after_commit` runs the section-specific follow-up once the write is verified (AI:
  probe and either return the usable config or explain how to finish; notification, in a
  later spec: send a test message).
- Later specs register `PlaybookAssistant("<type>")` entries; nothing else in the
  framework changes.

### `commit(ui, proposal, ctx) -> bool` (`commit.py`)

The only code that writes config files.

1. **Preview.** `Say` the section as TOML (fenced, `markdown=True`) and the target file.
2. **Confirm.** `Confirm("Write this to <file>?")`. "no" → return `False`, nothing written.
3. **Backup.** If the target file exists, copy it to
   `~/.ai-marketplace-monitor/backups/<file name>.<YYYYmmdd-HHMMSS>` with mode `0600`.
4. **Write** with `tomlkit`, preserving all other content, comments, and order; create the
   file and its parent directory if missing. A new section is appended; an existing section
   has all its keys replaced except `request`. `request` from the proposal is written only
   once `BaseConfig` accepts it (#362); until then it is dropped.
5. **Verify.** Re-read the files and compare the section's effective merged values (minus
   `request`) with `proposal.values`. A mismatch means a later file overrides keys:
   `Say(error)` naming that file and those keys, return `False`.
6. Return `True`.

When `normalize()` (#362) lands, step 4 becomes expand → apply → normalize → write; no
assistant changes.

## Playbooks (`playbooks.py`)

A playbook is a Markdown file with YAML frontmatter:

```markdown
---
section: ai               # section type, or "base" for AGENT.md
summary: Choose and configure the AI service aimm uses to rate listings and to chat.
fields: [provider, api_key, base_url, model, max_retries, timeout, enabled, request]
check: probe              # none | probe | test_message
---
# AI playbook
...
```

- `section`, `summary` required; `fields` required for section playbooks (every key the
  section accepts); `check` defaults to `none`.
- **Bundled playbooks** live in `chat/playbooks/` (package data). This spec ships
  `AGENT.md` and `ai.md`; later specs add the other section types.
- **User playbooks** live in `~/.ai-marketplace-monitor/playbooks/` with the same file
  names (`AGENT.md`, `item.md`, …). A user playbook is **appended** to the bundled one of
  the same name under a `## House rules (from <path>)` heading; its frontmatter is
  optional and only `summary` may be set (it replaces the bundled summary). A user
  playbook with no bundled counterpart is ignored with a warning. Users cannot remove
  bundled rules — `AGENT.md` safety rules always apply.
- `load_playbooks(user_dir) -> PlaybookSet` loads both once per session; malformed
  frontmatter in a bundled playbook is a programming error (tests catch it), in a user
  playbook a warning and the file is skipped.

### Bundled content

`AGENT.md` (applies to every conversation):
- what aimm does and how config sections fit together;
- never ask for, accept, or repeat an API key or password; credentials are always
  `${VAR}` references to environment variables;
- end section work with a concrete proposal for the user to review; never claim a change
  was saved unless the commit step confirmed it;
- `request` is a short summary of what the user wants, never a transcript;
- the user has the final word; say when unsure.

`ai.md` (knowledge for the plain chat; the AI flow itself is `ScriptedAIAssistant`):
- the supported providers, their defaults, and when to choose each;
- why UnitySVC is recommended (one key for the AI and for email through
  `smtp.svcpass.com`; tiers `fast` / `balanced` / `coding` / `premium` with automatic
  failover);
- what each probe failure means and how to fix it.

### Instruction assembly

`build_instructions(playbooks, focus: str | None, config_text: str) -> str`:

| Chat instance | Instructions |
|---|---|
| General (`aimm --chat`) | `AGENT.md` + the `summary` of every section playbook + the bodies of playbooks in focus (this spec: `ai.md`) + the redacted config |
| Scoped (later: `aimm --chat item.bike`, GUI "Chat" button) | `AGENT.md` + that section's playbook + its current values + context names (users, AI backends, regions) |

Redacted config = each config file passed through `webui.secrets_redact.redact`, in a fenced
block labeled with its path.

## AI usability check

### Discovering AI sections (`ai_sections.py`)

```python
@dataclass
class AISection:
    name: str              # "unitysvc" for [ai.unitysvc]
    raw: Dict[str, Any]    # merged, unprocessed values
    files: List[Path]      # files defining it, in read order; files[-1] owns it
    config: AIConfig | None
    problem: str | None    # why config could not be built (None if built or disabled)

def load_ai_sections(files: List[Path]) -> List[AISection]
```

- Reads each file with `tomllib` (not `Config`, which requires marketplace/user/item
  sections a first-time user may not have) and merges only the `ai` tables with the same
  later-file-wins rule as the real loader (`merge_dicts`). Order: first appearance.
- A file that fails to parse raises `ConfigReadError(path, message)`; the session shows
  it and stops (nothing can be written safely into an unparsable file).
- `config` is built with the monitor's own classes:
  `supported_ai_backends[raw.get("provider", name).lower()].get_config(name=name, **raw)`.
- `problem` messages (known causes first, the exception text otherwise):

| Cause | Message |
|---|---|
| `api_key = "${VAR}"` and `VAR` unset | `Set the environment variable VAR` (the loader's warning is suppressed) |
| no `api_key` where required | the provider's own `... requires a string api_key ...` message |
| unknown provider | `Unknown provider "foo"; supported: anthropic, deepseek, gemini, ollama, openai, unitysvc` |

- `enabled = false` sections are listed as disabled; they are never probed or chosen.

### Two-step probe (`probe.py`)

```python
@dataclass
class ProbeResult:
    ok: bool
    step: str              # "config" | "models" | "request"
    model: str             # configured model, or the backend's default_model
    message: str
    available: List[str]   # model ids from step 1, when obtained

def probe(section: AISection, timeout: float = 15) -> ProbeResult
```

- A section with `problem` returns `ok=False, step="config"` without network access.
- Otherwise build the backend from `section.config`, call its existing `connect()`, and use
  `client.with_options(timeout=timeout, max_retries=0)`.

**Step 1 — list models (free).** `client.models.list()` (OpenAI SDK and Anthropic SDK).
- 401/403 → `Key rejected by <provider>`.
- Connection error / timeout → `Can't reach <base_url>`.
- 404/405 (listing unsupported) → skip to step 2.
- Configured model not listed → `Model "X" isn't available; available: a, b, c, …` (first
  10). Matching ignores a `models/` prefix (Gemini) and a `:latest` suffix (Ollama).

**Step 2 — one 1-token request.**
- OpenAI-compatible: `chat.completions.create(model, messages=[{"role": "user",
  "content": "ping"}], max_tokens=1)`; if rejected with an error mentioning
  `max_completion_tokens`, retry once with `max_completion_tokens=1`.
- Anthropic: `messages.create(model, max_tokens=1, messages=[...])`.
- Any failure → `<provider> request failed: <provider error text, truncated to 200
  chars>`. Status codes are not interpreted here: UnitySVC returns 401 both for a bad key
  and for an unknown model (verified 2026-10-04), which step 1 disambiguates.

**Concurrency.** All enabled sections are probed at once with
`asyncio.gather(*(asyncio.to_thread(probe, s) for s in sections))` after a
`Say("Checking N AI services…")`.

**Secrets.** No `message` contains a key: provider error text is scrubbed of the section's
resolved `api_key` value and of any `svcpass_…` / `sk-…` token.

## `ScriptedAIAssistant` (`assistants/ai.py`)

### `propose(ui, ref, ctx)`

Reached when no AI section works, when the user picks "Set up a different AI…", or for
`aimm --chat ai` / `ai.<name>`.

1. `Choose("Which AI do you want to use?")` (for `ai.<name>`, the provider is preselected
   from that section):

   | value | label | hint | default |
   |---|---|---|---|
   | `unitysvc` | UnitySVC | recommended — one key for the AI and for email notifications | ✓ |
   | `openai` | OpenAI | | |
   | `anthropic` | Anthropic | | |
   | `ollama` | Ollama | runs on your own machine, no key | |
   | `quit` | Quit | | |

2. Follow-up questions:

   | Provider | Questions | Env var |
   |---|---|---|
   | UnitySVC | `Choose` tier: `fast`, `balanced` (default), `coding`, `premium` | `UNITYSVC_API_KEY` |
   | OpenAI | `AskText` model, default `OpenAIBackend.default_model` | `OPENAI_API_KEY` |
   | Anthropic | `AskText` model, default `AnthropicBackend.default_model` | `ANTHROPIC_API_KEY` |
   | Ollama | `AskText` base_url, default `http://localhost:11434/v1`; `AskText` model, default `OllamaBackend.default_model` | none |

3. Target: an existing section whose provider matches (the named one for `ai.<name>`,
   else the first) is **updated**, keeping its `${VAR}` name if `api_key` is already a
   placeholder; otherwise a new section `[ai.<provider>]` (suffix `_2`, `_3`, … if the
   name is taken by another provider). `target_file`: the existing section's owner
   (`files[-1]`), else `ctx.default_file`.
4. Values omit keys equal to the provider's default for the section name (no `provider`
   for `[ai.unitysvc]`):

   ```toml
   [ai.unitysvc]
   api_key = "${UNITYSVC_API_KEY}"
   model = "balanced"
   ```

   `request`: e.g. `"Use UnitySVC (balanced tier) for rating listings and chat."`

**Key-looking input.** If any `AskText` answer matches `^(svcpass_|sk-ant-|sk-)\S{8,}`, it
is discarded (never stored, echoed, or sent anywhere), the user is told keys belong in the
environment variable, and the question is asked again.

### `after_commit(ui, proposal, ctx) -> AISetupOutcome`

```python
@dataclass
class AISetupOutcome:
    config: AIConfig | None   # set when the new section works now
    retry: bool = False       # True: it failed its probe; offer setup again
```

- No env var needed (Ollama) or the env var is already set: probe the section. OK →
  `AISetupOutcome(config)`. Failed → `Say(error, message)` and
  `AISetupOutcome(None, retry=True)`.
- Otherwise: `Say` where to get a key (UnitySVC `https://unitysvc.com`; OpenAI
  `https://platform.openai.com/api-keys`; Anthropic
  `https://console.anthropic.com/settings/keys`), then

  ```bash
  export UNITYSVC_API_KEY=<your key>
  ```

  plus "add it to your shell profile to keep it", then "Run `aimm --chat` again." Return
  `AISetupOutcome(None)`.

## Session (`session.py`)

```python
async def run_chat(ui: ChatUI, config_files: List[Path], target: str | None = None) -> int
```

1. Build `ChatContext`: `resolve_config_files`, default file, `load_playbooks`.
2. **Determine the AI** (always, unless `target` is an AI section, which goes straight to
   step 3 with that ref):
   - `load_ai_sections` + concurrent probes; one `Say` per section:
     `✓ unitysvc — UnitySVC, balanced` / `✗ openai — Set the environment variable
     OPENAI_API_KEY` / `– old — disabled`.
   - Working sections exist → `Choose("Which AI should this chat use?")`: one option per
     working section, then `new` ("Set up a different AI…") and `quit`; default: the first
     working section.
   - Nothing works, or `new` → step 3 with `SectionRef("ai", None)`.
3. **Section edit** (AI): `proposal = await ASSISTANTS["ai"].propose(...)`; `None` → return
   0. `commit` declined → back to `propose`. Committed → `after_commit`: `config` set →
   step 4; `retry` → step 3; otherwise return 0.
4. **Plain chat** with the chosen AI:
   - Instructions = `build_instructions(playbooks, focus="ai", config_text)`.
   - `Say` a greeting with the AI's name and model and the commands.
   - Loop on `AskText("You")`: empty → ask again; `/exit`, `/quit` → return 0; `/help`
     → list commands; `/edit ai` → step 3 with `SectionRef("ai", <current>)`, then resume
     the chat with the (possibly new) AI; otherwise append the user message, call
     `await asyncio.to_thread(backend.chat, messages)`, append and
     `Say(reply, kind="assistant", markdown=True)`. A provider error → `Say(error)`, drop
     the failed user turn, continue.
5. `ChatClosed` anywhere → return 0. `ConfigReadError` → `Say(error)`, return 1.

`AIBackend.chat` sends the full message list with no `max_tokens` cap (reasoning models
need room); uses `config.model or default_model`; `AnthropicBackend` passes the system
message as `system=`. History lives in memory only.

## CLI

`aimm --chat [SECTION]`:
- no `SECTION` → general session (determine the AI, then plain chat);
- `ai` or `ai.<name>` → go straight to the AI assistant for that section, then plain chat;
- any other section type → `Say(error, "Chatting about <type> sections isn't available yet")`,
  exit 1.

It computes `resolve_config_files(config_files)`, runs
`asyncio.run(run_chat(CLIChatUI(), files, target))`, and exits with its code. It does not
start Playwright, the monitor, or the web UI. `RuntimeError` from `CLIChatUI` (no TTY) →
print and exit 1.

## Testing

No test needs network access except the opt-in live test.

| File | Covers |
|---|---|
| `tests/test_chat_messages.py` | `to_dict` / `message_from_dict` round-trip for every type |
| `tests/test_chat_ai_sections.py` | merge and ownership across files; unset env var, missing key, unknown provider, disabled; unparsable file raises `ConfigReadError` |
| `tests/test_chat_probe.py` | fake SDK clients: 401, connection error, model missing (with list), list unsupported → request step, request error text; Gemini/Ollama name matching; `max_completion_tokens` retry; key never in messages |
| `tests/test_chat_commit.py` | preview shown; decline writes nothing; new section into a missing default file; update preserving comments, other sections, and `request`; backup created with mode 0600; override by a later file detected and reported |
| `tests/test_chat_playbooks.py` | bundled playbooks parse with required frontmatter and valid `check`; `ai.md` `fields` covers every `AIConfig` field; user playbook appended under "House rules"; user `summary` override; orphan user playbook warned and ignored; malformed user frontmatter skipped; `build_instructions` contents for the general instance |
| `tests/test_chat_ai_assistant.py` | `ScriptedChatUI` conversations: each provider's questions and resulting proposal; existing section updated with its `${VAR}` kept; name collision suffix; key-looking input refused; quit; `after_commit` env-set → probe → config, env-unset → instructions, Ollama probe failure → setup again |
| `tests/test_chat_session.py` | pick a working AI → plain chat; nothing works → UnitySVC committed → restart instructions → exit 0; declined commit → back to propose; `/edit ai`; fake backend reply rendered as assistant Markdown; `/exit`; provider error then recovery; instructions contain `AGENT.md`, summaries, and redacted config |
| `tests/test_cli.py` (additions) | `--chat` calls `run_chat` and never constructs `MarketplaceMonitor`; `--chat item` exits 1 with "isn't available yet"; non-TTY exits 1 |
| `tests/test_chat_live.py` | real UnitySVC probe with `balanced`; marked `live`, skipped unless `UNITYSVC_API_KEY` is set |

## Documentation

- `docs/usage.rst`: `aimm --chat [SECTION]`, the AI setup flow, and user playbooks
  (`~/.ai-marketplace-monitor/playbooks/AGENT.md` for house rules that apply to every
  chat; section playbooks take effect once that section's assistant exists).
- `docs/README.md`: mention `aimm --chat` as the easiest way to get started.
- `CHANGELOG.md`: Unreleased → Added.
