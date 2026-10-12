"""Saving the Facebook session, so that a restart does not log in again."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Dict, List

import pytest

from ai_marketplace_monitor import facebook
from ai_marketplace_monitor.facebook import FacebookMarketplace, FacebookMarketplaceConfig

STATE = {"cookies": [{"name": "c_user", "value": "1"}], "origins": []}
HOME = "https://www.facebook.com/"
LOGIN = "https://www.facebook.com/login/?next=https%3A%2F%2Fwww.facebook.com%2F"


class FakeContext:
    def __init__(self, cookies: List[str]) -> None:
        self.cookie_names = cookies

    def cookies(self, url: str | None = None) -> List[Dict[str, str]]:
        return [{"name": name, "value": "1"} for name in self.cookie_names]

    def storage_state(self) -> Dict[str, Any]:
        return {"cookies": self.cookies(), "origins": []}


class FakePage:
    def __init__(self, cookies: List[str], url: str = "about:blank") -> None:
        self.context = FakeContext(cookies)
        self.url = url
        self.login_form = False

    def query_selector(self, selector: str) -> object | None:
        return object() if self.login_form and selector == 'input[name="pass"]' else None


class FakeBrowser:
    """Creates contexts; fails on a saved state if ``bad_state``, on any if ``broken``."""

    def __init__(self, bad_state: bool = False, broken: bool = False) -> None:
        self.bad_state = bad_state
        self.broken = broken
        self.states: List[Any] = []

    def new_context(self, proxy: Any = None, storage_state: Any = None) -> Any:
        self.states.append(storage_state)
        if self.broken:
            raise RuntimeError("browser has been closed")
        if storage_state is not None and self.bad_state:
            raise ValueError("invalid storage state")
        browser = self

        class Context:
            def new_page(self) -> str:
                return f"page {len(browser.states)}"

        return Context()


def _marketplace(username: str = "user@example.com") -> FacebookMarketplace:
    marketplace = FacebookMarketplace("facebook", None)
    marketplace.config = FacebookMarketplaceConfig(
        name="facebook", username=username, password="test-password"
    )
    return marketplace


def _save(path: Path, username: str = "user@example.com", state: Any = STATE) -> None:
    path.write_text(json.dumps({"username": username, "storage_state": state}))


def test_the_session_is_saved_for_the_account_and_only_the_user_can_read_it(
    facebook_session_file: Path,
) -> None:
    marketplace = _marketplace()
    marketplace.page = FakePage(["c_user", "xs"])  # type: ignore[assignment]
    marketplace.save_session()
    saved = json.loads(facebook_session_file.read_text())
    assert saved["username"] == "user@example.com"
    assert [c["name"] for c in saved["storage_state"]["cookies"]] == ["c_user", "xs"]
    if os.name == "posix":
        assert stat.S_IMODE(facebook_session_file.stat().st_mode) == 0o600
    assert marketplace.saved_session() == saved["storage_state"]
    assert _marketplace("another@example.com").saved_session() is None


def test_a_session_that_cannot_be_read_is_removed(facebook_session_file: Path) -> None:
    facebook_session_file.write_text("{not json")
    assert _marketplace().saved_session() is None
    assert not facebook_session_file.exists()
    assert _marketplace().saved_session() is None  # no saved session at all


def test_the_saved_session_is_loaded_into_the_browser(facebook_session_file: Path) -> None:
    _save(facebook_session_file)
    marketplace = _marketplace()
    browser = FakeBrowser()
    marketplace.browser = browser  # type: ignore[assignment]
    marketplace.create_page()
    assert browser.states == [STATE]


def test_a_session_the_browser_rejects_is_discarded(facebook_session_file: Path) -> None:
    _save(facebook_session_file)
    marketplace = _marketplace()
    browser = FakeBrowser(bad_state=True)
    marketplace.browser = browser  # type: ignore[assignment]
    assert marketplace.create_page() == "page 2"  # type: ignore[comparison-overlap]
    assert browser.states == [STATE, None]
    assert not facebook_session_file.exists()


def test_a_browser_failure_keeps_the_saved_session(facebook_session_file: Path) -> None:
    _save(facebook_session_file)
    marketplace = _marketplace()
    browser = FakeBrowser(broken=True)
    marketplace.browser = browser  # type: ignore[assignment]
    with pytest.raises(RuntimeError):
        marketplace.create_page()
    assert browser.states == [STATE, None]
    assert facebook_session_file.exists()


def test_saving_leaves_no_temporary_file(
    facebook_session_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marketplace = _marketplace()
    marketplace.page = FakePage(["c_user"])  # type: ignore[assignment]
    marketplace.save_session()
    assert [p.name for p in facebook_session_file.parent.iterdir()] == [facebook_session_file.name]

    def fail(*args: Any, **kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(facebook.json, "dump", fail)
    marketplace.save_session()  # logs the failure
    assert [p.name for p in facebook_session_file.parent.iterdir()] == [facebook_session_file.name]
    assert json.loads(facebook_session_file.read_text())["storage_state"]["cookies"]


def _login(
    monkeypatch: pytest.MonkeyPatch, page: FakePage, logged_in_at_home: bool
) -> Dict[str, List[str]]:
    """Log in on ``page``: the pages visited, whether the login form was used, the saves."""
    marketplace = _marketplace()
    marketplace.browser = object()  # type: ignore[assignment]
    calls: Dict[str, List[str]] = {"visited": [], "form": [], "saved": []}

    def goto_url(url: str) -> None:
        calls["visited"].append(url)
        if url == marketplace.home_url and not logged_in_at_home:
            page.url = LOGIN
            page.context.cookie_names = []  # Facebook ends the session

    class Button:
        def is_visible(self) -> bool:
            return False

    monkeypatch.setattr(marketplace, "create_page", lambda swap_proxy: page)
    monkeypatch.setattr(marketplace, "goto_url", goto_url)
    monkeypatch.setattr(marketplace, "save_session", lambda: calls["saved"].append("saved"))
    monkeypatch.setattr(marketplace, "wait_for_login", lambda: calls["form"].append("used"))
    monkeypatch.setattr(facebook.time, "sleep", lambda seconds: None)
    page.get_by_role = lambda *a, **k: Button()  # type: ignore[attr-defined]
    page.wait_for_selector = lambda selector: None  # type: ignore[attr-defined]
    page.keyboard = type("Keyboard", (), {"press": lambda self, key: None})()  # type: ignore[attr-defined]
    marketplace.login()
    return calls


def test_a_saved_session_that_still_works_skips_the_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = FakePage(["c_user"])
    calls = _login(monkeypatch, page, logged_in_at_home=True)
    assert calls == {"visited": [HOME], "form": [], "saved": ["saved"]}


def test_a_session_facebook_has_ended_logs_in_again(monkeypatch: pytest.MonkeyPatch) -> None:
    page = FakePage(["c_user"])
    calls = _login(monkeypatch, page, logged_in_at_home=False)
    assert calls == {
        "visited": [HOME, FacebookMarketplace.initial_url],
        "form": ["used"],
        "saved": ["saved"],
    }


def test_a_login_form_on_the_home_page_is_not_a_login(monkeypatch: pytest.MonkeyPatch) -> None:
    page = FakePage(["c_user"])
    page.login_form = True
    calls = _login(monkeypatch, page, logged_in_at_home=True)
    assert calls["form"] == ["used"]


def test_without_a_saved_session_aimm_logs_in(monkeypatch: pytest.MonkeyPatch) -> None:
    page = FakePage([])
    calls = _login(monkeypatch, page, logged_in_at_home=True)
    assert calls["visited"] == [FacebookMarketplace.initial_url]
    assert calls["form"] == ["used"]


def test_the_session_is_saved_after_the_login(monkeypatch: pytest.MonkeyPatch) -> None:
    marketplace = _marketplace()
    marketplace.page = FakePage(["c_user"], url=LOGIN)  # type: ignore[assignment]
    saved: List[bool] = []
    monkeypatch.setattr(marketplace, "wait_for_login", lambda: None)
    monkeypatch.setattr(marketplace, "save_session", lambda: saved.append(True))
    assert marketplace.recover_login() is True
    assert saved == [True]
