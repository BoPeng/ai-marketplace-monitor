"""Tests for secret redaction / restoration in config content."""

from __future__ import annotations

from ai_marketplace_monitor.webui.secrets_redact import (
    MASK,
    has_mask,
    redact,
    restore,
)


def test_redact_replaces_password_and_token():
    src = """
[marketplace.facebook]
username = "ben@example.com"
password = "s3cret-pass"

[user.me]
pushbullet_token = "abc123token"
"""
    redacted, secrets = redact(src)
    assert f'"{MASK}"' in redacted
    assert "ben@example.com" not in redacted
    assert "s3cret-pass" not in redacted
    assert "abc123token" not in redacted
    assert secrets[("marketplace.facebook", "username")] == "ben@example.com"
    assert secrets[("marketplace.facebook", "password")] == "s3cret-pass"
    assert secrets[("user.me", "pushbullet_token")] == "abc123token"


def test_redact_leaves_non_sensitive_keys_alone():
    src = """
[marketplace.facebook]
search_city = "houston"
search_phrases = "gopro hero"
"""
    redacted, secrets = redact(src)
    assert redacted == src
    assert secrets == {}


def test_restore_round_trips_unchanged_masks():
    src = """
[marketplace.facebook]
password = "real-password"
"""
    redacted, secrets = redact(src)
    assert restore(redacted, secrets) == src


def test_restore_leaves_user_edits_alone():
    src = """
[marketplace.facebook]
password = "old-password"
"""
    redacted, secrets = redact(src)
    # User types a new value over the mask.
    edited = redacted.replace(f'"{MASK}"', '"new-password"')
    restored = restore(edited, secrets)
    assert "new-password" in restored
    assert "old-password" not in restored


def test_same_key_in_different_sections_no_collision():
    src = """
[user.alice]
pushbullet_token = "alice-token"

[user.bob]
pushbullet_token = "bob-token"
"""
    redacted, secrets = redact(src)
    assert secrets[("user.alice", "pushbullet_token")] == "alice-token"
    assert secrets[("user.bob", "pushbullet_token")] == "bob-token"
    restored = restore(redacted, secrets)
    assert "alice-token" in restored
    assert "bob-token" in restored


def test_redact_idempotent():
    src = '[x]\npassword = "foo"\n'
    once, secrets1 = redact(src)
    twice, _ = redact(once)
    assert once == twice
    # Second redact on already-masked content finds no new secrets.
    # But the original secret must still be available for restore.
    assert secrets1[("x", "password")] == "foo"


def test_empty_value_not_redacted():
    src = '[x]\npassword = ""\n'
    redacted, secrets = redact(src)
    assert redacted == src
    assert secrets == {}


def test_has_mask():
    assert has_mask(f'password = "{MASK}"')
    assert not has_mask('password = "real"')


def test_preserves_trailing_comment():
    src = '[x]\napi_key = "sk-abc"  # my key\n'
    redacted, secrets = redact(src)
    assert "# my key" in redacted
    assert "sk-abc" not in redacted
    assert restore(redacted, secrets) == src


def test_single_quoted_string_redacted():
    src = "[x]\npassword = 'quoted'\n"
    redacted, secrets = redact(src)
    assert "quoted" not in redacted
    assert MASK in redacted
    assert secrets[("x", "password")] == "quoted"
    assert restore(redacted, secrets) == src
