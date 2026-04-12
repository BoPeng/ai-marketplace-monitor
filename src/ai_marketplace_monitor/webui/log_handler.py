"""Logging handler that broadcasts records to the web UI.

Each record is:
  1. Serialized to a JSON-friendly dict.
  2. Stripped of ANSI/Rich markup in the rendered message.
  3. Redacted for obvious secrets.
  4. Appended to a bounded ring buffer for late-joining clients.
  5. Fanned out to any attached asyncio queues (for WebSocket streaming).

The handler is thread-safe: the monitor logs from the main thread, while
uvicorn and WebSocket consumers live on a dedicated asyncio loop in another
thread. All cross-thread wakeups go through ``loop.call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import re
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Set

# Regex patterns for redacting obvious secrets from log messages before
# they are shipped to the browser. Not a complete DLP solution — just a
# safety net against accidental leaks of API keys printed during debug.
_SECRET_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "sk-***REDACTED***"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"), "Bearer ***REDACTED***"),
    (
        re.compile(r"(?i)(api[_-]?key|token|secret)\s*[:=]\s*['\"]?[A-Za-z0-9._\-]{12,}['\"]?"),
        r"\1=***REDACTED***",
    ),
]

# Rich markup like "[bold red]foo[/bold red]" and ANSI escapes. We ship
# plain text to the browser and let CSS handle styling by level.
_RICH_MARKUP = re.compile(r"\[/?[^\[\]]{1,40}\]")
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def _redact(text: str) -> str:
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _clean(text: str) -> str:
    text = _ANSI_ESCAPE.sub("", text)
    text = _RICH_MARKUP.sub("", text)
    return _redact(text)


class LogBroadcastHandler(logging.Handler):
    """Logging handler that retains a ring buffer and fans records out to
    registered asyncio queues on another loop.
    """

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self._buffer: Deque[Dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._subscribers: Set["asyncio.Queue[Dict[str, Any]]"] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._counter = itertools.count(1)

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the asyncio loop used by FastAPI/uvicorn so we can wake it."""
        self._loop = loop

    def subscribe(self, queue: "asyncio.Queue[Dict[str, Any]]") -> None:
        with self._lock:
            self._subscribers.add(queue)

    def unsubscribe(self, queue: "asyncio.Queue[Dict[str, Any]]") -> None:
        with self._lock:
            self._subscribers.discard(queue)

    def snapshot(
        self,
        limit: int | None = None,
        min_level: int = 0,
        kind: str | None = None,
        item: str | None = None,
        min_score: int | None = None,
    ) -> List[Dict[str, Any]]:
        def keep(r: Dict[str, Any]) -> bool:
            if r["levelno"] < min_level:
                return False
            extra = r.get("extra") or {}
            if kind and extra.get("kind") != kind:
                return False
            if item and extra.get("item") != item:
                return False
            if min_score is not None:
                score = extra.get("score")
                if score is None or score < min_score:
                    return False
            return True

        with self._lock:
            items = [r for r in self._buffer if keep(r)]
        if limit is not None and len(items) > limit:
            items = items[-limit:]
        return items

    # ------------------------------------------------------------------
    # Record handling
    # ------------------------------------------------------------------

    def _serialize(self, record: logging.LogRecord) -> Dict[str, Any]:
        try:
            raw_message = record.getMessage()
        except Exception:  # pragma: no cover — defensive
            raw_message = str(record.msg)
        message = _clean(raw_message)

        aimm_extra = getattr(record, "aimm", None)
        if isinstance(aimm_extra, dict):
            extra: Dict[str, Any] | None = aimm_extra
        else:
            extra = None

        payload: Dict[str, Any] = {
            "id": next(self._counter),
            "time": record.created,
            "iso_time": time.strftime("%H:%M:%S", time.localtime(record.created)),
            "level": record.levelname,
            "levelno": record.levelno,
            "logger": record.name,
            "message": message,
            "location": f"{record.module}:{record.lineno}",
        }
        if extra is not None:
            payload["extra"] = extra
        if record.exc_info:
            payload["exc_text"] = _clean(self.format(record)) if self.formatter else None
        return payload

    def emit(self, record: logging.LogRecord) -> None:
        try:
            payload = self._serialize(record)
        except Exception:  # pragma: no cover — never let logging raise
            self.handleError(record)
            return

        with self._lock:
            self._buffer.append(payload)
            subscribers = list(self._subscribers)

        if not subscribers or self._loop is None:
            return

        loop = self._loop
        for queue in subscribers:
            try:
                loop.call_soon_threadsafe(self._safe_put, queue, payload)
            except RuntimeError:
                # Loop is closed — drop this subscriber silently.
                with self._lock:
                    self._subscribers.discard(queue)

    @staticmethod
    def _safe_put(queue: "asyncio.Queue[Dict[str, Any]]", payload: Dict[str, Any]) -> None:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            # Drop oldest to make room — slow consumers must not block logging.
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass
