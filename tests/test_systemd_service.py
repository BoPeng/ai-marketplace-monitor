"""Unit tests for the systemd service helpers.

These tests exercise the pure rendering and path logic so they are
platform-independent; the install/uninstall helpers themselves shell out
to ``systemctl`` and are only meaningful on Linux, so they are covered
manually rather than here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ai_marketplace_monitor import systemd_service


def test_render_unit_defaults_headless() -> None:
    unit = systemd_service.render_unit(exec_start="/usr/bin/ai-marketplace-monitor")
    assert "ExecStart=/usr/bin/ai-marketplace-monitor --headless" in unit
    assert "Restart=on-failure" in unit
    assert "WantedBy=default.target" in unit


def test_render_unit_preserves_user_headless_flag() -> None:
    unit = systemd_service.render_unit(
        exec_start="/usr/bin/ai-marketplace-monitor",
        extra_args=["--headless", "-v"],
    )
    # --headless should appear exactly once even if the caller already passed it.
    assert unit.count("--headless") == 1
    assert "-v" in unit


def test_unit_dir_respects_xdg_config_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert systemd_service._unit_dir() == tmp_path / "systemd" / "user"
    assert systemd_service._unit_path().name == systemd_service.SERVICE_NAME
