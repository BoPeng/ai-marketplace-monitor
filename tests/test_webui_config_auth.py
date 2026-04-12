"""Tests for config_auth: credential extraction and TOML line editing."""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_marketplace_monitor.webui.config_auth import (
    extract_credentials,
    set_value_in_section,
)


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(content, encoding="utf-8")
    return p


# ----------------------------------------------------------------------
# extract_credentials
# ----------------------------------------------------------------------


def test_extract_returns_facebook_creds_when_both_set(tmp_path: Path):
    p = _write(
        tmp_path,
        '[marketplace.facebook]\nusername = "me@example.com"\npassword = "secret"\n',
    )
    got = extract_credentials([p])
    assert got.username == "me@example.com"
    assert got.password == "secret"


def test_extract_returns_none_when_username_missing(tmp_path: Path):
    p = _write(tmp_path, '[marketplace.facebook]\npassword = "secret"\n')
    got = extract_credentials([p])
    assert got.username is None
    assert got.password is None


def test_extract_returns_none_when_password_missing(tmp_path: Path):
    p = _write(tmp_path, '[marketplace.facebook]\nusername = "me@example.com"\n')
    got = extract_credentials([p])
    assert got.username is None
    assert got.password is None


def test_extract_returns_none_when_section_missing(tmp_path: Path):
    p = _write(tmp_path, '[marketplace.other]\nusername = "x"\npassword = "y"\n')
    got = extract_credentials([p])
    # Only marketplace.facebook is consulted.
    assert got.username is None
    assert got.password is None


def test_extract_tolerates_malformed_file(tmp_path: Path):
    p = _write(tmp_path, "not valid = = toml")
    got = extract_credentials([p])
    assert got.username is None
    assert got.password is None


def test_extract_empty_values_treated_as_unset(tmp_path: Path):
    p = _write(
        tmp_path,
        '[marketplace.facebook]\nusername = ""\npassword = ""\n',
    )
    got = extract_credentials([p])
    assert got.username is None
    assert got.password is None


# ----------------------------------------------------------------------
# set_value_in_section
# ----------------------------------------------------------------------


def test_set_value_inserts_when_key_absent():
    content = '[marketplace.facebook]\nsearch_city = "houston"\n'
    new, modified = set_value_in_section(
        content, "marketplace.facebook", "username", "me@x.com"
    )
    assert modified
    assert 'username = "me@x.com"' in new
    assert 'search_city = "houston"' in new


def test_set_value_replaces_existing_assignment():
    content = '[marketplace.facebook]\nusername = "old@x.com"\n'
    new, modified = set_value_in_section(
        content, "marketplace.facebook", "username", "new@x.com"
    )
    assert modified
    assert 'username = "new@x.com"' in new
    assert "old@x.com" not in new


def test_set_value_replaces_commented_assignment():
    content = '[marketplace.facebook]\n# username = "you@example.com"\n'
    new, modified = set_value_in_section(
        content, "marketplace.facebook", "username", "real@x.com"
    )
    assert modified
    assert 'username = "real@x.com"' in new
    # The commented template line gets replaced (not left alongside).
    assert "# username" not in new


def test_set_value_appends_section_when_missing():
    content = '[item.foo]\nsearch_phrases = "x"\n'
    new, modified = set_value_in_section(
        content, "marketplace.facebook", "username", "me@x.com"
    )
    assert modified
    assert "[marketplace.facebook]" in new
    assert 'username = "me@x.com"' in new


def test_set_value_stops_at_section_boundary():
    """Inserting into a section should not spill into the next one."""
    content = (
        '[marketplace.facebook]\n'
        'search_city = "houston"\n'
        '[item.foo]\n'
        'search_phrases = "x"\n'
    )
    new, _ = set_value_in_section(
        content, "marketplace.facebook", "username", "me@x.com"
    )
    # The new line should appear before [item.foo].
    fb_idx = new.index("[marketplace.facebook]")
    user_idx = new.index('username = "me@x.com"')
    item_idx = new.index("[item.foo]")
    assert fb_idx < user_idx < item_idx
