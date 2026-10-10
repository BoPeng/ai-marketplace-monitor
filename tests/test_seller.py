"""Seller information: parsing what Facebook shows, caching it, and the warning signs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from diskcache import Cache  # type: ignore

from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.seller import (
    Seller,
    count_listing_tiles,
    parse_seller_panel,
    parse_seller_profile,
    seller_id_from_url,
    seller_warnings,
)
from ai_marketplace_monitor.utils import Translator

# the shapes Facebook used on 2026-10-10 (names made up)
PANEL_RATED = """Seller information
Seller details
Pat Doe
(182)
Highly rated on Marketplace
Joined Facebook in 2009"""
PANEL_RATED_LABELS = ["4.6 out of 5 stars, From one review'"]
PANEL_NEW = """Seller information
Seller details
Sam Roe
Joined Facebook in 2025"""

PROFILE_RATED = """4.6 (182)
Pat Doe
Joined Facebook in 2009
20+ active listings
 · 115 followers
Follow
Message
Badge
Highly rated
4.5-stars or higher rating from at least 5 buyers
Seller ratings
Based on 182 ratings"""
PROFILE_REVIEWS = (
    PROFILE_RATED
    + """
Pat's strengths
Here's what buyers appreciate about Pat:
Item description (85)
Shipping Speed (84)
Communication (67)
Seller reviews (180)
Hai
August 29, 2026
Notable:
Punctuality

· Communication
Friendly and helpful. I would recommend Pat.
Like
\ufeff
0
Lee
August 3, 2026
Never showed up and stopped answering messages.
Like
1"""
)
PROFILE_SHOP = """Corner Wireless
Joined Facebook in 2024
20+ active listings
Follow
Message
About
Lives in Houston, Texas"""
PROFILE_ONE = """Sam Roe
Joined Facebook in 2025
1 active listing
Follow"""


def test_seller_id_from_a_profile_link() -> None:
    assert seller_id_from_url("/marketplace/profile/571956381/?ref=x") == "571956381"
    assert seller_id_from_url("https://www.facebook.com/marketplace/profile/61568279347481/") == (
        "61568279347481"
    )
    assert seller_id_from_url("/profile.php?id=1") == ""


def test_the_seller_panel_of_a_listing() -> None:
    rated = parse_seller_panel(PANEL_RATED, PANEL_RATED_LABELS, "1", name="Pat Doe")
    assert (rated.joined_year, rated.rating, rated.rating_count, rated.highly_rated) == (
        2009,
        4.6,
        182,
        True,
    )
    new = parse_seller_panel(PANEL_NEW, [], "2", name="Sam Roe")
    assert (new.joined_year, new.rating, new.rating_count, new.highly_rated) == (
        2025,
        None,
        None,
        False,
    )
    # stars without a number of ratings are not the seller's
    assert parse_seller_panel(PANEL_NEW, ["5 out of 5 stars"], "2").rating is None


def test_the_seller_profile() -> None:
    rated = parse_seller_profile(PROFILE_RATED, ["4.6 out of 5 rating"], "1")
    assert (rated.rating, rated.rating_count, rated.active_listings) == (4.6, 182, 20)
    assert rated.active_listings_capped and rated.highly_rated and rated.profile_checked
    shop = parse_seller_profile(PROFILE_SHOP, [], "3")
    assert (shop.joined_year, shop.active_listings, shop.rating) == (2024, 20, None)
    one = parse_seller_profile(PROFILE_ONE, [], "2")
    assert (one.active_listings, one.active_listings_capped) == (1, False)


def test_what_buyers_say() -> None:
    seller = parse_seller_profile(PROFILE_REVIEWS, [], "1")
    assert seller.strengths == [
        "Item description (85)",
        "Shipping Speed (84)",
        "Communication (67)",
    ]
    assert seller.reviews == [
        "Notable: Punctuality Communication Friendly and helpful. I would recommend Pat.",
        "Never showed up and stopped answering messages.",
    ]
    assert seller.summary().endswith(
        'Recent reviews: "Notable: Punctuality Communication Friendly and helpful. I would '
        'recommend Pat." | "Never showed up and stopped answering messages."'
    )


def test_translated_pages() -> None:
    translator = Translator(
        dictionary={"Joined Facebook in": "Membre de Facebook depuis", "active listing": "annonce"}
    )
    seller = parse_seller_profile(
        "Pat\nMembre de Facebook depuis 2019\n3 annonces actives", [], "1", translator=translator
    )
    assert (seller.joined_year, seller.active_listings) == (2019, 3)


def test_sold_listings_are_counted_from_their_tiles() -> None:
    labels = [
        "iPhone 14 128GB unlocked, $350, reduced from $400, Houston, TX, listing 1417940473406809",
        "Inventory availability status",
        "iPhone 13, $300, Houston, TX, listing 1",
        "iPhone 13, $300, Houston, TX, listing 1",
    ]
    assert count_listing_tiles(labels) == 2


@pytest.mark.parametrize(
    "seller, expected",
    [
        (Seller(id="1", joined_year=2009, rating=4.6, rating_count=182), []),
        (Seller(id="1", joined_year=2025), ["new account (joined Facebook in 2025)"]),
        (
            Seller(id="1", joined_year=2015, rating=3.2, rating_count=10),
            ["low rating (3.2 out of 5 from 10)"],
        ),
        # one bad rating is not enough
        (Seller(id="1", joined_year=2015, rating=1.0, rating_count=1), []),
        (
            Seller(
                id="1",
                joined_year=2015,
                active_listings=20,
                active_listings_capped=True,
                sold_listings=1,
            ),
            [
                "20+ active listings, likely a dealer or a shop",
                "20+ active listings but only 1 sold",
            ],
        ),
        (
            Seller(id="1", joined_year=2015, active_listings=6, sold_listings=0),
            ["6 active listings but none sold"],
        ),
        (
            Seller(id="1", joined_year=2026, active_listings=1),
            [
                "new account (joined Facebook in 2026)",
                "a single listing on a new account, a pattern of bait listings: "
                "check that the price is realistic",
            ],
        ),
    ],
)
def test_warning_signs(seller: Seller, expected: list) -> None:
    assert seller_warnings(seller, year=2026) == expected


def test_thresholds_can_be_changed_or_disabled() -> None:
    seller = Seller(id="1", joined_year=2025, rating=3.5, rating_count=5, active_listings=12)
    assert seller_warnings(seller, year=2026) == [
        "new account (joined Facebook in 2025)",
        "low rating (3.5 out of 5 from 5)",
    ]
    assert seller_warnings(seller, 0, 0, 10, year=2026) == [
        "12 active listings, likely a dealer or a shop"
    ]


def test_the_summary_for_the_ai_and_the_buyer() -> None:
    seller = Seller(
        id="1",
        joined_year=2024,
        rating=4.6,
        rating_count=182,
        highly_rated=True,
        active_listings=20,
        active_listings_capped=True,
        sold_listings=1,
        profile_checked=True,
    )
    assert seller.summary() == (
        "joined Facebook in 2024, rated 4.6 out of 5 by 182 buyers, badge: highly rated on "
        "Marketplace, 20+ active listings, 1 sold listing"
    )
    assert Seller(id="2", joined_year=2025).summary() == "joined Facebook in 2025, no ratings"


def test_sellers_are_cached(tmp_path: Path) -> None:
    local = Cache(str(tmp_path))
    Seller(id="7", name="Pat", joined_year=2020, profile_checked=True).to_cache(local)
    cached = Seller.from_cache("7", local)
    assert cached is not None and cached.joined_year == 2020 and cached.profile_checked
    assert Seller.from_cache("8", local) is None
    assert Seller.from_cache("", local) is None


def test_a_later_reading_completes_an_earlier_one() -> None:
    seller = Seller(id="1", name="Pat", joined_year=2020, active_listings=4, profile_checked=True)
    seller.update(Seller(id="1", rating=4.9, rating_count=12))
    assert (seller.joined_year, seller.active_listings, seller.rating) == (2020, 4, 4.9)


def test_a_count_of_zero_is_kept() -> None:
    """0 == False in Python: a profile with nothing sold must still say so."""
    seller = Seller(id="1", joined_year=2015)
    seller.update(Seller(id="1", active_listings=8, sold_listings=0, profile_checked=True))
    assert seller.sold_listings == 0
    assert seller_warnings(seller, year=2026) == ["8 active listings but none sold"]


def _listing(**kwargs: Any) -> Listing:
    values: dict[str, Any] = {
        "marketplace": "facebook",
        "name": "ipad",
        "id": "1",
        "title": "iPad",
        "image": "",
        "price": "$200",
        "post_url": "https://www.facebook.com/marketplace/item/1/",
        "location": "Houston, TX",
        "seller": "Sam Roe",
        "condition": "used",
        "description": "works",
    }
    values.update(kwargs)
    return Listing(**values)


def test_seller_information_does_not_change_the_listing_hash() -> None:
    """Cached AI answers and notifications stay valid."""
    plain = _listing()
    with_seller = _listing(seller_id="2", seller_info={"warnings": ["new account"]})
    assert plain.hash == with_seller.hash


def test_cached_listings_without_seller_fields_still_load(tmp_path: Path) -> None:
    from dataclasses import asdict

    local = Cache(str(tmp_path))
    old = asdict(_listing())
    del old["seller_id"], old["seller_info"]
    local.set(("listing-details", "https://www.facebook.com/marketplace/item/1/"), old)
    loaded = Listing.from_cache("https://www.facebook.com/marketplace/item/1/", local)
    assert loaded is not None and loaded.seller_info == {}


def test_the_ai_prompt_describes_the_seller_and_its_warning_signs() -> None:
    from ai_marketplace_monitor.ai import OpenAIBackend, OpenAIConfig
    from ai_marketplace_monitor.facebook import FacebookItemConfig, FacebookMarketplaceConfig

    backend = OpenAIBackend(OpenAIConfig(name="openai", api_key="sk-test"))
    item = FacebookItemConfig(name="ipad", search_phrases=["ipad"])
    market = FacebookMarketplaceConfig(name="facebook")
    listing = _listing(
        seller_info={
            "summary": "joined Facebook in 2025, no ratings, 1 active listing",
            "warnings": ["new account (joined Facebook in 2025)"],
        }
    )
    prompt = backend.get_prompt(listing, item, market)
    assert (
        "About the seller, Sam Roe: joined Facebook in 2025, no ratings, 1 active listing."
        in prompt
    )
    assert "Possible warning signs: new account (joined Facebook in 2025)." in prompt
    assert "whether the seller is legitimate" in prompt
    # nothing about the seller without seller information
    assert "About the seller" not in backend.get_prompt(_listing(), item, market)


# --- the marketplace: the rating filter, completing seller information, notifications
def _marketplace(local: Cache, **kwargs: Any) -> Any:
    from unittest.mock import MagicMock

    from ai_marketplace_monitor.facebook import FacebookMarketplace, FacebookMarketplaceConfig

    mp = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=None)
    mp.configure(FacebookMarketplaceConfig(name="facebook", search_city=["houston"], **kwargs))
    mp.page = MagicMock()
    return mp


def _item_config(**kwargs: Any) -> Any:
    from ai_marketplace_monitor.facebook import FacebookItemConfig

    return FacebookItemConfig(name="ipad", search_phrases=["ipad"], **kwargs)


def _rated(rating: float, count: int) -> Listing:
    return _listing(
        seller_id="1",
        seller_info={"seller": {"id": "1", "rating": rating, "rating_count": count}},
    )


def test_seller_min_rating_excludes_low_rated_sellers(tmp_path: Path) -> None:
    mp = _marketplace(Cache(str(tmp_path)), seller_min_rating=4)
    item = _item_config()
    assert mp.exclusion_reason(_rated(3.5, 10), item) == "seller rated 3.5 out of 5"
    assert mp.exclusion_reason(_rated(4.5, 10), item) is None
    assert mp.exclusion_reason(_rated(1.0, 2), item) is None  # too few ratings
    assert mp.exclusion_reason(_listing(), item) is None  # no ratings
    # the item can turn it off
    assert mp.exclusion_reason(_rated(3.5, 10), _item_config(seller_min_rating=0)) is None


@pytest.mark.parametrize("value", [6, -1, "four", True])
def test_seller_min_rating_must_be_0_to_5(value: Any) -> None:
    with pytest.raises(ValueError, match="seller_min_rating"):
        _item_config(seller_min_rating=value)


def test_seller_information_is_completed_from_the_profile_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ai_marketplace_monitor.seller as seller_module
    from ai_marketplace_monitor import facebook

    local = Cache(str(tmp_path))
    monkeypatch.setattr(seller_module, "cache", local)
    monkeypatch.setattr(facebook.time, "sleep", lambda s: None)
    opened: list = []

    class FakeProfile:
        def __init__(self, *args: Any) -> None:
            pass

        def parse(self, seller_id: str) -> Seller:
            opened.append(seller_id)
            return Seller(
                id=seller_id, active_listings=1, profile_checked=True, reviews=["No show."]
            )

    monkeypatch.setattr(facebook, "FacebookSellerProfilePage", FakeProfile)
    mp = _marketplace(local)
    listing = _listing(
        seller_id="9", seller_info={"seller": {"id": "9", "name": "Sam Roe", "joined_year": 2026}}
    )
    mp.add_seller_info(listing, _item_config())
    assert opened == ["9"]
    assert listing.seller_info["summary"] == (
        'joined Facebook in 2026, no ratings, 1 active listing. Recent reviews: "No show."'
    )
    assert listing.seller_info["warnings"][0] == "new account (joined Facebook in 2026)"
    # the next listing of the same seller uses the cached profile
    again = _listing(seller_id="9", seller_info={"seller": {"id": "9", "joined_year": 2026}})
    mp.add_seller_info(again, _item_config())
    assert opened == ["9"] and again.seller_info["seller"]["active_listings"] == 1


def test_a_profile_rating_can_exclude_the_seller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rating known only from the profile (or the cache) is checked after enrichment."""
    import ai_marketplace_monitor.seller as seller_module
    from ai_marketplace_monitor import facebook

    local = Cache(str(tmp_path))
    monkeypatch.setattr(seller_module, "cache", local)
    monkeypatch.setattr(facebook.time, "sleep", lambda s: None)

    class FakeProfile:
        def __init__(self, *args: Any) -> None:
            pass

        def parse(self, seller_id: str) -> Seller:
            return Seller(id=seller_id, rating=2.5, rating_count=12, profile_checked=True)

    monkeypatch.setattr(facebook, "FacebookSellerProfilePage", FakeProfile)
    mp = _marketplace(local, seller_min_rating=4)
    listing = _listing(seller_id="9", seller_info={"seller": {"id": "9", "joined_year": 2015}})
    item = _item_config()
    assert mp.exclusion_reason(listing, item) is None  # the listing page showed no rating
    mp.add_seller_info(listing, item)
    assert mp.exclusion_reason(listing, item) == "seller rated 2.5 out of 5"


def test_a_failed_profile_keeps_what_the_listing_showed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ai_marketplace_monitor.seller as seller_module
    from ai_marketplace_monitor import facebook

    local = Cache(str(tmp_path))
    monkeypatch.setattr(seller_module, "cache", local)

    class BrokenProfile:
        def __init__(self, *args: Any) -> None:
            pass

        def parse(self, seller_id: str) -> Seller:
            raise ValueError("No seller profile found")

    monkeypatch.setattr(facebook, "FacebookSellerProfilePage", BrokenProfile)
    mp = _marketplace(local)
    listing = _listing(seller_id="9", seller_info={"seller": {"id": "9", "joined_year": 2015}})
    mp.add_seller_info(listing, _item_config())
    assert listing.seller_info["summary"] == "joined Facebook in 2015, no ratings"
    # nothing to do without a seller id
    plain = _listing()
    mp.add_seller_info(plain, _item_config())
    assert plain.seller_info == {}


@pytest.mark.parametrize(
    "fmt, line",
    [
        ("plain_text", "\nSeller warning: new account (joined Facebook in 2026)"),
        ("markdown", "\n**Seller warning**: new account (joined Facebook in 2026)"),
        ("html", "<br><b>Seller warning</b>: new account (joined Facebook in 2026)"),
    ],
)
def test_notifications_show_the_warning_signs(fmt: str, line: str) -> None:
    from ai_marketplace_monitor.ai import AIResponse
    from ai_marketplace_monitor.notification import NotificationStatus
    from ai_marketplace_monitor.pushbullet import PushbulletNotificationConfig

    config = PushbulletNotificationConfig(name="pb", pushbullet_token="x" * 34)
    config.message_format = fmt  # Pushbullet itself sends plain text
    sent: list = []
    config.send_message_with_retry = lambda *a, **k: sent.append(a) or True  # type: ignore
    listing = _listing(seller_info={"warnings": ["new account (joined Facebook in 2026)"]})
    rating = AIResponse(name="ai", score=2, comment="New account; be careful.")
    config.notify([listing], [rating], [NotificationStatus.NOT_NOTIFIED])
    assert sent and any(line in str(part) for part in sent[0])
