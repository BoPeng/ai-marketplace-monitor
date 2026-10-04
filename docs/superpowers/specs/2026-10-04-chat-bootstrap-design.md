# Design: `aimm --chat` bootstrap and plain chat

**Date:** 2026-10-04
**Status:** Approved (brainstorm), pending implementation plan
**Related:** #362 (config normalization, needed later for chat-driven config edits), #365 (UnitySVC provider)

## Summary

Add `aimm --chat`: an interactive session that first determines which AI to use (the
**bootstrap**) and then runs a **plain chat** with that AI about the user's configuration.

The question/answer logic lives in a UI-independent async engine. This spec ships the
engine, a terminal front end, and a scripted front end for tests. A GUI chat panel
(WebSocket front end) is the next spec and plugs into the same engine unchanged.

## Goals

- A first-time user with no AI configured gets to a working AI with as little friction as
  possible, without ever pasting an API key into aimm or into a config file.
- A user with working AI sections confirms one (or sets up another) in one step.
- Every failure says exactly what to fix.
- The engine is front-end independent, so the CLI and the GUI ask the same questions.

## Non-goals (later specs)

- GUI chat panel (WebSocket front end).
- Chat tools and config edits (depend on `normalize()` from #362).
- Setting up notifications.
- Persisting chat history.
- `prompt_toolkit` input (history, multi-line editing).

## Architecture

New package `src/ai_marketplace_monitor/chat/`, one file per concern:

| File | Responsibility |
|---|---|
| `messages.py` | Message types the engine sends; JSON-serializable dataclasses |
| `ui.py` | `ChatUI` protocol; `ScriptedChatUI` (canned answers, records messages) |
| `cli_ui.py` | `CLIChatUI`, terminal front end built on `rich` |
| `ai_sections.py` | Read `[ai.*]` sections across config files with ownership; write/update one section with backup |
| `probe.py` | Two-step usability check |
| `bootstrap.py` | The setup flow |
| `session.py` | `run_chat(ui, config_files)`: bootstrap, then the chat loop |
| `system_prompt.md` | Package data: the chat's system prompt text |

Supporting changes outside the package:

- `config.py`: `resolve_config_files(config_files) -> List[Path]` — the default
  `~/.ai-marketplace-monitor/config.toml` (if it exists) followed by each `--config` file,
  resolved. `MarketplaceMonitor.__init__` calls it instead of computing the list inline.
  (May conflict trivially with #363, which also edits `config.py`.)
- `ai.py`: `AIBackend.chat(messages: List[Dict[str, str]]) -> str`, implemented by
  `OpenAIBackend` (covers OpenAI, DeepSeek, Gemini, Ollama, UnitySVC) and
  `AnthropicBackend`.
- `cli.py`: `--chat` flag.
- `pyproject.toml`: new dependency `tomlkit`.

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

class ChatUI(Protocol):
    async def say(self, message: Say) -> None: ...
    async def ask(self, question: Question) -> str: ...
```

- Every message type has `to_dict()` (including a `"type"` discriminator) and a
  `message_from_dict()` inverse, so a WebSocket front end can send them as JSON.
- Answers are always strings: the chosen `Option.value` for `Choose`, the typed text for
  `AskText` (empty input returns `default` if set, else `""`), `"yes"`/`"no"` for
  `Confirm`.
- There is no secret-input question type: keys are never typed into aimm.
- `ScriptedChatUI(answers: List[str])` returns answers in order and appends every `Say`
  and question to `.transcript`. Asking past the end of the script raises
  `AssertionError("unexpected question: ...")`.
- A front end signals "user wants to leave" (Ctrl-C, Ctrl-D, closed socket) by raising
  `ChatClosed` from `ask`; the engine lets it propagate and nothing is written.

### `CLIChatUI`

- Refuses to start when stdin is not a TTY: the constructor raises
  `RuntimeError("aimm --chat needs an interactive terminal")`, which the CLI prints before
  exiting with code 1.
- `Say`: styled by `kind` (`success` green, `warning` yellow, `error` red, `assistant`
  rendered as Markdown when `markdown=True`).
- `Choose`: numbered list `1) UnitySVC — recommended — one key for the AI and email`,
  prompt for a number; empty input selects `default`; invalid input re-asks.
- `AskText` / `Confirm`: `rich.prompt` style with the default shown.
- Input is read with `asyncio.to_thread(input)` so the event loop is not blocked.
- `KeyboardInterrupt` / `EOFError` while reading → `ChatClosed`.

## Discovering AI sections (`ai_sections.py`)

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
  later-file-wins rule as the real loader (`merge_dicts`). Section order: first
  appearance.
- A file that fails to parse yields an error message naming the file; bootstrap shows it
  and stops (nothing can be written safely into an unparsable file).
- `config` is built with the monitor's own classes:
  `supported_ai_backends[raw.get("provider", name).lower()].get_config(name=name, **raw)`.
- `problem` messages (known causes first, the exception text otherwise):

| Cause | Message |
|---|---|
| `api_key = "${VAR}"` and `VAR` unset | `Set the environment variable VAR` (the loader's warning is suppressed) |
| no `api_key` where required | the provider's own `... requires a string api_key ...` message |
| unknown provider | `Unknown provider "foo"; supported: anthropic, deepseek, gemini, ollama, openai, unitysvc` |

- `enabled = false` sections are listed as disabled; they are never probed or chosen.

## Two-step usability check (`probe.py`)

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
  `client.with_options(timeout=timeout, max_retries=0)` (both SDKs support it).

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

**Concurrency.** Bootstrap probes all enabled sections at once with
`asyncio.gather(*(asyncio.to_thread(probe, s) for s in sections))` after a
`Say("Checking N AI services…")`.

**Secrets.** No `message` ever contains a key: provider error text is scrubbed of the
section's resolved `api_key` value and of any `svcpass_…` / `sk-…` token before use.

## Setup flow (`bootstrap.py`)

`async def bootstrap(ui: ChatUI, files: List[Path]) -> AIConfig | None` — `None` means
"stop; the user has to do something first".

1. **Check.** `load_ai_sections` + probes. One `Say` per section:
   `✓ unitysvc — UnitySVC, balanced` / `✗ openai — Set the environment variable
   OPENAI_API_KEY` / `– old — disabled`.
2. **Working sections exist.** `Choose("Which AI should this chat use?")` with one option
   per working section, then `new` ("Set up a different AI…") and `quit`; default: the
   first working section. A section choice returns its `config`.
3. **Set up.** Reached when nothing works, or on `new`.
   `Choose("Which AI do you want to use?")`:

   | value | label | hint | default |
   |---|---|---|---|
   | `unitysvc` | UnitySVC | recommended — one key for the AI and for email notifications | ✓ |
   | `openai` | OpenAI | | |
   | `anthropic` | Anthropic | | |
   | `ollama` | Ollama | runs on your own machine, no key | |
   | `quit` | Quit | | |

   Follow-up questions:

   | Provider | Questions | Env var |
   |---|---|---|
   | UnitySVC | `Choose` tier: `fast`, `balanced` (default), `coding`, `premium` | `UNITYSVC_API_KEY` |
   | OpenAI | `AskText` model, default `OpenAIBackend.default_model` | `OPENAI_API_KEY` |
   | Anthropic | `AskText` model, default `AnthropicBackend.default_model` | `ANTHROPIC_API_KEY` |
   | Ollama | `AskText` base_url, default `http://localhost:11434/v1`; `AskText` model, default `OllamaBackend.default_model` | none |

   Target section: an existing section whose provider matches (the first one, if several)
   is **updated**, keeping its `${VAR}` name if `api_key` is already a placeholder;
   otherwise a new section `[ai.<provider>]` (suffix `_2`, `_3`… if the name is taken by
   another provider).
4. **Write.** New section content (keys omitted when they equal the provider's default for
   the section name, e.g. no `provider` for `[ai.unitysvc]`):

   ```toml
   [ai.unitysvc]
   api_key = "${UNITYSVC_API_KEY}"
   model = "balanced"
   ```

   Show the TOML and the target file, then `Confirm("Write this to <file>?")`. On "no",
   go back to step 3's provider choice.
   - Target file: an existing section's owner (`files[-1]`); a new section goes to the
     default `~/.ai-marketplace-monitor/config.toml`, created (with parent directory) if
     missing.
   - Backup: before writing an existing file, copy it to
     `~/.ai-marketplace-monitor/backups/<file name>.<YYYYmmdd-HHMMSS>` with mode `0600`.
   - Write with `tomlkit`, preserving all other content, comments, and order. Updating a
     section replaces all its keys except `request`.
   - Verify: re-run `load_ai_sections`; the section's effective `raw` (minus `request`)
     must equal what was written. Otherwise `Say(error)` naming the overriding file and
     keys, and return `None`.
5. **Finish.**
   - No env var needed (Ollama) or the env var is already set: probe the section now. OK →
     return its config. Failed → `Say(error, message)` and go back to step 3.
   - Otherwise: `Say` where to get a key (UnitySVC: `https://unitysvc.com`; OpenAI:
     `https://platform.openai.com/api-keys`; Anthropic:
     `https://console.anthropic.com/settings/keys`), then:

     ```bash
     export UNITYSVC_API_KEY=<your key>
     ```

     plus "add it to your shell profile to keep it", then "Run `aimm --chat` again." Return
     `None`.

**Key-looking input.** If any `AskText` answer matches `^(svcpass_|sk-|sk-ant-)\S{8,}`, it
is discarded (never stored, echoed, or sent anywhere), the user is told keys belong in the
environment variable, and the question is asked again.

## Chat loop (`session.py`)

```python
async def run_chat(ui: ChatUI, config_files: List[Path]) -> int   # exit code
```

1. `config = await bootstrap(ui, files)`; `None` → return 0.
2. Build the backend for `config`. System prompt = `system_prompt.md` (what aimm is; this
   chat can explain configuration but cannot change it yet) followed by the user's current
   config files, each passed through `webui.secrets_redact.redact`, in a fenced block per
   file.
3. `Say` a one-line greeting with the AI's name and model and the commands.
4. Loop: `text = await ui.ask(AskText("You"))`.
   - Empty → ask again. `/exit`, `/quit` → return 0. `/help` → list commands.
   - Otherwise append `{"role": "user", "content": text}`, call
     `await asyncio.to_thread(backend.chat, messages)`, append the reply, and
     `Say(reply, kind="assistant", markdown=True)`.
   - Provider error → `Say(error)`, remove the failed user turn, continue.
5. `ChatClosed` anywhere → return 0.

`AIBackend.chat` sends the full message list; no `max_tokens` cap (reasoning models need
room); uses `config.model or default_model`; `AnthropicBackend` passes the system message
as `system=`. History lives in memory only.

## CLI

`aimm --chat`: computes `resolve_config_files(config_files)`, runs
`asyncio.run(run_chat(CLIChatUI(), files))`, and exits with its code. It does not start
Playwright, the monitor, or the web UI. `RuntimeError` from `CLIChatUI` (no TTY) → print
and exit 1.

## Testing

No test needs network access except the opt-in live test.

| File | Covers |
|---|---|
| `tests/test_chat_messages.py` | `to_dict` / `message_from_dict` round-trip for every type |
| `tests/test_chat_ai_sections.py` | merge and ownership across files; unset env var, missing key, unknown provider, disabled; unparsable file; new section into a missing default file; update of an existing section preserving comments and `request`; backup created with mode 0600; override by a later file detected |
| `tests/test_chat_probe.py` | fake SDK clients: 401, connection error, model missing (with list), list unsupported → request step, request error text; Gemini/Ollama name matching; `max_completion_tokens` retry; key never in messages |
| `tests/test_chat_bootstrap.py` | `ScriptedChatUI` conversations: pick a working AI; nothing works → UnitySVC written → restart instructions; Ollama probed OK → returns config; declined write leaves file unchanged; quit; key-looking input refused |
| `tests/test_chat_session.py` | fake backend: reply rendered as assistant Markdown; `/exit`; provider error then recovery; system prompt contains redacted config |
| `tests/test_cli.py` (additions) | `--chat` calls `run_chat` and never constructs `MarketplaceMonitor`; non-TTY exits 1 |
| `tests/test_chat_live.py` | real UnitySVC probe with `balanced`; marked `live`, skipped unless `UNITYSVC_API_KEY` is set |

## Documentation

- `docs/usage.rst`: `--chat` usage and the setup flow.
- `docs/README.md`: mention `aimm --chat` as the easiest way to get started.
- `CHANGELOG.md`: Unreleased → Added.
