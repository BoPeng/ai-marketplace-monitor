"""Run-time state shared by the monitor and the web UI, which run in the same process.

The web UI pauses and resumes searches here, and reads whether the monitor is waiting for
the user to finish logging in to Facebook. Nothing is saved: a restart resumes searching.
"""

from __future__ import annotations

import threading
from typing import Dict


class MonitorControl:
    def __init__(self: "MonitorControl") -> None:
        self._running = threading.Event()
        self._running.set()
        self.waiting_for_login = False

    def pause(self: "MonitorControl") -> None:
        self._running.clear()

    def resume(self: "MonitorControl") -> None:
        self._running.set()

    def is_paused(self: "MonitorControl") -> bool:
        return not self._running.is_set()

    def wait_until_resumed(self: "MonitorControl", timeout: float | None = None) -> bool:
        """Block while paused; True once resumed, False if ``timeout`` passed first."""
        return self._running.wait(timeout)

    def status(self: "MonitorControl") -> Dict[str, bool]:
        return {"paused": self.is_paused(), "waiting_for_login": self.waiting_for_login}


control = MonitorControl()
