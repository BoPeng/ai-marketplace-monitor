from dataclasses import dataclass, fields
from typing import Any

from ai_marketplace_monitor.facebook import FacebookItemConfig, FacebookMarketItemCommonConfig
from ai_marketplace_monitor.marketplace import (
    Fallback,
    MarketItemCommonConfig,
    option,
    option_fallbacks,
    resolve_option,
)
from ai_marketplace_monitor.utils import BaseConfig


@dataclass
class _Options:
    """Stand-in config declaring one option per rule."""

    truthy: Any = option(Fallback.TRUTHY)
    not_none: Any = option(Fallback.NOT_NONE)
    price: Any = option(Fallback.TRUTHY, item_only_in=("ai_prompt",))


def test_every_common_option_except_search_region_declares_a_rule() -> None:
    base = {f.name for f in fields(BaseConfig)}
    common = {
        f.name
        for cls in (MarketItemCommonConfig, FacebookMarketItemCommonConfig)
        for f in fields(cls)
    } - base
    assert set(option_fallbacks(FacebookItemConfig)) == common - {"search_region"}


def test_truthy_rule() -> None:
    market = _Options(truthy=["m"])
    assert resolve_option("truthy", _Options(truthy=None), market) == ["m"]
    assert resolve_option("truthy", _Options(truthy=[]), market) == ["m"]
    assert resolve_option("truthy", _Options(truthy=["i"]), market) == ["i"]


def test_not_none_rule() -> None:
    market = _Options(not_none=["m"])
    assert resolve_option("not_none", _Options(not_none=None), market) == ["m"]
    assert resolve_option("not_none", _Options(not_none=[]), market) == []
    assert resolve_option("not_none", _Options(not_none=["i"]), market) == ["i"]


def test_item_only_site() -> None:
    item, market = _Options(price=None), _Options(price="100")
    assert resolve_option("price", item, market, site="ai_prompt") is None
    assert resolve_option("price", item, market) == "100"
