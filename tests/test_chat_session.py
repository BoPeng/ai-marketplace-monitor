from pathlib import Path
from typing import Dict, List

import pytest

from ai_marketplace_monitor.ai import OpenAIBackend
from ai_marketplace_monitor.chat import session as session_module
from ai_marketplace_monitor.chat.builders import ai as ai_module
from ai_marketplace_monitor.chat.probe import ProbeResult
from ai_marketplace_monitor.chat.session import render_config, run_chat
from ai_marketplace_monitor.chat.ui import CLOSE, ScriptedChatUI

WORKING = (
    '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\n'
    '[user.u]\npushbullet_token = "secret-token-value"\n'
)


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
    written = (home / "config.toml").read_text()
    assert written.startswith(
        '[ai.unitysvc]\nrequest = "Use UnitySVC (balanced) to rate listings and to chat."\n'
        'api_key = "${UNITYSVC_API_KEY}"'
    )
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
    assert render_config([]) == (
        "# The user's current configuration\n\n(no configuration files yet)"
    )


def test_render_config_masks_structurally(tmp_path: Path) -> None:
    path = config(
        tmp_path,
        'user.password = "zzz"\n'
        'notification.tg = { telegram_token = "123:abc" }\n'
        'note = "svcpass_leakedvalue123"\n'
        '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\n'
        '[smtp]\npassword = "pa\'ss"\n',
    )
    text = render_config([path])
    for leaked in ("pa'ss", "zzz", "123:abc", "svcpass_leakedvalue123"):
        assert leaked not in text
    assert "${UNITYSVC_API_KEY}" in text


async def test_provider_error_scrubs_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_test")
    ok(monkeypatch)

    def leaky(self: OpenAIBackend, messages: List[Dict[str, str]]) -> str:
        raise RuntimeError("401 for key svcpass_test")

    monkeypatch.setattr(OpenAIBackend, "chat", leaky)
    ui = ScriptedChatUI(["unitysvc", "hello", CLOSE])
    assert await run_chat(ui, [config(tmp_path, WORKING)], home=tmp_path / "home") == 0
    assert ui.said("error")
    assert all("svcpass_test" not in t for t in ui.said("error"))


async def test_closed_at_setup_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ok(monkeypatch, ok=False)
    home = tmp_path / "home"
    assert await run_chat(ScriptedChatUI(["unitysvc", CLOSE]), [], home=home) == 0
    assert not (home / "config.toml").exists()


async def test_closed_inside_edit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_test")
    ok(monkeypatch)
    path = config(tmp_path, WORKING)
    ui = ScriptedChatUI(["unitysvc", "/edit ai", CLOSE])
    assert await run_chat(ui, [path], home=tmp_path / "home") == 0
    assert path.read_text() == WORKING


def test_render_config_masks_identifiers(tmp_path: Path) -> None:
    path = config(
        tmp_path,
        '[user.u]\npushover_user_key = "uQiRzpo4DXghDmr9QzzfQu27cmVRsG"\n'
        'telegram_chat_id = "987654321"\n',
    )
    text = render_config([path])
    assert "uQiRzpo4" not in text and "987654321" not in text


async def test_pasted_key_is_not_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chats: List[List[Dict[str, str]]]
) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "plainsecretvalue")
    ok(monkeypatch)
    ui = ScriptedChatUI(
        ["unitysvc", "here: sk-abcdef123456", "mine is plainsecretvalue", "hello", "/exit"]
    )
    assert await run_chat(ui, [config(tmp_path, WORKING)], home=tmp_path / "home") == 0
    sent = [m["content"] for call in chats for m in call if m["role"] == "user"]
    assert sent == ["hello"]
    warnings = ui.said("warning")
    assert len(warnings) == 2 and "environment" in warnings[0]
    every = [t for kind in ("warning", "error", "assistant") for t in ui.said(kind)]
    assert all("sk-abcdef" not in t and "plainsecretvalue" not in t for t in every)
