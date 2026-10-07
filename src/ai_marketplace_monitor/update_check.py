"""Tell the user when a newer aimm release is on PyPI.

aimm runs unattended for days, and Facebook changes its pages often, so an old version can stop
working long after a fix is released. The check asks PyPI at most once a day (the answer is
cached), runs in the background, never fails or delays the monitor, and is skipped for
development builds. Turn it off with ``check_updates = false`` in ``[monitor]`` or the
``AIMM_NO_UPDATE_CHECK`` environment variable.

In the Docker image, the web UI can also install the new release in place (``start_self_update``):
pip installs it inside the container, then aimm exits and supervisord starts the new version.
The update lives in the container, so it survives ``docker restart`` but not recreating the
container from an older image; the update check then offers it again.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from logging import Logger
from typing import Any, Dict, List, Tuple

from . import __version__
from .utils import CacheType, cache, hilight

PYPI_URL = "https://pypi.org/pypi/ai-marketplace-monitor/json"
CHANGELOG_URL = "https://github.com/BoPeng/ai-marketplace-monitor/blob/main/CHANGELOG.md"
CHECK_EVERY = 24 * 60 * 60  # seconds
_RELEASE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class UpdateNotice:
    current: str
    latest: str
    command: str  # how to upgrade this installation
    changelog: str = CHANGELOG_URL

    def message(self: "UpdateNotice") -> str:
        return (
            f"AI Marketplace Monitor {self.latest} is available (you have {self.current}). "
            f"Upgrade with: {self.command}"
        )


# the latest result, for the web UI; None until a check finds a newer release
_notice: UpdateNotice | None = None


def current_notice() -> Dict[str, Any] | None:
    """The update notice for the web UI, or None."""
    return asdict(_notice) if _notice is not None else None


def _release(version: str) -> Tuple[int, int, int] | None:
    """A plain release version as a tuple; None for dev, local or pre-release versions."""
    match = _RELEASE.match(version)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def is_newer(latest: str, current: str) -> bool:
    new, old = _release(latest), _release(current)
    return new is not None and old is not None and new > old


def upgrade_command() -> str:
    """The upgrade command for how aimm was installed."""
    if os.environ.get("AIMM_DOCKER") == "1":
        # `docker restart` keeps the old image; the container must be recreated.
        return (
            "the Update button next to the version in the web UI, or"
            " docker pull ghcr.io/bopeng/ai-marketplace-monitor:latest && docker rm -f aimm,"
            " then run your `docker run` command again"
        )
    prefix = sys.prefix.replace("\\", "/")
    if "/pipx/" in prefix:
        return "pipx upgrade ai-marketplace-monitor"
    if "/uv/tools/" in prefix:
        return "uv tool upgrade ai-marketplace-monitor"
    return "pip install --upgrade ai-marketplace-monitor"


def enabled(check_updates: bool | None) -> bool:
    if check_updates is False or os.environ.get("AIMM_NO_UPDATE_CHECK"):
        return False
    return _release(__version__) is not None  # not for development builds


def latest_version(timeout: float = 5.0) -> str | None:
    """The latest release on PyPI, asked at most once a day; None if it cannot be found."""
    key = (CacheType.UPDATE_CHECK.value, "latest")
    cached = cache.get(key)
    if isinstance(cached, str):
        return cached
    try:
        import requests  # type: ignore

        response = requests.get(PYPI_URL, timeout=timeout)
        response.raise_for_status()
        latest = str(response.json()["info"]["version"])
    except Exception:
        return None  # offline, blocked, or PyPI changed: try again next start
    cache.set(key, latest, expire=CHECK_EVERY, tag=CacheType.UPDATE_CHECK.value)
    return latest


def check(logger: Logger | None, current: str = __version__) -> UpdateNotice | None:
    """Check once; log and remember a notice when a newer release exists."""
    global _notice
    latest = latest_version()
    if latest is None or not is_newer(latest, current):
        return None
    _notice = UpdateNotice(current=current, latest=latest, command=upgrade_command())
    if logger:
        logger.info(f"""{hilight("[UPDATE]", "info")} {_notice.message()}""")
    return _notice


@dataclass(frozen=True)
class SelfUpdate:
    state: str = "idle"  # idle, running, failed, or restarting
    version: str | None = None  # the release being installed
    error: str | None = None


_self_update = SelfUpdate()
_self_update_lock = threading.Lock()
RESTART_GRACE = 60  # seconds to clean up before aimm exits anyway


def can_self_update() -> bool:
    """Only the Docker image restarts aimm (with supervisord) after it exits."""
    return os.environ.get("AIMM_DOCKER") == "1"


def self_update_status() -> Dict[str, Any]:
    """The in-place update, for the web UI."""
    return {"available": can_self_update(), **asdict(_self_update)}


def start_self_update(logger: Logger | None) -> str:
    """Install the newer release in the background, then restart aimm.

    Returns the version being installed; raises RuntimeError when an update cannot start.
    """
    global _self_update
    if not can_self_update():
        raise RuntimeError("aimm can update itself only in the Docker image.")
    notice = _notice
    if notice is None:
        raise RuntimeError("No newer release is available.")
    with _self_update_lock:
        if _self_update.state in ("running", "restarting"):
            raise RuntimeError("An update is already in progress.")
        _self_update = SelfUpdate("running", notice.latest)
    threading.Thread(
        target=install_and_restart,
        args=(notice.latest, logger),
        daemon=True,
        name="aimm-self-update",
    ).start()
    return notice.latest


def install_and_restart(version: str, logger: Logger | None) -> None:
    global _self_update
    if logger:
        logger.info(f"""{hilight("[UPDATE]", "info")} Installing aimm {version}...""")
    try:
        _run(
            [sys.executable, "-m", "pip", "install", f"ai-marketplace-monitor=={version}"], logger
        )
        # a newer Playwright cannot drive the Chromium that came with the image
        _run([sys.executable, "-m", "playwright", "install", "chromium"], logger)
    except Exception as e:
        _self_update = SelfUpdate("failed", version, str(e))
        if logger:
            logger.error(
                f"""{hilight("[UPDATE]", "fail")} Failed to install aimm {version}: {e}"""
            )
        return
    _self_update = SelfUpdate("restarting", version)
    if logger:
        logger.info(f"""{hilight("[UPDATE]", "succ")} Installed aimm {version}. Restarting...""")
    _restart()


def _run(command: List[str], logger: Logger | None) -> None:
    """Run a command, logging its output; raise with the last lines when it fails."""
    output: List[str] = []
    with subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    ) as process:
        assert process.stdout is not None
        for line in process.stdout:
            output.append(line.rstrip())
            if logger:
                logger.debug(f"""{hilight("[UPDATE]", "info")} {line.rstrip()}""")
    if process.returncode != 0:
        tail = "\n".join(output[-5:])
        raise RuntimeError(f"`{' '.join(command[2:])}` exited with {process.returncode}:\n{tail}")


def _restart() -> None:
    """Exit so that supervisord starts the new version.

    SIGINT runs the same cleanup as Ctrl-C (the browser and the web UI) in the main thread.
    """
    timer = threading.Timer(RESTART_GRACE, os._exit, args=(0,))  # if the cleanup hangs
    timer.daemon = True
    timer.start()
    os.kill(os.getpid(), signal.SIGINT)


def check_in_background(logger: Logger | None, check_updates: bool | None) -> None:
    """Start the check without delaying the monitor (a no-op when turned off)."""
    if enabled(check_updates):
        threading.Thread(target=check, args=(logger,), daemon=True, name="aimm-update").start()
