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
            if raw.isdecimal() and 1 <= int(raw) <= len(question.options):
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
