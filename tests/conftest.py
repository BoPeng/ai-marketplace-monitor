"""Fixtures for all tests."""

from pathlib import Path

import pytest

from ai_marketplace_monitor import shared_browser
from ai_marketplace_monitor.marketplaces.facebook import marketplace as facebook
from ai_marketplace_monitor.utils import CacheType, cache


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


@pytest.fixture(autouse=True)
def forget_offerup_searches() -> None:
    """Each test may run an OfferUp search, however recently another test ran it."""
    cache.evict(CacheType.OFFERUP_SEARCHES.value)
