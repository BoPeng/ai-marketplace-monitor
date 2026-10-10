"""Tests for config_auth: credential extraction."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_marketplace_monitor.webui.config_auth import extract_credentials, local_credentials


@pytest.fixture(autouse=True)
def no_credentials_in_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests set the environment themselves where they need it."""
    monkeypatch.delenv("FACEBOOK_USERNAME", raising=False)
    monkeypatch.delenv("FACEBOOK_PASSWORD", raising=False)
    monkeypatch.delenv("AIMM_WEBUI_USERNAME", raising=False)
    monkeypatch.delenv("AIMM_WEBUI_PASSWORD", raising=False)
    monkeypatch.delenv("AIMM_WEBUI_AUTH", raising=False)


def _write(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(content, encoding="utf-8")
    return p


# ----------------------------------------------------------------------
# extract_credentials — config file
# ----------------------------------------------------------------------


def test_extract_returns_facebook_creds_when_both_set(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        '[marketplace.facebook]\nusername = "me@example.com"\npassword = "secret"\n',
    )
    got = extract_credentials([p])
    assert got.username == "me@example.com"
    assert got.password == "secret"


def test_extract_returns_none_when_username_missing(tmp_path: Path) -> None:
    p = _write(tmp_path, '[marketplace.facebook]\npassword = "secret"\n')
    got = extract_credentials([p])
    assert got.username is None
    assert got.password is None


def test_extract_returns_none_when_password_missing(tmp_path: Path) -> None:
    p = _write(tmp_path, '[marketplace.facebook]\nusername = "me@example.com"\n')
    got = extract_credentials([p])
    assert got.username is None
    assert got.password is None


def test_extract_returns_creds_from_any_marketplace(tmp_path: Path) -> None:
    """Any [marketplace.*] section with both fields should work."""
    p = _write(
        tmp_path,
        '[marketplace.other]\nusername = "x"\npassword = "y"\n',
    )
    got = extract_credentials([p])
    assert got.username == "x"
    assert got.password == "y"


def test_extract_tolerates_malformed_file(tmp_path: Path) -> None:
    p = _write(tmp_path, "not valid = = toml")
    got = extract_credentials([p])
    assert got.username is None
    assert got.password is None


def test_extract_empty_values_treated_as_unset(tmp_path: Path) -> None:
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


def test_extract_falls_back_to_env_vars(tmp_path: Path) -> None:
    """When config has no credentials, FACEBOOK_USERNAME/PASSWORD are used."""
    p = _write(tmp_path, "[marketplace.facebook]\n")
    with patch.dict(os.environ, {"FACEBOOK_USERNAME": "envuser", "FACEBOOK_PASSWORD": "envpass"}):
        got = extract_credentials([p])
    assert got.username == "envuser"
    assert got.password == "envpass"


def test_extract_config_takes_priority_over_env(tmp_path: Path) -> None:
    """Config credentials should win over environment variables."""
    p = _write(
        tmp_path,
        '[marketplace.facebook]\nusername = "cfguser"\npassword = "cfgpass"\n',
    )
    with patch.dict(os.environ, {"FACEBOOK_USERNAME": "envuser", "FACEBOOK_PASSWORD": "envpass"}):
        got = extract_credentials([p])
    assert got.username == "cfguser"
    assert got.password == "cfgpass"


def test_extract_env_vars_need_both(tmp_path: Path) -> None:
    """Only FACEBOOK_USERNAME without FACEBOOK_PASSWORD should not match."""
    p = _write(tmp_path, "")
    with patch.dict(os.environ, {"FACEBOOK_USERNAME": "envuser"}, clear=False):
        env = os.environ.copy()
        env.pop("FACEBOOK_PASSWORD", None)
        with patch.dict(os.environ, env, clear=True):
            got = extract_credentials([p])
    assert got.username is None
    assert got.password is None


def test_extract_no_config_no_env(tmp_path: Path) -> None:
    """No config, no env vars → None."""
    p = _write(tmp_path, "")
    with patch.dict(os.environ, {}, clear=True):
        got = extract_credentials([p])
    assert got.username is None
    assert got.password is None


# ----------------------------------------------------------------------
# extract_credentials — ${VAR} references in the config
# ----------------------------------------------------------------------


def test_extract_resolves_env_references(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Username = "${FACEBOOK_USERNAME}" is the variable's value, not the literal text."""
    p = _write(
        tmp_path,
        '[marketplace.facebook]\nusername = "${FB_USER}"\npassword = "${FB_PASS}"\n',
    )
    monkeypatch.setenv("FB_USER", "me@example.com")
    monkeypatch.setenv("FB_PASS", "secret")
    got = extract_credentials([p])
    assert got.username == "me@example.com"
    assert got.password == "secret"


def test_extract_unset_reference_falls_back_to_env_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unset ${VAR} is no value: never the literal text as the login."""
    p = _write(
        tmp_path,
        '[marketplace.facebook]\nusername = "${UNSET_USER}"\npassword = "${UNSET_PASS}"\n',
    )
    monkeypatch.delenv("UNSET_USER", raising=False)
    monkeypatch.delenv("UNSET_PASS", raising=False)
    assert extract_credentials([p]).username is None
    monkeypatch.setenv("FACEBOOK_USERNAME", "envuser")
    monkeypatch.setenv("FACEBOOK_PASSWORD", "envpass")
    got = extract_credentials([p])
    assert got.username == "envuser"
    assert got.password == "envpass"


def test_local_mode_uses_only_the_webui_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A web UI password of its own, e.g. one generated by an app platform."""
    monkeypatch.setenv("AIMM_WEBUI_PASSWORD", "generated-secret")
    creds = local_credentials()
    assert (creds.username, creds.password) == ("admin", "generated-secret")
    monkeypatch.setenv("AIMM_WEBUI_USERNAME", "umbrel")
    assert local_credentials().username == "umbrel"
    monkeypatch.setenv("AIMM_WEBUI_PASSWORD", "")
    with pytest.raises(ValueError, match="needs AIMM_WEBUI_PASSWORD"):
        local_credentials()


def test_facebook_mode_ignores_the_webui_password(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _write(
        tmp_path, '[marketplace.facebook]\nusername = "fb@example.com"\npassword = "fb-pw"\n'
    )
    monkeypatch.setenv("AIMM_WEBUI_PASSWORD", "generated-secret")
    assert extract_credentials([cfg]).username == "fb@example.com"


def test_local_mode_starts_without_marketplace_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The web UI starts before the Facebook credentials are set (a store install)."""
    from ai_marketplace_monitor.webui.log_handler import LogBroadcastHandler
    from ai_marketplace_monitor.webui.server import WebUIConfig, WebUIServer, start_webui

    cfg = _write(
        tmp_path, '[marketplace.facebook]\nusername = "fb@example.com"\npassword = "fb-pw"\n'
    )
    monkeypatch.setattr(WebUIServer, "start", lambda self: None)
    monkeypatch.setenv("AIMM_WEBUI_AUTH", "local")
    config = WebUIConfig(
        host="0.0.0.0", config_files=[cfg], log_handler=LogBroadcastHandler()  # noqa: S104
    )
    # local mode never falls back to the marketplace login
    with pytest.raises(RuntimeError, match="AIMM_WEBUI_AUTH=local needs AIMM_WEBUI_PASSWORD"):
        start_webui(config)
    # nor starts without its password on loopback, where the web UI is open
    loopback = WebUIConfig(host="127.0.0.1", config_files=[cfg], log_handler=config.log_handler)
    with pytest.raises(RuntimeError, match="AIMM_WEBUI_AUTH=local needs AIMM_WEBUI_PASSWORD"):
        start_webui(loopback)
    monkeypatch.setenv("AIMM_WEBUI_PASSWORD", "generated-secret")
    _, info = start_webui(config)
    assert info.username == "admin"
