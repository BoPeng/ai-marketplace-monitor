"""Tests for LogBroadcastHandler: ring buffer, redaction, fanout."""

from __future__ import annotations

import asyncio
import logging
import threading

from ai_marketplace_monitor.webui.log_handler import (
    LogBroadcastHandler,
    _clean,
    _redact,
)


def _make_record(
    message: str, level: int = logging.INFO, extra: dict | None = None
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test", level=level, pathname="t.py", lineno=1, msg=message, args=(), exc_info=None
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


def test_redact_strips_sk_keys() -> None:
    assert "sk-***REDACTED***" in _redact("key is sk-abcdefghij0123456789")


def test_redact_strips_bearer() -> None:
    assert "***REDACTED***" in _redact("Authorization: Bearer abcdefghijklmnop")


def test_clean_removes_rich_markup_and_ansi() -> None:
    assert _clean("[bold red]hi[/bold red]\x1b[31mx\x1b[0m") == "hix"


def test_ring_buffer_caps_at_capacity() -> None:
    h = LogBroadcastHandler(capacity=3)
    for i in range(10):
        h.emit(_make_record(f"msg {i}"))
    snapshot = h.snapshot()
    assert len(snapshot) == 3
    assert snapshot[0]["message"] == "msg 7"
    assert snapshot[-1]["message"] == "msg 9"


def test_snapshot_respects_min_level() -> None:
    h = LogBroadcastHandler(capacity=10)
    h.emit(_make_record("debug msg", logging.DEBUG))
    h.emit(_make_record("info msg", logging.INFO))
    h.emit(_make_record("err msg", logging.ERROR))
    assert len(h.snapshot(min_level=logging.INFO)) == 2
    assert len(h.snapshot(min_level=logging.ERROR)) == 1


def test_snapshot_filters_by_kind_item_and_score() -> None:
    h = LogBroadcastHandler()
    h.emit(
        _make_record("search done", extra={"aimm": {"kind": "search_summary", "item": "iphone"}})
    )
    h.emit(
        _make_record(
            "ai done",
            extra={"aimm": {"kind": "ai_eval", "item": "iphone", "score": 5}},
        )
    )
    h.emit(
        _make_record(
            "ai done low",
            extra={"aimm": {"kind": "ai_eval", "item": "ipad", "score": 2}},
        )
    )

    assert len(h.snapshot(kind="ai_eval")) == 2
    assert len(h.snapshot(kind="ai_eval", item="iphone")) == 1
    assert len(h.snapshot(kind="ai_eval", min_score=4)) == 1
    assert len(h.snapshot(item="ipad")) == 1


def test_aimm_extra_is_attached() -> None:
    h = LogBroadcastHandler()
    h.emit(_make_record("listing found", extra={"aimm": {"kind": "ai_eval", "score": 5}}))
    records = h.snapshot()
    assert records[-1]["extra"] == {"kind": "ai_eval", "score": 5}


def test_fanout_to_subscribed_queue() -> None:
    """Emit from a background thread, verify the queue receives it."""
    loop = asyncio.new_event_loop()
    h = LogBroadcastHandler()
    h.attach_loop(loop)
    queue: asyncio.Queue = asyncio.Queue()
    h.subscribe(queue)

    # Emit from a separate thread (like the real monitor).
    t = threading.Thread(target=h.emit, args=(_make_record("hello"),))
    t.start()
    t.join()

    # Drain the loop so call_soon_threadsafe callbacks execute.
    loop.run_until_complete(asyncio.sleep(0.05))
    assert not queue.empty()
    payload = queue.get_nowait()
    assert payload["message"] == "hello"
    loop.close()


def test_full_queue_drops_oldest() -> None:
    """When the queue is full, oldest messages are dropped."""
    loop = asyncio.new_event_loop()
    h = LogBroadcastHandler()
    h.attach_loop(loop)
    queue: asyncio.Queue = asyncio.Queue(maxsize=2)
    h.subscribe(queue)

    def emit_all() -> None:
        h.emit(_make_record("a"))
        h.emit(_make_record("b"))
        h.emit(_make_record("c"))

    t = threading.Thread(target=emit_all)
    t.start()
    t.join()

    loop.run_until_complete(asyncio.sleep(0.05))
    got = []
    while not queue.empty():
        got.append(queue.get_nowait()["message"])
    assert got == ["b", "c"]
    loop.close()
