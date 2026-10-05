"""Remove the repetition of the expanded form (internal step of normalize())."""

import copy
from typing import Any, Dict, List, Tuple

from ..marketplace import Fallback
from .model import AI_PROMPT_ITEM_ONLY, COMMON_OPTIONS, LOCATION_KEYS, OPTION_FALLBACK
from .pushdown import Notes, bound_marketplace

_ABSENT = object()


def _shared(key: str, group: List[Dict[str, Any]]) -> bool:
    values = [item.get(key, _ABSENT) for item in group]
    if values[0] is _ABSENT or any(v != values[0] for v in values):
        return False
    # item.x or marketplace.x: a falsy shared value would be replaced by the marketplace's
    return not (OPTION_FALLBACK.get(key) is Fallback.TRUTHY and not values[0])


def _hoist(cfg: Dict[str, Any], notes: Notes) -> None:
    markets: Dict[str, Any] = cfg.get("marketplace", {})
    items: Dict[str, Any] = cfg.get("item", {})
    for market_name, market in markets.items():
        group = [it for it in items.values() if bound_marketplace(it, markets) == market_name]
        if len(group) < 2:
            continue
        keys = [
            k
            for k in COMMON_OPTIONS
            if k not in AI_PROMPT_ITEM_ONLY and k not in LOCATION_KEYS and _shared(k, group)
        ]
        location = [k for k in LOCATION_KEYS if any(k in it for it in group)]
        if location and all(_shared(k, group) for k in location):
            keys += location
        for key in keys:
            market[key] = copy.deepcopy(group[0][key])
            notes[(f"marketplace.{market_name}", key)] = f"{key} shared by all items"
            for item in group:
                del item[key]


def _merge_notifications(cfg: Dict[str, Any], notes: Notes) -> None:
    notifs: Dict[str, Any] = cfg.get("notification", {})
    names = list(notifs)
    replace: Dict[str, str] = {}
    # identical raw content implies the same notification type
    for i, keep in enumerate(names):
        if keep in replace:
            continue
        for other in names[i + 1 :]:
            if other not in replace and notifs[other] == notifs[keep]:
                replace[other] = keep
    for other, keep in replace.items():
        del notifs[other]
        notes[(f"notification.{other}", None)] = f"merged into notification.{keep}"
    for user in cfg.get("user", {}).values():
        if isinstance(user.get("notify_with"), list):
            merged = (replace.get(n, n) for n in user["notify_with"])
            user["notify_with"] = list(dict.fromkeys(merged))


def compact(expanded: Dict[str, Any]) -> Tuple[Dict[str, Any], Notes]:
    """Hoist values shared by all items of a marketplace and merge identical sections."""
    cfg = copy.deepcopy(expanded)
    notes: Notes = {}
    _hoist(cfg, notes)
    _merge_notifications(cfg, notes)
    return cfg, notes
