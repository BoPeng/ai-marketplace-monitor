"""Tests for persisting the logged-in browser session across restarts.

Without this, every process restart launches a fresh (unauthenticated)
browser context, forcing a brand new Facebook login -- which triggers a
new "approve this login" prompt on the account owner's device every
single time. Persisting Playwright's storage_state to disk lets a
restarted process resume the previous session instead.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import ai_marketplace_monitor.facebook as facebook_module
import ai_marketplace_monitor.marketplace as marketplace_module
from ai_marketplace_monitor.facebook import FacebookMarketplace
from ai_marketplace_monitor.marketplace import Marketplace


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


def test_login_saves_storage_state_after_completing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "browser_state.json"
    monkeypatch.setattr(marketplace_module, "browser_state_file", state_file)
    monkeypatch.setattr(facebook_module, "browser_state_file", state_file)

    marketplace = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=MagicMock())
    marketplace.config = MagicMock(
        username="user@example.com", password="hunter2", login_wait_time=0
    )

    marketplace.login()

    marketplace.page.context.storage_state.assert_called_once_with(path=state_file)
