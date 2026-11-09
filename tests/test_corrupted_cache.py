"""A corrupted cache database: aimm still starts, and --clear-cache all removes it."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
import typer
from diskcache_community import Cache, Disk

from ai_marketplace_monitor import utils
from ai_marketplace_monitor.commands import admin, common


@pytest.fixture
def corrupted(tmp_path: Path) -> Path:
    (tmp_path / "cache.db").write_bytes(b"this is not a database" * 200)
    (tmp_path / "cache.db-wal").write_bytes(b"")
    (tmp_path / "cache.db-shm").write_bytes(b"\0" * 32)
    (tmp_path / "3f" / "a1").mkdir(parents=True)
    (tmp_path / "3f" / "a1" / "value.val").write_bytes(b"large value")
    (tmp_path / "config.toml").write_text("[monitor]\n")  # not the cache's
    (tmp_path / "backups").mkdir()
    return tmp_path


def test_a_corrupted_cache_opens_as_broken(corrupted: Path) -> None:
    cache: Any = utils.open_cache(corrupted)
    assert utils.is_cache_broken(cache)
    with pytest.raises(utils.CacheCorruptedError, match="--clear-cache all"):
        cache.get("key")
    cache.close()  # stopping the monitor closes the cache; that must not fail


def test_clear_cache_all_removes_a_corrupted_cache(
    corrupted: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(admin, "cache", utils.open_cache(corrupted))
    admin.run_clear_cache("all")
    assert sorted(p.name for p in corrupted.iterdir()) == ["backups", "config.toml"]
    fresh = utils.open_cache(corrupted)  # what the next start of aimm opens
    assert not utils.is_cache_broken(fresh)
    fresh.set("key", "value")
    assert fresh.get("key") == "value"
    fresh.close()


def test_clear_cache_all_removes_a_cache_that_fails_to_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    cache = utils.open_cache(tmp_path)
    cache.set("key", "value")

    def clear() -> None:
        raise sqlite3.DatabaseError("database disk image is malformed")

    monkeypatch.setattr(cache, "clear", clear)
    monkeypatch.setattr(admin, "cache", cache)
    admin.run_clear_cache("all")
    assert not (tmp_path / "cache.db").exists()


def test_clearing_one_type_of_a_corrupted_cache_asks_for_all(
    corrupted: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(admin, "cache", utils.open_cache(corrupted))
    with pytest.raises(typer.Exit):
        admin.run_clear_cache(utils.CacheType.AI_INQUIRY.value)
    assert (corrupted / "cache.db").exists()


def test_commands_stop_early_on_a_corrupted_cache(
    corrupted: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(common, "cache", utils.open_cache(corrupted))
    logger = logging.getLogger("corrupted-cache-test")
    with caplog.at_level(logging.ERROR, logger="corrupted-cache-test"), pytest.raises(typer.Exit):
        common.require_readable_cache(logger)
    assert "docker exec aimm aimm admin --clear-cache all" in caplog.text
    monkeypatch.setattr(common, "cache", utils.open_cache(corrupted / "backups"))
    common.require_readable_cache(logger)  # a healthy cache passes


def _write_marker(path: str) -> str:
    Path(path).write_text("ran")
    return "9.9.9"


class _Planted:
    def __init__(self: "_Planted", path: str) -> None:
        self.path = path

    def __reduce__(self: "_Planted") -> Any:
        return (_write_marker, (self.path,))


def test_an_entry_rewritten_as_a_pickle_reads_as_missing(tmp_path: Path) -> None:
    cache = utils.open_cache(tmp_path / "cache")
    key = (utils.CacheType.UPDATE_CHECK.value, "latest")
    cache.set(key, "0.10.17")
    assert cache.get(key) == "0.10.17"
    marker = tmp_path / "marker"
    with Cache(tmp_path / "cache", disk=Disk) as other_writer:
        other_writer.set(key, _Planted(str(marker)))
    assert cache.get(key) is None
    assert not marker.exists()
    cache.close()
