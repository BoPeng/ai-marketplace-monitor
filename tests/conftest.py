"""Fixtures for all tests."""

from pathlib import Path

import pytest

from ai_marketplace_monitor import shared_browser
from ai_marketplace_monitor.marketplaces.facebook import marketplace as facebook


@pytest.fixture(autouse=True)
def facebook_session_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tests never read or overwrite the user's saved Facebook session."""
    path = tmp_path / "facebook-session.json"
    monkeypatch.setattr(facebook, "SESSION_FILE", path)
    return path


@pytest.fixture(autouse=True)
def browser_endpoint_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tests never read or replace the endpoint of the user's running monitor."""
    path = tmp_path / "browser-endpoint.json"
    monkeypatch.setattr(shared_browser, "ENDPOINT_FILE", path)
    monkeypatch.setattr(shared_browser, "_endpoint", None)
    return path
