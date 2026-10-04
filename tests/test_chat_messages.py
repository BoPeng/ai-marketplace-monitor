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


async def test_scripted_ui_empty_answer_takes_default() -> None:
    ui = ScriptedChatUI(["", ""])
    # Choose with default should return the default when answer is ""
    assert await ui.ask(Choose("Pick", [Option("a", "A"), Option("b", "B")], default="a")) == "a"
    # Confirm with default=True should return "yes" when answer is ""
    assert await ui.ask(Confirm("Ok?", default=True)) == "yes"


async def test_scripted_ui_empty_answer_confirm_default_false() -> None:
    ui = ScriptedChatUI([""])
    # Confirm with default=False should return "no" when answer is ""
    assert await ui.ask(Confirm("Ok?", default=False)) == "no"
