"""AIMM_WEBUI_AUTH=proxy: a reverse proxy signs users in, aimm asks for no password."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ai_marketplace_monitor.webui import server as webui_server
from ai_marketplace_monitor.webui.config_api import ConfigFileService
from ai_marketplace_monitor.webui.log_handler import LogBroadcastHandler
from ai_marketplace_monitor.webui.server import (
    AuthState,
    WebUIConfig,
    _resolve_auth,
    create_app,
    start_webui,
    webui_auth_mode,
)


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("FACEBOOK_USERNAME", "FACEBOOK_PASSWORD", "AIMM_WEBUI_AUTH"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text("[marketplace.facebook]\nsearch_city = 'dallas'\n", encoding="utf-8")
    return path


def proxy_client(config_path: Path) -> TestClient:
    handler = LogBroadcastHandler()
    state = AuthState()
    state.exposed = True
    state.proxy_auth = True
    app = create_app(
        WebUIConfig(host="0.0.0.0", config_files=[config_path], log_handler=handler),  # noqa: S104
        state,
        ConfigFileService([config_path]),
        handler,
    )
    return TestClient(app)


@pytest.mark.parametrize(
    "value, mode", [(None, "password"), ("", "password"), ("proxy", "proxy"), (" Proxy ", "proxy")]
)
def test_auth_mode_from_environment(
    monkeypatch: pytest.MonkeyPatch, value: str | None, mode: str
) -> None:
    if value is not None:
        monkeypatch.setenv("AIMM_WEBUI_AUTH", value)
    assert webui_auth_mode() == mode


def test_unknown_auth_mode_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIMM_WEBUI_AUTH", "none")
    with pytest.raises(ValueError, match="use password or proxy"):
        webui_auth_mode()


def test_proxy_mode_applies_only_when_exposed(
    monkeypatch: pytest.MonkeyPatch, config_path: Path
) -> None:
    monkeypatch.setenv("AIMM_WEBUI_AUTH", "proxy")
    state, info = _resolve_auth(WebUIConfig(host="127.0.0.1", config_files=[config_path]))
    assert not state.proxy_auth and not info.proxy_auth  # loopback is open anyway
    state, info = _resolve_auth(WebUIConfig(host="0.0.0.0", config_files=[config_path]))  # noqa: S104
    assert state.proxy_auth and info.proxy_auth
    assert state.auth is None and info.username is None


def test_exposed_web_ui_starts_without_credentials_in_proxy_mode(
    monkeypatch: pytest.MonkeyPatch, config_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    started: list = []
    monkeypatch.setattr(webui_server.WebUIServer, "start", lambda self: started.append(self))
    config = WebUIConfig(
        host="0.0.0.0", config_files=[config_path], log_handler=LogBroadcastHandler()  # noqa: S104
    )
    # without proxy mode, an exposed web UI needs credentials
    with pytest.raises(RuntimeError, match="AIMM_WEBUI_AUTH=proxy"):
        start_webui(config)
    monkeypatch.setenv("AIMM_WEBUI_AUTH", "proxy")
    logger = logging.getLogger("monitor-test")
    with caplog.at_level(logging.WARNING, logger="monitor-test"):
        _, info = start_webui(config, logger=logger)
    assert started and info.proxy_auth
    assert "reachable only through your reverse proxy" in caplog.text


def test_proxy_mode_signs_in_without_a_password(config_path: Path) -> None:
    client = proxy_client(config_path)
    assert client.get("/api/auth/info").json()["open"] is True
    # still no access without a session
    assert client.get("/api/status").status_code == 401
    login = client.post("/api/login")
    assert login.status_code == 200 and login.json()["username"] == "proxy"
    status = client.get("/api/status").json()
    assert status["auth_mode"] == "proxy"
    assert status["open"] is True  # nothing to log out of


def test_proxy_mode_still_requires_the_csrf_token(config_path: Path) -> None:
    """Proxy credentials ride along with cross-site requests; the CSRF token stops them."""
    client = proxy_client(config_path)
    csrf = client.post("/api/login").json()["csrf"]
    assert client.post("/api/monitor/pause").status_code == 403
    assert client.post("/api/monitor/pause", headers={"X-CSRF-Token": csrf}).status_code != 403


def test_proxy_mode_still_checks_websocket_origin_and_session(config_path: Path) -> None:
    client = proxy_client(config_path)
    # no session
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/ws/stream", headers={"origin": "http://testserver"}):
            pass
    assert closed.value.code == 4401
    client.post("/api/login")
    # a page on another site
    with pytest.raises(WebSocketDisconnect) as closed:
        with client.websocket_connect("/ws/stream", headers={"origin": "http://evil.example"}):
            pass
    assert closed.value.code == 4403
    with client.websocket_connect("/ws/stream", headers={"origin": "http://testserver"}):
        pass


def test_banner_says_the_proxy_signs_users_in(capsys: pytest.CaptureFixture) -> None:
    from ai_marketplace_monitor.commands.common import print_webui_banner
    from ai_marketplace_monitor.webui.server import StartupInfo

    print_webui_banner(
        StartupInfo(
            urls=["http://127.0.0.1:8467"],
            username=None,
            host="0.0.0.0",  # noqa: S104
            port=8467,
            exposed=True,
            proxy_auth=True,
        )
    )
    out = capsys.readouterr().out
    assert "AIMM_WEBUI_AUTH=proxy" in out
    assert "user:" not in out  # no credentials to show
