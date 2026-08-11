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

import ai_marketplace_monitor.facebook as facebook_module
import ai_marketplace_monitor.marketplace as marketplace_module
from ai_marketplace_monitor.facebook import FacebookMarketplace
from ai_marketplace_monitor.marketplace import Marketplace


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


def test_login_saves_storage_state_when_logged_in(
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

    marketplace.login()

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
