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
        "note": "",
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


def test_docker_command_can_be_copied_and_run(
    pypi: PyPI, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("AIMM_DOCKER", "1")
    logger = logging.getLogger("monitor-test")
    with caplog.at_level(logging.INFO, logger="monitor-test"):
        notice = update_check.check(logger, current="0.10.3")
    assert notice is not None
    # the command alone, so pasting it does not hand the instructions to `docker rm`
    assert notice.command == (
        "docker pull ghcr.io/bopeng/ai-marketplace-monitor:latest && docker rm -f aimm"
    )
    assert "run your `docker run` command again" in notice.note
    assert notice.note in caplog.text


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


@pytest.fixture
def installer(monkeypatch: pytest.MonkeyPatch, pypi: PyPI) -> List[Any]:
    """Docker, a newer release found, and commands and restarts recorded instead of run."""
    calls: List[Any] = []
    monkeypatch.setenv("AIMM_DOCKER", "1")
    monkeypatch.setattr(update_check, "_self_update", update_check.SelfUpdate())

    def run(command: List[str], logger: Any) -> str:
        calls.append(command)
        return "ai-marketplace-monitor==0.10.3\nplaywright==1.50.0\n"  # for `pip freeze`

    monkeypatch.setattr(update_check, "_run", run)
    monkeypatch.setattr(update_check, "_restart", lambda: calls.append("restart"))
    update_check.check(None, current="0.10.3")
    return calls


def test_self_update_installs_the_release_then_restarts(installer: List[Any]) -> None:
    update_check.install_and_restart("0.11.0", None)
    freeze, pip, playwright, restart = installer
    assert freeze[1:4] == ["-m", "pip", "freeze"]
    assert pip[1:] == ["-m", "pip", "install", "ai-marketplace-monitor==0.11.0"]
    assert playwright[1:] == ["-m", "playwright", "install", "chromium"]
    assert restart == "restart"
    assert update_check.self_update_status()["state"] == "restarting"


def test_failed_self_update_keeps_aimm_running(
    installer: List[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(command: List[str], logger: Any) -> str:
        raise RuntimeError("no network")

    monkeypatch.setattr(update_check, "_run", fail)
    update_check.install_and_restart("0.11.0", None)
    assert "restart" not in installer
    status = update_check.self_update_status()
    assert (status["state"], status["error"]) == ("failed", "no network")


@pytest.mark.parametrize("restore_fails", [False, True])
def test_failed_browser_install_restores_the_previous_packages(
    installer: List[Any], monkeypatch: pytest.MonkeyPatch, restore_fails: bool
) -> None:
    restored: List[str] = []

    def run(command: List[str], logger: Any) -> str:
        if "freeze" in command:
            return "ai-marketplace-monitor==0.10.3\nplaywright==1.50.0\n"
        if "playwright" in command:
            raise RuntimeError("download failed")
        if "-r" in command:  # the restore: the snapshot, without resolving again
            if restore_fails:
                raise RuntimeError("no network")
            assert "--no-deps" in command
            with open(command[-1], encoding="utf-8") as requirements:
                restored.append(requirements.read())
        return ""

    monkeypatch.setattr(update_check, "_run", run)
    update_check.install_and_restart("0.11.0", None)
    assert "restart" not in installer
    status = update_check.self_update_status()
    assert status["state"] == "failed"
    assert status["error"].startswith("download failed\n")
    if restore_fails:
        assert "recreate the container" in status["error"]
    else:
        assert restored == ["ai-marketplace-monitor==0.10.3\nplaywright==1.50.0\n"]
        assert "Restored aimm" in status["error"]


def test_run_kills_a_command_that_does_not_finish() -> None:
    with pytest.raises(RuntimeError, match=r"did not finish in 0\.5 seconds"):
        update_check._run([sys.executable, "-c", "import time; time.sleep(30)"], None, timeout=0.5)


def test_self_update_needs_docker_a_release_and_no_update_running(
    installer: List[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    started: List[str] = []
    monkeypatch.setattr(update_check, "install_and_restart", lambda v, logger: started.append(v))
    assert update_check.start_self_update(None) == "0.11.0"
    with pytest.raises(RuntimeError, match="already in progress"):
        update_check.start_self_update(None)
    monkeypatch.setattr(update_check, "_self_update", update_check.SelfUpdate())
    monkeypatch.setattr(update_check, "_notice", None)
    with pytest.raises(RuntimeError, match="No newer release"):
        update_check.start_self_update(None)
    monkeypatch.delenv("AIMM_DOCKER")
    with pytest.raises(RuntimeError, match="Docker"):
        update_check.start_self_update(None)
    assert update_check.self_update_status()["available"] is False


def test_self_update_needs_a_writable_installation(
    installer: List[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A container run as another user (e.g. a custom PUID) is updated with a new image."""
    import os

    monkeypatch.setattr(os, "access", lambda path, mode: False)
    assert update_check.can_restart() is True
    assert update_check.can_self_update() is False
    assert update_check.self_update_status()["available"] is False
    with pytest.raises(RuntimeError, match="aimm user"):
        update_check.start_self_update(None)
    assert "where you installed it" in update_check.upgrade_note()
    assert "click Update" not in update_check.upgrade_note()


def test_run_reports_the_end_of_a_failed_command() -> None:
    script = "print('resolving'); print('no matching distribution'); raise SystemExit(3)"
    with pytest.raises(RuntimeError, match="exited with 3:\nresolving\nno matching distribution"):
        update_check._run([sys.executable, "-c", script], None)


def test_web_ui_update_endpoint(
    tmp_path: Path, installer: List[Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_marketplace_monitor.webui.config_api import ConfigFileService
    from ai_marketplace_monitor.webui.log_handler import LogBroadcastHandler
    from ai_marketplace_monitor.webui.server import AuthState, WebUIConfig, create_app

    started: List[str] = []
    monkeypatch.setattr(update_check, "install_and_restart", lambda v, logger: started.append(v))
    cfg = tmp_path / "config.toml"
    cfg.write_text("[marketplace.facebook]\nsearch_city = 'dallas'\n", encoding="utf-8")
    handler = LogBroadcastHandler()
    client = TestClient(
        create_app(
            WebUIConfig(config_files=[cfg], log_handler=handler),
            AuthState(),
            ConfigFileService([cfg]),
            handler,
        )
    )
    assert client.get("/api/status").json()["self_update"]["available"] is True
    assert client.post("/api/update").json() == {"ok": True, "version": "0.11.0"}
    assert client.get("/api/status").json()["self_update"]["state"] == "running"
    response = client.post("/api/update")
    assert response.status_code == 409
    assert "already in progress" in response.json()["detail"]
