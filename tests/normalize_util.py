"""Helpers shared by config loading and normalization tests."""

import json
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ai_marketplace_monitor.config import SYSTEM_CONFIG

ROOT = Path(__file__).parent.parent
EXAMPLES: List[Path] = [
    ROOT / "docs" / "minimal_config.toml",
    ROOT / "docs" / "example_config.toml",
]


def parse(text: str) -> Dict[str, Any]:
    return tomllib.loads(textwrap.dedent(text))


def system_cfg() -> Dict[str, Any]:
    with open(SYSTEM_CONFIG, "rb") as f:
        return tomllib.load(f)


def dumps(cfg: Dict[str, Any]) -> str:
    """Order-sensitive serialization (plain dict == ignores key order)."""
    return json.dumps(cfg, default=str)
