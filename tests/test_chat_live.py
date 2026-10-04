"""Opt-in live test against UnitySVC; skipped unless UNITYSVC_API_KEY is set."""

import os
from pathlib import Path

import pytest

from ai_marketplace_monitor.chat.ai_sections import load_ai_sections
from ai_marketplace_monitor.chat.probe import probe

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.environ.get("UNITYSVC_API_KEY"), reason="needs UNITYSVC_API_KEY"),
]


def test_unitysvc_balanced_probe(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\n')
    [section] = load_ai_sections([path])
    result = probe(section)
    assert result.ok, result.message
    assert "balanced" in result.available
