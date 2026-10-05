"""Front ends for interactive configuration: the protocol plus terminal, JSON and test adapters."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, ClassVar, Dict, List, Protocol, Tuple

from rich.console import Console
from rich.markdown import Markdown


class SetupClosedError(Exception):
    """The user left the setup flow."""


@dataclass(frozen=True)
class Choice:
    value: str
    label: str
    hint: str = ""

    def to_json(self: "Choice") -> Dict[str, str]:
        return {"value": self.value, "label": self.label, "hint": self.hint}


class SetupUI(Protocol):
    async def say(
        self: "SetupUI", text: str, *, kind: str = "info", markdown: bool = False
    ) -> None: ...

    async def choose(
        self: "SetupUI",
        prompt: str,
        options: List[Choice],
        default: str | None = None,
        *,
        allow_text: bool = False,
    ) -> str:
        """One of the option values; with ``allow_text``, any other answer typed instead."""
        ...

    async def ask_text(self: "SetupUI", prompt: str, default: str | None = None) -> str: ...

    async def confirm(self: "SetupUI", prompt: str, default: bool = True) -> bool: ...


class JsonSetupUI:
    """JSON message adapter for WebSocket or other remote front ends.

    An invalid answer (or an unexpected message) is reported to the front end as an error
    message and the prompt is sent again, so one bad message never ends the session.
    """

    def __init__(
        self: "JsonSetupUI",
        send: Callable[[Dict[str, Any]], Awaitable[None]],
        receive: Callable[[], Awaitable[Dict[str, Any]]],
    ) -> None:
        self._send = send
        self._receive = receive

    async def say(
        self: "JsonSetupUI", text: str, *, kind: str = "info", markdown: bool = False
    ) -> None:
        await self._send({"type": "message", "kind": kind, "text": text, "markdown": markdown})

    async def choose(
        self: "JsonSetupUI",
        prompt: str,
        options: List[Choice],
        default: str | None = None,
        *,
        allow_text: bool = False,
    ) -> str:
        allowed = {option.value for option in options}

        def parse(answer: Any) -> str:
            if answer in (None, "") and default is not None:
                return default
            if allow_text and isinstance(answer, str) and answer.strip():
                return answer.strip()
            if not isinstance(answer, str) or answer not in allowed:
                raise ValueError(f"Choose one of: {', '.join(sorted(allowed))}.")
            return answer

        message = {
            "type": "prompt",
            "prompt_type": "choice",
            "prompt": prompt,
            "options": [option.to_json() for option in options],
            "default": default,
            "allow_text": allow_text,
        }
        return await self._prompt(message, parse)  # type: ignore[no-any-return]

    async def ask_text(self: "JsonSetupUI", prompt: str, default: str | None = None) -> str:
        def parse(answer: Any) -> str:
            if answer in (None, "") and default is not None:
                return default
            if not isinstance(answer, str):
                raise ValueError("The answer must be text.")
            return answer

        message = {"type": "prompt", "prompt_type": "text", "prompt": prompt, "default": default}
        return await self._prompt(message, parse)  # type: ignore[no-any-return]

    async def confirm(self: "JsonSetupUI", prompt: str, default: bool = True) -> bool:
        def parse(answer: Any) -> bool:
            if answer in (None, ""):
                return default
            if isinstance(answer, bool):
                return answer
            if isinstance(answer, str) and answer.lower() in ("y", "yes", "true"):
                return True
            if isinstance(answer, str) and answer.lower() in ("n", "no", "false"):
                return False
            raise ValueError("Answer yes or no.")

        message = {
            "type": "prompt",
            "prompt_type": "confirm",
            "prompt": prompt,
            "default": default,
        }
        return await self._prompt(message, parse)  # type: ignore[no-any-return]

    async def _prompt(
        self: "JsonSetupUI", message: Dict[str, Any], parse: Callable[[Any], Any]
    ) -> Any:
        while True:
            await self._send(message)
            reply = await self._receive()
            reply_type = reply.get("type")
            if reply_type in ("cancel", "close"):
                raise SetupClosedError
            try:
                if reply_type != "answer":
                    raise ValueError(f"Expected an answer message, got {reply_type!r}.")
                return parse(reply.get("value"))
            except ValueError as e:
                await self.say(str(e), kind="error")


class ConsoleSetupUI:
    """Terminal front end."""

    _styles: ClassVar[Dict[str, str]] = {
        "info": "",
        "success": "green",
        "warning": "yellow",
        "error": "bold red",
    }

    def __init__(
        self: "ConsoleSetupUI",
        console: Console | None = None,
        read: Callable[[str], str] = input,
        interactive: bool | None = None,
    ) -> None:
        if interactive is None:
            interactive = sys.stdin.isatty()
        if not interactive:
            raise RuntimeError("aimm-configure needs an interactive terminal")
        self.console = console or Console()
        self._read = read

    async def say(
        self: "ConsoleSetupUI", text: str, *, kind: str = "info", markdown: bool = False
    ) -> None:
        if markdown:
            self.console.print(Markdown(text))
            return
        self.console.print(text, style=self._styles.get(kind, ""), markup=False, highlight=False)

    async def choose(
        self: "ConsoleSetupUI",
        prompt: str,
        options: List[Choice],
        default: str | None = None,
        *,
        allow_text: bool = False,
    ) -> str:
        if allow_text:
            prompt += " (enter a number, or type a value)"
        self.console.print(prompt, markup=False, highlight=False)
        for index, option in enumerate(options, 1):
            hint = f" - {option.hint}" if option.hint else ""
            suffix = " (default)" if option.value == default else ""
            self.console.print(
                f"  {index}) {option.label}{hint}{suffix}", markup=False, highlight=False
            )
        while True:
            raw = self._input("> ").strip()
            if not raw and default is not None:
                return default
            if raw.isdecimal() and 1 <= int(raw) <= len(options):
                return options[int(raw) - 1].value
            if allow_text and raw and not raw.isdecimal():
                return raw
            self.console.print(f"Please enter a number from 1 to {len(options)}.", style="yellow")

    async def ask_text(self: "ConsoleSetupUI", prompt: str, default: str | None = None) -> str:
        suffix = f" [{default}]" if default else ""
        raw = self._input(f"{prompt}{suffix}: ")
        if not raw.strip() and default is not None:
            return default
        return raw

    async def confirm(self: "ConsoleSetupUI", prompt: str, default: bool = True) -> bool:
        suffix = " [Y/n] " if default else " [y/N] "
        while True:
            raw = self._input(prompt + suffix).strip().lower()
            if not raw:
                return default
            if raw in ("y", "yes"):
                return True
            if raw in ("n", "no"):
                return False
            self.console.print("Please answer y or n.", style="yellow")

    def _input(self: "ConsoleSetupUI", prompt: str) -> str:
        try:
            return self._read(prompt)
        except (KeyboardInterrupt, EOFError) as e:
            raise SetupClosedError from e


class ScriptedSetupUI:
    """Test front end with canned answers."""

    def __init__(self: "ScriptedSetupUI", answers: List[str]) -> None:
        self.answers = list(answers)
        self.messages: List[Tuple[str, str]] = []
        self.questions: List[str] = []

    async def say(
        self: "ScriptedSetupUI", text: str, *, kind: str = "info", markdown: bool = False
    ) -> None:
        self.messages.append((kind, text))

    async def choose(
        self: "ScriptedSetupUI",
        prompt: str,
        options: List[Choice],
        default: str | None = None,
        *,
        allow_text: bool = False,
    ) -> str:
        answer = self._answer(prompt)
        if not answer and default is not None:
            return default
        allowed = {option.value for option in options}
        if answer not in allowed and not allow_text:
            raise AssertionError(f"{answer!r} is not one of {sorted(allowed)}")
        return answer

    async def ask_text(self: "ScriptedSetupUI", prompt: str, default: str | None = None) -> str:
        answer = self._answer(prompt)
        return default if not answer and default is not None else answer

    async def confirm(self: "ScriptedSetupUI", prompt: str, default: bool = True) -> bool:
        answer = self._answer(prompt)
        if not answer:
            return default
        if answer not in ("yes", "no"):
            raise AssertionError(f"Confirm answers must be yes or no, got {answer!r}")
        return answer == "yes"

    def said(self: "ScriptedSetupUI", kind: str | None = None) -> List[str]:
        return [text for message_kind, text in self.messages if kind in (None, message_kind)]

    def _answer(self: "ScriptedSetupUI", prompt: str) -> str:
        self.questions.append(prompt)
        if not self.answers:
            raise AssertionError(f"unexpected question: {prompt}")
        answer = self.answers.pop(0)
        if answer == "<close>":
            raise SetupClosedError
        return answer
