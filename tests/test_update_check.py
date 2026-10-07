"""The update check: compare with PyPI once a day, log a line, and tell the web UI."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from ai_marketplace_monitor import update_check
from ai_marketplace_monitor.utils import MonitorConfig


class FakeCache:
    def __init__(self) -> None:
        self.data: Dict[Any, Any] = {}
        self.expire: Dict[Any, Any] = {}

    def get(self, key: Any) -> Any:
        return self.data.get(key)

    def set(self, key: Any, value: Any, expire: Any = None, tag: Any = None) -> None:
        self.data[key], self.expire[key] = value, expire


class FakeResponse:
    def __init__(self, version: str) -> None:
        self.version = version

    def raise_for_status(self) -> None:
        pass

    def json(self) -> Dict[str, Any]:
        return {"info": {"version": self.version}}


class PyPI:
    """What PyPI answers ("offline" raises), and the requests made."""

    def __init__(self) -> None:
        self.answer = "0.11.0"
        self.calls: List[str] = []


@pytest.fixture
def pypi(monkeypatch: pytest.MonkeyPatch) -> PyPI:
    import requests  # type: ignore

    fake = PyPI()

    def get(url: str, timeout: float) -> FakeResponse:
        fake.calls.append(url)
        if fake.answer == "offline":
            raise requests.ConnectionError("offline")
        return FakeResponse(fake.answer)

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(update_check, "cache", FakeCache())
    monkeypatch.setattr(update_check, "_notice", None)
    monkeypatch.delenv("AIMM_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("AIMM_DOCKER", raising=False)
    return fake


@pytest.mark.parametrize(
    "latest, current, newer",
    [
        ("0.11.0", "0.10.3", True),
        ("0.10.10", "0.10.9", True),
        ("0.10.3", "0.10.3", False),
        ("0.10.2", "0.10.3", False),
        ("0.11.0", "0.10.4.dev3+g1234", False),  # development builds are not compared
        ("0.11.0rc1", "0.10.3", False),
    ],
)
def test_is_newer(latest: str, current: str, newer: bool) -> None:
    assert update_check.is_newer(latest, current) is newer


def test_a_newer_release_is_logged_and_remembered(
    pypi: PyPI, caplog: pytest.LogCaptureFixture
) -> None:
    logger = logging.getLogger("monitor-test")
    with caplog.at_level(logging.INFO, logger="monitor-test"):
        notice = update_check.check(logger, current="0.10.3")
    assert notice is not None and notice.latest == "0.11.0"
    assert "0.11.0 is available (you have 0.10.3)" in caplog.text
    assert "pip install --upgrade ai-marketplace-monitor" in caplog.text
    assert update_check.current_notice() == {
        "current": "0.10.3",
        "latest": "0.11.0",
        "command": "pip install --upgrade ai-marketplace-monitor",
        "changelog": update_check.CHANGELOG_URL,
    }


def test_pypi_is_asked_once_a_day(pypi: PyPI) -> None:
    update_check.check(None, current="0.10.3")
    update_check.check(None, current="0.10.3")
    assert pypi.calls == [update_check.PYPI_URL]
    key = (update_check.CacheType.UPDATE_CHECK.value, "latest")
    assert update_check.cache.expire[key] == 24 * 60 * 60  # type: ignore[attr-defined]


def test_nothing_happens_when_current_or_offline(
    pypi: PyPI, caplog: pytest.LogCaptureFixture
) -> None:
    assert update_check.check(None, current="0.11.0") is None
    pypi.answer = "offline"
    update_check.cache.data.clear()  # type: ignore[attr-defined]
    assert update_check.check(None, current="0.10.3") is None  # no error either
    assert update_check.current_notice() is None


def test_turning_it_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update_check, "__version__", "0.10.3")
    monkeypatch.delenv("AIMM_NO_UPDATE_CHECK", raising=False)
    assert update_check.enabled(None) and update_check.enabled(True)
    assert not update_check.enabled(False)
    monkeypatch.setenv("AIMM_NO_UPDATE_CHECK", "1")
    assert not update_check.enabled(None)
    monkeypatch.delenv("AIMM_NO_UPDATE_CHECK")
    monkeypatch.setattr(update_check, "__version__", "0.10.4.dev3+g1234")
    assert not update_check.enabled(None)
    assert MonitorConfig(name="monitor", check_updates=False).check_updates is False
    with pytest.raises(ValueError, match="check_updates"):
        MonitorConfig(name="monitor", check_updates="no")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "docker, prefix, command",
    [
        ("1", "/usr/local", "docker pull ghcr.io/bopeng/ai-marketplace-monitor:latest"),
        (None, "/home/me/.local/share/pipx/venvs/ai-marketplace-monitor", "pipx upgrade"),
        (None, "/home/me/.local/share/uv/tools/ai-marketplace-monitor", "uv tool upgrade"),
        (None, "/home/me/venv", "pip install --upgrade"),
    ],
)
def test_upgrade_command_fits_the_installation(
    monkeypatch: pytest.MonkeyPatch, docker: str | None, prefix: str, command: str
) -> None:
    if docker:
        monkeypatch.setenv("AIMM_DOCKER", docker)
    else:
        monkeypatch.delenv("AIMM_DOCKER", raising=False)
    monkeypatch.setattr(sys, "prefix", prefix)
    assert update_check.upgrade_command().startswith(command)


def test_web_ui_status_carries_the_notice(tmp_path: Path, pypi: PyPI) -> None:
    from ai_marketplace_monitor.webui.config_api import ConfigFileService
    from ai_marketplace_monitor.webui.log_handler import LogBroadcastHandler
    from ai_marketplace_monitor.webui.server import AuthState, WebUIConfig, create_app

    cfg = tmp_path / "config.toml"
    cfg.write_text("[marketplace.facebook]\nsearch_city = 'dallas'\n", encoding="utf-8")
    handler = LogBroadcastHandler()
    app = create_app(
        WebUIConfig(config_files=[cfg], log_handler=handler),
        AuthState(),
        ConfigFileService([cfg]),
        handler,
    )
    client = TestClient(app)
    assert client.get("/api/status").json()["update"] is None
    assert client.get("/api/status").json()["version"] == update_check.__version__
    update_check.check(None, current="0.10.3")
    assert client.get("/api/status").json()["update"]["latest"] == "0.11.0"
