"""Move common options from marketplaces into the items bound to them."""

import copy
from typing import Any, Dict, Optional, Set, Tuple

from ..marketplace import COMMON_OPTION_FALLBACK, Fallback
from .model import AI_PROMPT_ITEM_ONLY, COMMON_OPTIONS, LOCATION_KEYS, NormalizeError

Notes = Dict[Tuple[str, Optional[str]], str]


def bound_marketplace(item_raw: Dict[str, Any], marketplaces: Dict[str, Any]) -> str:
    """Marketplace an item is searched in: its `marketplace` key, else the first one."""
    return item_raw.get("marketplace") or next(iter(marketplaces))


def _falls_back(key: str, item_raw: Dict[str, Any]) -> bool:
    if key not in item_raw:
        return True
    return COMMON_OPTION_FALLBACK.get(key) is Fallback.TRUTHY and not item_raw[key]


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
        market_name = bound_marketplace(item, markets)
        market = markets[market_name]
        location = _location_keys(item_name, item, market_name, market)
        for key in COMMON_OPTIONS:
            if key in LOCATION_KEYS:
                copy_it = key in location
            else:
                copy_it = key in market and _falls_back(key, item)
            if copy_it:
                item[key] = copy.deepcopy(market[key])
                extra = " (now also used in the AI prompt)" if key in AI_PROMPT_ITEM_ONLY else ""
                notes[(label, key)] = f"{key} copied from marketplace.{market_name}{extra}"
        if not item.get("notify"):
            item["notify"] = list(users)
            notes[(label, "notify")] = "notify made explicit: all users"
        if "ai" not in item and ais:
            item["ai"] = list(ais)
            notes[(label, "ai")] = "ai made explicit: all AI backends"
    for market_name, market in markets.items():
        has_region = "search_region" in market
        for key in COMMON_OPTIONS:
            if key not in market:
                continue
            del market[key]
            if has_region and key in LOCATION_KEYS[1:]:
                detail = f"{key} removed: overridden by search_region"
            else:
                detail = f"{key} moved into items"
            notes[(f"marketplace.{market_name}", key)] = detail
    return notes
