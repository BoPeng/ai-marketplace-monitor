"""Run-time state shared by the monitor and the web UI, which run in the same process.

The web UI pauses and resumes searches here, and reads whether the monitor is waiting for
the user to finish logging in to Facebook. Nothing is saved: a restart resumes searching.

The web UI also asks the monitor to do things in its browser (e.g. find a city's code in
Facebook's location dialog): the browser belongs to the monitor's thread, so the monitor runs
queued browser tasks itself, when it waits between searches or between listings.
"""

from __future__ import annotations

import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable, Dict, Tuple


class MonitorControl:
    def __init__(self: "MonitorControl") -> None:
        self._lock = threading.Lock()
        self._stop_requested = False
        self._running = threading.Event()
        self._running.set()
        self.waiting_for_login = False
        self.login_hint = ""  # where to finish logging in, while waiting_for_login
        self._browser_tasks: "queue.Queue[Tuple[str, Dict[str, Any], Future]]" = queue.Queue()
        self._browser_handler: Callable[..., Any] | None = None

    def pause(self: "MonitorControl") -> None:
        with self._lock:
            self._stop_requested = True
            self._running.clear()

    def resume(self: "MonitorControl") -> None:
        with self._lock:
            self._running.set()

    def consume_stop_request(self: "MonitorControl") -> bool:
        """Acknowledge a stop even if Start was clicked before the monitor reached it."""
        with self._lock:
            requested = self._stop_requested
            self._stop_requested = False
            return requested

    def is_paused(self: "MonitorControl") -> bool:
        return not self._running.is_set()

    def wait_until_resumed(self: "MonitorControl", timeout: float | None = None) -> bool:
        """Block while paused; True once resumed, False if ``timeout`` passed first."""
        return self._running.wait(timeout)

    # --- browser tasks: asked for by the web UI, run by the monitor in its own thread
    def set_browser_handler(self: "MonitorControl", handler: Callable[..., Any] | None) -> None:
        """The monitor's ``handler(name, **args)``, which runs a browser task; None: no browser."""
        self._browser_handler = handler

    def has_browser(self: "MonitorControl") -> bool:
        """Whether a monitor in this process can run browser tasks."""
        return self._browser_handler is not None

    def submit_browser_task(self: "MonitorControl", name: str, **args: Any) -> "Future[Any]":
        """Queue a browser task for the monitor; its result (or exception) comes in the Future."""
        future: "Future[Any]" = Future()
        if self._browser_handler is None:
            future.set_exception(RuntimeError("aimm's monitor and its browser are not running"))
        else:
            self._browser_tasks.put((name, args, future))
        return future

    def run_browser_tasks(self: "MonitorControl") -> None:
        """Run the queued browser tasks; called by the monitor, in its thread."""
        handler = self._browser_handler
        while True:
            try:
                name, args, future = self._browser_tasks.get_nowait()
            except queue.Empty:
                return
            if not future.set_running_or_notify_cancel():
                continue  # given up on while waiting
            try:
                if handler is None:
                    raise RuntimeError("aimm's monitor and its browser are not running")
                future.set_result(handler(name, **args))
            except KeyboardInterrupt:
                raise
            except Exception as e:
                future.set_exception(e)

    def status(self: "MonitorControl") -> Dict[str, Any]:
        return {
            "paused": self.is_paused(),
            "waiting_for_login": self.waiting_for_login,
            "login_hint": self.login_hint if self.waiting_for_login else "",
        }


control = MonitorControl()
