"""Run-time state shared by the monitor and the web UI, which run in the same process.

The web UI pauses and resumes searches here, and reads whether the monitor is waiting for
the user to finish logging in to Facebook, and asks for the browser when it is not running.
Nothing is saved: a restart resumes searching.
"""

from __future__ import annotations

import threading
from typing import Any, Dict


class MonitorControl:
    def __init__(self: "MonitorControl") -> None:
        self._lock = threading.Lock()
        self._stop_requested = False
        self._running = threading.Event()
        self._running.set()
        self.waiting_for_login = False
        self.login_hint = ""  # where to finish logging in, while waiting_for_login
        # set by the web UI's browser view when the monitor has not started a browser (no
        # marketplace needs one); the monitor, which owns the browser, starts it
        self.browser_requested = threading.Event()
        self.browser_running = False

    def request_browser(self: "MonitorControl") -> None:
        """Ask the monitor to start its browser; nothing to do if it is running."""
        if not self.browser_running:
            self.browser_requested.set()

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

    def status(self: "MonitorControl") -> Dict[str, Any]:
        return {
            "paused": self.is_paused(),
            "waiting_for_login": self.waiting_for_login,
            "login_hint": self.login_hint if self.waiting_for_login else "",
        }


control = MonitorControl()
