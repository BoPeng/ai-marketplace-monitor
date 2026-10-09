"""Waiting for the Facebook login to finish, and pausing searches from the web UI."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest
import schedule
from fastapi.testclient import TestClient

from ai_marketplace_monitor import facebook
from ai_marketplace_monitor import monitor as monitor_module
from ai_marketplace_monitor.control import control
from ai_marketplace_monitor.facebook import FacebookMarketplace, FacebookMarketplaceConfig
from ai_marketplace_monitor.monitor import MarketplaceMonitor

LOGIN_URL = "https://www.facebook.com/login/device-based/regular/login/?login_attempt=1"
MARKETPLACE_URL = "https://www.facebook.com/marketplace/houston/"


class FakeContext:
    def __init__(self) -> None:
        self.logged_in = False

    def cookies(self, url: str) -> List[Dict[str, str]]:
        return [{"name": "c_user", "value": "1"}] if self.logged_in else [{"name": "datr"}]


class FakePage:
    """A page on which the user finishes logging in after ``polls_to_login`` checks."""

    def __init__(self, url: str = LOGIN_URL, polls_to_login: int = 3) -> None:
        self.url = url
        self.context = FakeContext()
        self.polls = 0
        self.polls_to_login = polls_to_login
        self.waiting_seen: List[bool] = []

    def wait_for_timeout(self, ms: float) -> None:
        self.polls += 1
        self.waiting_seen.append(control.waiting_for_login)
        if self.polls >= self.polls_to_login:
            self.url = MARKETPLACE_URL
            self.context.logged_in = True


@pytest.fixture(autouse=True)
def fresh_control() -> Iterator[None]:
    control.resume()
    control.waiting_for_login = False
    yield
    control.resume()
    control.waiting_for_login = False


def _marketplace(page: FakePage) -> FacebookMarketplace:
    marketplace = FacebookMarketplace("facebook", None)
    marketplace.config = FacebookMarketplaceConfig(
        name="facebook", username="user@example.com", password="test-password"
    )
    marketplace.page = page  # type: ignore[assignment]
    return marketplace


def test_wait_for_login_waits_until_facebook_has_logged_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(facebook, "LOGIN_REMINDER_EVERY", 0)  # remind on every check
    reminders: List[str] = []

    class Logger:
        def warning(self, message: str, **kwargs: Any) -> None:
            reminders.append(message)

        def info(self, message: str, **kwargs: Any) -> None:
            pass

    page = FakePage(polls_to_login=3)
    marketplace = _marketplace(page)
    marketplace.logger = Logger()  # type: ignore[assignment]
    marketplace.wait_for_login()
    assert page.polls == 3
    assert page.waiting_seen == [True, True, True]  # the web UI shows "waiting for login"
    assert control.waiting_for_login is False
    assert len(reminders) >= 2 and "CAPTCHA" in reminders[0]


@pytest.mark.parametrize(
    "docker, where",
    [
        ("1", "Click Open browser in the web UI"),
        (None, "in the browser window aimm opened"),
    ],
)
def test_the_login_hint_says_where_to_finish_logging_in(
    monkeypatch: pytest.MonkeyPatch, docker: str | None, where: str
) -> None:
    if docker:
        monkeypatch.setenv("AIMM_DOCKER", docker)
    else:
        monkeypatch.delenv("AIMM_DOCKER", raising=False)
    hints: List[str] = []

    class HintPage(FakePage):
        def wait_for_timeout(self, ms: float) -> None:
            hints.append(control.status()["login_hint"])
            super().wait_for_timeout(ms)

    page = HintPage(polls_to_login=2)
    marketplace = _marketplace(page)
    marketplace.wait_for_login()
    assert where in hints[0] and "CAPTCHA" in hints[0]
    assert control.status()["login_hint"] == ""  # only while waiting


def test_a_logged_in_page_does_not_wait() -> None:
    page = FakePage(url=MARKETPLACE_URL)
    page.context.logged_in = True
    _marketplace(page).wait_for_login()
    assert page.polls == 0


@pytest.mark.parametrize(
    "url",
    [
        LOGIN_URL,
        "https://www.facebook.com/checkpoint/1501092823525282/",
        "https://www.facebook.com/two_step_verification/authentication/",
    ],
)
def test_the_cookie_alone_is_not_enough_on_a_login_page(url: str) -> None:
    page = FakePage(url=url)
    page.context.logged_in = True
    assert _marketplace(page).on_login_page()
    assert not _marketplace(page).logged_in()


def test_recover_login(monkeypatch: pytest.MonkeyPatch) -> None:
    # a page that failed for another reason is not retried
    assert _marketplace(FakePage(url=MARKETPLACE_URL)).recover_login() is False
    # redirected to the login page: wait for the login, then retry
    page = FakePage()
    assert _marketplace(page).recover_login() is True
    assert page.context.logged_in


def test_login_waits_for_the_login(monkeypatch: pytest.MonkeyPatch) -> None:
    waited: List[bool] = []
    marketplace = _marketplace(FakePage())
    monkeypatch.setattr(marketplace, "create_page", lambda swap_proxy: marketplace.page)
    monkeypatch.setattr(marketplace, "goto_url", lambda url: None)
    monkeypatch.setattr(marketplace, "wait_for_login", lambda: waited.append(True))
    monkeypatch.setattr(facebook.time, "sleep", lambda seconds: None)

    class Element:
        def type(self, text: str, delay: int) -> None:
            pass

    class Keyboard:
        def press(self, key: str) -> None:
            pass

    class Button:
        def is_visible(self) -> bool:
            return False

    page: Any = marketplace.page
    page.wait_for_selector = lambda selector: Element()
    page.keyboard = Keyboard()
    page.get_by_role = lambda role, name: Button()
    marketplace.browser = object()  # type: ignore[assignment]
    marketplace.login()
    assert waited == [True]


def test_listing_details_are_retried_after_the_login(monkeypatch: pytest.MonkeyPatch) -> None:
    class Details:
        def to_cache(self, post_url: str) -> None:
            pass

    details = Details()
    results: List[Any] = [None, details]  # the first attempt lands on the login page
    visited: List[str] = []
    page = FakePage()
    marketplace = _marketplace(page)
    monkeypatch.setattr(facebook.Listing, "from_cache", lambda post_url: None)
    monkeypatch.setattr(facebook, "parse_listing", lambda *args: results.pop(0))
    monkeypatch.setattr(marketplace, "goto_url", visited.append)
    url = "https://www.facebook.com/marketplace/item/1/"
    item_config: Any = type("Item", (), {"name": "ipad"})()
    assert marketplace.get_listing_details(url, item_config) == (details, False)
    assert visited == [url, url]


@pytest.mark.parametrize("missing", ["FACEBOOK_USERNAME", "FACEBOOK_PASSWORD"])
def test_a_marketplace_without_credentials_is_rejected(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    from ai_marketplace_monitor.config import Config

    monkeypatch.delenv(missing)
    sections = {
        "marketplace": {"facebook": {"search_city": "houston"}},
        "item": {"ipad": {"search_phrases": "ipad"}},
        "user": {"me": {"email": "me@example.com"}},
    }
    with pytest.raises(ValueError, match="searches only while logged in"):
        Config.from_dicts({}, sections)
    # a disabled marketplace does not search, and a config being written may be incomplete
    disabled = {**sections, "marketplace": {"facebook": {"search_city": "x", "enabled": False}}}
    Config.from_dicts({}, disabled)
    Config.from_dicts({}, sections, partial=True)


def test_login_wait_time_is_deprecated(monkeypatch: pytest.MonkeyPatch) -> None:
    warnings: List[str] = []

    class Logger:
        def warning(self, message: str, **kwargs: Any) -> None:
            warnings.append(message)

        def debug(self, message: str) -> None:
            pass

    marketplace = _marketplace(FakePage(url=MARKETPLACE_URL))
    marketplace.config.login_wait_time = 120
    marketplace.logger = Logger()  # type: ignore[assignment]
    monkeypatch.setattr(marketplace, "create_page", lambda swap_proxy: marketplace.page)
    monkeypatch.setattr(marketplace, "goto_url", lambda url: None)
    monkeypatch.setattr(marketplace, "wait_for_login", lambda: None)
    monkeypatch.setattr(facebook.time, "sleep", lambda seconds: None)
    page: Any = marketplace.page
    page.wait_for_selector = lambda selector: None
    page.keyboard = type("Keyboard", (), {"press": lambda self, key: None})()
    page.get_by_role = lambda role, name: type("B", (), {"is_visible": lambda self: False})()
    marketplace.browser = object()  # type: ignore[assignment]
    marketplace.login()
    assert any("login_wait_time is deprecated and ignored" in w for w in warnings)


VALID_CONFIG = """
[marketplace.facebook]
username = "user@example.com"
password = "test-password"
search_city = "houston"

[item.ipad]
search_phrases = "ipad"

[user.me]
pushbullet_token = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
"""


def _stopped_monitor() -> MarketplaceMonitor:
    """A monitor with a scheduled job and a loaded config, as between two searches."""
    monitor = MarketplaceMonitor.__new__(MarketplaceMonitor)
    monitor.logger = None
    monitor.keyboard_monitor = None
    monitor.config_hash = "loaded"
    schedule.clear()
    schedule.every(10).minutes.do(lambda: None)
    return monitor


def test_web_ui_pause_stops_the_monitor_until_started() -> None:
    monitor = _stopped_monitor()
    control.pause()
    resumed: List[bool] = []

    def resume_soon() -> None:
        # stopped: no job is left, and the config is reloaded on restart
        resumed.append(not schedule.get_jobs() and monitor.config_hash is None)
        control.resume()

    threading.Timer(0.2, resume_soon).start()
    assert monitor.handle_pause() is True
    assert resumed == [True] and not control.is_paused()


def test_not_paused_keeps_the_monitor_running() -> None:
    monitor = _stopped_monitor()
    assert monitor.handle_pause() is False
    assert schedule.get_jobs() and monitor.config_hash == "loaded"
    schedule.clear()


class FakeKeyboard:
    def __init__(self, confirmed: bool) -> None:
        self.paused = True
        self.confirmed = confirmed

    def is_paused(self) -> bool:
        return self.paused

    def confirm(self) -> bool:
        self.paused = False
        return self.confirmed


def test_keyboard_pause_without_interactive_session_resumes() -> None:
    monitor = _stopped_monitor()
    monitor.keyboard_monitor = FakeKeyboard(confirmed=False)  # type: ignore[assignment]
    assert monitor.handle_pause() is False
    assert schedule.get_jobs() and monitor.config_hash == "loaded"  # resumes where it was
    schedule.clear()


def test_interactive_session_stops_and_restarts_the_monitor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = _stopped_monitor()
    monitor.keyboard_monitor = FakeKeyboard(confirmed=True)  # type: ignore[assignment]
    answers = iter(["https://www.facebook.com/marketplace/item/1", "exit"])
    jobs_during_session: List[int] = []
    checked: List[str] = []

    def check_items(items: List[str], for_item: Any = None) -> None:
        jobs_during_session.append(len(schedule.get_jobs()))
        checked.extend(items)
        monitor.config_hash = "loaded"  # checking an item loads the config

    monkeypatch.setattr(monitor_module.Prompt, "ask", lambda *a, **k: next(answers))
    monkeypatch.setattr(monitor, "check_items", check_items)
    assert monitor.handle_pause() is True
    assert checked == ["https://www.facebook.com/marketplace/item/1"]
    assert jobs_during_session == [0]  # stopped while checking
    assert not schedule.get_jobs() and monitor.config_hash is None


def _web_ui(cfg: Path) -> TestClient:
    from ai_marketplace_monitor.webui.config_api import ConfigFileService
    from ai_marketplace_monitor.webui.log_handler import LogBroadcastHandler
    from ai_marketplace_monitor.webui.server import AuthState, WebUIConfig, create_app

    handler = LogBroadcastHandler()
    return TestClient(
        create_app(
            WebUIConfig(config_files=[cfg], log_handler=handler),
            AuthState(),
            ConfigFileService([cfg]),
            handler,
        )
    )


def test_web_ui_pause_and_resume(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(VALID_CONFIG, encoding="utf-8")
    client = _web_ui(cfg)
    monitor = client.get("/api/status").json()["monitor"]
    assert monitor == {"paused": False, "waiting_for_login": False, "login_hint": ""}
    os.utime(cfg, (1, 1))
    assert client.post("/api/monitor/pause").json()["paused"] is True
    assert control.is_paused()
    assert cfg.stat().st_mtime > 1  # touched: a sleeping monitor wakes up and stops now
    assert client.get("/api/status").json()["monitor"]["paused"] is True
    assert client.post("/api/monitor/resume").json()["paused"] is False
    assert not control.is_paused()


def test_web_ui_does_not_start_with_an_invalid_config(tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(VALID_CONFIG, encoding="utf-8")
    client = _web_ui(cfg)
    assert client.post("/api/monitor/pause").json()["paused"] is True
    cfg.write_text(VALID_CONFIG + "\n[item.broken\n", encoding="utf-8")  # edited by hand
    res = client.post("/api/monitor/resume")
    assert res.status_code == 400
    data = res.json()
    assert data["ok"] is False and data["paused"] is True
    assert "configuration is invalid" in data["error"]
    assert control.is_paused()  # still stopped
    cfg.write_text(VALID_CONFIG, encoding="utf-8")
    assert client.post("/api/monitor/resume").json()["paused"] is False
