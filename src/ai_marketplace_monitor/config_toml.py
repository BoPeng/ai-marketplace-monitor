"""Render a config dict as TOML, one table per section (no comments, no inline tables)."""

import json
import re
from typing import Any

_BARE_TOML_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def _toml_key(value: str) -> str:
    if _BARE_TOML_KEY.match(value):
        return value
    return json.dumps(value, ensure_ascii=False)


def _toml_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"Cannot write {type(value).__name__} value {value!r} as TOML")


def dump_config_toml(cfg: dict[str, Any]) -> str:
    lines: list[str] = []
    for section_type, body in cfg.items():
        if section_type == "monitor":
            lines.append("[monitor]")
            lines.extend(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in body.items())
            lines.append("")
            continue
        for name, section in body.items():
            lines.append(f"[{_toml_key(section_type)}.{_toml_key(name)}]")
            lines.extend(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in section.items())
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
