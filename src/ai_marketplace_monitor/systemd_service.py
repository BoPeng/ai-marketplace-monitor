"""Install / uninstall ai-marketplace-monitor as a systemd user service.

The feature is Linux-only. It generates a ``systemd --user`` unit file so the
monitor can be supervised by systemd and automatically restarted on crash. A
user-level unit (rather than a system unit) is used because:

* Playwright browsers are installed under the user's home directory.
* The monitor reads configuration from ``~/.ai-marketplace-monitor``.
* No ``sudo`` is required to install, enable, or inspect the unit.

Because the Facebook marketplace flow may require an interactive login, the
unit defaults to ``--headless`` and expects credentials to be stored in the
TOML config. See ``docs/linux-installation.md`` for the full workflow.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

SERVICE_NAME = "ai-marketplace-monitor.service"


def _unit_dir() -> Path:
    """Return the per-user systemd unit directory (``~/.config/systemd/user``)."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "systemd" / "user"


def _unit_path() -> Path:
    return _unit_dir() / SERVICE_NAME


def _require_linux() -> None:
    if sys.platform != "linux":
        raise RuntimeError(
            "systemd service management is only supported on Linux. "
            f"Current platform: {sys.platform}."
        )


def _require_systemctl() -> str:
    systemctl = shutil.which("systemctl")
    if systemctl is None:
        raise RuntimeError(
            "`systemctl` was not found on PATH. A systemd-based Linux "
            "distribution is required to use this feature."
        )
    return systemctl


def _resolve_executable() -> str:
    """Find the absolute path to the ``ai-marketplace-monitor`` entry point.

    systemd requires an absolute ``ExecStart`` path, so fall back to the
    current Python interpreter plus ``-m`` if the console script cannot be
    located on ``PATH``.
    """
    exe = shutil.which("ai-marketplace-monitor")
    if exe:
        return exe
    return f"{sys.executable} -m ai_marketplace_monitor"


def render_unit(
    exec_start: str | None = None,
    extra_args: List[str] | None = None,
) -> str:
    """Render the systemd unit file contents as a string."""
    command = exec_start or _resolve_executable()
    args = list(extra_args or [])
    if "--headless" not in args:
        args.append("--headless")
    exec_line = command + (" " + " ".join(args) if args else "")

    return f"""[Unit]
Description=AI Marketplace Monitor
Documentation=https://github.com/BoPeng/ai-marketplace-monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={exec_line}
Restart=on-failure
RestartSec=30s
# Give playwright browsers time to shut down cleanly on stop.
TimeoutStopSec=30s
# Keep a reasonable log footprint; journald captures stdout/stderr.
StandardOutput=journal
StandardError=journal
# Playwright/Chromium needs a writable HOME and cache dir.
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
"""


def _run(systemctl: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [systemctl, "--user", *args],
        check=False,
        capture_output=True,
        text=True,
    )


def install_service(extra_args: List[str] | None = None, enable: bool = True) -> Path:
    """Write the unit file and (optionally) enable + start it.

    Returns the path of the installed unit file.
    """
    _require_linux()
    systemctl = _require_systemctl()

    unit_path = _unit_path()
    unit_path.parent.mkdir(parents=True, exist_ok=True)
    unit_path.write_text(render_unit(extra_args=extra_args))

    # Reload the user unit cache so systemd picks up the new file.
    reload_result = _run(systemctl, "daemon-reload")
    if reload_result.returncode != 0:
        raise RuntimeError(
            "systemctl --user daemon-reload failed: " + reload_result.stderr.strip()
        )

    if enable:
        enable_result = _run(systemctl, "enable", "--now", SERVICE_NAME)
        if enable_result.returncode != 0:
            raise RuntimeError(
                "systemctl --user enable --now failed: " + enable_result.stderr.strip()
            )

    return unit_path


def uninstall_service() -> Path | None:
    """Stop, disable, and remove the unit file. Returns the removed path or None."""
    _require_linux()
    systemctl = _require_systemctl()

    unit_path = _unit_path()
    if unit_path.exists():
        _run(systemctl, "disable", "--now", SERVICE_NAME)
        unit_path.unlink()
        _run(systemctl, "daemon-reload")
        return unit_path
    return None


def service_status() -> str:
    """Return a short human-readable status string from ``systemctl status``."""
    _require_linux()
    systemctl = _require_systemctl()
    result = _run(systemctl, "status", SERVICE_NAME, "--no-pager")
    # systemctl status exits non-zero when inactive/failed, but its stdout is
    # still the useful payload. Surface it verbatim.
    return (result.stdout or result.stderr).rstrip()
