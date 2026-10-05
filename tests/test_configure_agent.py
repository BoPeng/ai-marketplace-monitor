"""The agent loop with a scripted model: tool calls, plain text, limits, errors."""

import sys
from pathlib import Path
from typing import Any, List

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ai_marketplace_monitor.configure import agent
from ai_marketplace_monitor.configure.agent import ServiceError, run_agent
from ai_marketplace_monitor.configure.tools import Outcome, ToolExecutor
from ai_marketplace_monitor.configure.ui import SetupClosedError
from tests.configure_util import ONE_ITEM, FakeModel, Step, make_ws, ui_of

ASK = "ask_user"
SHOW = ("marketplace_show", {"name": "facebook"})


async def run(
    tmp_path: Path, steps: List[Step], answers: List[str], text: str = ONE_ITEM
) -> tuple[Outcome, ToolExecutor, FakeModel]:
    ws = await make_ws(tmp_path, text, answers)
    executor = ToolExecutor(ws, only=("marketplace", "facebook"))
    model = FakeModel(steps).bind(executor.tools_for_model(), lambda: executor.done)
    outcome = await run_agent(executor, model, "system", "opening")
    return outcome, executor, model


async def test_conversation_saves_through_tools(tmp_path: Path) -> None:
    outcome, executor, model = await run(
        tmp_path,
        [
            [SHOW, (ASK, {"message": "What would you like to change?"})],
            [
                (
                    "marketplace_update",
                    {"name": "facebook", "values": {"max_price": "1000"}, "request": "Max $1000."},
                ),
                (ASK, {"message": "Max price $1000. Anything else?"}),
            ],
            [("save", {"message": "Saving max price $1000."})],
            [("finish", {"message": "Done."})],
        ],
        ["set max price to $1000", "no", "yes"],
    )
    assert outcome is Outcome.SAVED and executor.done
    ui = ui_of(executor.ws)
    assert ui.questions == ["You", "You", "Write these changes?"]
    assert "What would you like to change?" in ui.said() and "Done." in ui.said()
    written = tomllib.loads((tmp_path / "config.toml").read_text())
    assert written["marketplace"]["facebook"]["max_price"] == "1000"
    assert written["item"]["example"]["max_price"] == 300
    assert model.results(ASK)[0] == {"ok": True, "reply": "set max price to $1000"}


async def test_plain_text_reply_is_shown_and_answered(tmp_path: Path) -> None:
    outcome, executor, model = await run(
        tmp_path,
        ["Hello! What would you like to change?", [("finish", {"message": "Bye."})]],
        ["nothing"],
    )
    assert outcome is Outcome.UNCHANGED
    assert "Hello! What would you like to change?" in ui_of(executor.ws).said()
    assert model.user_texts == ["nothing"]


async def test_update_errors_go_back_to_the_model(tmp_path: Path) -> None:
    outcome, _, model = await run(
        tmp_path,
        [
            [("marketplace_update", {"name": "facebook", "values": {"condition": ["mint"]}})],
            [("finish", {"message": "Bye."})],
        ],
        [],
    )
    assert outcome is Outcome.UNCHANGED
    assert not model.results("marketplace_update")[0]["ok"]


async def test_quit_ends_without_writing(tmp_path: Path) -> None:
    outcome, executor, _ = await run(
        tmp_path,
        [
            [("marketplace_update", {"name": "facebook", "values": {"max_price": "5"}})],
            [(ASK, {"message": "Anything else?"})],
        ],
        ["/quit"],
    )
    assert outcome is Outcome.CANCELLED
    assert "Nothing more was written." in ui_of(executor.ws).said("success")
    assert 'max_price = "5"' not in (tmp_path / "config.toml").read_text()


async def test_ctrl_c_propagates(tmp_path: Path) -> None:
    with pytest.raises(SetupClosedError):
        await run(tmp_path, [[(ASK, {"message": "Hi?"})]], ["<close>"])


async def test_service_error_then_retry(tmp_path: Path) -> None:
    outcome, executor, _ = await run(
        tmp_path,
        [ServiceError("The AI service failed: 504"), [("finish", {"message": "Bye."})]],
        [""],
    )
    assert outcome is Outcome.UNCHANGED
    ui = ui_of(executor.ws)
    assert "The AI service failed: 504" in ui.said("error")
    assert "Press Enter to try again, or /quit to stop" in ui.questions


async def test_too_many_steps_without_the_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent, "MAX_STEPS_WITHOUT_USER", 2)
    outcome, _, model = await run(
        tmp_path,
        [[SHOW], [SHOW], [SHOW], [(ASK, {"message": "OK?"})], [("finish", {"message": "Bye."})]],
        ["fine"],
    )
    assert outcome is Outcome.UNCHANGED
    shows: List[Any] = model.results("marketplace_show")
    assert shows[0]["ok"] and shows[1]["ok"]
    assert shows[2]["errors"] == ["Too many steps without the user: call ask_user now."]


async def test_call_limit_offers_save_of_complete_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent, "MAX_MODEL_CALLS", 2)
    outcome, executor, _ = await run(
        tmp_path,
        [
            [("marketplace_update", {"name": "facebook", "values": {"max_price": "7"}})],
            [SHOW],
        ],
        ["yes"],
    )
    assert outcome is Outcome.SAVED
    assert any("you can save them now" in m for m in ui_of(executor.ws).said())
