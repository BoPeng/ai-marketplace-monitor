# Chat Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `aimm --chat` — a UI-independent chat engine with section builders (field guides, playbook, interpret, converse), a shared commit path, playbooks (bundled + user), a scripted AI-setup builder, and a plain chat with the chosen AI.

**Architecture:** New package `ai_marketplace_monitor.chat`. The engine talks to front ends only through `ChatUI.say` / `ChatUI.ask` with JSON-serializable messages; `CLIChatUI` is the terminal front end and `ScriptedChatUI` drives tests. Section builders describe their fields with `FieldGuide`s and produce `SectionProposal`s that one `commit()` writes with `tomlkit`; new sections start from an existing one. The AI builder is code; the chat's instructions are assembled from Markdown playbooks.

**Tech Stack:** Python 3.10+, asyncio, `rich`, `tomlkit` (new), `openai` / `anthropic` SDKs, pytest with `asyncio_mode = "auto"`.

**Spec:** `docs/superpowers/specs/2026-10-04-chat-bootstrap-design.md` — read it before any task; it is the binding authority.

## Global Constraints

- Work in the worktree `/Users/bpeng/BoPeng/ai-marketplace-monitor/.claude/worktrees/chat-bootstrap`, branch `feat/chat-bootstrap`. Never touch the main checkout (another session uses it).
- Commit after every task with `git add` of explicit paths; end every commit message with exactly `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `uv run …` rewrites `uv.lock`. Only Task 7 (which adds `tomlkit`) commits `uv.lock`; every other task runs `git checkout -- uv.lock` before `git add`.
- Commands (the project env lacks ruff/mypy, and `tests/test_facebook.py` needs `pytest_playwright`):
  - tests: `uv run pytest -q --ignore=tests/test_facebook.py` (focused: `uv run pytest <file> -v`)
  - lint: `uvx 'ruff>=0.9.2,<0.17' check src tests` — baseline is 3 pre-existing RUF059 errors (`monitor.py:696`, `tests/test_webui_config_api.py:177` and `:189`); add none
  - types: `uv run --with mypy mypy src`
- Code style: every function fully annotated, including tests (ruff `ANN`); methods annotate `self: "ClassName"`; package `__init__.py` files need a one-line docstring (ruff `D104`); line length 99.
- No API key or password is ever stored, echoed, logged, or written; credentials are always `${VAR}` references.
- Answers from `ChatUI.ask` are strings: `Option.value` for `Choose`, text for `AskText`, `"yes"`/`"no"` for `Confirm`.

## File Structure

| File | Responsibility |
|---|---|
| `src/ai_marketplace_monitor/chat/__init__.py` | package docstring |
| `chat/messages.py` | `Say`, `Option`, `Choose`, `AskText`, `Confirm`, `to_dict` / `message_from_dict` |
| `chat/ui.py` | `ChatUI`, `ChatClosed`, `ScriptedChatUI`, `CLOSE` |
| `chat/cli_ui.py` | `CLIChatUI` |
| `chat/ai_sections.py` | `AISection`, `ConfigReadError`, `read_toml`, `env_var_name`, `load_ai_sections` |
| `chat/probe.py` | `ProbeResult`, `probe`, `scrub`, `model_matches` |
| `chat/playbooks.py` | `Playbook`, `PlaybookSet`, `PlaybookError`, `load_playbooks`, `build_instructions` |
| `chat/playbooks/AGENT.md`, `chat/playbooks/ai.md` | bundled playbooks |
| `chat/sections.py` | `SectionRef`, `FieldGuide`, `InterpretResult`, `SectionProposal`, `ChatContext`, `SectionBuilder` |
| `chat/commit.py` | `CommitOutcome`, `commit`, `render_section`, `write_section`, `backup_file` |
| `chat/builders/__init__.py` | `BUILDERS` registry |
| `chat/builders/ai.py` | `ProviderSpec`, `PROVIDERS`, `AI_FIELDS`, `AISetupOutcome`, `ScriptedAIBuilder` |
| `chat/session.py` | `run_chat`, `render_config` |
| `config.py` (modify) | `resolve_config_files` |
| `monitor.py` (modify) | use `resolve_config_files` |
| `ai.py` (modify) | `AIBackend.chat` and implementations |
| `cli.py` (modify) | `--chat`, `--section` |
| `pyproject.toml` (modify) | `tomlkit` dependency; `live` pytest marker |
| `docs/usage.rst`, `docs/README.md`, `CHANGELOG.md` (modify) | docs |

Spec refinements made while planning (already reflected below; the spec is updated in Task 10):
- `commit()` returns `CommitOutcome` (`WRITTEN` / `DECLINED` / `FAILED`) instead of `bool`, so the session can tell "user said no" (back to converse) from "verification failed" (stop).
- `CLIChatUI` reads input synchronously instead of `asyncio.to_thread(input)`: nothing runs concurrently while waiting for input, and a blocked worker thread would make Ctrl-C hang on interpreter shutdown.
- `AnthropicBackend.chat` passes `max_tokens=4096` because the Anthropic API requires it; OpenAI-compatible calls stay uncapped.

---

### Task 1: Messages and the UI protocol

**Files:**
- Create: `src/ai_marketplace_monitor/chat/__init__.py`, `src/ai_marketplace_monitor/chat/messages.py`, `src/ai_marketplace_monitor/chat/ui.py`
- Test: `tests/test_chat_messages.py`

**Interfaces:**
- Produces: `Say(text, kind="info", markdown=False)`, `Option(value, label, hint="")`, `Choose(prompt, options, default=None)`, `AskText(prompt, default=None)`, `Confirm(prompt, default=True)`; each has `.to_dict() -> Dict[str, Any]`; `message_from_dict(data) -> Message`; type aliases `Question`, `Message`.
- Produces: `ChatClosed(Exception)`; `ChatUI` protocol (`async say(Say)`, `async ask(Question) -> str`); `ScriptedChatUI(answers)` with `.transcript: List[Message]` and `.said(kind=None) -> List[str]`; sentinel `CLOSE = "<close>"` (an answer that makes `ask` raise `ChatClosed`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_chat_messages.py
import json

import pytest

from ai_marketplace_monitor.chat.messages import (
    AskText,
    Choose,
    Confirm,
    Message,
    Option,
    Say,
    message_from_dict,
)
from ai_marketplace_monitor.chat.ui import CLOSE, ChatClosed, ScriptedChatUI

MESSAGES = [
    Say("hi"),
    Say("**bold**", kind="assistant", markdown=True),
    Choose("Pick one", [Option("a", "A", "the first"), Option("b", "B")], default="a"),
    AskText("Name", default="bob"),
    Confirm("Ok?", default=False),
]


@pytest.mark.parametrize("message", MESSAGES)
def test_round_trip_through_json(message: Message) -> None:
    data = message.to_dict()
    assert json.loads(json.dumps(data)) == data
    assert message_from_dict(data) == message


def test_type_discriminator() -> None:
    assert [m.to_dict()["type"] for m in MESSAGES] == [
        "say",
        "say",
        "choose",
        "ask_text",
        "confirm",
    ]


async def test_scripted_ui_answers_in_order_and_records() -> None:
    ui = ScriptedChatUI(["a", "hello", "yes"])
    await ui.say(Say("start"))
    assert await ui.ask(Choose("Pick", [Option("a", "A")])) == "a"
    assert await ui.ask(AskText("Name")) == "hello"
    assert await ui.ask(Confirm("Ok?")) == "yes"
    assert ui.said() == ["start"]
    assert len(ui.transcript) == 4


async def test_scripted_ui_filters_said_by_kind() -> None:
    ui = ScriptedChatUI([])
    await ui.say(Say("fine"))
    await ui.say(Say("bad", kind="error"))
    assert ui.said("error") == ["bad"]


async def test_scripted_ui_rejects_unexpected_question() -> None:
    ui = ScriptedChatUI([])
    with pytest.raises(AssertionError, match="unexpected question"):
        await ui.ask(AskText("Name"))


async def test_scripted_ui_rejects_answer_that_is_not_an_option() -> None:
    ui = ScriptedChatUI(["c"])
    with pytest.raises(AssertionError, match="not an option"):
        await ui.ask(Choose("Pick", [Option("a", "A"), Option("b", "B")]))


async def test_scripted_ui_rejects_bad_confirm_answer() -> None:
    ui = ScriptedChatUI(["maybe"])
    with pytest.raises(AssertionError, match="yes or no"):
        await ui.ask(Confirm("Ok?"))


async def test_scripted_ui_close_raises_chat_closed() -> None:
    ui = ScriptedChatUI([CLOSE])
    with pytest.raises(ChatClosed):
        await ui.ask(AskText("Name"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_messages.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ai_marketplace_monitor.chat'`.

- [ ] **Step 3: Implement**

```python
# src/ai_marketplace_monitor/chat/__init__.py
"""Interactive, conversation-based configuration (``aimm --chat``)."""
```

```python
# src/ai_marketplace_monitor/chat/messages.py
"""Messages exchanged between the chat engine and a front end (JSON-serializable)."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Union


class _Message:
    def to_dict(self: "_Message") -> Dict[str, Any]:
        return {"type": _NAMES[type(self)], **asdict(self)}  # type: ignore[call-overload]


@dataclass
class Say(_Message):
    text: str
    kind: str = "info"  # info | success | warning | error | assistant
    markdown: bool = False


@dataclass
class Option:
    value: str
    label: str
    hint: str = ""


@dataclass
class Choose(_Message):
    prompt: str
    options: List[Option] = field(default_factory=list)
    default: str | None = None


@dataclass
class AskText(_Message):
    prompt: str
    default: str | None = None


@dataclass
class Confirm(_Message):
    prompt: str
    default: bool = True


Question = Union[Choose, AskText, Confirm]
Message = Union[Say, Choose, AskText, Confirm]

_TYPES: Dict[str, type] = {"say": Say, "choose": Choose, "ask_text": AskText, "confirm": Confirm}
_NAMES: Dict[type, str] = {cls: name for name, cls in _TYPES.items()}


def message_from_dict(data: Dict[str, Any]) -> Message:
    """Inverse of ``to_dict``."""
    values = dict(data)
    cls = _TYPES[values.pop("type")]
    if cls is Choose:
        values["options"] = [Option(**o) for o in values.get("options", [])]
    return cls(**values)  # type: ignore[no-any-return]
```

```python
# src/ai_marketplace_monitor/chat/ui.py
"""The interface between the chat engine and its front ends."""

from typing import List, Protocol

from .messages import AskText, Choose, Confirm, Message, Question, Say

# An answer for ScriptedChatUI that simulates the user leaving (Ctrl-C, closed socket).
CLOSE = "<close>"


class ChatClosed(Exception):
    """The user left the conversation; nothing should be written."""


class ChatUI(Protocol):
    async def say(self: "ChatUI", message: Say) -> None: ...

    async def ask(self: "ChatUI", question: Question) -> str: ...


class ScriptedChatUI:
    """Front end for tests: returns canned answers in order and records every message."""

    def __init__(self: "ScriptedChatUI", answers: List[str]) -> None:
        self.answers = list(answers)
        self.transcript: List[Message] = []

    async def say(self: "ScriptedChatUI", message: Say) -> None:
        self.transcript.append(message)

    async def ask(self: "ScriptedChatUI", question: Question) -> str:
        self.transcript.append(question)
        if not self.answers:
            raise AssertionError(f"unexpected question: {question}")
        answer = self.answers.pop(0)
        if answer == CLOSE:
            raise ChatClosed
        if isinstance(question, Choose) and answer not in {o.value for o in question.options}:
            raise AssertionError(f"{answer!r} is not an option of {question}")
        if isinstance(question, Confirm) and answer not in ("yes", "no"):
            raise AssertionError(f"Confirm answers must be yes or no, got {answer!r}")
        if isinstance(question, AskText) and not answer and question.default is not None:
            return question.default
        return answer

    def said(self: "ScriptedChatUI", kind: str | None = None) -> List[str]:
        """Texts of the Say messages, optionally only those of one kind."""
        return [
            m.text for m in self.transcript if isinstance(m, Say) and kind in (None, m.kind)
        ]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_chat_messages.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint, types, commit**

Run: `uvx 'ruff>=0.9.2,<0.17' check src tests && uv run --with mypy mypy src` (only the 3 baseline ruff errors). If mypy reports an unused `type: ignore`, remove that comment.

```bash
git checkout -- uv.lock
git add src/ai_marketplace_monitor/chat/__init__.py src/ai_marketplace_monitor/chat/messages.py src/ai_marketplace_monitor/chat/ui.py tests/test_chat_messages.py
git commit -m "feat(chat): message types and UI protocol

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Terminal front end `CLIChatUI`

**Files:**
- Create: `src/ai_marketplace_monitor/chat/cli_ui.py`
- Test: `tests/test_chat_cli_ui.py`

**Interfaces:**
- Consumes: messages and `ChatClosed` (Task 1).
- Produces: `CLIChatUI(console: Console | None = None, read: Callable[[str], str] = input, interactive: bool | None = None)`; raises `RuntimeError("aimm --chat needs an interactive terminal")` when not interactive (`interactive=None` means `sys.stdin.isatty()`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_chat_cli_ui.py
import io
from typing import Callable, Union

import pytest
from rich.console import Console

from ai_marketplace_monitor.chat.cli_ui import CLIChatUI
from ai_marketplace_monitor.chat.messages import AskText, Choose, Confirm, Option, Say
from ai_marketplace_monitor.chat.ui import ChatClosed


def reader(*answers: Union[str, BaseException]) -> Callable[[str], str]:
    it = iter(answers)

    def read(prompt: str) -> str:
        value = next(it)
        if isinstance(value, BaseException):
            raise value
        return value

    return read


def make_ui(*answers: Union[str, BaseException]) -> tuple[CLIChatUI, io.StringIO]:
    out = io.StringIO()
    console = Console(file=out, width=100, color_system=None)
    return CLIChatUI(console=console, read=reader(*answers), interactive=True), out


PICK = Choose("Which AI?", [Option("u", "UnitySVC", "recommended"), Option("o", "OpenAI")], "u")


def test_refuses_without_terminal() -> None:
    with pytest.raises(RuntimeError, match="interactive terminal"):
        CLIChatUI(interactive=False)


async def test_choose_by_number_lists_options() -> None:
    ui, out = make_ui("2")
    assert await ui.ask(PICK) == "o"
    text = out.getvalue()
    assert "1) UnitySVC — recommended (default)" in text
    assert "2) OpenAI" in text


async def test_choose_empty_takes_default_and_invalid_reasks() -> None:
    ui, out = make_ui("9", "x", "")
    assert await ui.ask(PICK) == "u"
    assert out.getvalue().count("Please enter a number from 1 to 2.") == 2


async def test_confirm_answers_and_default() -> None:
    ui, out = make_ui("y", "no", "", "what", "Y")
    assert await ui.ask(Confirm("Write?")) == "yes"
    assert await ui.ask(Confirm("Write?")) == "no"
    assert await ui.ask(Confirm("Write?", default=False)) == "no"
    assert await ui.ask(Confirm("Write?")) == "yes"
    assert "Please answer y or n." in out.getvalue()


async def test_text_default() -> None:
    ui, _ = make_ui("", "gpt-5")
    assert await ui.ask(AskText("Model", default="gpt-4o")) == "gpt-4o"
    assert await ui.ask(AskText("Model", default="gpt-4o")) == "gpt-5"


@pytest.mark.parametrize("error", [EOFError(), KeyboardInterrupt()])
async def test_leaving_raises_chat_closed(error: BaseException) -> None:
    ui, _ = make_ui(error)
    with pytest.raises(ChatClosed):
        await ui.ask(AskText("You"))


async def test_say_plain_and_markdown() -> None:
    ui, out = make_ui()
    await ui.say(Say("[not markup] done", kind="success"))
    await ui.say(Say("**Bold** reply", kind="assistant", markdown=True))
    text = out.getvalue()
    assert "[not markup] done" in text
    assert "Bold reply" in text and "**" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_cli_ui.py -v`
Expected: FAIL — `ModuleNotFoundError: ... chat.cli_ui`.

- [ ] **Step 3: Implement**

```python
# src/ai_marketplace_monitor/chat/cli_ui.py
"""Terminal front end for the chat engine."""

import sys
from typing import Callable, Dict

from rich.console import Console
from rich.markdown import Markdown

from .messages import AskText, Choose, Confirm, Question, Say
from .ui import ChatClosed

_STYLES: Dict[str, str] = {
    "info": "",
    "success": "green",
    "warning": "yellow",
    "error": "bold red",
    "assistant": "",
}


class CLIChatUI:
    """Renders engine messages in the terminal and reads answers from stdin.

    Input is read synchronously: nothing else runs while the user is typing, and a
    blocked worker thread would make Ctrl-C hang on interpreter shutdown.
    """

    def __init__(
        self: "CLIChatUI",
        console: Console | None = None,
        read: Callable[[str], str] = input,
        interactive: bool | None = None,
    ) -> None:
        if interactive is None:
            interactive = sys.stdin.isatty()
        if not interactive:
            raise RuntimeError("aimm --chat needs an interactive terminal")
        self.console = console or Console()
        self._read = read

    async def say(self: "CLIChatUI", message: Say) -> None:
        if message.markdown:
            self.console.print(Markdown(message.text))
        else:
            self.console.print(
                message.text, style=_STYLES.get(message.kind, ""), markup=False, highlight=False
            )

    async def ask(self: "CLIChatUI", question: Question) -> str:
        if isinstance(question, Choose):
            return self._choose(question)
        if isinstance(question, Confirm):
            return self._confirm(question)
        return self._text(question)

    def _input(self: "CLIChatUI", prompt: str) -> str:
        try:
            return self._read(prompt)
        except (KeyboardInterrupt, EOFError) as e:
            raise ChatClosed from e

    def _choose(self: "CLIChatUI", question: Choose) -> str:
        self.console.print(question.prompt, markup=False, highlight=False)
        for i, option in enumerate(question.options, 1):
            hint = f" — {option.hint}" if option.hint else ""
            default = " (default)" if option.value == question.default else ""
            self.console.print(
                f"  {i}) {option.label}{hint}{default}", markup=False, highlight=False
            )
        while True:
            raw = self._input("> ").strip()
            if not raw and question.default is not None:
                return question.default
            if raw.isdigit() and 1 <= int(raw) <= len(question.options):
                return question.options[int(raw) - 1].value
            self.console.print(
                f"Please enter a number from 1 to {len(question.options)}.", style="yellow"
            )

    def _confirm(self: "CLIChatUI", question: Confirm) -> str:
        suffix = " [Y/n] " if question.default else " [y/N] "
        while True:
            raw = self._input(question.prompt + suffix).strip().lower()
            if not raw:
                return "yes" if question.default else "no"
            if raw in ("y", "yes"):
                return "yes"
            if raw in ("n", "no"):
                return "no"
            self.console.print("Please answer y or n.", style="yellow")

    def _text(self: "CLIChatUI", question: AskText) -> str:
        suffix = f" [{question.default}]" if question.default else ""
        raw = self._input(f"{question.prompt}{suffix}: ")
        if not raw.strip() and question.default is not None:
            return question.default
        return raw
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_chat_cli_ui.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint, types, commit**

Run: `uvx 'ruff>=0.9.2,<0.17' check src tests && uv run --with mypy mypy src`

```bash
git checkout -- uv.lock
git add src/ai_marketplace_monitor/chat/cli_ui.py tests/test_chat_cli_ui.py
git commit -m "feat(chat): terminal front end

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `resolve_config_files` and `AIBackend.chat`

**Files:**
- Modify: `src/ai_marketplace_monitor/config.py` (add `resolve_config_files`; import `amm_home` from `.utils`)
- Modify: `src/ai_marketplace_monitor/monitor.py:45-51` (use it)
- Modify: `src/ai_marketplace_monitor/ai.py` (`AIBackend.chat`, `OpenAIBackend.chat`, `AnthropicBackend.chat`)
- Test: `tests/test_chat_backend.py`

**Interfaces:**
- Produces: `resolve_config_files(config_files: List[Path] | None) -> List[Path]` (default `amm_home / "config.toml"` first if it exists, then each given file `expanduser().resolve()`d; a missing given file raises `FileNotFoundError(f"Config file {path} not found.")`).
- Produces: `AIBackend.chat(messages: List[Dict[str, str]]) -> str`; `ANTHROPIC_CHAT_MAX_TOKENS = 4096` in `ai.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_chat_backend.py
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ai_marketplace_monitor import config as config_module
from ai_marketplace_monitor.ai import (
    AnthropicBackend,
    AnthropicConfig,
    UnitySVCBackend,
    UnitySVCConfig,
)
from ai_marketplace_monitor.config import resolve_config_files


def test_resolve_without_default_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_module, "amm_home", tmp_path / "home")
    given = tmp_path / "a.toml"
    given.write_text("")
    assert resolve_config_files([given]) == [given.resolve()]


def test_resolve_puts_default_file_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text("")
    monkeypatch.setattr(config_module, "amm_home", home)
    given = tmp_path / "a.toml"
    given.write_text("")
    assert resolve_config_files([given]) == [home / "config.toml", given.resolve()]
    assert resolve_config_files(None) == [home / "config.toml"]


def test_resolve_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        resolve_config_files([tmp_path / "missing.toml"])


def test_openai_compatible_chat_uses_default_model() -> None:
    backend = UnitySVCBackend(UnitySVCConfig(name="unitysvc", api_key="svcpass_test"))
    backend.client = MagicMock()
    reply = SimpleNamespace(message=SimpleNamespace(content="hello"))
    backend.client.chat.completions.create.return_value = SimpleNamespace(choices=[reply])
    messages = [{"role": "system", "content": "be nice"}, {"role": "user", "content": "hi"}]
    assert backend.chat(messages) == "hello"
    backend.client.chat.completions.create.assert_called_once_with(
        model="balanced", messages=messages
    )


def test_anthropic_chat_moves_system_messages() -> None:
    backend = AnthropicBackend(AnthropicConfig(name="anthropic", api_key="sk-ant-test"))
    backend.client = MagicMock()
    backend.client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="hel"), SimpleNamespace(type="text", text="lo")]
    )
    messages = [{"role": "system", "content": "be nice"}, {"role": "user", "content": "hi"}]
    assert backend.chat(messages) == "hello"
    kwargs = backend.client.messages.create.call_args.kwargs
    assert kwargs["system"] == "be nice"
    assert kwargs["messages"] == [{"role": "user", "content": "hi"}]
    assert kwargs["max_tokens"] == 4096
    assert kwargs["model"] == AnthropicBackend.default_model
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_backend.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_config_files'`.

- [ ] **Step 3: Implement `resolve_config_files`**

In `config.py`, change `from .utils import MonitorConfig, Translator, hilight, merge_dicts` (or the current equivalent multi-line import) to also import `amm_home`, then add above `class ConfigItem`:

```python
def resolve_config_files(config_files: List[Path] | None) -> List[Path]:
    """Config files in read order: the default file (if it exists), then each given file."""
    for file_path in config_files or []:
        if not file_path.exists():
            raise FileNotFoundError(f"Config file {file_path} not found.")
    default_config = amm_home / "config.toml"
    return ([default_config] if default_config.exists() else []) + [
        x.expanduser().resolve() for x in config_files or []
    ]
```

In `monitor.py` `MarketplaceMonitor.__init__`, replace the loop that checks `file_path.exists()` and the `default_config = ...` / `self.config_files = ...` lines with:

```python
        self.config_files = resolve_config_files(config_files)
```

and add `resolve_config_files` to monitor.py's existing `from .config import ...` line. Remove `amm_home` from monitor.py's imports only if nothing else in monitor.py uses it.

- [ ] **Step 4: Implement `chat`**

In `ai.py`, add `Dict` and `List` to the `typing` import if missing, add the constant near the top (after imports):

```python
# the Anthropic API requires max_tokens; OpenAI-compatible chat calls stay uncapped
ANTHROPIC_CHAT_MAX_TOKENS = 4096
```

In `AIBackend` (after `evaluate`):

```python
    def chat(self: "AIBackend", messages: List[Dict[str, str]]) -> str:
        """Send a conversation (system/user/assistant messages); return the reply text."""
        raise NotImplementedError("chat must be implemented by subclasses.")
```

In `OpenAIBackend`:

```python
    def chat(self: "OpenAIBackend", messages: List[Dict[str, str]]) -> str:
        self.connect()
        assert self.client is not None
        response = self.client.chat.completions.create(
            model=self.config.model or self.default_model, messages=messages
        )
        return response.choices[0].message.content or ""
```

In `AnthropicBackend`:

```python
    def chat(self: "AnthropicBackend", messages: List[Dict[str, str]]) -> str:
        self.connect()
        assert self.client is not None
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        conversation = [m for m in messages if m["role"] != "system"]
        response = self.client.messages.create(
            model=self.config.model or self.default_model,
            max_tokens=ANTHROPIC_CHAT_MAX_TOKENS,
            system=system,
            messages=conversation,
        )
        return "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_chat_backend.py -v && uv run pytest -q --ignore=tests/test_facebook.py`
Expected: all PASS (the full suite proves the monitor refactor kept behavior).

- [ ] **Step 6: Lint, types, commit**

Run: `uvx 'ruff>=0.9.2,<0.17' check src tests && uv run --with mypy mypy src`

```bash
git checkout -- uv.lock
git add src/ai_marketplace_monitor/config.py src/ai_marketplace_monitor/monitor.py src/ai_marketplace_monitor/ai.py tests/test_chat_backend.py
git commit -m "feat: resolve_config_files and AIBackend.chat

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Discover AI sections

**Files:**
- Create: `src/ai_marketplace_monitor/chat/ai_sections.py`
- Test: `tests/test_chat_ai_sections.py`

**Interfaces:**
- Consumes: `supported_ai_backends` (`config.py`), `merge_dicts` (`utils.py`).
- Produces: `ConfigReadError(path, message)` with `.path`; `read_toml(path) -> Dict[str, Any]`; `env_var_name(value) -> str | None` (`"${X}"` → `"X"`); `AISection(name, raw, files, config=None, problem=None)` with properties `.enabled: bool` and `.provider: str` (lowercase); `load_ai_sections(files: List[Path]) -> List[AISection]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_chat_ai_sections.py
from pathlib import Path

import pytest

from ai_marketplace_monitor.ai import UnitySVCConfig
from ai_marketplace_monitor.chat.ai_sections import (
    ConfigReadError,
    env_var_name,
    load_ai_sections,
)


def write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_env_var_name() -> None:
    assert env_var_name("${UNITYSVC_API_KEY}") == "UNITYSVC_API_KEY"
    assert env_var_name("svcpass_x") is None
    assert env_var_name(None) is None


def test_merge_and_ownership(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_test")
    a = write(tmp_path / "a.toml", '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\n')
    b = write(tmp_path / "b.toml", '[ai.unitysvc]\nmodel = "fast"\n[ai.other]\nprovider = "openai"\napi_key = "k"\n')
    sections = load_ai_sections([a, b])
    assert [s.name for s in sections] == ["unitysvc", "other"]
    unitysvc = sections[0]
    assert unitysvc.raw == {"api_key": "${UNITYSVC_API_KEY}", "model": "fast"}
    assert unitysvc.files == [a, b]
    assert isinstance(unitysvc.config, UnitySVCConfig)
    assert unitysvc.problem is None
    assert sections[1].provider == "openai"


def test_unset_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNITYSVC_API_KEY", raising=False)
    path = write(tmp_path / "a.toml", '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\n')
    [section] = load_ai_sections([path])
    assert section.config is None
    assert section.problem == "Set the environment variable UNITYSVC_API_KEY"


def test_missing_key_uses_provider_message(tmp_path: Path) -> None:
    [section] = load_ai_sections([write(tmp_path / "a.toml", "[ai.unitysvc]\n")])
    assert section.problem is not None
    assert "UnitySVC requires a string api_key" in section.problem


def test_unknown_provider(tmp_path: Path) -> None:
    [section] = load_ai_sections([write(tmp_path / "a.toml", '[ai.x]\nprovider = "foo"\n')])
    assert section.problem == (
        'Unknown provider "foo"; supported: anthropic, deepseek, gemini, ollama, openai, unitysvc'
    )


def test_disabled_section_not_built(tmp_path: Path) -> None:
    [section] = load_ai_sections(
        [write(tmp_path / "a.toml", '[ai.unitysvc]\nenabled = false\napi_key = "k"\n')]
    )
    assert not section.enabled
    assert section.config is None and section.problem is None


def test_unparsable_file(tmp_path: Path) -> None:
    path = write(tmp_path / "bad.toml", "[ai\n")
    with pytest.raises(ConfigReadError) as info:
        load_ai_sections([path])
    assert info.value.path == path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_ai_sections.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/ai_marketplace_monitor/chat/ai_sections.py
"""Read [ai.*] sections across config files without loading the full config."""

import copy
import os
import re
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ..ai import AIConfig
from ..config import supported_ai_backends
from ..utils import merge_dicts

_PLACEHOLDER = re.compile(r"^\$\{(\w+)\}$")
_MARKUP = re.compile(r"\[/?[a-z ]+\]")


class ConfigReadError(Exception):
    """A config file could not be read or parsed."""

    def __init__(self: "ConfigReadError", path: Path, message: str) -> None:
        super().__init__(f"Cannot read {path}: {message}")
        self.path = path


@dataclass
class AISection:
    name: str
    raw: Dict[str, Any]
    files: List[Path]
    config: AIConfig | None = None
    problem: str | None = None

    @property
    def enabled(self: "AISection") -> bool:
        return self.raw.get("enabled") is not False

    @property
    def provider(self: "AISection") -> str:
        return str(self.raw.get("provider", self.name)).lower()


def read_toml(path: Path) -> Dict[str, Any]:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ConfigReadError(path, str(e)) from e


def env_var_name(value: Any) -> str | None:
    """`"${VAR}"` -> `"VAR"`; anything else -> None."""
    match = _PLACEHOLDER.match(value) if isinstance(value, str) else None
    return match.group(1) if match else None


def _build(name: str, raw: Dict[str, Any]) -> Tuple[AIConfig | None, str | None]:
    provider = str(raw.get("provider", name)).lower()
    backend = supported_ai_backends.get(provider)
    if backend is None:
        supported = ", ".join(sorted(supported_ai_backends))
        return None, f'Unknown provider "{provider}"; supported: {supported}'
    var = env_var_name(raw.get("api_key"))
    if var is not None and var not in os.environ:
        return None, f"Set the environment variable {var}"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return backend.get_config(name=name, **raw), None
    except Exception as e:
        return None, _MARKUP.sub("", str(e))


def load_ai_sections(files: List[Path]) -> List[AISection]:
    """Merge [ai.*] tables across files (later file wins) and build each section's config."""
    merged: Dict[str, Dict[str, Any]] = {}
    owners: Dict[str, List[Path]] = {}
    for path in files:
        for name, values in read_toml(path).get("ai", {}).items():
            merged[name] = merge_dicts([copy.deepcopy(merged.get(name, {})), copy.deepcopy(values)])
            owners.setdefault(name, []).append(path)
    sections = []
    for name, raw in merged.items():
        section = AISection(name=name, raw=raw, files=owners[name])
        if section.enabled:
            section.config, section.problem = _build(name, raw)
        sections.append(section)
    return sections
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_chat_ai_sections.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint, types, commit**

Run: `uvx 'ruff>=0.9.2,<0.17' check src tests && uv run --with mypy mypy src`

```bash
git checkout -- uv.lock
git add src/ai_marketplace_monitor/chat/ai_sections.py tests/test_chat_ai_sections.py
git commit -m "feat(chat): discover AI sections across config files

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Two-step probe

**Files:**
- Create: `src/ai_marketplace_monitor/chat/probe.py`
- Test: `tests/test_chat_probe.py`

**Interfaces:**
- Consumes: `AISection` (Task 4), backends from `ai.py`, `supported_ai_backends`.
- Produces: `ProbeResult(ok, step, model, message, available=[])`; `probe(section, timeout=15.0) -> ProbeResult`; `scrub(text, secret) -> str`; `model_matches(model, available) -> bool`; internal `_client(backend, timeout)` (tests monkeypatch it).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_chat_probe.py
from types import SimpleNamespace
from typing import Any, Iterator, List

import httpx
import openai
import pytest

from ai_marketplace_monitor.ai import UnitySVCConfig
from ai_marketplace_monitor.chat import probe as probe_module
from ai_marketplace_monitor.chat.ai_sections import AISection
from ai_marketplace_monitor.chat.probe import model_matches, probe, scrub

REQUEST = httpx.Request("GET", "https://api.svcpass.com/p/llm/models")


def status_error(code: int, message: str = "boom") -> openai.APIStatusError:
    return openai.APIStatusError(message, response=httpx.Response(code, request=REQUEST), body=None)


class FakeClient:
    def __init__(
        self: "FakeClient",
        models: List[str] | None = None,
        list_error: Exception | None = None,
        create_errors: List[Exception] | None = None,
    ) -> None:
        self._models = models if models is not None else ["fast", "balanced"]
        self._list_error = list_error
        self._create_errors = list(create_errors or [])
        self.create_calls: List[dict] = []
        self.models = SimpleNamespace(list=self._list)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _list(self: "FakeClient") -> Iterator[Any]:
        if self._list_error:
            raise self._list_error
        return iter(SimpleNamespace(id=m) for m in self._models)

    def _create(self: "FakeClient", **kwargs: Any) -> Any:
        self.create_calls.append(kwargs)
        if self._create_errors:
            raise self._create_errors.pop(0)
        return SimpleNamespace(choices=[])


def section(model: str | None = None, problem: str | None = None) -> AISection:
    raw = {"api_key": "svcpass_secretvalue123"} | ({"model": model} if model else {})
    config = None if problem else UnitySVCConfig(name="unitysvc", **raw)
    return AISection("unitysvc", raw, [], config=config, problem=problem)


def use(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> None:
    monkeypatch.setattr(probe_module, "_client", lambda backend, timeout: client)


def test_config_problem_skips_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(backend: Any, timeout: float) -> Any:
        raise AssertionError("no network expected")

    monkeypatch.setattr(probe_module, "_client", fail)
    result = probe(section(problem="Set the environment variable UNITYSVC_API_KEY"))
    assert (result.ok, result.step) == (False, "config")
    assert result.model == "balanced"
    assert result.message == "Set the environment variable UNITYSVC_API_KEY"


def test_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    use(monkeypatch, client)
    result = probe(section())
    assert result.ok and result.available == ["fast", "balanced"]
    assert client.create_calls[0]["max_tokens"] == 1
    assert client.create_calls[0]["model"] == "balanced"


def test_key_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, FakeClient(list_error=status_error(401)))
    result = probe(section())
    assert (result.ok, result.step, result.message) == (False, "models", "Key rejected by unitysvc")


def test_cannot_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, FakeClient(list_error=openai.APIConnectionError(request=REQUEST)))
    result = probe(section())
    assert result.message == "Can't reach https://api.svcpass.com/p/llm"


def test_model_not_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, FakeClient(models=[f"m{i}" for i in range(12)]))
    result = probe(section(model="nope"))
    assert not result.ok and result.step == "models"
    assert result.message.startswith('Model "nope" isn\'t available; available: m0, m1')
    assert result.message.endswith(", …")


def test_listing_unsupported_goes_to_request(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, FakeClient(list_error=status_error(404)))
    assert probe(section()).ok


def test_request_error_is_scrubbed(monkeypatch: pytest.MonkeyPatch) -> None:
    error = status_error(401, "no credit for svcpass_secretvalue123 / sk-abcdefghijk")
    use(monkeypatch, FakeClient(create_errors=[error]))
    result = probe(section())
    assert (result.ok, result.step) == (False, "request")
    assert "svcpass_secretvalue123" not in result.message
    assert "sk-abcdefghijk" not in result.message
    assert result.message.startswith("unitysvc request failed:")


def test_retries_with_max_completion_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(
        create_errors=[status_error(400, "Use 'max_completion_tokens' instead of max_tokens")]
    )
    use(monkeypatch, client)
    assert probe(section()).ok
    assert client.create_calls[1]["max_completion_tokens"] == 1


def test_model_matching() -> None:
    assert model_matches("gemini-2.5-flash", ["models/gemini-2.5-flash"])
    assert model_matches("llama3", ["llama3:latest"])
    assert not model_matches("llama3", ["llama3.1:latest"])


def test_scrub() -> None:
    assert scrub("key abc123 leaked", "abc123") == "key <REDACTED> leaked"
    assert scrub("token sk-ant-abcdefgh", None) == "token <REDACTED>"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_probe.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/ai_marketplace_monitor/chat/probe.py
"""Two-step check that an AI section is usable: list models, then a 1-token request."""

import re
from dataclasses import dataclass, field
from typing import Any, List

import anthropic
import openai

from ..ai import AIBackend, AnthropicBackend
from ..config import supported_ai_backends
from .ai_sections import AISection

_TOKEN = re.compile(r"(svcpass_|sk-ant-|sk-)[A-Za-z0-9_\-]{4,}")
_PING = [{"role": "user", "content": "ping"}]
_CONNECTION_ERRORS = (openai.APIConnectionError, anthropic.APIConnectionError)


@dataclass
class ProbeResult:
    ok: bool
    step: str  # "config" | "models" | "request"
    model: str
    message: str
    available: List[str] = field(default_factory=list)


def scrub(text: str, secret: str | None) -> str:
    """Remove a known secret and anything that looks like an API key."""
    if secret:
        text = text.replace(secret, "<REDACTED>")
    return _TOKEN.sub("<REDACTED>", text)


def _normalize(model: str) -> str:
    return model.removeprefix("models/").removesuffix(":latest")


def model_matches(model: str, available: List[str]) -> bool:
    target = _normalize(model)
    return any(_normalize(m) == target for m in available)


def _client(backend: AIBackend, timeout: float) -> Any:
    backend.connect()
    return backend.client.with_options(timeout=timeout, max_retries=0)


def _base_url(backend: AIBackend) -> str:
    return (
        getattr(backend.config, "base_url", None)
        or getattr(backend, "base_url", None)
        or "the provider's API"
    )


def _ping(backend: AIBackend, client: Any, model: str) -> None:
    if isinstance(backend, AnthropicBackend):
        client.messages.create(model=model, max_tokens=1, messages=_PING)
        return
    try:
        client.chat.completions.create(model=model, messages=_PING, max_tokens=1)
    except Exception as e:
        if "max_completion_tokens" not in str(e):
            raise
        client.chat.completions.create(model=model, messages=_PING, max_completion_tokens=1)


def probe(section: AISection, timeout: float = 15.0) -> ProbeResult:
    backend_class = supported_ai_backends.get(section.provider)
    default_model = backend_class.default_model if backend_class else ""
    model = str(section.raw.get("model") or default_model)
    if section.config is None or backend_class is None:
        return ProbeResult(False, "config", model, section.problem or "Section could not be loaded")

    backend = backend_class(config=section.config)
    secret = section.config.api_key
    name = section.name
    client = _client(backend, timeout)

    available: List[str] = []
    try:
        available = [m.id for m in client.models.list()]
    except _CONNECTION_ERRORS:
        return ProbeResult(False, "models", model, f"Can't reach {_base_url(backend)}")
    except Exception as e:
        status = getattr(e, "status_code", None)
        if status in (401, 403):
            return ProbeResult(False, "models", model, f"Key rejected by {name}")
        if status not in (404, 405) and not isinstance(e, AttributeError):
            message = f"{name}: {scrub(str(e), secret)[:200]}"
            return ProbeResult(False, "models", model, message)
        available = []
    if available and not model_matches(model, available):
        shown = ", ".join(available[:10]) + (", …" if len(available) > 10 else "")
        message = f'Model "{model}" isn\'t available; available: {shown}'
        return ProbeResult(False, "models", model, message, available)

    try:
        _ping(backend, client, model)
    except _CONNECTION_ERRORS:
        return ProbeResult(False, "request", model, f"Can't reach {_base_url(backend)}", available)
    except Exception as e:
        message = f"{name} request failed: {scrub(str(e), secret)[:200]}"
        return ProbeResult(False, "request", model, message, available)
    return ProbeResult(True, "request", model, f"{name} — {model}", available)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_chat_probe.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint, types, commit**

Run: `uvx 'ruff>=0.9.2,<0.17' check src tests && uv run --with mypy mypy src`

```bash
git checkout -- uv.lock
git add src/ai_marketplace_monitor/chat/probe.py tests/test_chat_probe.py
git commit -m "feat(chat): two-step AI usability probe

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Playbooks

**Files:**
- Create: `src/ai_marketplace_monitor/chat/playbooks.py`, `src/ai_marketplace_monitor/chat/playbooks/AGENT.md`, `src/ai_marketplace_monitor/chat/playbooks/ai.md`
- Test: `tests/test_chat_playbooks.py`

**Interfaces:**
- Produces: `CHECKS = ("none", "probe", "test_message")`; `PlaybookError(ValueError)`; `Playbook(name, section, summary, body, check="none", house_rules=[])` with `.text() -> str`; `PlaybookSet(base: Playbook, sections: Dict[str, Playbook])`; `BUNDLED_DIR: Path`; `load_playbooks(user_dir: Path, bundled_dir: Path = BUNDLED_DIR, logger: logging.Logger | None = None) -> PlaybookSet`; `build_instructions(playbooks: PlaybookSet, focus: Sequence[str], config_text: str, details: Mapping[str, str] | None = None) -> str` (`details[section]`, e.g. a builder's field guide, is appended after that playbook).

Frontmatter format (no YAML dependency): the file starts with a `---` line, then `key: value` lines, then a `---` line. A value in `[a, b, c]` form is a list of stripped strings; anything else is a stripped string. Bundled files must have `section` and `summary`; `check` must be one of `CHECKS`. Field descriptions are not in playbooks — they are the builders' `FieldGuide`s (Task 7/8).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_chat_playbooks.py
import logging
from pathlib import Path

import pytest

from ai_marketplace_monitor.chat.playbooks import (
    BUNDLED_DIR,
    CHECKS,
    build_instructions,
    load_playbooks,
)


def test_bundled_playbooks_parse(tmp_path: Path) -> None:
    playbooks = load_playbooks(user_dir=tmp_path)
    assert playbooks.base.section == "base"
    assert "never ask for" in playbooks.base.body.lower()
    assert set(playbooks.sections) == {"ai"}
    for playbook in playbooks.sections.values():
        assert playbook.summary
        assert playbook.check in CHECKS


def test_user_playbook_appended_as_house_rules(tmp_path: Path) -> None:
    (tmp_path / "AGENT.md").write_text("Always answer in French.\n")
    (tmp_path / "ai.md").write_text("---\nsummary: My AI notes.\n---\nPrefer Ollama.\n")
    playbooks = load_playbooks(user_dir=tmp_path)
    assert "## House rules (from" in playbooks.base.text()
    assert "Always answer in French." in playbooks.base.text()
    assert playbooks.sections["ai"].summary == "My AI notes."
    assert playbooks.sections["ai"].text().endswith("Prefer Ollama.")


def test_orphan_and_malformed_user_playbooks_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "pets.md").write_text("Rules for a section that does not exist.\n")
    (tmp_path / "ai.md").write_text("---\nsummary: no closing fence\n")
    with caplog.at_level(logging.WARNING):
        playbooks = load_playbooks(user_dir=tmp_path, logger=logging.getLogger("test"))
    assert "pets.md" in caplog.text and "ai.md" in caplog.text
    assert playbooks.sections["ai"].house_rules == []


def test_missing_user_dir_is_fine(tmp_path: Path) -> None:
    assert load_playbooks(user_dir=tmp_path / "nope").sections["ai"].house_rules == []


def test_build_instructions(tmp_path: Path) -> None:
    playbooks = load_playbooks(user_dir=tmp_path)
    text = build_instructions(playbooks, ["ai"], "CONFIG-TEXT", {"ai": "FIELD-GUIDE"})
    assert text.startswith(playbooks.base.text())
    assert f"- `ai`: {playbooks.sections['ai'].summary}" in text
    body_at = text.index(playbooks.sections["ai"].body.strip())
    assert body_at < text.index("FIELD-GUIDE") < text.index("CONFIG-TEXT")
    assert text.endswith("CONFIG-TEXT")


def test_bundled_dir_is_inside_package() -> None:
    assert (BUNDLED_DIR / "AGENT.md").is_file()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_playbooks.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the bundled playbooks**

```markdown
<!-- src/ai_marketplace_monitor/chat/playbooks/AGENT.md -->
---
section: base
summary: Rules for every conversation with an AI Marketplace Monitor user.
---
# AI Marketplace Monitor assistant

You help a user configure AI Marketplace Monitor (aimm). aimm searches Facebook
Marketplace for the items the user describes, asks an AI to rate each listing, and
notifies the user about good matches.

Its configuration is a TOML file made of sections:
- `[ai.*]` — the AI services that rate listings (and power this chat);
- `[marketplace.*]` — where to search, and defaults shared by items;
- `[item.*]` — what to look for;
- `[user.*]` — who gets notified, and how;
- `[notification.*]` — shared notification channels (email, Telegram, ...);
- `[region.*]`, `[translation.*]`, `[monitor]` — search regions, page-language
  translations, and global settings.

## Rules

- Never ask for, accept, or repeat an API key, token, or password. Credentials always go
  into environment variables and the config refers to them as `${VARIABLE_NAME}`. If the
  user pastes a secret, tell them not to and do not repeat it.
- When you work on a section, end with a concrete proposal the user can review. Never say
  a change was saved unless aimm confirmed it.
- Each section may have a `request`: a one- or two-sentence summary of what the user wants
  from it, never a transcript of the conversation.
- The user has the final word. If you are not sure what they want, ask; if you are not
  sure how aimm behaves, say so instead of guessing.
- In this version you can explain the configuration but cannot change it. To set up or
  change the AI, the user can type `/edit ai`.
```

```markdown
<!-- src/ai_marketplace_monitor/chat/playbooks/ai.md -->
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
```

Each playbook file must begin with the `---` line itself; the `<!-- ... -->` lines above only label the snippets in this plan and are **not** part of the files.

- [ ] **Step 4: Implement the loader**

```python
# src/ai_marketplace_monitor/chat/playbooks.py
"""Playbooks: Markdown instructions that become part of a chat instance."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple

BUNDLED_DIR = Path(__file__).parent / "playbooks"
CHECKS = ("none", "probe", "test_message")


class PlaybookError(ValueError):
    """A playbook file is malformed."""


@dataclass
class Playbook:
    name: str  # file stem: "AGENT", "ai", ...
    section: str
    summary: str
    body: str
    check: str = "none"
    house_rules: List[Tuple[Path, str]] = field(default_factory=list)

    def text(self: "Playbook") -> str:
        parts = [self.body.strip()]
        for path, rules in self.house_rules:
            parts.append(f"## House rules (from {path})\n\n{rules}")
        return "\n\n".join(parts)


@dataclass
class PlaybookSet:
    base: Playbook
    sections: Dict[str, Playbook]


def split_frontmatter(text: str, source: Path) -> Tuple[Dict[str, object], str]:
    """Return (frontmatter, body); a file without frontmatter has an empty dict."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        raise PlaybookError(f"{source}: frontmatter has no closing '---'") from None
    meta: Dict[str, object] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise PlaybookError(f"{source}: bad frontmatter line {line!r}")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = value
    return meta, "\n".join(lines[end + 1 :]).strip() + "\n"


def parse_playbook(path: Path) -> Playbook:
    meta, body = split_frontmatter(path.read_text(encoding="utf-8"), path)
    for key in ("section", "summary"):
        if not isinstance(meta.get(key), str) or not meta[key]:
            raise PlaybookError(f"{path}: frontmatter needs '{key}'")
    section = str(meta["section"])
    check = str(meta.get("check", "none"))
    if check not in CHECKS:
        raise PlaybookError(f"{path}: check must be one of {CHECKS}")
    return Playbook(
        name=path.stem,
        section=section,
        summary=str(meta["summary"]),
        body=body,
        check=check,
    )


def _warn(logger: logging.Logger | None, message: str) -> None:
    (logger or logging.getLogger(__name__)).warning(message)


def load_playbooks(
    user_dir: Path, bundled_dir: Path = BUNDLED_DIR, logger: logging.Logger | None = None
) -> PlaybookSet:
    """Load bundled playbooks, then append user playbooks of the same name as house rules."""
    bundled = {p.stem: parse_playbook(p) for p in sorted(bundled_dir.glob("*.md"))}
    base = bundled.pop("AGENT")
    if user_dir.is_dir():
        for path in sorted(user_dir.glob("*.md")):
            target = base if path.stem == "AGENT" else bundled.get(path.stem)
            if target is None:
                _warn(logger, f"Ignoring playbook {path}: no bundled playbook named {path.stem}")
                continue
            try:
                meta, body = split_frontmatter(path.read_text(encoding="utf-8"), path)
            except PlaybookError as e:
                _warn(logger, f"Ignoring playbook {path}: {e}")
                continue
            for key in set(meta) - {"summary"}:
                _warn(logger, f"Ignoring '{key}' in {path}: only 'summary' can be set")
            if isinstance(meta.get("summary"), str) and meta["summary"]:
                target.summary = str(meta["summary"])
            if body.strip():
                target.house_rules.append((path, body.strip()))
    return PlaybookSet(base=base, sections={p.section: p for p in bundled.values()})


def build_instructions(
    playbooks: PlaybookSet,
    focus: Sequence[str],
    config_text: str,
    details: Mapping[str, str] | None = None,
) -> str:
    """System instructions: base rules, every summary, focused playbooks + details, config."""
    summaries = "\n".join(
        f"- `{p.section}`: {p.summary}" for p in playbooks.sections.values()
    )
    parts = [playbooks.base.text(), f"# Section playbooks\n\n{summaries}"]
    for name in focus:
        if name in playbooks.sections:
            parts.append(playbooks.sections[name].text())
        if details and name in details:
            parts.append(details[name])
    parts.append(config_text)
    return "\n\n".join(parts)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_chat_playbooks.py -v`
Expected: all PASS.

- [ ] **Step 6: Lint, types, commit**

Run: `uvx 'ruff>=0.9.2,<0.17' check src tests && uv run --with mypy mypy src`

```bash
git checkout -- uv.lock
git add src/ai_marketplace_monitor/chat/playbooks.py src/ai_marketplace_monitor/chat/playbooks/AGENT.md src/ai_marketplace_monitor/chat/playbooks/ai.md tests/test_chat_playbooks.py
git commit -m "feat(chat): bundled and user playbooks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Section builders and the commit path

**Files:**
- Create: `src/ai_marketplace_monitor/chat/sections.py`, `src/ai_marketplace_monitor/chat/commit.py`
- Modify: `pyproject.toml` (dependency `tomlkit`), `uv.lock` (this task only)
- Test: `tests/test_chat_sections.py`, `tests/test_chat_commit.py`

**Interfaces:**
- Consumes: `ChatUI`, `Say`, `Confirm` (Task 1); `AIBackend` (`ai.py`); `read_toml` (Task 4); `PlaybookSet` (Task 6).
- Produces (`sections.py`): `SectionRef(type, name=None)` with `.parse(text)` and `.label()`; `FieldGuide(name, derive, ask=None, inherit=True)`; `InterpretResult(values, notes=[], questions=[])`; `SectionProposal(ref, values, request, target_file)`; `ChatContext(files, default_file, playbooks, backup_dir, ai=None)`; `SectionBuilder` base class with class attributes `section_type`, `playbook`, `uses_ai`, `fields`, and methods `guide_text() -> str`, `instructions(ctx) -> str`, `template_values(template) -> Dict[str, Any]`, `interpret(current, request, ctx) -> InterpretResult` (raises `NotImplementedError`), `async converse(ui, ref, ctx) -> SectionProposal | None` (raises `NotImplementedError`), `async after_commit(ui, proposal, ctx) -> Any` (returns `None`).
- Produces (`commit.py`): `CommitOutcome` enum (`WRITTEN`, `DECLINED`, `FAILED`); `render_section(proposal) -> str`; `backup_file(path, backup_dir) -> Path`; `write_section(path, type, name, values, request)`; `effective_section(files, type, name) -> Dict[str, Any]`; `async commit(ui, proposal, ctx) -> CommitOutcome`. On `WRITTEN`, `proposal.target_file` is in `ctx.files` (inserted first if it was the newly created default file).

- [ ] **Step 1: Add the dependency**

Run: `uv add "tomlkit>=0.13"`
Expected: `pyproject.toml` gains `"tomlkit>=0.13"` in `dependencies` and `uv.lock` is updated.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_chat_commit.py
import stat
from pathlib import Path

from ai_marketplace_monitor.chat.commit import CommitOutcome, commit, render_section
from ai_marketplace_monitor.chat.playbooks import load_playbooks
from ai_marketplace_monitor.chat.sections import ChatContext, SectionProposal, SectionRef
from ai_marketplace_monitor.chat.ui import ScriptedChatUI

VALUES = {"api_key": "${UNITYSVC_API_KEY}", "model": "balanced"}

EXISTING = """\
# my config
[marketplace.facebook]
search_city = "houston"  # home

[ai.unitysvc]
request = "keep me"
api_key = "${OLD_KEY}"
model = "fast"

[item.bike]
search_phrases = "bike"
"""


def context(tmp_path: Path, files: list[Path]) -> ChatContext:
    return ChatContext(
        files=files,
        default_file=tmp_path / "home" / "config.toml",
        playbooks=load_playbooks(user_dir=tmp_path / "playbooks"),
        backup_dir=tmp_path / "backups",
    )


def proposal(target: Path, name: str = "unitysvc") -> SectionProposal:
    return SectionProposal(SectionRef("ai", name), dict(VALUES), "Use UnitySVC.", target)


def test_render_section() -> None:
    text = render_section(proposal(Path("x.toml")))
    assert text == '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\nmodel = "balanced"\n'


async def test_decline_writes_nothing(tmp_path: Path) -> None:
    ctx = context(tmp_path, [])
    ui = ScriptedChatUI(["no"])
    assert await commit(ui, proposal(ctx.default_file), ctx) is CommitOutcome.DECLINED
    assert not ctx.default_file.exists()
    assert "```toml" in ui.said()[0]


async def test_new_default_file_created(tmp_path: Path) -> None:
    ctx = context(tmp_path, [])
    outcome = await commit(ScriptedChatUI(["yes"]), proposal(ctx.default_file), ctx)
    assert outcome is CommitOutcome.WRITTEN
    assert ctx.default_file.read_text() == render_section(proposal(ctx.default_file))
    assert ctx.files == [ctx.default_file]
    assert not (tmp_path / "backups").exists()


async def test_update_preserves_file_and_request(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(EXISTING)
    ctx = context(tmp_path, [path])
    assert await commit(ScriptedChatUI(["yes"]), proposal(path), ctx) is CommitOutcome.WRITTEN
    text = path.read_text()
    assert text.startswith("# my config\n[marketplace.facebook]\nsearch_city = \"houston\"  # home")
    assert 'request = "keep me"\napi_key = "${UNITYSVC_API_KEY}"\nmodel = "balanced"' in text
    assert "[item.bike]" in text and "OLD_KEY" not in text
    [backup] = list((tmp_path / "backups").iterdir())
    assert backup.name.startswith("config.toml.")
    assert backup.read_text() == EXISTING
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


async def test_append_new_section_to_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(EXISTING)
    ctx = context(tmp_path, [path])
    outcome = await commit(ScriptedChatUI(["yes"]), proposal(path, "second"), ctx)
    assert outcome is CommitOutcome.WRITTEN
    text = path.read_text()
    assert "[ai.unitysvc]" in text and "[ai.second]" in text


async def test_override_by_later_file_detected(tmp_path: Path) -> None:
    first = tmp_path / "config.toml"
    first.write_text("")
    later = tmp_path / "later.toml"
    later.write_text('[ai.unitysvc]\nmodel = "fast"\n')
    ctx = context(tmp_path, [first, later])
    ui = ScriptedChatUI(["yes"])
    assert await commit(ui, proposal(first), ctx) is CommitOutcome.FAILED
    [error] = ui.said("error")
    assert str(later) in error and "model" in error
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_commit.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 4: Write the failing tests for section builders**

```python
# tests/test_chat_sections.py
from pathlib import Path

import pytest

from ai_marketplace_monitor.chat.playbooks import load_playbooks
from ai_marketplace_monitor.chat.sections import (
    ChatContext,
    FieldGuide,
    SectionBuilder,
    SectionRef,
)
from ai_marketplace_monitor.chat.ui import ScriptedChatUI


class DemoBuilder(SectionBuilder):
    section_type = "ai"
    playbook = "ai"
    fields = (
        FieldGuide("model", "The model the user asked for.", ask="Which model?", inherit=False),
        FieldGuide("timeout", "Keep the default unless the user asks."),
    )


def context(tmp_path: Path) -> ChatContext:
    return ChatContext(
        files=[],
        default_file=tmp_path / "config.toml",
        playbooks=load_playbooks(user_dir=tmp_path / "playbooks"),
        backup_dir=tmp_path / "backups",
    )


def test_section_ref_parse() -> None:
    assert SectionRef.parse("ai") == SectionRef("ai", None)
    assert SectionRef.parse("ai.unitysvc") == SectionRef("ai", "unitysvc")
    assert SectionRef("ai", "unitysvc").label() == "ai.unitysvc"


def test_guide_text() -> None:
    text = DemoBuilder().guide_text()
    assert text.startswith("# Field guide for [ai.*] sections")
    assert "- `model`: The model the user asked for. Ask: Which model?" in text
    assert "- `timeout`: Keep the default unless the user asks. (shared: copied" in text


def test_instructions_combine_playbook_and_guide(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    builder = DemoBuilder()
    text = builder.instructions(ctx)
    assert text.startswith(ctx.playbooks.sections["ai"].text())
    assert text.endswith(builder.guide_text())


def test_template_values_keep_only_inherited_fields() -> None:
    template = {"model": "fast", "timeout": 30, "request": "theirs", "unknown": 1}
    assert DemoBuilder().template_values(template) == {"timeout": 30}


async def test_generic_interpret_and_converse_not_available_yet(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    with pytest.raises(NotImplementedError):
        DemoBuilder().interpret({}, "use a fast model", ctx)
    with pytest.raises(NotImplementedError):
        await DemoBuilder().converse(ScriptedChatUI([]), SectionRef("ai"), ctx)
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_sections.py tests/test_chat_commit.py -v`
Expected: FAIL — `ModuleNotFoundError: ... chat.sections`.

- [ ] **Step 6: Implement `sections.py`**

```python
# src/ai_marketplace_monitor/chat/sections.py
"""Section builders: everything aimm knows about creating or revising one section type."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple

from ..ai import AIBackend
from .playbooks import PlaybookSet
from .ui import ChatUI


@dataclass
class SectionRef:
    type: str  # "ai", "item", "user", ...
    name: str | None = None  # None: create a new section

    @classmethod
    def parse(cls: type["SectionRef"], text: str) -> "SectionRef":
        section_type, _, name = text.partition(".")
        return cls(section_type, name or None)

    def label(self: "SectionRef") -> str:
        return f"{self.type}.{self.name}" if self.name else self.type


@dataclass(frozen=True)
class FieldGuide:
    name: str  # a key the section accepts
    derive: str  # how to work out the value
    ask: str | None = None  # what to ask the user when it cannot be derived; None: never ask
    inherit: bool = True  # a new section copies it from its template section


@dataclass
class InterpretResult:
    values: Dict[str, Any]  # proposed field values (raw, e.g. "${VAR}")
    notes: List[str] = field(default_factory=list)  # what to tell the user
    questions: List[str] = field(default_factory=list)  # still needed; empty = complete


@dataclass
class SectionProposal:
    ref: SectionRef  # name filled in
    values: Dict[str, Any]  # raw keys, e.g. {"api_key": "${UNITYSVC_API_KEY}"}
    request: str | None  # one-sentence summary of what the user asked for
    target_file: Path


@dataclass
class ChatContext:
    files: List[Path]  # config files in read order
    default_file: Path  # ~/.ai-marketplace-monitor/config.toml
    playbooks: PlaybookSet
    backup_dir: Path  # ~/.ai-marketplace-monitor/backups
    ai: AIBackend | None = None  # the chat's AI; None until it is chosen


class SectionBuilder:
    """Base class: one subclass per section type.

    Subclasses set ``section_type``, ``playbook`` (bundled playbook name), ``uses_ai``, and
    ``fields`` (how to derive each field and what to ask). The generic AI-backed
    ``interpret`` and ``converse`` arrive with the first AI-driven builder; scripted builders
    override ``converse``.
    """

    section_type: str = ""
    playbook: str = ""
    uses_ai: bool = True
    fields: Tuple[FieldGuide, ...] = ()

    def guide_text(self: "SectionBuilder") -> str:
        lines = [f"# Field guide for [{self.section_type}.*] sections", ""]
        for guide in self.fields:
            line = f"- `{guide.name}`: {guide.derive}"
            if guide.ask:
                line += f" Ask: {guide.ask}"
            if guide.inherit:
                line += " (shared: copied from an existing section when creating a new one)"
            lines.append(line)
        return "\n".join(lines)

    def instructions(self: "SectionBuilder", ctx: ChatContext) -> str:
        playbook = ctx.playbooks.sections.get(self.playbook)
        parts = [playbook.text()] if playbook else []
        return "\n\n".join([*parts, self.guide_text()])

    def template_values(self: "SectionBuilder", template: Dict[str, Any]) -> Dict[str, Any]:
        """Fields a new section copies from an existing section of the same type."""
        inherited = {g.name for g in self.fields if g.inherit}
        return {k: v for k, v in template.items() if k in inherited}

    def interpret(
        self: "SectionBuilder", current: Dict[str, Any], request: str, ctx: ChatContext
    ) -> InterpretResult:
        raise NotImplementedError(
            f"{type(self).__name__} has no interpret step; the AI-backed one comes later."
        )

    async def converse(
        self: "SectionBuilder", ui: ChatUI, ref: SectionRef, ctx: ChatContext
    ) -> SectionProposal | None:
        raise NotImplementedError(
            f"{type(self).__name__} has no conversation; the AI-backed one comes later."
        )

    async def after_commit(
        self: "SectionBuilder", ui: ChatUI, proposal: SectionProposal, ctx: ChatContext
    ) -> Any:
        return None
```

- [ ] **Step 7: Implement `commit.py`**

```python
# src/ai_marketplace_monitor/chat/commit.py
"""The single path that writes chat proposals into config files."""

import os
import shutil
from dataclasses import fields
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List

import tomlkit

from ..utils import BaseConfig
from .ai_sections import read_toml
from .messages import Confirm, Say
from .sections import ChatContext, SectionProposal
from .ui import ChatUI

# `request` is written only once the loader accepts it (added by #362)
REQUEST_SUPPORTED = "request" in {f.name for f in fields(BaseConfig)}


class CommitOutcome(Enum):
    WRITTEN = "written"
    DECLINED = "declined"  # the user said no; nothing written
    FAILED = "failed"  # written, but a later file overrides it


def render_section(proposal: SectionProposal) -> str:
    assert proposal.ref.name is not None
    return tomlkit.dumps({proposal.ref.type: {proposal.ref.name: proposal.values}})


def backup_file(path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{path.name}.{datetime.now():%Y%m%d-%H%M%S}"
    dest = backup_dir / stem
    counter = 1
    while dest.exists():
        counter += 1
        dest = backup_dir / f"{stem}-{counter}"
    shutil.copy2(path, dest)
    os.chmod(dest, 0o600)
    return dest


def write_section(
    path: Path, section_type: str, name: str, values: Dict[str, Any], request: str | None
) -> None:
    """Add or replace one section, leaving the rest of the file untouched."""
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    doc = tomlkit.parse(text) if text else tomlkit.document()
    if section_type not in doc:
        doc[section_type] = tomlkit.table(is_super_table=True)
    parent: Any = doc[section_type]
    old = parent.get(name)
    table = tomlkit.table()
    if REQUEST_SUPPORTED and request:
        table["request"] = request
    elif old is not None and "request" in old:
        table["request"] = old["request"]
    for key, value in values.items():
        table[key] = value
    parent[name] = table
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def effective_section(files: List[Path], section_type: str, name: str) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for path in files:
        merged.update(read_toml(path).get(section_type, {}).get(name, {}))
    return merged


async def commit(ui: ChatUI, proposal: SectionProposal, ctx: ChatContext) -> CommitOutcome:
    """Preview, confirm, back up, write, and verify one proposal."""
    ref, path = proposal.ref, proposal.target_file
    assert ref.name is not None
    await ui.say(Say(f"```toml\n{render_section(proposal)}```", markdown=True))
    if await ui.ask(Confirm(f"Write this to {path}?")) != "yes":
        return CommitOutcome.DECLINED
    if path.exists():
        backup_file(path, ctx.backup_dir)
    write_section(path, ref.type, ref.name, proposal.values, proposal.request)
    if path not in ctx.files:
        ctx.files.insert(0, path)  # only the default file can be new; it is read first

    effective = effective_section(ctx.files, ref.type, ref.name)
    effective.pop("request", None)
    if effective == proposal.values:
        await ui.say(Say(f"Saved [{ref.label()}] to {path}.", kind="success"))
        return CommitOutcome.WRITTEN
    later = ctx.files[ctx.files.index(path) + 1 :]
    overrides = []
    for other in later:
        keys = sorted(read_toml(other).get(ref.type, {}).get(ref.name, {}))
        if keys:
            overrides.append(f"{other} ({', '.join(keys)})")
    await ui.say(
        Say(
            f"Saved to {path}, but [{ref.label()}] is overridden by {'; '.join(overrides)}. "
            "Remove those keys there for this change to take effect.",
            kind="error",
        )
    )
    return CommitOutcome.FAILED
```

- [ ] **Step 8: Run tests**

Run: `uv run pytest tests/test_chat_sections.py tests/test_chat_commit.py -v`
Expected: all PASS. If `test_render_section` fails only on spacing, adjust the expected string in the test to `tomlkit`'s actual output **only if** the output is still the section header followed by the two keys.

- [ ] **Step 9: Lint, types, commit (including `uv.lock`)**

Run: `uvx 'ruff>=0.9.2,<0.17' check src tests && uv run --with mypy mypy src && uv run pytest -q --ignore=tests/test_facebook.py`

```bash
git add pyproject.toml uv.lock src/ai_marketplace_monitor/chat/sections.py src/ai_marketplace_monitor/chat/commit.py tests/test_chat_sections.py tests/test_chat_commit.py
git commit -m "feat(chat): section builders and the shared commit path

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Scripted AI builder

**Files:**
- Create: `src/ai_marketplace_monitor/chat/builders/__init__.py`, `src/ai_marketplace_monitor/chat/builders/ai.py`
- Test: `tests/test_chat_ai_builder.py`

**Interfaces:**
- Consumes: Tasks 1, 4, 5, 7 (`SectionBuilder`, `FieldGuide`, `SectionProposal`, `SectionRef`, `ChatContext`); backends' `default_model`.
- Produces: `ProviderSpec(key, label, hint, env_var, key_url)`; `PROVIDERS: List[ProviderSpec]` (unitysvc, openai, anthropic, ollama); `PROVIDER_LABELS: Dict[str, str]` (all six providers → display name); `UNITYSVC_TIERS = ["fast", "balanced", "coding", "premium"]`; `KEY_PATTERN`; `AI_FIELDS: Tuple[FieldGuide, ...]`; `AISetupOutcome(config: AIConfig | None, retry: bool = False)`; `ScriptedAIBuilder(SectionBuilder)` (`section_type = "ai"`, `playbook = "ai"`, `uses_ai = False`, `fields = AI_FIELDS`, `converse`, `after_commit -> AISetupOutcome`); `BUILDERS: Dict[str, SectionBuilder] = {"ai": ScriptedAIBuilder()}` in `builders/__init__.py`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_chat_ai_builder.py
from dataclasses import fields
from pathlib import Path

import pytest

from ai_marketplace_monitor.ai import AIConfig
from ai_marketplace_monitor.chat.builders import BUILDERS
from ai_marketplace_monitor.chat.builders import ai as ai_module
from ai_marketplace_monitor.chat.builders.ai import ScriptedAIBuilder
from ai_marketplace_monitor.chat.playbooks import load_playbooks
from ai_marketplace_monitor.chat.probe import ProbeResult
from ai_marketplace_monitor.chat.sections import ChatContext, SectionProposal, SectionRef
from ai_marketplace_monitor.chat.ui import ScriptedChatUI


def context(tmp_path: Path, text: str | None = None) -> ChatContext:
    files = []
    if text is not None:
        path = tmp_path / "config.toml"
        path.write_text(text)
        files.append(path)
    return ChatContext(
        files=files,
        default_file=tmp_path / "home" / "config.toml",
        playbooks=load_playbooks(user_dir=tmp_path / "playbooks"),
        backup_dir=tmp_path / "backups",
    )


async def converse(
    answers: list[str], ctx: ChatContext, ref: SectionRef | None = None
) -> SectionProposal | None:
    return await ScriptedAIBuilder().converse(ScriptedChatUI(answers), ref or SectionRef("ai"), ctx)


def test_registry_and_builder_attributes() -> None:
    builder = BUILDERS["ai"]
    assert isinstance(builder, ScriptedAIBuilder)
    assert (builder.section_type, builder.playbook, builder.uses_ai) == ("ai", "ai", False)


def test_field_guides_cover_every_ai_field() -> None:
    guided = {g.name for g in ScriptedAIBuilder.fields}
    assert {f.name for f in fields(AIConfig)} - {"name"} <= guided
    inherited = {g.name for g in ScriptedAIBuilder.fields if g.inherit}
    assert inherited == {"max_retries", "timeout"}


async def test_unitysvc_new_section(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    proposal = await converse(["unitysvc", "balanced"], ctx)
    assert proposal is not None
    assert proposal.ref == SectionRef("ai", "unitysvc")
    assert proposal.values == {"api_key": "${UNITYSVC_API_KEY}", "model": "balanced"}
    assert proposal.target_file == ctx.default_file
    assert proposal.request == "Use UnitySVC (balanced) to rate listings and to chat."


async def test_new_section_inherits_shared_fields(tmp_path: Path) -> None:
    ctx = context(
        tmp_path,
        '[ai.openai]\napi_key = "${OPENAI_API_KEY}"\nmax_retries = 3\ntimeout = 30\n',
    )
    proposal = await converse(["unitysvc", "fast"], ctx)
    assert proposal is not None
    assert proposal.ref.name == "unitysvc"
    assert proposal.values == {
        "api_key": "${UNITYSVC_API_KEY}",
        "model": "fast",
        "max_retries": 3,
        "timeout": 30,
    }


async def test_openai_model_default(tmp_path: Path) -> None:
    proposal = await converse(["openai", ""], context(tmp_path))
    assert proposal is not None
    assert proposal.values == {"api_key": "${OPENAI_API_KEY}", "model": "gpt-4o"}


async def test_ollama_needs_no_key(tmp_path: Path) -> None:
    proposal = await converse(["ollama", "", "llama3"], context(tmp_path))
    assert proposal is not None
    assert proposal.values == {"base_url": "http://localhost:11434/v1", "model": "llama3"}


async def test_existing_section_updated_keeping_var(tmp_path: Path) -> None:
    ctx = context(
        tmp_path,
        '[ai.mine]\nprovider = "unitysvc"\napi_key = "${MY_KEY}"\nmodel = "fast"\ntimeout = 5\n',
    )
    proposal = await converse(["unitysvc", "premium"], ctx)
    assert proposal is not None
    assert proposal.ref.name == "mine"
    assert proposal.values == {
        "provider": "unitysvc",
        "api_key": "${MY_KEY}",
        "model": "premium",
        "timeout": 5,
    }
    assert proposal.target_file == ctx.files[0]


async def test_name_taken_by_other_provider_gets_suffix(tmp_path: Path) -> None:
    ctx = context(tmp_path, '[ai.unitysvc]\nprovider = "openai"\napi_key = "${OPENAI_API_KEY}"\n')
    proposal = await converse(["unitysvc", "balanced"], ctx)
    assert proposal is not None
    assert proposal.ref.name == "unitysvc_2"
    assert proposal.values["provider"] == "unitysvc"


async def test_named_ref_preselects_provider(tmp_path: Path) -> None:
    ctx = context(
        tmp_path, '[ai.local]\nprovider = "ollama"\nbase_url = "http://x:1/v1"\nmodel = "m"\n'
    )
    proposal = await converse(["", "", ""], ctx, SectionRef("ai", "local"))
    assert proposal is not None
    assert proposal.values == {"provider": "ollama", "base_url": "http://x:1/v1", "model": "m"}


async def test_key_like_input_refused(tmp_path: Path) -> None:
    ui = ScriptedChatUI(["openai", "sk-abcdefghijklmnop", "gpt-5"])
    proposal = await ScriptedAIBuilder().converse(ui, SectionRef("ai"), context(tmp_path))
    assert proposal is not None and proposal.values["model"] == "gpt-5"
    [warning] = ui.said("warning")
    assert "sk-abcdefghijklmnop" not in warning and "environment variable" in warning


async def test_quit(tmp_path: Path) -> None:
    assert await converse(["quit"], context(tmp_path)) is None


def written(tmp_path: Path, text: str, values: dict) -> tuple[ChatContext, SectionProposal]:
    ctx = context(tmp_path, text)
    return ctx, SectionProposal(SectionRef("ai", "unitysvc"), values, None, ctx.files[0])


async def test_after_commit_env_set_probe_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_test")
    monkeypatch.setattr(
        ai_module, "probe", lambda s: ProbeResult(True, "request", "balanced", "ok")
    )
    values = {"api_key": "${UNITYSVC_API_KEY}"}
    ctx, proposal = written(tmp_path, '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\n', values)
    outcome = await ScriptedAIBuilder().after_commit(ScriptedChatUI([]), proposal, ctx)
    assert outcome.config is not None and outcome.config.name == "unitysvc"


async def test_after_commit_env_unset_gives_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNITYSVC_API_KEY", raising=False)
    values = {"api_key": "${UNITYSVC_API_KEY}"}
    ctx, proposal = written(tmp_path, '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\n', values)
    ui = ScriptedChatUI([])
    outcome = await ScriptedAIBuilder().after_commit(ui, proposal, ctx)
    assert outcome.config is None and not outcome.retry
    text = "\n".join(ui.said())
    assert "https://unitysvc.com" in text
    assert "export UNITYSVC_API_KEY=<your key>" in text
    assert "aimm --chat" in text


async def test_after_commit_probe_failure_offers_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ai_module, "probe", lambda s: ProbeResult(False, "models", "m", "Can't reach http://x:1/v1")
    )
    values = {"provider": "ollama", "base_url": "http://x:1/v1", "model": "m"}
    ctx, proposal = written(
        tmp_path,
        '[ai.unitysvc]\nprovider = "ollama"\nbase_url = "http://x:1/v1"\nmodel = "m"\n',
        values,
    )
    ui = ScriptedChatUI([])
    outcome = await ScriptedAIBuilder().after_commit(ui, proposal, ctx)
    assert outcome.config is None and outcome.retry
    assert ui.said("error") == ["Can't reach http://x:1/v1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_ai_builder.py -v`
Expected: FAIL — `ModuleNotFoundError: ... chat.builders`.

- [ ] **Step 3: Implement**

```python
# src/ai_marketplace_monitor/chat/builders/__init__.py
"""Section builders, by section type."""

from typing import Dict

from ..sections import SectionBuilder
from .ai import ScriptedAIBuilder

BUILDERS: Dict[str, SectionBuilder] = {"ai": ScriptedAIBuilder()}
```

```python
# src/ai_marketplace_monitor/chat/builders/ai.py
"""Scripted builder for [ai.*] sections: no AI exists yet to drive a conversation."""

import asyncio
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from ...ai import AIConfig, AnthropicBackend, OllamaBackend, OpenAIBackend
from ..ai_sections import AISection, env_var_name, load_ai_sections
from ..messages import AskText, Choose, Option, Say
from ..probe import probe
from ..sections import ChatContext, FieldGuide, SectionBuilder, SectionProposal, SectionRef
from ..ui import ChatUI

KEY_PATTERN = re.compile(r"^(svcpass_|sk-ant-|sk-)\S{8,}")
UNITYSVC_TIERS = ["fast", "balanced", "coding", "premium"]
OLLAMA_URL = "http://localhost:11434/v1"


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    label: str
    hint: str
    env_var: str | None
    key_url: str | None


PROVIDERS: List[ProviderSpec] = [
    ProviderSpec(
        "unitysvc",
        "UnitySVC",
        "recommended — one key for the AI and for email notifications",
        "UNITYSVC_API_KEY",
        "https://unitysvc.com",
    ),
    ProviderSpec("openai", "OpenAI", "", "OPENAI_API_KEY", "https://platform.openai.com/api-keys"),
    ProviderSpec(
        "anthropic",
        "Anthropic",
        "",
        "ANTHROPIC_API_KEY",
        "https://console.anthropic.com/settings/keys",
    ),
    ProviderSpec("ollama", "Ollama", "runs on your own machine, no key", None, None),
]
_BY_KEY = {p.key: p for p in PROVIDERS}
PROVIDER_LABELS: Dict[str, str] = {
    **{p.key: p.label for p in PROVIDERS},
    "deepseek": "DeepSeek",
    "gemini": "Gemini",
}

AI_FIELDS: Tuple[FieldGuide, ...] = (
    FieldGuide(
        "provider",
        "The service the user chose; omit it when it equals the section name.",
        ask="Which AI do you want to use?",
        inherit=False,
    ),
    FieldGuide(
        "api_key",
        "Always a ${VARIABLE} reference: keep an existing variable name, otherwise use the "
        "provider's standard one (UNITYSVC_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY). "
        "Not used by Ollama. Never a literal key.",
        inherit=False,
    ),
    FieldGuide(
        "base_url",
        "Omit it to use the provider's default. Ollama needs it, usually "
        "http://localhost:11434/v1.",
        ask="Where is Ollama running?",
        inherit=False,
    ),
    FieldGuide(
        "model",
        "For UnitySVC a tier: fast, balanced (default), coding, or premium. Otherwise a "
        "model name the provider offers; default to the provider's default model.",
        ask="Which tier or model?",
        inherit=False,
    ),
    FieldGuide("max_retries", "Keep the default (10) unless the user asks for another number."),
    FieldGuide("timeout", "Seconds to wait for an answer; omit unless the user asks."),
    FieldGuide(
        "enabled",
        "Omit (enabled). Set false only when the user wants to keep the section but not use it.",
        inherit=False,
    ),
    FieldGuide(
        "request",
        "One sentence: the provider and model, and that it rates listings and powers the chat.",
        inherit=False,
    ),
)


@dataclass
class AISetupOutcome:
    config: AIConfig | None  # set when the section works now
    retry: bool = False  # it failed its probe; offer setup again


async def _ask_text(ui: ChatUI, prompt: str, default: str) -> str:
    while True:
        answer = (await ui.ask(AskText(prompt, default=default))).strip()
        if KEY_PATTERN.match(answer):
            await ui.say(
                Say(
                    "That looks like an API key. Keys never go into aimm — you will set it "
                    "as an environment variable instead, and I will show you how.",
                    kind="warning",
                )
            )
            continue
        return answer or default


def _new_name(provider: str, sections: List[AISection]) -> str:
    names = {s.name for s in sections}
    name, suffix = provider, 1
    while name in names:
        suffix += 1
        name = f"{provider}_{suffix}"
    return name


class ScriptedAIBuilder(SectionBuilder):
    section_type = "ai"
    playbook = "ai"
    uses_ai = False
    fields = AI_FIELDS

    async def converse(
        self: "ScriptedAIBuilder", ui: ChatUI, ref: SectionRef, ctx: ChatContext
    ) -> SectionProposal | None:
        sections = load_ai_sections(ctx.files)
        named = next((s for s in sections if s.name == ref.name), None) if ref.name else None
        default = named.provider if named and named.provider in _BY_KEY else "unitysvc"
        options = [Option(p.key, p.label, p.hint) for p in PROVIDERS] + [Option("quit", "Quit")]
        choice = await ui.ask(Choose("Which AI do you want to use?", options, default))
        if choice == "quit":
            return None
        spec = _BY_KEY[choice]
        if named is not None and named.provider == choice:
            target = named
        else:
            target = next((s for s in sections if s.provider == choice), None)
        old: Dict[str, Any] = target.raw if target else {}

        values: Dict[str, Any] = {"provider": choice}
        if spec.env_var:
            var = env_var_name(old.get("api_key")) or spec.env_var
            values["api_key"] = "${" + var + "}"
        if choice == "unitysvc":
            current = old.get("model")
            tier_default = current if current in UNITYSVC_TIERS else "balanced"
            tiers = [Option(t, t) for t in UNITYSVC_TIERS]
            values["model"] = await ui.ask(Choose("Which UnitySVC tier?", tiers, tier_default))
        elif choice == "ollama":
            values["base_url"] = await _ask_text(ui, "Ollama URL", old.get("base_url") or OLLAMA_URL)
            model_default = old.get("model") or OllamaBackend.default_model
            values["model"] = await _ask_text(ui, "Model", model_default)
        else:
            backend = OpenAIBackend if choice == "openai" else AnthropicBackend
            values["model"] = await _ask_text(ui, "Model", old.get("model") or backend.default_model)

        if target is not None:
            # an updated section keeps its own shared settings
            values.update(self.template_values(target.raw))
        else:
            # a new section starts from the named section, else the first existing one
            template = named or (sections[0] if sections else None)
            if template is not None:
                values.update(self.template_values(template.raw))

        name = target.name if target else _new_name(choice, sections)
        if name == choice:
            values.pop("provider")
        return SectionProposal(
            ref=SectionRef("ai", name),
            values=values,
            request=f"Use {spec.label} ({values['model']}) to rate listings and to chat.",
            target_file=target.files[-1] if target else ctx.default_file,
        )

    async def after_commit(
        self: "ScriptedAIBuilder", ui: ChatUI, proposal: SectionProposal, ctx: ChatContext
    ) -> AISetupOutcome:
        var = env_var_name(proposal.values.get("api_key"))
        if var is None or var in os.environ:
            section = next(s for s in load_ai_sections(ctx.files) if s.name == proposal.ref.name)
            result = await asyncio.to_thread(probe, section)
            if result.ok:
                await ui.say(Say(f"{section.name} works ({result.model}).", kind="success"))
                return AISetupOutcome(section.config)
            await ui.say(Say(result.message, kind="error"))
            return AISetupOutcome(None, retry=True)
        provider = str(proposal.values.get("provider", proposal.ref.name))
        spec = _BY_KEY.get(provider)
        if spec and spec.key_url:
            await ui.say(Say(f"Get a {spec.label} API key at {spec.key_url}."))
        await ui.say(
            Say(
                f"Set it in your shell (and add the line to your shell profile to keep it):\n\n"
                f"```bash\nexport {var}=<your key>\n```",
                markdown=True,
            )
        )
        await ui.say(Say("Then run `aimm --chat` again.", markdown=True))
        return AISetupOutcome(None)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_chat_ai_builder.py -v`
Expected: all PASS.

- [ ] **Step 5: Lint, types, commit**

Run: `uvx 'ruff>=0.9.2,<0.17' check src tests && uv run --with mypy mypy src` (wrap any line over 99 columns).

```bash
git checkout -- uv.lock
git add src/ai_marketplace_monitor/chat/builders/__init__.py src/ai_marketplace_monitor/chat/builders/ai.py tests/test_chat_ai_builder.py
git commit -m "feat(chat): scripted AI builder with field guides and templates

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Session — choosing the AI and the plain chat

**Files:**
- Create: `src/ai_marketplace_monitor/chat/session.py`
- Test: `tests/test_chat_session.py`

**Interfaces:**
- Consumes: everything above (`BUILDERS`, `SectionBuilder.converse` / `after_commit` / `guide_text`, `ChatContext.ai`); `redact` from `webui/secrets_redact.py`; `supported_ai_backends`. The session sets `ctx.ai` to the chosen backend before the chat starts.
- Produces: `render_config(files: List[Path]) -> str`; `async run_chat(ui, config_files: List[Path], target: str | None = None, *, home: Path | None = None) -> int` (`home` defaults to `amm_home`; the default file is `home / "config.toml"`, user playbooks `home / "playbooks"`, backups `home / "backups"`). `config_files` is the already-resolved read order.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_chat_session.py
from pathlib import Path
from typing import Dict, List

import pytest

from ai_marketplace_monitor.ai import OpenAIBackend
from ai_marketplace_monitor.chat import session as session_module
from ai_marketplace_monitor.chat.builders import ai as ai_module
from ai_marketplace_monitor.chat.probe import ProbeResult
from ai_marketplace_monitor.chat.session import render_config, run_chat
from ai_marketplace_monitor.chat.ui import CLOSE, ScriptedChatUI

WORKING = '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\n[user.u]\npushbullet_token = "secret-token-value"\n'


@pytest.fixture
def chats(monkeypatch: pytest.MonkeyPatch) -> List[List[Dict[str, str]]]:
    calls: List[List[Dict[str, str]]] = []

    def fake_chat(self: OpenAIBackend, messages: List[Dict[str, str]]) -> str:
        calls.append([dict(m) for m in messages])
        if messages[-1]["content"] == "fail":
            raise RuntimeError("upstream down")
        return f"**reply** to {messages[-1]['content']}"

    monkeypatch.setattr(OpenAIBackend, "chat", fake_chat)
    return calls


def ok(monkeypatch: pytest.MonkeyPatch, ok: bool = True) -> None:
    result = ProbeResult(ok, "request", "balanced", "ok" if ok else "Key rejected by unitysvc")
    monkeypatch.setattr(session_module, "probe", lambda s: result)
    monkeypatch.setattr(ai_module, "probe", lambda s: result)


def config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


async def test_working_ai_then_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chats: List[List[Dict[str, str]]]
) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_test")
    ok(monkeypatch)
    ui = ScriptedChatUI(["unitysvc", "hello", "/exit"])
    assert await run_chat(ui, [config(tmp_path, WORKING)], home=tmp_path / "home") == 0
    assert "**reply** to hello" in ui.said("assistant")
    system = chats[0][0]["content"]
    assert "AI Marketplace Monitor assistant" in system
    assert "- `ai`:" in system
    assert "# Field guide for [ai.*] sections" in system
    assert "secret-token-value" not in system and "<REDACTED>" in system


async def test_nothing_works_sets_up_unitysvc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNITYSVC_API_KEY", raising=False)
    ok(monkeypatch, ok=False)
    home = tmp_path / "home"
    ui = ScriptedChatUI(["unitysvc", "balanced", "yes"])
    assert await run_chat(ui, [], home=home) == 0
    assert '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"' in (home / "config.toml").read_text()
    assert any("export UNITYSVC_API_KEY=<your key>" in t for t in ui.said())


async def test_declined_commit_goes_back_to_choice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok(monkeypatch, ok=False)
    home = tmp_path / "home"
    ui = ScriptedChatUI(["unitysvc", "balanced", "no", "quit"])
    assert await run_chat(ui, [], home=home) == 0
    assert not (home / "config.toml").exists()


async def test_provider_error_then_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chats: List[List[Dict[str, str]]]
) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_test")
    ok(monkeypatch)
    ui = ScriptedChatUI(["unitysvc", "fail", "again", CLOSE])
    assert await run_chat(ui, [config(tmp_path, WORKING)], home=tmp_path / "home") == 0
    assert any("upstream down" in t for t in ui.said("error"))
    assert [m["content"] for m in chats[-1] if m["role"] == "user"] == ["again"]


async def test_edit_ai_from_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chats: List[List[Dict[str, str]]]
) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_test")
    ok(monkeypatch)
    path = config(tmp_path, WORKING)
    ui = ScriptedChatUI(["unitysvc", "/edit ai", "unitysvc", "premium", "yes", "hi", "/exit"])
    assert await run_chat(ui, [path], home=tmp_path / "home") == 0
    assert 'model = "premium"' in path.read_text()
    assert "**reply** to hi" in ui.said("assistant")


async def test_other_section_types_not_available(tmp_path: Path) -> None:
    ui = ScriptedChatUI([])
    assert await run_chat(ui, [], "item.bike", home=tmp_path / "home") == 1
    assert ui.said("error") == ["Chatting about item sections isn't available yet."]


async def test_unparsable_config(tmp_path: Path) -> None:
    ui = ScriptedChatUI([])
    assert await run_chat(ui, [config(tmp_path, "[ai\n")], home=tmp_path / "home") == 1
    assert "Cannot read" in ui.said("error")[0]


def test_render_config(tmp_path: Path) -> None:
    path = config(tmp_path, 'telegram_token = "123:abc"\n')
    text = render_config([path])
    assert str(path) in text and "123:abc" not in text
    assert render_config([]) == "# The user's current configuration\n\n(no configuration files yet)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_chat_session.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/ai_marketplace_monitor/chat/session.py
"""A chat session: determine the AI (setting it up if needed), then chat with it."""

import asyncio
from pathlib import Path
from typing import Dict, List, Tuple

from ..ai import AIConfig
from ..config import supported_ai_backends
from ..utils import amm_home
from ..webui.secrets_redact import redact
from .ai_sections import AISection, ConfigReadError, load_ai_sections
from .builders import BUILDERS
from .builders.ai import PROVIDER_LABELS
from .commit import CommitOutcome, commit
from .messages import AskText, Choose, Option, Say
from .playbooks import build_instructions, load_playbooks
from .probe import ProbeResult, probe, scrub
from .sections import ChatContext, SectionRef
from .ui import ChatClosed, ChatUI

HELP = (
    "Commands: `/edit ai` set up or change the AI · `/help` this list · "
    "`/exit` leave (or press Ctrl-D)"
)


def render_config(files: List[Path]) -> str:
    """The user's config files with secrets masked, for the chat instructions."""
    blocks = []
    for path in files:
        redacted, _ = redact(path.read_text(encoding="utf-8"))
        blocks.append(f"`{path}`:\n\n```toml\n{redacted.rstrip()}\n```")
    body = "\n\n".join(blocks) if blocks else "(no configuration files yet)"
    return f"# The user's current configuration\n\n{body}"


def _label(section: AISection, result: ProbeResult) -> str:
    provider = PROVIDER_LABELS.get(section.provider, section.provider)
    return f"{section.name} — {provider}, {result.model}"


async def _check_sections(ui: ChatUI, ctx: ChatContext) -> List[Tuple[AISection, ProbeResult]]:
    sections = load_ai_sections(ctx.files)
    enabled = [s for s in sections if s.enabled]
    if enabled:
        await ui.say(Say(f"Checking {len(enabled)} AI service(s)…"))
    results = await asyncio.gather(*(asyncio.to_thread(probe, s) for s in enabled))
    by_name = dict(zip([s.name for s in enabled], results))
    usable = []
    for section in sections:
        result = by_name.get(section.name)
        if result is None:
            await ui.say(Say(f"– {section.name} — disabled"))
        elif result.ok:
            await ui.say(Say(f"✓ {_label(section, result)}", kind="success"))
            usable.append((section, result))
        else:
            await ui.say(Say(f"✗ {section.name} — {result.message}", kind="warning"))
    return usable


async def _edit_ai(ui: ChatUI, ctx: ChatContext, ref: SectionRef) -> AIConfig | None:
    builder = BUILDERS["ai"]
    while True:
        proposal = await builder.converse(ui, ref, ctx)
        if proposal is None:
            return None
        outcome = await commit(ui, proposal, ctx)
        if outcome is CommitOutcome.DECLINED:
            continue
        if outcome is CommitOutcome.FAILED:
            return None
        result = await builder.after_commit(ui, proposal, ctx)
        if result.config is not None:
            return result.config  # type: ignore[no-any-return]
        if not result.retry:
            return None
        ref = proposal.ref


async def _choose_ai(ui: ChatUI, ctx: ChatContext, ref: SectionRef | None) -> AIConfig | None:
    if ref is None:
        usable = await _check_sections(ui, ctx)
        if usable:
            options = [Option(s.name, _label(s, r)) for s, r in usable]
            options += [Option("new", "Set up a different AI…"), Option("quit", "Quit")]
            choice = await ui.ask(
                Choose("Which AI should this chat use?", options, usable[0][0].name)
            )
            if choice == "quit":
                return None
            if choice != "new":
                return next(s.config for s, _ in usable if s.name == choice)
        ref = SectionRef("ai")
    return await _edit_ai(ui, ctx, ref)


def _model(config: AIConfig) -> str:
    backend = supported_ai_backends[(config.provider or config.name).lower()]
    return config.model or backend.default_model


async def _chat(ui: ChatUI, ctx: ChatContext, config: AIConfig) -> None:
    backend = supported_ai_backends[(config.provider or config.name).lower()](config=config)
    ctx.ai = backend
    instructions = build_instructions(
        ctx.playbooks,
        ["ai"],
        render_config(ctx.files),
        {"ai": BUILDERS["ai"].guide_text()},
    )
    messages: List[Dict[str, str]] = [{"role": "system", "content": instructions}]
    await ui.say(Say(f"Chatting with {config.name} ({_model(config)}). {HELP}", markdown=True))
    while True:
        text = (await ui.ask(AskText("You"))).strip()
        if not text:
            continue
        if text in ("/exit", "/quit"):
            return
        if text == "/help":
            await ui.say(Say(HELP, markdown=True))
            continue
        if text.split()[0] == "/edit":
            arg = text.split(maxsplit=1)[1] if " " in text else "ai"
            ref = SectionRef.parse(arg)
            if ref.type != "ai":
                await ui.say(Say(f"Chatting about {ref.type} sections isn't available yet.", kind="error"))
                continue
            new = await _edit_ai(ui, ctx, SectionRef("ai", ref.name or config.name))
            if new is not None:
                return await _chat(ui, ctx, new)
            continue
        if text.startswith("/"):
            await ui.say(Say(f"Unknown command {text.split()[0]}. {HELP}", kind="warning", markdown=True))
            continue
        messages.append({"role": "user", "content": text})
        try:
            reply = await asyncio.to_thread(backend.chat, messages)
        except Exception as e:
            messages.pop()
            await ui.say(Say(f"The AI request failed: {scrub(str(e), config.api_key)[:300]}", kind="error"))
            continue
        messages.append({"role": "assistant", "content": reply})
        await ui.say(Say(reply, kind="assistant", markdown=True))


async def run_chat(
    ui: ChatUI, config_files: List[Path], target: str | None = None, *, home: Path | None = None
) -> int:
    """Run a chat session; return the process exit code."""
    home = home or amm_home
    ctx = ChatContext(
        files=list(config_files),
        default_file=home / "config.toml",
        playbooks=load_playbooks(user_dir=home / "playbooks"),
        backup_dir=home / "backups",
    )
    try:
        ref = SectionRef.parse(target) if target else None
        if ref is not None and ref.type != "ai":
            await ui.say(Say(f"Chatting about {ref.type} sections isn't available yet.", kind="error"))
            return 1
        config = await _choose_ai(ui, ctx, ref)
        if config is not None:
            await _chat(ui, ctx, config)
        return 0
    except ChatClosed:
        return 0
    except ConfigReadError as e:
        await ui.say(Say(str(e), kind="error"))
        return 1
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_chat_session.py -v`
Expected: all PASS. If mypy (next step) flags the `type: ignore` in `_edit_ai` as unused, remove it.

- [ ] **Step 5: Lint, types, commit**

Run: `uvx 'ruff>=0.9.2,<0.17' check src tests && uv run --with mypy mypy src && uv run pytest -q --ignore=tests/test_facebook.py`. Wrap any line ruff or the 99-column limit flags.

```bash
git checkout -- uv.lock
git add src/ai_marketplace_monitor/chat/session.py tests/test_chat_session.py
git commit -m "feat(chat): session — choose or set up the AI, then plain chat

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: CLI, live test, docs

**Files:**
- Modify: `src/ai_marketplace_monitor/cli.py` (`--chat`, `--section`, `_run_chat`)
- Modify: `pyproject.toml` (`[tool.pytest.ini_options]` gains `markers`)
- Create: `tests/test_chat_live.py`
- Modify: `tests/test_cli.py` (append tests)
- Modify: `docs/usage.rst`, `docs/README.md`, `CHANGELOG.md`, `docs/superpowers/specs/2026-10-04-chat-bootstrap-design.md`

**Interfaces:**
- Consumes: `CLIChatUI` (Task 2), `run_chat` (Task 9), `resolve_config_files` (Task 3).

- [ ] **Step 1: Write the failing CLI tests** (append to `tests/test_cli.py`)

```python
from pathlib import Path as _Path
from typing import Any as _Any, List as _List

from ai_marketplace_monitor.chat import cli_ui as chat_cli_ui
from ai_marketplace_monitor.chat import session as chat_session
from ai_marketplace_monitor.chat.ui import ScriptedChatUI as _ScriptedChatUI


def test_chat_runs_session_without_monitor(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: _List[_Any] = []

    async def fake_run_chat(ui: _Any, files: _List[_Path], target: str | None = None) -> int:
        calls.append((files, target))
        return 0

    def no_monitor(*args: _Any, **kwargs: _Any) -> None:
        raise AssertionError("the monitor must not start for --chat")

    monkeypatch.setattr(chat_session, "run_chat", fake_run_chat)
    monkeypatch.setattr(chat_cli_ui, "CLIChatUI", lambda: _ScriptedChatUI([]))
    monkeypatch.setattr("ai_marketplace_monitor.monitor.MarketplaceMonitor", no_monitor)
    result = runner.invoke(cli.app, ["--chat", "--section", "ai.unitysvc"])
    assert result.exit_code == 0
    assert calls and calls[0][1] == "ai.unitysvc"


def test_chat_other_section_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chat_cli_ui, "CLIChatUI", lambda: _ScriptedChatUI([]))
    result = runner.invoke(cli.app, ["--chat", "--section", "item"])
    assert result.exit_code == 1


def test_chat_needs_terminal() -> None:
    result = runner.invoke(cli.app, ["--chat"])
    assert result.exit_code == 1
    assert "interactive terminal" in result.output


def test_section_requires_chat() -> None:
    result = runner.invoke(cli.app, ["--section", "ai"])
    assert result.exit_code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -k "chat or section" -v`
Expected: FAIL — `No such option: --chat`.

- [ ] **Step 3: Implement the CLI**

Add two parameters to `main` in `cli.py` (after `verbose`):

```python
    chat: Annotated[
        bool,
        typer.Option(
            "--chat",
            help="Start an interactive chat that sets up the AI and answers questions about your configuration.",
        ),
    ] = False,
    section: Annotated[
        Optional[str],
        typer.Option(
            "--section",
            help="With --chat: the config section to work on, e.g. 'ai' or 'ai.unitysvc'.",
        ),
    ] = None,
```

Add this helper above `main`:

```python
def _run_chat(config_files: Optional[List[Path]], section: Optional[str]) -> int:
    """Run `aimm --chat`; return the exit code."""
    import asyncio

    from .chat import cli_ui, session
    from .config import resolve_config_files

    try:
        ui = cli_ui.CLIChatUI()
        files = resolve_config_files(config_files)
    except (RuntimeError, FileNotFoundError) as e:
        rich.print(f"[red]{e}[/red]")
        return 1
    return asyncio.run(session.run_chat(ui, files, section))
```

(The module-attribute lookups `cli_ui.CLIChatUI` and `session.run_chat` are what the tests patch.)

In `main`, immediately after the `if clear_cache is not None:` block and before `from .monitor import MarketplaceMonitor`:

```python
    if section is not None and not chat:
        logger.error(f"""{hilight("[Chat]", "fail")} --section can only be used with --chat.""")
        sys.exit(1)
    if chat:
        sys.exit(_run_chat(config_files, section))
```

Use the name of the existing `--config` parameter of `main` (it is `config_files`).

- [ ] **Step 4: Register the live marker and add the live test**

In `pyproject.toml` `[tool.pytest.ini_options]`, add:

```toml
markers = ["live: calls real external services; skipped unless credentials are set"]
```

```python
# tests/test_chat_live.py
import os
from pathlib import Path

import pytest

from ai_marketplace_monitor.chat.ai_sections import load_ai_sections
from ai_marketplace_monitor.chat.probe import probe

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("UNITYSVC_API_KEY"), reason="needs UNITYSVC_API_KEY"),
]


def test_unitysvc_balanced_probe(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\n')
    [section] = load_ai_sections([path])
    result = probe(section)
    assert result.ok, result.message
    assert "balanced" in result.available
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_cli.py tests/test_chat_live.py -v && uv run pytest -q --ignore=tests/test_facebook.py`
Expected: CLI tests PASS; the live test is SKIPPED (no key in the test environment); full suite passes.

- [ ] **Step 6: Docs**

`docs/usage.rst` — add a section:

```rst
Interactive setup and chat
--------------------------

Run ``aimm --chat`` to check which AI services in your configuration work, choose one,
or set one up, and then ask questions about your configuration in plain language.

When no AI works yet, the chat offers UnitySVC (recommended: one key covers the AI and
email notifications), OpenAI, Anthropic, or Ollama. It writes the ``[ai.*]`` section for
you, with the key referenced as an environment variable such as ``${UNITYSVC_API_KEY}``;
the key itself is never written to the file. Set the variable, then run ``aimm --chat``
again. Every write shows the change first, asks for confirmation, and keeps a backup in
``~/.ai-marketplace-monitor/backups/``.

Use ``aimm --chat --section ai`` (or ``--section ai.<name>``) to go straight to setting up
or changing an AI section. Inside the chat, type ``/edit ai`` to do the same, ``/help``
for commands, and ``/exit`` to leave.

House rules: put your own instructions in ``~/.ai-marketplace-monitor/playbooks/AGENT.md``
(for example "answer in French" or "I only buy within 30 miles"). They are added to the
built-in instructions of every chat. Section-specific files such as ``ai.md`` extend the
instructions for that section in the same way.
```

`docs/README.md` — in the AI Services section, after the provider notes, add:

```markdown
The easiest way to set up an AI service is `aimm --chat`: it checks your `[ai.*]` sections, helps you add one if none works, and writes the section with the key referenced as an environment variable.
```

`CHANGELOG.md` — under `## [Unreleased]` → `### Added` (create the heading if absent):

```markdown
- `aimm --chat`: interactive setup that checks which AI services work, sets one up (UnitySVC recommended), and chats about your configuration; user house rules in `~/.ai-marketplace-monitor/playbooks/`
```

Spec — in `docs/superpowers/specs/2026-10-04-chat-bootstrap-design.md`, record the two planning refinements not yet in it: `CLIChatUI` reads input synchronously (replace the `asyncio.to_thread(input)` sentence), and `AnthropicBackend.chat` passes `max_tokens=4096` (the Anthropic API requires it; add it to the `AIBackend.chat` paragraph).

- [ ] **Step 7: Lint, types, commit**

Run: `uvx 'ruff>=0.9.2,<0.17' check src tests && uv run --with mypy mypy src`

```bash
git checkout -- uv.lock
git add src/ai_marketplace_monitor/cli.py pyproject.toml tests/test_cli.py tests/test_chat_live.py docs/usage.rst docs/README.md CHANGELOG.md docs/superpowers/specs/2026-10-04-chat-bootstrap-design.md
git commit -m "feat: aimm --chat command, live UnitySVC test, docs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 8: Manual smoke test (with the user's key)**

Run in an interactive terminal where `UNITYSVC_API_KEY` is set:

```bash
uv run pytest tests/test_chat_live.py -v
```

Expected: PASS. Then `uv run aimm --chat` should list `✓ unitysvc — UnitySVC, balanced` (if the user's config has that section) or walk through setup.
