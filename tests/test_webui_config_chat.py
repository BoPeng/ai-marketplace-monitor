"""Tests for the Web UI configuration chat websocket."""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ai_marketplace_monitor.configure.ui import SetupClosedError
from ai_marketplace_monitor.webui import server as webui_server
from ai_marketplace_monitor.webui.config_api import ConfigFileService
from ai_marketplace_monitor.webui.log_handler import LogBroadcastHandler
from ai_marketplace_monitor.webui.server import AuthState, WebUIConfig, create_app

SAME_ORIGIN_HEADERS = {"origin": "http://testserver"}


def _make_client(tmp_path: Path, *, exposed: bool = False) -> TestClient:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[marketplace.facebook]\nsearch_city = 'dallas'\n", encoding="utf-8")
    handler = LogBroadcastHandler()
    config = WebUIConfig(config_files=[cfg_file], log_handler=handler)
    state = AuthState()
    state.exposed = exposed
    service = ConfigFileService([cfg_file])
    app = create_app(config, state, service, handler)
    return TestClient(app)


def _connect(client: TestClient, path: str) -> Any:
    return client.websocket_connect(path, headers=SAME_ORIGIN_HEADERS)


def test_configure_websocket_runs_front_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_configure_front_door(ui: Any, files: List[Path]) -> int:
        await ui.say("Hello from configure.")
        answer = await ui.ask_text("What should I change?")
        await ui.say(f"Got {answer}.", kind="success")
        return 0

    monkeypatch.setattr(webui_server, "configure_front_door", fake_configure_front_door)

    client = _make_client(tmp_path)
    with _connect(client, "/ws/configure") as ws:
        assert ws.receive_json() == {
            "type": "message",
            "kind": "info",
            "text": "Hello from configure.",
            "markdown": False,
        }
        prompt = ws.receive_json()
        assert prompt["type"] == "prompt"
        assert prompt["prompt_type"] == "text"
        assert prompt["prompt"] == "What should I change?"

        ws.send_json({"type": "answer", "value": "add an item"})

        assert ws.receive_json()["text"] == "Got add an item."
        assert ws.receive_json() == {"type": "done", "exit_code": 0}


def test_configure_websocket_runs_section(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_configure_section(ui: Any, files: List[Path], section: str) -> int:
        await ui.say(f"Section {section}")
        return 0

    monkeypatch.setattr(webui_server, "configure_section", fake_configure_section)

    client = _make_client(tmp_path)
    with _connect(client, "/ws/configure?section=item.gopro") as ws:
        assert ws.receive_json()["text"] == "Section item.gopro"
        assert ws.receive_json() == {"type": "done", "exit_code": 0}


def test_configure_websocket_reports_invalid_section(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    with _connect(client, "/ws/configure?section=unknown") as ws:
        error = ws.receive_json()
        assert error["type"] == "message"
        assert error["kind"] == "error"
        assert "Only" in error["text"]
        assert ws.receive_json() == {"type": "done", "exit_code": 1}


def test_configure_websocket_requires_session_when_exposed(tmp_path: Path) -> None:
    client = _make_client(tmp_path, exposed=True)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with _connect(client, "/ws/configure"):
            pass
    assert exc_info.value.code == 4401


def test_configure_websocket_rejects_cross_site_origin(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/ws/configure", headers={"origin": "http://example.invalid"}
        ):
            pass
    assert exc_info.value.code == 4403


def test_configure_websocket_cancel_sends_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_configure_front_door(ui: Any, files: List[Path]) -> int:
        try:
            await ui.ask_text("What should I change?")
        except SetupClosedError:
            return 0
        return 1

    monkeypatch.setattr(webui_server, "configure_front_door", fake_configure_front_door)

    client = _make_client(tmp_path)
    with _connect(client, "/ws/configure") as ws:
        prompt = ws.receive_json()
        assert prompt["type"] == "prompt"
        ws.send_json({"type": "cancel"})
        assert ws.receive_json() == {"type": "done", "exit_code": 0}
