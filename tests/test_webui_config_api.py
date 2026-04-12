"""Tests for ConfigFileService: validation rollback, atomic write, mtime conflict."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ai_marketplace_monitor.webui.config_api import ConfigFileService, scan_sections

SAMPLE_CONFIG = """
[marketplace.facebook]
username = "user@example.com"
search_city = "houston"

[item.iphone]
search_phrases = "iphone 13 pro"

[user.me]
pushbullet_token = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
"""


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    f = tmp_path / "config.toml"
    f.write_text(SAMPLE_CONFIG, encoding="utf-8")
    return f


def test_scan_sections_basic() -> None:
    content = (
        '[marketplace.facebook]\n'
        'username = "u"\n'
        'password = "p"\n'
        '\n'
        '[item.foo]\n'
        'search_phrases = "x"\n'
        '\n'
        '[user.me]\n'
        'pushbullet_token = "t"\n'
    )
    sections = scan_sections(content)
    names = [s.name for s in sections]
    assert names == ["marketplace.facebook", "item.foo", "user.me"]
    # First section spans lines 0..4 (exclusive), covering its 3 fields + blank
    assert sections[0].line_start == 0
    assert sections[0].line_end == 4
    assert sections[0].prefix == "marketplace"
    assert sections[0].suffix == "facebook"
    # Last section runs to EOF
    assert sections[-1].line_end == len(content.splitlines())


def test_scan_sections_handles_single_segment_name() -> None:
    content = '[monitor]\nproxy_server = "x"\n'
    sections = scan_sections(content)
    assert len(sections) == 1
    assert sections[0].name == "monitor"
    assert sections[0].prefix == "monitor"
    assert sections[0].suffix == ""


def test_scan_sections_empty_file() -> None:
    assert scan_sections("") == []
    assert scan_sections("# just a comment\n") == []


def test_scan_sections_malformed_still_works() -> None:
    # Garbage between sections doesn't break the scan.
    content = '[a.b]\nthis is not = = valid\n[c.d]\n'
    sections = scan_sections(content)
    assert [s.name for s in sections] == ["a.b", "c.d"]


def test_list_files_returns_editable(config_file: Path) -> None:
    svc = ConfigFileService([config_file])
    files = svc.list_files()
    assert len(files) == 1
    assert files[0].id == "primary"
    assert Path(files[0].path) == config_file


def test_read_returns_content_and_mtime(config_file: Path) -> None:
    svc = ConfigFileService([config_file])
    content, mtime = svc.read("primary")
    assert "[item.iphone]" in content
    assert mtime > 0


def test_read_unknown_id_raises(config_file: Path) -> None:
    svc = ConfigFileService([config_file])
    with pytest.raises(KeyError):
        svc.read("other")


def test_validate_rejects_garbage_toml(config_file: Path) -> None:
    svc = ConfigFileService([config_file])
    ok, error = svc.validate("this is not = = toml")
    assert ok is False
    assert error is not None


def test_write_rejects_invalid_and_leaves_file_untouched(config_file: Path) -> None:
    svc = ConfigFileService([config_file])
    original = config_file.read_text(encoding="utf-8")
    _, ok, error = svc.write("primary", "not = = toml", base_mtime=None)
    assert ok is False
    assert error is not None
    assert config_file.read_text(encoding="utf-8") == original


def test_write_mtime_conflict(config_file: Path) -> None:
    svc = ConfigFileService([config_file])
    _, stale = svc.read("primary")
    # Simulate an external edit.
    time.sleep(0.05)
    config_file.write_text(SAMPLE_CONFIG + "\n# external edit\n", encoding="utf-8")
    _, ok, error = svc.write("primary", SAMPLE_CONFIG, base_mtime=stale)
    assert ok is False
    assert error and "conflict" in error


def test_validate_accepts_incomplete_template(config_file: Path) -> None:
    """Validate the default first-run template without raising.

    The default template seeded on first run contains no real
    credentials. It's intentionally invalid until the user fills it in.
    Validation should return the error clearly rather than raising.
    """
    from ai_marketplace_monitor.cli import _DEFAULT_CONFIG_TEMPLATE

    svc = ConfigFileService([config_file])
    ok, error = svc.validate(_DEFAULT_CONFIG_TEMPLATE)
    # Template is intentionally minimal — we don't assert valid/invalid
    # (that depends on schema), but the call must not raise.
    assert isinstance(ok, bool)
    if not ok:
        assert error


def test_write_success_updates_file(config_file: Path) -> None:
    svc = ConfigFileService([config_file])
    _, mtime = svc.read("primary")
    # SAMPLE_CONFIG has a username so read() returns redacted content.
    # Start from the redacted version to mimic what the browser sends.
    redacted, _ = svc.read("primary")
    new_redacted = redacted + '\n[item.ipad]\nsearch_phrases = "ipad pro"\n'
    new_mtime, ok, error = svc.write("primary", new_redacted, base_mtime=mtime)
    assert ok, error
    on_disk = config_file.read_text(encoding="utf-8")
    assert "[item.ipad]" in on_disk
    # Original secret must still be on disk (round-tripped, not masked).
    assert "user@example.com" in on_disk
    assert new_mtime >= mtime


def test_read_returns_redacted_content(config_file: Path) -> None:
    svc = ConfigFileService([config_file])
    content, _ = svc.read("primary")
    # SAMPLE_CONFIG has username = "user@example.com" which is sensitive.
    assert "user@example.com" not in content
    assert "<REDACTED>" in content


def test_write_rejects_invalid_after_restore(config_file: Path) -> None:
    """Unchanged redacted content round-trips cleanly after restore.

    Masks must be restored before validation, so a user saving just
    the mask shouldn't accidentally write garbage.
    """
    svc = ConfigFileService([config_file])
    _, mtime = svc.read("primary")
    redacted, _ = svc.read("primary")
    # Unchanged redacted content must still validate and round-trip cleanly.
    new_mtime, ok, error = svc.write("primary", redacted, base_mtime=mtime)
    assert ok, error
    on_disk = config_file.read_text(encoding="utf-8")
    assert "user@example.com" in on_disk


def test_write_new_secret_over_mask(config_file: Path) -> None:
    svc = ConfigFileService([config_file])
    _, mtime = svc.read("primary")
    redacted, _ = svc.read("primary")
    # User types a new username over the mask.
    edited = redacted.replace('"<REDACTED>"', '"new-user@example.com"', 1)
    new_mtime, ok, error = svc.write("primary", edited, base_mtime=mtime)
    assert ok, error
    on_disk = config_file.read_text(encoding="utf-8")
    assert "new-user@example.com" in on_disk
    assert "user@example.com" not in on_disk.replace("new-user@example.com", "")
