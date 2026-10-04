# tests/test_option_fallback.py
"""Pin how item options fall back to marketplace options at each runtime use site."""

from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest

from ai_marketplace_monitor.ai import AIResponse, OllamaBackend, OllamaConfig
from ai_marketplace_monitor.facebook import (
    FacebookItemConfig,
    FacebookMarketplace,
    FacebookMarketplaceConfig,
)
from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.monitor import MarketplaceMonitor


def _market(**kwargs: Any) -> FacebookMarketplaceConfig:
    kwargs.setdefault("search_city", ["houston"])
    return FacebookMarketplaceConfig(name="facebook", **kwargs)


def _item(**kwargs: Any) -> FacebookItemConfig:
    return FacebookItemConfig(name="bike", search_phrases=["bike"], **kwargs)


def _search_urls(item: FacebookItemConfig, market: FacebookMarketplaceConfig) -> List[str]:
    mp = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=None)
    mp.configure(market)
    mp.page = MagicMock()
    urls: List[str] = []
    # ruff targets py39, so no parenthesized context managers
    with patch.object(mp, "goto_url", side_effect=urls.append), patch(
        "ai_marketplace_monitor.facebook.FacebookSearchResultPage"
    ) as page_cls, patch("ai_marketplace_monitor.facebook.time.sleep"), patch(
        "ai_marketplace_monitor.facebook.counter"
    ):
        page_cls.return_value.get_listings.return_value = []
        list(mp.search(item))
    return urls


@pytest.mark.parametrize(
    ("key", "item_value", "market_value", "fragment"),
    [
        ("condition", None, ["new"], "itemCondition=new"),
        ("condition", ["used_good"], ["new"], "itemCondition=used_good"),
        ("date_listed", None, [7], "daysSinceListed=7"),
        ("date_listed", [1], [7], "daysSinceListed=1"),
        ("delivery_method", None, ["shipping"], "deliveryMethod=shipping"),
        ("availability", None, ["out"], "availability=out"),
        ("sort_by", None, "new", "sortBy=creation_time_descend"),
        ("max_price", None, "300", "maxPrice=300"),
        ("max_price", "200", "300", "maxPrice=200"),
        ("min_price", None, "100", "minPrice=100"),
        ("category", None, "electronics", "category=electronics"),
    ],
)
def test_search_url_option_fallback(
    key: str, item_value: Any, market_value: Any, fragment: str
) -> None:
    item = _item(**({key: item_value} if item_value is not None else {}))
    url = _search_urls(item, _market(**{key: market_value}))[0]
    assert fragment in url


def test_search_city_empty_item_list_falls_back_to_marketplace() -> None:
    url = _search_urls(_item(search_city=[]), _market(search_city=["houston"]))[0]
    assert url.startswith("https://www.facebook.com/marketplace/houston/search?")


def test_search_city_item_overrides_marketplace() -> None:
    url = _search_urls(_item(search_city=["dallas"]), _market(search_city=["houston"]))[0]
    assert url.startswith("https://www.facebook.com/marketplace/dallas/search?")


def test_radius_from_marketplace_when_item_unset() -> None:
    url = _search_urls(_item(), _market(search_city=["houston"], radius=[50]))[0]
    assert "radius=50" in url


def _check(item: FacebookItemConfig, market: FacebookMarketplaceConfig, listing: Listing) -> bool:
    mp = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=None)
    mp.configure(market)
    return mp.check_listing(listing, item, description_available=False)


def test_seller_locations_empty_item_list_wins(listing: Listing) -> None:
    assert _check(_item(seller_locations=[]), _market(seller_locations=["dallas"]), listing)


def test_seller_locations_unset_item_uses_marketplace(listing: Listing) -> None:
    assert not _check(_item(), _market(seller_locations=["dallas"]), listing)


def test_exclude_sellers_empty_item_list_wins(listing: Listing) -> None:
    assert _check(_item(exclude_sellers=[]), _market(exclude_sellers=["some guy"]), listing)


def test_exclude_sellers_unset_item_uses_marketplace(listing: Listing) -> None:
    assert not _check(_item(), _market(exclude_sellers=["some guy"]), listing)


def _prompt(
    item: FacebookItemConfig, market: FacebookMarketplaceConfig, listing: Listing
) -> str:
    config = OllamaConfig(name="ollama", base_url="http://localhost:11434", model="m")
    return OllamaBackend(config, logger=None).get_prompt(listing, item, market)


def test_prompt_empty_item_string_wins(listing: Listing) -> None:
    assert "MARKET PROMPT" not in _prompt(_item(prompt=""), _market(prompt="MARKET PROMPT"), listing)


def test_prompt_unset_item_uses_marketplace(listing: Listing) -> None:
    assert "MARKET PROMPT" in _prompt(_item(), _market(prompt="MARKET PROMPT"), listing)


def test_extra_prompt_unset_item_uses_marketplace(listing: Listing) -> None:
    assert "MARKET EXTRA" in _prompt(_item(), _market(extra_prompt="MARKET EXTRA"), listing)


def test_rating_prompt_unset_item_uses_marketplace(listing: Listing) -> None:
    assert "MARKET RATING" in _prompt(_item(), _market(rating_prompt="MARKET RATING"), listing)


def test_ai_prompt_price_ignores_marketplace(listing: Listing) -> None:
    assert "Max price" not in _prompt(_item(), _market(max_price="300"), listing)


def test_ai_prompt_price_uses_item(listing: Listing) -> None:
    assert "Max price 200" in _prompt(_item(max_price="200"), _market(max_price="300"), listing)


def _monitor(*agent_names: str) -> MarketplaceMonitor:
    monitor = MarketplaceMonitor.__new__(MarketplaceMonitor)
    monitor.logger = None
    agents = []
    for name in agent_names:
        agent = MagicMock()
        agent.config.name = name
        agent.evaluate.return_value = name
        agents.append(agent)
    monitor.ai_agents = agents
    return monitor


def test_ai_empty_item_list_disables_ai(listing: Listing) -> None:
    monitor = _monitor("openai")
    result = monitor.evaluate_by_ai(listing, _item(ai=[]), _market(ai=["openai"]))
    assert isinstance(result, AIResponse)
    monitor.ai_agents[0].evaluate.assert_not_called()


def test_ai_unset_item_uses_marketplace(listing: Listing) -> None:
    monitor = _monitor("openai", "claude")
    assert monitor.evaluate_by_ai(listing, _item(), _market(ai=["claude"])) == "claude"


def test_ai_unset_everywhere_uses_all_agents(listing: Listing) -> None:
    monitor = _monitor("openai", "claude")
    assert monitor.evaluate_by_ai(listing, _item(), _market()) == "openai"
