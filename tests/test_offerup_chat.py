"""The configure chat's live tools with OfferUp: read directly, without the monitor (#472)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from ai_marketplace_monitor.configure import live
from ai_marketplace_monitor.configure.item import ItemToolkit
from ai_marketplace_monitor.configure.marketplace import MarketplaceToolkit
from ai_marketplace_monitor.configure.tools import ToolExecutor
from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.marketplaces.base import SearchPage
from ai_marketplace_monitor.marketplaces.facebook import FacebookMarketplace
from ai_marketplace_monitor.marketplaces.offerup import OfferUpClient, OfferUpMarketplace
from tests.configure_util import BASE, make_ws, run_in_fresh_loop

LID = "8fd87e4a-8aa6-3b79-8168-26e6abb3353f"
OFFERUP_ONLY = (
    BASE + '\n[marketplace.offerup]\nsearch_city = "77002"\n[item.bike]\nsearch_phrases = "bike"\n'
)


@pytest.fixture(autouse=True)
def fake_offerup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> List[str]:
    """OfferUp's answers, and a cache of this test's own."""
    from diskcache import Cache  # type: ignore

    from ai_marketplace_monitor import ai, evaluations, listing, seller

    local = Cache(str(tmp_path / "cache"))
    for module in (ai, evaluations, listing, seller):
        monkeypatch.setattr(module, "cache", local)
    calls: List[str] = []

    def search(self: Any, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        calls.append(f"search {params['q']}")
        return [
            {"listingId": LID, "title": "Trek bike", "price": "300", "locationName": "Houston, TX"}
        ]

    def listing_details(self: Any, listing_id: str) -> Dict[str, Any]:
        calls.append(f"listing {listing_id}")
        return {
            "listingId": listing_id,
            "title": "Trek bike",
            "price": "300",
            "condition": 40,
            "description": "Good bike.",
            "postDate": datetime.now(timezone.utc).isoformat(),
            "state": "LISTED",
            "locationDetails": {"locationName": "Houston, TX"},
            "fulfillmentDetails": {"localPickupEnabled": True},
            "owner": {"id": 44, "profile": {"name": "Pat"}},
        }

    def profile(self: Any, user_id: str) -> Dict[str, Any]:
        calls.append(f"profile {user_id}")
        return {
            "name": "Pat",
            "dateJoined": "2015-01-01T00:00:00Z",
            "itemsSold": "12",
            "ratingSummary": {"count": 9, "average": 5},
        }

    monkeypatch.setattr(OfferUpClient, "search", search)
    monkeypatch.setattr(OfferUpClient, "listing", listing_details)
    monkeypatch.setattr(OfferUpClient, "profile", profile)
    return calls


def _kits() -> Dict[str, Any]:
    return {"marketplace": MarketplaceToolkit(), "item": ItemToolkit()}


async def _call(ex: ToolExecutor, tool: str, **args: Any) -> Dict[str, Any]:
    out = await ex.call(tool, args)
    out.pop("session_state", None)
    return out


def _run(tmp_path: Path, text: str, tool: str, **args: Any) -> Dict[str, Any]:
    async def scenario() -> Dict[str, Any]:
        ex = ToolExecutor(await make_ws(tmp_path, text, toolkits=_kits()))
        out = await _call(ex, tool, **args)
        ex.end()
        return out

    return run_in_fresh_loop(scenario)


def test_references_name_their_marketplace() -> None:
    assert live.listing_ref(f"https://offerup.com/item/detail/{LID}") == (OfferUpMarketplace, LID)
    assert live.listing_ref("https://www.facebook.com/marketplace/item/123/") == (
        FacebookMarketplace,
        "123",
    )
    assert live.listing_ref("https://example.com/x") is None
    assert live.seller_ref("https://offerup.com/p/44/") == (OfferUpMarketplace, "offerup:44", "")
    assert live.seller_ref("offerup:44") == (OfferUpMarketplace, "offerup:44", "")
    assert live.seller_ref("https://www.facebook.com/marketplace/profile/9/") == (
        FacebookMarketplace,
        "9",
        "",
    )
    assert live.seller_ref(f"offerup.com/item/detail/{LID}") == (OfferUpMarketplace, "", LID)


def test_an_offerup_listing_is_rated_without_the_monitor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_offerup: List[str]
) -> None:
    from ai_marketplace_monitor import monitor

    # no AI service is asked (the test config's key is not a real one)
    monkeypatch.setattr(monitor, "make_ai_agents", lambda config, logger=None: [])
    out = _run(
        tmp_path,
        OFFERUP_ONLY,
        "evaluate_listing",
        listing=f"https://offerup.com/item/detail/{LID}",
    )
    assert out["ok"], out
    assert out["listing"]["url"] == f"https://offerup.com/item/detail/{LID}"
    assert out["listing"]["condition"] == "Used"
    assert "joined OfferUp in 2015" in out["seller"]["summary"]
    assert out["ai_rated"] is False
    assert fake_offerup == [f"listing {LID}", "profile 44"]


def test_an_offerup_seller_is_checked_without_the_monitor(
    tmp_path: Path, fake_offerup: List[str]
) -> None:
    out = _run(tmp_path, OFFERUP_ONLY, "check_seller", seller="https://offerup.com/p/44/")
    assert out["ok"], out
    assert out["seller"]["id"] == "offerup:44"
    assert out["seller"]["profile"] == "https://offerup.com/p/44/"
    assert fake_offerup == ["profile 44"]


def test_an_item_of_facebook_and_offerup_is_tried_in_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_offerup: List[str]
) -> None:
    class FakeFacebook:
        def search_pages(self, item: Any) -> List[SearchPage]:
            return [
                SearchPage(city="houston", city_name="Houston", radius=40, phrase="bike", url="u")
            ]

        def read_search_page(self, search: SearchPage) -> List[Listing]:
            return [
                Listing(
                    marketplace="facebook",
                    name="",
                    id="1",
                    title="Giant bike",
                    image="",
                    price="$200",
                    post_url="https://www.facebook.com/marketplace/item/1/",
                    location="Houston, TX",
                    seller="",
                    condition="",
                    description="",
                )
            ]

        def exclusion_reason(
            self, listing: Any, item: Any, description_available: bool = True
        ) -> None:
            return None

    @contextmanager
    def fake_session(self: Any, config: Any, marketplace_config: Any) -> Iterator[Any]:
        yield FakeFacebook()

    monkeypatch.setattr(live.LiveBrowser, "_facebook", fake_session)
    text = (
        BASE
        + '\n[marketplace.facebook]\nsearch_city = "houston"\n'
        + '[marketplace.offerup]\nsearch_city = "77002"\n[item.bike]\nsearch_phrases = "bike"\n'
    )
    out = _run(tmp_path, text, "try_item", item="bike")
    assert out["ok"], out
    assert [s["marketplace"] for s in out["searches"]] == ["facebook", "offerup"]
    assert sorted(x["marketplace"] for x in out["listings"]) == ["facebook", "offerup"]
    assert fake_offerup == ["search bike"]  # no listing page, no seller: search results only


def test_an_item_not_searched_on_facebook_cannot_rate_a_facebook_listing(tmp_path: Path) -> None:
    out = _run(
        tmp_path,
        OFFERUP_ONLY,
        "evaluate_listing",
        listing="https://www.facebook.com/marketplace/item/1/",
    )
    assert not out["ok"] and "is not searched in a Facebook marketplace" in out["errors"][0]
