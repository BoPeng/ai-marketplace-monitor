"""Tests for persisting the logged-in browser session across restarts.

Without this, every process restart launches a fresh (unauthenticated)
browser context, forcing a brand new Facebook login -- which triggers a
new "approve this login" prompt on the account owner's device every
single time. Persisting Playwright's storage_state to disk lets a
restarted process resume the previous session instead.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from playwright.sync_api import BrowserContext

import ai_marketplace_monitor.facebook as facebook_module
import ai_marketplace_monitor.marketplace as marketplace_module
import ai_marketplace_monitor.monitor as monitor_module
from ai_marketplace_monitor.facebook import FacebookMarketplace
from ai_marketplace_monitor.marketplace import Marketplace
from ai_marketplace_monitor.monitor import MarketplaceMonitor


def _mock_context_with_cookies(logged_in: bool) -> MagicMock:
    context = MagicMock()
    context.cookies.return_value = (
        [{"name": "c_user", "value": "12345"}] if logged_in else [{"name": "datr", "value": "x"}]
    )
    return context


def test_create_page_passes_storage_state_when_file_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "browser_state.json"
    state_file.write_text("{}")
    monkeypatch.setattr(marketplace_module, "browser_state_file", state_file)

    mock_browser = MagicMock()
    mp = Marketplace(name="facebook", browser=mock_browser)
    mp.config = MagicMock(monitor_config=None)

    mp.create_page()

    _, kwargs = mock_browser.new_context.call_args
    assert kwargs["storage_state"] == str(state_file)


def test_create_page_passes_no_storage_state_when_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(marketplace_module, "browser_state_file", state_file)

    mock_browser = MagicMock()
    mp = Marketplace(name="facebook", browser=mock_browser)
    mp.config = MagicMock(monitor_config=None)

    mp.create_page()

    _, kwargs = mock_browser.new_context.call_args
    assert kwargs["storage_state"] is None


def test_create_page_recovers_from_corrupted_storage_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malformed/incompatible saved session shouldn't crash the monitor."""
    state_file = tmp_path / "browser_state.json"
    state_file.write_text("not valid json")
    monkeypatch.setattr(marketplace_module, "browser_state_file", state_file)

    mock_browser = MagicMock()
    good_context = MagicMock()
    good_context.pages = []
    # first call (with storage_state) fails, second call (fallback) succeeds
    mock_browser.new_context.side_effect = [Exception("invalid storage_state"), good_context]

    mp = Marketplace(name="facebook", browser=mock_browser, logger=MagicMock())
    mp.config = MagicMock(monitor_config=None)

    page = mp.create_page()

    assert page is good_context.new_page.return_value
    assert mock_browser.new_context.call_count == 2
    first_kwargs = mock_browser.new_context.call_args_list[0].kwargs
    second_kwargs = mock_browser.new_context.call_args_list[1].kwargs
    assert first_kwargs["storage_state"] == str(state_file)
    assert second_kwargs["storage_state"] is None
    # proxy config should be preserved across both attempts
    assert first_kwargs["proxy"] == second_kwargs["proxy"]
    # the bad file should be quarantined, not left in place to fail again
    assert not state_file.exists()
    assert state_file.with_suffix(".json.invalid").exists()


def test_create_page_recovers_when_quarantine_file_already_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A leftover .invalid file shouldn't block quarantining a new one.

    .rename() raises FileExistsError on Windows when the destination
    already exists, which would leave the active (still-bad) state file
    in place to keep failing every restart; .replace() overwrites
    unconditionally on every platform.
    """
    state_file = tmp_path / "browser_state.json"
    state_file.write_text("not valid json")
    (tmp_path / "browser_state.json.invalid").write_text("older quarantine")
    monkeypatch.setattr(marketplace_module, "browser_state_file", state_file)

    mock_browser = MagicMock()
    good_context = MagicMock()
    good_context.pages = []
    mock_browser.new_context.side_effect = [Exception("invalid storage_state"), good_context]

    mp = Marketplace(name="facebook", browser=mock_browser, logger=MagicMock())
    mp.config = MagicMock(monitor_config=None)

    page = mp.create_page()

    assert page is good_context.new_page.return_value
    assert not state_file.exists()
    assert (tmp_path / "browser_state.json.invalid").read_text() == "not valid json"


def test_login_saves_storage_state_when_logged_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The early-return (already-authenticated) path must still persist.

    Regression test: an earlier version returned before ever reaching the
    save logic when already authenticated, so a persistent profile's
    storage_state fallback (used e.g. for multi-proxy rotation) would
    never get created or refreshed. Asserting goto was never called proves
    this exercises that early-return branch specifically, not the full
    login flow.
    """
    state_file = tmp_path / "browser_state.json"
    monkeypatch.setattr(marketplace_module, "browser_state_file", state_file)
    monkeypatch.setattr(facebook_module, "browser_state_file", state_file)

    marketplace = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=MagicMock())
    marketplace.config = MagicMock(
        username="user@example.com", password="hunter2", login_wait_time=0
    )
    marketplace.page = MagicMock(context=_mock_context_with_cookies(logged_in=True))
    marketplace.create_page = MagicMock(return_value=marketplace.page)  # type: ignore[method-assign]

    marketplace.login()

    marketplace.page.goto.assert_not_called()
    marketplace.page.context.storage_state.assert_called_once_with(path=state_file)


@pytest.mark.skipif(
    sys.platform.startswith("win"), reason="POSIX file modes don't apply on Windows"
)
def test_login_saves_storage_state_with_restricted_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "browser_state.json"
    monkeypatch.setattr(marketplace_module, "browser_state_file", state_file)
    monkeypatch.setattr(facebook_module, "browser_state_file", state_file)

    marketplace = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=MagicMock())
    marketplace.config = MagicMock(
        username="user@example.com", password="hunter2", login_wait_time=0
    )
    marketplace.page = MagicMock(context=_mock_context_with_cookies(logged_in=True))
    marketplace.create_page = MagicMock(return_value=marketplace.page)  # type: ignore[method-assign]

    # storage_state() is mocked and won't actually write the file, so create
    # it ourselves to let the chmod call under test run against a real path
    def _fake_storage_state(path: Path) -> None:
        Path(path).write_text("{}")

    marketplace.page.context.storage_state.side_effect = _fake_storage_state

    marketplace.login()

    assert (state_file.stat().st_mode & 0o777) == 0o600


def test_login_skips_navigation_when_already_authenticated() -> None:
    """Skip re-authenticating an already-valid session.

    A valid session (persistent profile or resumed storage_state) should
    skip navigating to the login page and re-submitting credentials --
    Facebook treats that explicit login-form submission as a real login
    event and alerts the account owner, even when nothing needed to change.
    """
    marketplace = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=MagicMock())
    marketplace.config = MagicMock(
        username="user@example.com", password="hunter2", login_wait_time=0
    )
    mock_page = MagicMock(context=_mock_context_with_cookies(logged_in=True))
    marketplace.create_page = MagicMock(return_value=mock_page)  # type: ignore[method-assign]

    marketplace.login()

    mock_page.goto.assert_not_called()
    mock_page.wait_for_selector.assert_not_called()
    mock_page.keyboard.press.assert_not_called()


def test_login_skips_save_when_not_logged_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "browser_state.json"
    monkeypatch.setattr(marketplace_module, "browser_state_file", state_file)
    monkeypatch.setattr(facebook_module, "browser_state_file", state_file)

    marketplace = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=MagicMock())
    marketplace.config = MagicMock(
        username="user@example.com", password="hunter2", login_wait_time=0
    )
    marketplace.page = MagicMock(context=_mock_context_with_cookies(logged_in=False))
    marketplace.create_page = MagicMock(return_value=marketplace.page)  # type: ignore[method-assign]

    marketplace.login()

    marketplace.page.context.storage_state.assert_not_called()
    assert not state_file.exists()


# --- Persistent browser profile (stronger than storage_state alone) ---


def _mock_marketplace_config(proxy_server: list | None = None) -> MagicMock:
    monitor_config = MagicMock(proxy_server=proxy_server)
    monitor_config.get_proxy_options.return_value = (
        {"server": proxy_server[0]} if proxy_server else None
    )
    return MagicMock(monitor_config=monitor_config)


def _monitor_with_config(config: MagicMock) -> MarketplaceMonitor:
    # bypass __init__ (which starts a real Playwright driver process) --
    # these methods only touch self.config/.headless/.playwright/.logger
    m = MarketplaceMonitor.__new__(MarketplaceMonitor)
    m.config = config
    m.headless = True
    m.logger = None
    return m


def test_create_page_uses_persistent_context_directly(tmp_path: Path) -> None:
    mock_context = MagicMock(spec=BrowserContext)
    mock_context.pages = []

    mp = Marketplace(name="facebook", browser=mock_context)
    mp.config = MagicMock(monitor_config=None)

    page = mp.create_page()

    assert page is mock_context.new_page.return_value
    mock_context.new_context.assert_not_called()


def test_create_page_reuses_existing_page_on_persistent_context() -> None:
    existing_page = MagicMock()
    mock_context = MagicMock(spec=BrowserContext)
    mock_context.pages = [existing_page]

    mp = Marketplace(name="facebook", browser=mock_context)
    mp.config = MagicMock(monitor_config=None)

    page = mp.create_page()

    assert page is existing_page
    mock_context.new_page.assert_not_called()


def test_uses_multi_proxy_rotation_true_when_any_marketplace_rotates() -> None:
    config = MagicMock()
    config.marketplace = {
        "facebook": _mock_marketplace_config(proxy_server=["http://a", "http://b"]),
    }
    m = _monitor_with_config(config)
    assert m._uses_multi_proxy_rotation() is True


def test_uses_multi_proxy_rotation_false_for_none_or_single_proxy() -> None:
    config = MagicMock()
    config.marketplace = {
        "facebook": _mock_marketplace_config(proxy_server=None),
        "other": _mock_marketplace_config(proxy_server=["http://a"]),
    }
    m = _monitor_with_config(config)
    assert m._uses_multi_proxy_rotation() is False


def test_launch_browser_uses_persistent_profile_when_no_rotation_needed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_dir = tmp_path / "profile"
    monkeypatch.setattr(monitor_module, "browser_profile_dir", profile_dir)

    config = MagicMock()
    config.marketplace = {"facebook": _mock_marketplace_config(proxy_server=None)}
    m = _monitor_with_config(config)

    mock_context = MagicMock()
    mock_chromium = MagicMock()
    mock_chromium.launch_persistent_context.return_value = mock_context
    m.playwright = MagicMock(chromium=mock_chromium)

    result = m._launch_browser()

    assert result is mock_context
    mock_chromium.launch.assert_not_called()
    mock_chromium.launch_persistent_context.assert_called_once()
    assert mock_chromium.launch_persistent_context.call_args.kwargs["user_data_dir"] == str(
        profile_dir
    )


def test_launch_browser_falls_back_to_classic_launch_for_non_chromium(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Firefox/WebKit fall back to a regular (non-persistent) launch.

    browser_profile_dir is a Chromium user-data directory and isn't
    meaningful for other engines.
    """
    profile_dir = tmp_path / "profile"
    monkeypatch.setattr(monitor_module, "browser_profile_dir", profile_dir)

    config = MagicMock()
    config.marketplace = {"facebook": _mock_marketplace_config(proxy_server=None)}
    m = _monitor_with_config(config)

    mock_chromium = MagicMock()
    mock_chromium.launch_persistent_context.side_effect = Exception("chromium not installed")

    mock_firefox_browser = MagicMock()
    mock_firefox = MagicMock()
    mock_firefox.launch.return_value = mock_firefox_browser

    m.playwright = MagicMock(chromium=mock_chromium, firefox=mock_firefox)

    result = m._launch_browser()

    assert result is mock_firefox_browser
    mock_chromium.launch_persistent_context.assert_called_once()
    mock_chromium.launch.assert_not_called()
    mock_firefox.launch.assert_called_once()
    mock_firefox.launch_persistent_context.assert_not_called()


def test_launch_browser_uses_classic_browser_when_rotation_needed() -> None:
    config = MagicMock()
    config.marketplace = {
        "facebook": _mock_marketplace_config(proxy_server=["http://a", "http://b"]),
    }
    m = _monitor_with_config(config)

    mock_browser = MagicMock()
    mock_chromium = MagicMock()
    mock_chromium.launch.return_value = mock_browser
    m.playwright = MagicMock(chromium=mock_chromium)

    result = m._launch_browser()

    assert result is mock_browser
    mock_chromium.launch_persistent_context.assert_not_called()
    mock_chromium.launch.assert_called_once()
