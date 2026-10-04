from dataclasses import fields
from types import SimpleNamespace

import pytest

from ai_marketplace_monitor.facebook import FacebookMarketItemCommonConfig
from ai_marketplace_monitor.marketplace import (
    COMMON_OPTION_FALLBACK,
    Fallback,
    MarketItemCommonConfig,
    resolve_option,
)
from ai_marketplace_monitor.utils import BaseConfig


def test_table_covers_every_common_option_except_search_region() -> None:
    base = {f.name for f in fields(BaseConfig)}
    common = {
        f.name
        for cls in (MarketItemCommonConfig, FacebookMarketItemCommonConfig)
        for f in fields(cls)
    } - base
    assert set(COMMON_OPTION_FALLBACK) == common - {"search_region"}


@pytest.mark.parametrize(
    "key", [k for k, rule in COMMON_OPTION_FALLBACK.items() if rule is Fallback.TRUTHY]
)
def test_truthy_rule(key: str) -> None:
    market = SimpleNamespace(**{key: ["m"]})
    assert resolve_option(key, SimpleNamespace(**{key: None}), market) == ["m"]
    assert resolve_option(key, SimpleNamespace(**{key: []}), market) == ["m"]
    assert resolve_option(key, SimpleNamespace(**{key: ["i"]}), market) == ["i"]


@pytest.mark.parametrize(
    "key", [k for k, rule in COMMON_OPTION_FALLBACK.items() if rule is Fallback.NOT_NONE]
)
def test_not_none_rule(key: str) -> None:
    market = SimpleNamespace(**{key: ["m"]})
    assert resolve_option(key, SimpleNamespace(**{key: None}), market) == ["m"]
    assert resolve_option(key, SimpleNamespace(**{key: []}), market) == []


def test_expected_not_none_keys() -> None:
    not_none = {k for k, rule in COMMON_OPTION_FALLBACK.items() if rule is Fallback.NOT_NONE}
    assert not_none == {
        "ai",
        "exclude_sellers",
        "seller_locations",
        "prompt",
        "extra_prompt",
        "rating_prompt",
    }


def test_ai_prompt_site_prices_are_item_only() -> None:
    item, market = SimpleNamespace(min_price=None), SimpleNamespace(min_price="100")
    assert resolve_option("min_price", item, market, site="ai_prompt") is None
    assert resolve_option("min_price", item, market) == "100"
