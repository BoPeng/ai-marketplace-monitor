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
    ui, out = make_ui("9", "x", "²", "")
    assert await ui.ask(PICK) == "u"
    assert out.getvalue().count("Please enter a number from 1 to 2.") == 3


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
