"""Tests for LogBroadcastHandler: ring buffer, redaction, fanout."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable, Dict

from ai_marketplace_monitor.webui.log_handler import (
    LogBroadcastHandler,
    _clean,
    _redact,
)


def _make_record(
    message: str, level: int = logging.INFO, extra: dict | None = None
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test",
        level=level,
        pathname="t.py",
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


def test_redact_strips_sk_keys() -> None:
    key = "sk-abc123456789abcdef0"  # 16+ chars after sk-
    assert key not in _redact(f"key={key} done")
    assert "***" in _redact(f"key={key} done")


def test_redact_strips_bearer() -> None:
    token = "abcdef0123456789abcdef"  # 16+ chars
    assert token not in _redact(f"Authorization: Bearer {token}")


def test_clean_removes_rich_markup_and_ansi() -> None:
    raw = "\x1b[31m[bold]hello[/bold]\x1b[0m"
    cleaned = _clean(raw)
    assert "\x1b" not in cleaned


def test_ring_buffer_caps_at_capacity() -> None:
    h = LogBroadcastHandler(capacity=3)
    for i in range(5):
        h.emit(_make_record(f"m{i}"))
    snap = h.snapshot()
    assert len(snap) == 3
    assert snap[0]["message"] == "m2"


def test_snapshot_respects_min_level() -> None:
    h = LogBroadcastHandler()
    h.emit(_make_record("dbg", level=logging.DEBUG))
    h.emit(_make_record("warn", level=logging.WARNING))
    snap = h.snapshot(min_level=logging.WARNING)
    assert len(snap) == 1
    assert snap[0]["message"] == "warn"


def test_snapshot_filters_by_kind_item_and_score() -> None:
    h = LogBroadcastHandler()
    h.emit(
        _make_record(
            "matched",
            extra={"aimm": {"kind": "ai_eval", "item": "gopro", "score": 5}},
        )
    )
    h.emit(
        _make_record(
            "skipped",
            extra={"aimm": {"kind": "listing_skip", "item": "ipad"}},
        )
    )
    assert len(h.snapshot(kind="ai_eval")) == 1
    assert len(h.snapshot(item="gopro")) == 1
    assert len(h.snapshot(min_score=4)) == 1


def test_aimm_extra_is_attached() -> None:
    h = LogBroadcastHandler()
    h.emit(_make_record("x", extra={"aimm": {"kind": "ai_eval", "score": 5}}))
    records = h.snapshot()
    assert len(records) == 1
    assert records[-1]["extra"] == {"kind": "ai_eval", "score": 5}


def _run_fanout_test(
    emitter: Callable[[LogBroadcastHandler], None],
    checker: Callable[["asyncio.Queue[Dict[str, Any]]"], None],
    maxsize: int = 0,
) -> None:
    """Run a fanout test with the event loop on a dedicated thread.

    This avoids conflicts with pytest-asyncio's loop. The pattern
    mirrors production: uvicorn loop on one thread, monitor emits
    from another.
    """
    loop = asyncio.new_event_loop()
    errors: list[AssertionError] = []

    async def _loop_body() -> None:
        h = LogBroadcastHandler()
        h.attach_loop(loop)
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=maxsize)
        h.subscribe(queue)

        t = threading.Thread(target=emitter, args=(h,))
        t.start()
        t.join()

        # Let call_soon_threadsafe callbacks run.
        await asyncio.sleep(0.05)
        try:
            checker(queue)
        except AssertionError as e:
            errors.append(e)

    def run_loop() -> None:
        loop.run_until_complete(_loop_body())

    t = threading.Thread(target=run_loop)
    t.start()
    t.join(timeout=5)
    loop.close()
    if errors:
        raise errors[0]


def test_fanout_to_subscribed_queue() -> None:
    """Emit from a background thread, verify the queue receives it."""

    def emitter(h: LogBroadcastHandler) -> None:
        h.emit(_make_record("hello"))

    def checker(queue: "asyncio.Queue[Dict[str, Any]]") -> None:
        assert not queue.empty()
        payload = queue.get_nowait()
        assert payload["message"] == "hello"

    _run_fanout_test(emitter, checker, maxsize=0)


def test_full_queue_drops_oldest() -> None:
    """When the queue is full, oldest messages are dropped."""

    def emitter(h: LogBroadcastHandler) -> None:
        h.emit(_make_record("a"))
        h.emit(_make_record("b"))
        h.emit(_make_record("c"))

    def checker(queue: "asyncio.Queue[Dict[str, Any]]") -> None:
        got = []
        while not queue.empty():
            got.append(queue.get_nowait()["message"])
        assert got == ["b", "c"]

    _run_fanout_test(emitter, checker, maxsize=2)
