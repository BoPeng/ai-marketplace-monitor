"""Tests for auth helpers: password hashing, sessions, rate limiting."""

from __future__ import annotations

from pathlib import Path

from ai_marketplace_monitor.webui.auth import (
    RateLimiter,
    SessionManager,
    generate_password,
    hash_password,
    read_password_file,
    verify_password,
    write_password_file,
)


def test_password_roundtrip() -> None:
    pw = generate_password()
    h = hash_password(pw)
    assert verify_password(pw, h)
    assert not verify_password("wrong", h)


def test_verify_password_rejects_garbage_hash() -> None:
    assert not verify_password("whatever", "not-a-hash")


def test_password_file_roundtrip(tmp_path: Path) -> None:
    f = tmp_path / "pw"
    h = hash_password("hello")
    write_password_file(f, h)
    assert read_password_file(f) == h
    assert read_password_file(tmp_path / "missing") is None


def test_session_issue_and_validate() -> None:
    sm = SessionManager("secret-key")
    token, csrf = sm.issue("admin")
    assert sm.validate(token) == "admin"
    assert csrf != ""
    # Different secret → validation fails.
    assert SessionManager("other").validate(token) is None


def test_session_rejects_tampered_token() -> None:
    sm = SessionManager("secret-key")
    token, _ = sm.issue("admin")
    assert sm.validate(token + "x") is None


def test_rate_limiter_locks_after_threshold() -> None:
    rl = RateLimiter()
    for _ in range(5):
        rl.record_failure("1.2.3.4")
    assert rl.is_locked("1.2.3.4")
    assert not rl.is_locked("5.6.7.8")


def test_rate_limiter_reset_on_success() -> None:
    rl = RateLimiter()
    for _ in range(4):
        rl.record_failure("1.2.3.4")
    rl.reset("1.2.3.4")
    assert not rl.is_locked("1.2.3.4")


def test_generate_password_structure() -> None:
    pw = generate_password()
    assert "-" in pw
    assert len(pw.replace("-", "")) == 20
