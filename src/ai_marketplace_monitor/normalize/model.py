"""Shared types, constants, ordering, and change descriptions for normalization."""

import json
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional, Tuple

from rich.text import Text

from ..ai import AIConfig
from ..facebook import (
    FacebookItemConfig,
    FacebookMarketItemCommonConfig,
    FacebookMarketplaceConfig,
)
from ..marketplace import SITE_FALLBACK, MarketItemCommonConfig
from ..region import RegionConfig
from ..user import UserConfig
from ..utils import BaseConfig, MonitorConfig, TranslationConfig, is_sensitive_key

SECTION_ORDER: Tuple[str, ...] = (
    "monitor",
    "ai",
    "marketplace",
    "user",
    "notification",
    "region",
    "item",
    "translation",
)
_BASE_FIELDS = {f.name for f in fields(BaseConfig)}
COMMON_OPTIONS: Tuple[str, ...] = tuple(
    dict.fromkeys(
        f.name
        for cls in (MarketItemCommonConfig, FacebookMarketItemCommonConfig)
        for f in fields(cls)
        if f.name not in _BASE_FIELDS
    )
)
LOCATION_KEYS: Tuple[str, ...] = (
    "search_region",
    "search_city",
    "city_name",
    "radius",
    "currency",
)
AI_PROMPT_ITEM_ONLY: Tuple[str, ...] = tuple(
    k for (site, k) in SITE_FALLBACK if site == "ai_prompt"
)
MASK = "<REDACTED>"

# dataclass fields that never appear as config keys (runtime state, or the
# translation `dictionary`, whose entries are the section's remaining keys)
_RUNTIME_FIELDS = {"searched_count", "monitor_config", "dictionary"}
_FIELD_ORDER: Dict[str, List[str]] = {
    section: [f.name for f in fields(cls) if f.name not in _RUNTIME_FIELDS]
    for section, cls in {
        "monitor": MonitorConfig,
        "ai": AIConfig,
        "marketplace": FacebookMarketplaceConfig,
        "user": UserConfig,
        # notification sections hold a subset of UserConfig fields
        "notification": UserConfig,
        "region": RegionConfig,
        "item": FacebookItemConfig,
        "translation": TranslationConfig,
    }.items()
}


class NormalizeError(ValueError):
    """Normalization is impossible or would change runtime behavior."""


def plain(e: BaseException) -> str:
    """Error text without rich markup (loader errors embed tags such as [cyan])."""
    try:
        return Text.from_markup(str(e)).plain
    except Exception:
        return str(e)


@dataclass
class Change:
    section: str  # e.g. "user.alice", "notification.email", "*" for whole-file
    action: str  # "add" | "move" | "set" | "remove"
    key: Optional[str]
    detail: str


@dataclass
class NormalizeResult:
    config: Dict[str, Any]
    changes: List[Change] = field(default_factory=list)


def mask(key: Optional[str], value: Any) -> Any:
    """Mask a value if the key is sensitive."""
    return MASK if key is not None and is_sensitive_key(key) else value


def _order_section(section_type: str, raw: Dict[str, Any]) -> Dict[str, Any]:
    """Order keys within a section: request, enabled, then declared fields, then unknown."""
    declared = _FIELD_ORDER.get(section_type)
    if declared is None:
        return dict(raw)
    out: Dict[str, Any] = {k: raw[k] for k in ("request", "enabled") if k in raw}
    out.update({k: raw[k] for k in declared if k in raw and k not in out})
    out.update({k: v for k, v in raw.items() if k not in out})
    return out


def order_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Fixed type order, input order within a type, canonical key order within a section."""
    out: Dict[str, Any] = {}
    for section_type in [*SECTION_ORDER, *(t for t in cfg if t not in SECTION_ORDER)]:
        if section_type not in cfg:
            continue
        body = cfg[section_type]
        if section_type == "monitor":
            out[section_type] = _order_section("monitor", body)
        else:
            out[section_type] = {n: _order_section(section_type, s) for n, s in body.items()}
    return out


def _sections(cfg: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Flatten config into (section.name, section_dict) map."""
    out: Dict[str, Dict[str, Any]] = {}
    for section_type, body in cfg.items():
        if section_type == "monitor":
            out["monitor"] = body
        else:
            out.update({f"{section_type}.{n}": s for n, s in body.items()})
    return out


_MISSING = object()


def _key_changes(
    label: str,
    old: Dict[str, Any],
    new: Dict[str, Any],
    notes: Dict[Tuple[str, Optional[str]], str],
) -> List[Change]:
    """Generate Change records for differences in a single section."""
    changes = []
    for key in [*old, *(k for k in new if k not in old)]:
        old_value, new_value = old.get(key, _MISSING), new.get(key, _MISSING)
        if old_value == new_value:
            continue
        if new_value is _MISSING:
            action, detail = "remove", f"removed {key}"
        elif old_value is _MISSING:
            action, detail = "set", f"{key} = {mask(key, new_value)!r}"
        else:
            action = "set"
            detail = f"{key}: {mask(key, old_value)!r} -> {mask(key, new_value)!r}"
        changes.append(Change(label, action, key, notes.get((label, key), detail)))
    return changes


def describe_changes(
    before: Dict[str, Any],
    after: Dict[str, Any],
    notes: Optional[Dict[Tuple[str, Optional[str]], str]] = None,
) -> List[Change]:
    """Human-readable list of differences between two raw configs (secrets masked)."""
    notes = notes or {}
    old_sections, new_sections = _sections(before), _sections(after)
    changes: List[Change] = []
    for label in [*old_sections, *(k for k in new_sections if k not in old_sections)]:
        if label not in old_sections:
            changes.append(Change(label, "add", None, notes.get((label, None), "new section")))
        elif label not in new_sections:
            detail = notes.get((label, None), "section removed")
            changes.append(Change(label, "remove", None, detail))
        else:
            changes.extend(_key_changes(label, old_sections[label], new_sections[label], notes))
    if not changes and json.dumps(before, default=str) != json.dumps(after, default=str):
        changes.append(Change("*", "set", None, "reordered sections and keys"))
    return changes
