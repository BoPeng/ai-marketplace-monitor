"""One Chromium for the monitor and the configure chat.

The monitor drives its browser with Playwright's sync API, whose objects belong to the
monitor's thread, so the web UI's chat cannot use them. Instead the monitor launches Chromium
with a DevTools (CDP) port on 127.0.0.1, and the chat connects to it with its own Playwright
connection. Both use the browser's default context, so they share one live cookie jar: the
chat is logged in to Facebook whenever the monitor is, and never logs in itself.

A context made with ``Browser.new_context()`` is invisible to another CDP client, so the
shared browser is a persistent context (``launch_persistent_context``) on a profile directory
made for this run and removed at exit; the Facebook login is kept between runs by the saved
session (``facebook-session.json``), as before. Its proxy is chosen at launch.

The CDP port has no authentication: anyone on this machine who can connect to 127.0.0.1 can
drive the browser, logged in to Facebook. In Docker, 127.0.0.1 is the container's own.

Only Chromium speaks CDP. When aimm falls back to Firefox or WebKit, nothing is shared.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import tempfile
import threading
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

from .utils import amm_home

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Playwright, ProxySettings  # type: ignore

# where a running monitor says how to reach its browser (for `aimm configure` in a terminal)
ENDPOINT_FILE = amm_home / "browser-endpoint.json"
# Chromium writes the port it chose (for --remote-debugging-port=0) to this file in its profile
DEVTOOLS_PORT_FILE = "DevToolsActivePort"
PORT_WAIT_SECONDS = 15
# the least time between two page loads by different users of the browser (monitor and chat)
NAVIGATION_GAP = 3.0

_endpoint: str | None = None  # this process's shared browser, while it runs
_navigation_lock = threading.Lock()
_search_lock = threading.Lock()  # one search at a time (see search_slot)
_last_navigation = 0.0
_last_navigator: int | None = None  # the thread that loaded the last page


class BrowserBusyError(RuntimeError):
    """The shared browser stayed busy longer than the caller would wait."""


def launch_shared_chromium(
    playwright: "Playwright", proxy: "ProxySettings | None" = None, headless: bool = False
) -> "BrowserContext":
    """Launch Chromium with a CDP port on 127.0.0.1, and publish how to reach it.

    The window is shown (``headless`` False) because the user may need to complete a login
    check in it.
    """
    global _endpoint
    profile = tempfile.mkdtemp(prefix="aimm-chromium-")
    atexit.register(shutil.rmtree, profile, True)
    context = playwright.chromium.launch_persistent_context(
        profile,
        headless=headless,
        proxy=proxy,
        args=["--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0"],
    )
    try:
        port = _read_port(Path(profile))
    except Exception:
        context.close()
        raise
    _endpoint = f"http://127.0.0.1:{port}"
    _publish(port)
    atexit.register(_unpublish, port)
    return context


def _read_port(profile: Path) -> int:
    path = profile / DEVTOOLS_PORT_FILE
    deadline = time.monotonic() + PORT_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            first = path.read_text(encoding="utf-8").splitlines()[0]
            return int(first)
        except (OSError, IndexError, ValueError):
            time.sleep(0.1)
    raise RuntimeError(f"Chromium did not report its DevTools port in {path}.")


def _publish(port: int) -> None:
    """Write the endpoint file, readable only by the user, replacing any other atomically."""
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=ENDPOINT_FILE.parent, prefix=ENDPOINT_FILE.name)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"port": port, "pid": os.getpid(), "started": time.time()}, f)
        os.replace(tmp, ENDPOINT_FILE)
    except OSError:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _unpublish(port: int) -> None:
    """Remove the endpoint file if it is still this browser's."""
    global _endpoint
    _endpoint = None
    try:
        if json.loads(ENDPOINT_FILE.read_text(encoding="utf-8")).get("port") == port:
            ENDPOINT_FILE.unlink()
    except (OSError, ValueError, AttributeError):
        pass


def _answers(endpoint: str) -> bool:
    """Whether a Chromium answers DevTools requests at this endpoint."""
    try:
        url = f"{endpoint}/json/version"  # always http://127.0.0.1:<port>
        with urllib.request.urlopen(url, timeout=2) as response:  # noqa: S310
            info: Any = json.load(response)
    except (OSError, ValueError):
        return False
    return isinstance(info, dict) and "webSocketDebuggerUrl" in info


def shared_endpoint() -> str | None:
    """The CDP endpoint of the monitor's browser, or None if no shared browser is running.

    The web UI runs in the monitor's process and knows it directly; ``aimm configure`` in a
    terminal reads the file a monitor on this machine wrote. A file written in a Docker
    container names the container's own port, which does not answer outside it.
    """
    if _endpoint is not None:
        return _endpoint
    try:
        port = int(json.loads(ENDPOINT_FILE.read_text(encoding="utf-8"))["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    endpoint = f"http://127.0.0.1:{port}"
    return endpoint if _answers(endpoint) else None


@contextmanager
def search_slot(timeout: float | None = None) -> Iterator[None]:
    """Run one search page at a time: set the account's radius, reload and read the results.

    Facebook searches with the radius saved on the account, so another search must not change
    it between this search's update and its reload (within this process: the monitor and the
    web UI's chat). Page loads inside still take turns with ``navigation_slot``. ``timeout``
    (seconds) raises BrowserBusyError instead of waiting longer; None waits as long as it
    takes.
    """
    if not _search_lock.acquire(timeout=-1 if timeout is None else timeout):
        raise BrowserBusyError("aimm's browser is busy with another search.")
    try:
        yield
    finally:
        _search_lock.release()


@contextmanager
def navigation_slot(timeout: float | None = None) -> Iterator[None]:
    """Take turns loading pages: one at a time, and NAVIGATION_GAP seconds after another user's.

    The monitor and the chat use one Facebook account, so their page loads are paced together
    (within this process); the monitor's own pace, with its sleeps, is unchanged. ``timeout``
    (seconds) raises BrowserBusyError instead of waiting longer; None waits as long as it
    takes.
    """
    global _last_navigation, _last_navigator
    if not _navigation_lock.acquire(timeout=-1 if timeout is None else timeout):
        raise BrowserBusyError("aimm's browser is busy loading another page.")
    try:
        me = threading.get_ident()
        wait = _last_navigation + NAVIGATION_GAP - time.monotonic()
        if _last_navigator not in (None, me) and wait > 0:
            time.sleep(wait)
        yield
    finally:
        _last_navigation, _last_navigator = time.monotonic(), threading.get_ident()
        _navigation_lock.release()
