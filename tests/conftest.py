"""Fixtures for all tests."""

from pathlib import Path

import pytest

from ai_marketplace_monitor import facebook


@pytest.fixture(autouse=True)
def facebook_session_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tests never read or overwrite the user's saved Facebook session."""
    path = tmp_path / "facebook-session.json"
    monkeypatch.setattr(facebook, "SESSION_FILE", path)
    return path
