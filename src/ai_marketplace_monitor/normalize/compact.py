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
        for key in ("notify_with", "digest_with"):
            if isinstance(user.get(key), list):
                merged = (replace.get(n, n) for n in user[key])
                user[key] = list(dict.fromkeys(merged))


def _remove_default_marketplace_bindings(cfg: Dict[str, Any], notes: Notes) -> None:
    markets: Dict[str, Any] = cfg.get("marketplace", {})
    if not markets:
        return
    default_market = next(iter(markets))
    for item_name, item in cfg.get("item", {}).items():
        if item.get("marketplace") == default_market:
            del item["marketplace"]
            notes[(f"item.{item_name}", "marketplace")] = (
                f"marketplace omitted: defaults to {default_market}"
            )


def _drop_explicit_defaults(cfg: Dict[str, Any], notes: Notes) -> None:
    """Drop raw values that are identical to runtime defaults."""
    for section_type in (
        "ai",
        "marketplace",
        "user",
        "notification",
        "region",
        "item",
        "translation",
    ):
        for name, section in cfg.get(section_type, {}).items():
            label = f"{section_type}.{name}"
            if section.get("enabled") is True:
                del section["enabled"]
                notes[(label, "enabled")] = "enabled omitted: defaults to true"
    for name, ai in cfg.get("ai", {}).items():
        if ai.get("max_retries") == 10:
            del ai["max_retries"]
            notes[(f"ai.{name}", "max_retries")] = "max_retries omitted: defaults to 10"
    for name, market in cfg.get("marketplace", {}).items():
        if market.get("market_type") == "facebook":
            del market["market_type"]
            notes[(f"marketplace.{name}", "market_type")] = (
                "market_type omitted: defaults to facebook"
            )


def _default_item_notify(market: Dict[str, Any], users: List[str]) -> List[str]:
    return market.get("notify") or users


def _default_item_ai(market: Dict[str, Any], ais: List[str]) -> List[str]:
    return market["ai"] if "ai" in market else ais


def _drop_implicit_all_lists(cfg: Dict[str, Any], notes: Notes) -> None:
    """Drop lists that exactly restate their inherited default set."""
    users = list(cfg.get("user", {}))
    ais = list(cfg.get("ai", {}))
    markets: Dict[str, Any] = cfg.get("marketplace", {})

    for name, market in markets.items():
        label = f"marketplace.{name}"
        if market.get("notify") == users:
            del market["notify"]
            notes[(label, "notify")] = "notify omitted: defaults to all users"
        if market.get("ai") == ais:
            del market["ai"]
            notes[(label, "ai")] = "ai omitted: defaults to all AI backends"

    for name, item in cfg.get("item", {}).items():
        market = markets[bound_marketplace(item, markets)]
        label = f"item.{name}"
        if item.get("notify") == _default_item_notify(market, users):
            del item["notify"]
            notes[(label, "notify")] = "notify omitted: inherits the same users"
        if item.get("ai") == _default_item_ai(market, ais):
            del item["ai"]
            notes[(label, "ai")] = "ai omitted: inherits the same AI backends"

    enabled_notifications = [
        name
        for name, notification in cfg.get("notification", {}).items()
        if notification.get("enabled") is not False
    ]
    for name, user in cfg.get("user", {}).items():
        if user.get("notify_with") == enabled_notifications:
            del user["notify_with"]
            notes[(f"user.{name}", "notify_with")] = (
                "notify_with omitted: defaults to all enabled notifications"
            )


def compact(expanded: Dict[str, Any]) -> Tuple[Dict[str, Any], Notes]:
    """Hoist values shared by all items of a marketplace and merge identical sections."""
    cfg = copy.deepcopy(expanded)
    notes: Notes = {}
    _hoist(cfg, notes)
    _merge_notifications(cfg, notes)
    _remove_default_marketplace_bindings(cfg, notes)
    _drop_explicit_defaults(cfg, notes)
    _drop_implicit_all_lists(cfg, notes)
    return cfg, notes
