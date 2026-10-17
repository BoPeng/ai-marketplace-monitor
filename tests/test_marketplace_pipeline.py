"""The search pipeline of the Marketplace base class, with a marketplace that needs no browser."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.marketplaces.base import Marketplace, SearchPage
from ai_marketplace_monitor.marketplaces.facebook import (
    FacebookItemConfig,
    FacebookMarketplaceConfig,
)
from ai_marketplace_monitor.seller import Seller


def _card(lid: str, title: str) -> Listing:
    return Listing(
        marketplace="http",
        name="",
        id=lid,
        title=title,
        image="",
        price="$100",
        post_url=f"https://market.example/item/{lid}?ref=search",
        location="Houston, TX",
        seller="",
        condition="",
        description="",
    )


class HttpMarketplace(Marketplace):
    """Searched over HTTP: implements only the site-specific steps."""

    market_type = "http"
    needs_browser = False
    search_page_delay = listing_page_delay = profile_page_delay = 0

    def __init__(self) -> None:
        super().__init__("http", None)
        self.calls: List[str] = []

    def search_pages(self, item_config: Any) -> List[SearchPage]:
        return [
            SearchPage(city="77002", city_name=None, radius=None, phrase=phrase, url=phrase)
            for phrase in item_config.search_phrases
        ]

    def read_search_page(self, search: SearchPage) -> List[Listing]:
        self.calls.append(f"search {search.phrase}")
        return {
            "bike": [_card("1", "Trek road bike"), _card("2", "Road bike, broken frame")],
            "trek": [_card("1", "Trek road bike"), _card("3", "Trek hybrid")],
        }[search.phrase]

    def get_listing_details(
        self,
        post_url: str,
        item_config: Any,
        price: str | None = None,
        title: str | None = None,
    ) -> Tuple[Listing, bool]:
        lid = post_url.split("/item/")[1].split("?")[0]
        self.calls.append(f"listing {lid}")
        details = _card(lid, title or "")
        details.description = "Good condition."
        details.seller = f"Seller {lid}"
        details.seller_id = f"s{lid}"
        return details, False

    def read_seller_profile(self, seller_id: str, item_config: Any = None) -> Seller:
        self.calls.append(f"seller {seller_id}")
        return Seller(id=seller_id, name="Pat", joined_year=2010, rating=4.9, rating_count=40)


@pytest.fixture(autouse=True)
def aimm_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from diskcache import Cache  # type: ignore

    from ai_marketplace_monitor import evaluations, listing, seller

    local = Cache(str(tmp_path / "cache"))
    for module in (evaluations, listing, seller):
        monkeypatch.setattr(module, "cache", local)
    return local


def test_the_base_class_runs_the_search_of_a_marketplace_without_a_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ai_marketplace_monitor.marketplaces import base

    seen: List[Tuple[str, str]] = []
    monkeypatch.setattr(
        base, "record_seen", lambda market, lid, item, price: seen.append((market, lid))
    )
    recorded: List[Dict[str, Any]] = []
    monkeypatch.setattr(
        base, "record_evaluation", lambda record: recorded.append(dict(vars(record)))
    )

    marketplace = HttpMarketplace()
    marketplace.configure(FacebookMarketplaceConfig(name="http", search_city=["77002"]))
    item = FacebookItemConfig(
        name="bike", search_phrases=["bike", "trek"], antikeywords=["broken"]
    )
    found = list(marketplace.search(item))

    assert [x.id for x in found] == ["1", "3"]
    # each listing once; the excluded one is not opened; each seller's profile is read
    assert marketplace.calls == [
        "search bike",
        "listing 1",
        "seller s1",
        "search trek",
        "listing 3",
        "seller s3",
    ]
    assert seen == [("http", "1"), ("http", "2"), ("http", "3")]  # the marketplace's type
    assert [(r["id"], r["reason"]) for r in recorded] == [("2", "excluded keyword: broken")]
    assert found[0].seller_info["seller"]["rating"] == 4.9
    assert item.searched_count == 1
