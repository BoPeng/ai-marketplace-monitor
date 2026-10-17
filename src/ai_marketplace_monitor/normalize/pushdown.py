"""Move common options from marketplaces into the items bound to them."""

import copy
from typing import Any, Dict, List, Optional, Set, Tuple

from ..marketplaces.base import Fallback
from .model import (
    AI_PROMPT_ITEM_ONLY,
    COMMON_OPTIONS,
    LOCATION_KEYS,
    OPTION_FALLBACK,
    NormalizeError,
)

Notes = Dict[Tuple[str, Optional[str]], str]
_ABSENT = object()


def bound_marketplaces(item_raw: Dict[str, Any], marketplaces: Dict[str, Any]) -> List[str]:
    """Marketplaces an item is searched in: its `marketplace` (a name or a list), else all."""
    value = item_raw.get("marketplace")
    if not value:
        return list(marketplaces)
    return [value] if isinstance(value, str) else list(dict.fromkeys(value))


def bound_marketplace(item_raw: Dict[str, Any], marketplaces: Dict[str, Any]) -> str:
    """The first marketplace an item is searched in."""
    bound = bound_marketplaces(item_raw, marketplaces)
    return bound[0] if bound else next(iter(marketplaces))


def _falls_back(key: str, item_raw: Dict[str, Any]) -> bool:
    if key not in item_raw:
        return True
    return OPTION_FALLBACK.get(key) is Fallback.TRUTHY and not item_raw[key]


def _location_keys(
    item_name: str, item_raw: Dict[str, Any], market_name: str, market_raw: Dict[str, Any]
) -> Set[str]:
    """Location keys to copy from the marketplace into the item.

    A `search_region` replaces all four other location keys of the section that sets it
    (`Config.expand_regions`), so the marketplace's raw city keys are dead when it has a
    region, and the item's own region makes the marketplace's location irrelevant.
    """
    if "search_region" in item_raw:
        return set()
    if "search_region" not in market_raw:
        return {k for k in LOCATION_KEYS if k in market_raw and _falls_back(k, item_raw)}
    if _falls_back("search_city", item_raw):
        # loading rejects city_name/radius/currency without search_city, so the region
        # (which supplies all four keys) is all the item inherits
        return {"search_region"}
    missing = [k for k in ("radius", "currency") if _falls_back(k, item_raw)]
    if missing:
        keys = ", ".join(missing)
        raise NormalizeError(
            f"Item {item_name} sets its own search_city but inherits {keys} from the "
            f"search_region of marketplace {market_name}; set {keys} on the item "
            "or give it its own search_region."
        )
    return set()


def push_down(cfg: Dict[str, Any]) -> Notes:
    """Make every item self-contained; return change notes keyed by (section, key)."""
    notes: Notes = {}
    markets: Dict[str, Any] = cfg.get("marketplace", {})
    users = list(cfg.get("user", {}))
    ais = list(cfg.get("ai", {}))
    for item_name, item in cfg.get("item", {}).items():
        label = f"item.{item_name}"
        targets = bound_marketplaces(item, markets)
        if len(targets) == 1:
            market_name = targets[0]
            market = markets[market_name]
            location = _location_keys(item_name, item, market_name, market)
            for key in COMMON_OPTIONS:
                if key in LOCATION_KEYS:
                    copy_it = key in location
                else:
                    copy_it = key in market and _falls_back(key, item)
                if copy_it:
                    item[key] = copy.deepcopy(market[key])
                    extra = (
                        " (now also used in the AI prompt)" if key in AI_PROMPT_ITEM_ONLY else ""
                    )
                    notes[(label, key)] = f"{key} copied from marketplace.{market_name}{extra}"
        else:
            # searched in several marketplaces: only what they all set alike can move into the
            # item; their locations stay theirs
            for key in COMMON_OPTIONS:
                if key in LOCATION_KEYS or not _falls_back(key, item):
                    continue
                values = [markets[m].get(key, _ABSENT) for m in targets]
                if values[0] is _ABSENT or any(v != values[0] for v in values):
                    continue
                item[key] = copy.deepcopy(values[0])
                extra = " (now also used in the AI prompt)" if key in AI_PROMPT_ITEM_ONLY else ""
                notes[(label, key)] = f"{key} copied from marketplaces {', '.join(targets)}{extra}"
        if not item.get("notify"):
            item["notify"] = list(users)
            notes[(label, "notify")] = "notify made explicit: all users"
        if "ai" not in item and ais:
            item["ai"] = list(ais)
            notes[(label, "ai")] = "ai made explicit: all AI backends"
    searching: Dict[str, List[Dict[str, Any]]] = {name: [] for name in markets}
    for item in cfg.get("item", {}).values():
        for market_name in bound_marketplaces(item, markets):
            searching[market_name].append(item)
    for market_name, market in markets.items():
        # a marketplace without items keeps its options as defaults for future items
        if not searching[market_name]:
            continue
        shared = [it for it in searching[market_name] if len(bound_marketplaces(it, markets)) > 1]
        has_region = "search_region" in market
        for key in COMMON_OPTIONS:
            if key not in market:
                continue
            # an item that is also searched elsewhere still reads what it did not get
            if any(key not in item for item in shared):
                continue
            del market[key]
            if has_region and key in LOCATION_KEYS and key != "search_region":
                detail = f"{key} removed: overridden by search_region"
            else:
                detail = f"{key} moved into items"
            notes[(f"marketplace.{market_name}", key)] = detail
    return notes
