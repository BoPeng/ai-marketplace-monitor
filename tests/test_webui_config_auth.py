"""Tests for config_auth: credential extraction."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_marketplace_monitor.webui.config_auth import extract_credentials


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(content, encoding="utf-8")
    return p


# ----------------------------------------------------------------------
# extract_credentials — config file
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


def test_extract_returns_creds_from_any_marketplace(tmp_path: Path):
    """Any [marketplace.*] section with both fields should work."""
    p = _write(
        tmp_path,
        '[marketplace.other]\nusername = "x"\npassword = "y"\n',
    )
    got = extract_credentials([p])
    assert got.username == "x"
    assert got.password == "y"


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
# extract_credentials — environment variable fallback
# ----------------------------------------------------------------------


def test_extract_falls_back_to_env_vars(tmp_path: Path):
    """When config has no credentials, FACEBOOK_USERNAME/PASSWORD are used."""
    p = _write(tmp_path, "[marketplace.facebook]\n")
    with patch.dict(os.environ, {"FACEBOOK_USERNAME": "envuser", "FACEBOOK_PASSWORD": "envpass"}):
        got = extract_credentials([p])
    assert got.username == "envuser"
    assert got.password == "envpass"


def test_extract_config_takes_priority_over_env(tmp_path: Path):
    """Config credentials should win over environment variables."""
    p = _write(
        tmp_path,
        '[marketplace.facebook]\nusername = "cfguser"\npassword = "cfgpass"\n',
    )
    with patch.dict(os.environ, {"FACEBOOK_USERNAME": "envuser", "FACEBOOK_PASSWORD": "envpass"}):
        got = extract_credentials([p])
    assert got.username == "cfguser"
    assert got.password == "cfgpass"


def test_extract_env_vars_need_both(tmp_path: Path):
    """Only FACEBOOK_USERNAME without FACEBOOK_PASSWORD should not match."""
    p = _write(tmp_path, "")
    with patch.dict(os.environ, {"FACEBOOK_USERNAME": "envuser"}, clear=False):
        env = os.environ.copy()
        env.pop("FACEBOOK_PASSWORD", None)
        with patch.dict(os.environ, env, clear=True):
            got = extract_credentials([p])
    assert got.username is None
    assert got.password is None


def test_extract_no_config_no_env(tmp_path: Path):
    """No config, no env vars → None."""
    p = _write(tmp_path, "")
    with patch.dict(os.environ, {}, clear=True):
        got = extract_credentials([p])
    assert got.username is None
    assert got.password is None
