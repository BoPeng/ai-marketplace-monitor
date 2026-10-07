"""Tests for the Docker noVNC bridge helpers."""

from __future__ import annotations

from ai_marketplace_monitor.webui.server import _select_vnc_subprotocol


def test_select_vnc_subprotocol_matches_browser_defaults() -> None:
    assert _select_vnc_subprotocol(None) is None
    assert _select_vnc_subprotocol("") is None


def test_select_vnc_subprotocol_uses_binary_only_when_requested() -> None:
    assert _select_vnc_subprotocol("binary") == "binary"
    assert _select_vnc_subprotocol("base64, binary") == "binary"
    assert _select_vnc_subprotocol("base64") is None
