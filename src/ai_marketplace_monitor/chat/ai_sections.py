"""Read [ai.*] sections across config files without loading the full config."""

import copy
import os
import re
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ..ai import AIConfig
from ..config import supported_ai_backends
from ..utils import merge_dicts

_PLACEHOLDER = re.compile(r"^\$\{(\w+)\}$")
_MARKUP = re.compile(r"\[/?[a-z ]+\]")


class ConfigReadError(Exception):
    """A config file could not be read or parsed."""

    def __init__(self: "ConfigReadError", path: Path, message: str) -> None:
        super().__init__(f"Cannot read {path}: {message}")
        self.path = path


@dataclass
class AISection:
    name: str
    raw: Dict[str, Any]
    files: List[Path]
    config: AIConfig | None = None
    problem: str | None = None

    @property
    def enabled(self: "AISection") -> bool:
        return self.raw.get("enabled") is not False

    @property
    def provider(self: "AISection") -> str:
        return str(self.raw.get("provider", self.name)).lower()


def read_toml(path: Path) -> Dict[str, Any]:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ConfigReadError(path, str(e)) from e


def env_var_name(value: Any) -> str | None:
    """`"${VAR}"` -> `"VAR"`; anything else -> None."""
    match = _PLACEHOLDER.match(value) if isinstance(value, str) else None
    return match.group(1) if match else None


def _build(name: str, raw: Dict[str, Any]) -> Tuple[AIConfig | None, str | None]:
    provider = str(raw.get("provider", name)).lower()
    backend = supported_ai_backends.get(provider)
    if backend is None:
        supported = ", ".join(sorted(supported_ai_backends))
        return None, f'Unknown provider "{provider}"; supported: {supported}'
    var = env_var_name(raw.get("api_key"))
    if var is not None and var not in os.environ:
        return None, f"Set the environment variable {var}"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return backend.get_config(name=name, **raw), None
    except Exception as e:
        return None, _MARKUP.sub("", str(e))


def load_ai_sections(files: List[Path]) -> List[AISection]:
    """Merge [ai.*] tables across files (later file wins) and build each section's config."""
    merged: Dict[str, Dict[str, Any]] = {}
    owners: Dict[str, List[Path]] = {}
    for path in files:
        for name, values in read_toml(path).get("ai", {}).items():
            merged[name] = merge_dicts(
                [copy.deepcopy(merged.get(name, {})), copy.deepcopy(values)]
            )
            owners.setdefault(name, []).append(path)
    sections = []
    for name, raw in merged.items():
        section = AISection(name=name, raw=raw, files=owners[name])
        if section.enabled:
            section.config, section.problem = _build(name, raw)
        sections.append(section)
    return sections
