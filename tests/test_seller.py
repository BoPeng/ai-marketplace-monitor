"""Seller information: parsing what Facebook shows, caching it, and the warning signs."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from diskcache import Cache  # type: ignore

from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.seller import (
    Seller,
    parse_seller_panel,
    parse_seller_profile,
    seller_id_from_url,
    seller_status,
    seller_warnings,
    sold_grid_count,
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


def test_sold_listings_are_counted_once_the_grid_has_loaded() -> None:
    """The sold grid in the shapes of a live profile (2026-10-10).

    The switch to "Sold & out of stock" keeps the active tiles for a moment, then shows sold
    tiles or "No listings found".
    """
    header = "Pat's listings\nSold & out of stock\nSort by\n"
    # still the active listings: tiles start with their price
    assert sold_grid_count(header + "$499\nIphone 15 pro", ["$499", "$419"]) is None
    assert sold_grid_count(header + "$200\n$220\niPad", ["$200"]) is None
    # nothing shown yet
    assert sold_grid_count(header, []) is None
    # loaded
    assert sold_grid_count(header + "Sold\n·\n$100\nPops", ["Sold", "Sold", "Sold"]) == 3
    assert sold_grid_count(header + "No listings found", []) == 0


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
    Seller(id="7", name="Pat", joined_year=2020, profile_checked=True, checked_at=1.0).to_cache(
        local, now=2.0
    )
    cached = Seller.from_cache("7", local)
    assert cached is not None and cached.joined_year == 2020 and cached.profile_checked
    assert Seller.from_cache("8", local) is None
    assert Seller.from_cache("", local) is None


def test_writing_a_seller_again_does_not_postpone_the_next_profile_visit(tmp_path: Path) -> None:
    from ai_marketplace_monitor.seller import SELLER_CACHE_SECONDS, UNCHECKED_CACHE_SECONDS

    local = Cache(str(tmp_path))
    day = 24 * 3600.0
    now = 1_000_000_000.0
    seller = Seller(id="7", profile_checked=True, checked_at=now - 20 * day)
    seller.to_cache(local, now=now)
    _, expire_time = local.get(("seller-info", "7"), expire_time=True)
    # it expires when the profile turns a month old, not a month from now
    assert expire_time == pytest.approx(time.time() + SELLER_CACHE_SECONDS - 20 * day, abs=5)
    assert not seller.needs_profile(now)
    assert seller.needs_profile(now + 11 * day)
    # a profile that could not be read is tried again within a day
    Seller(id="8", joined_year=2020).to_cache(local, now=now)
    _, expire_time = local.get(("seller-info", "8"), expire_time=True)
    assert expire_time == pytest.approx(time.time() + UNCHECKED_CACHE_SECONDS, abs=5)
    assert Seller(id="8").needs_profile(now)


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
    assert "Warning signs about the seller: new account (joined Facebook in 2025)." in prompt
    assert "The seller matters as much as the item" in prompt
    assert "no higher than 2" in prompt and "moving sale" in prompt
    assert "what you concluded about the seller" in prompt
    # the profile was not read
    assert "treat the seller as not verified" in prompt
    checked = _listing(
        seller_info={
            "seller": {"id": "1", "profile_checked": True},
            "summary": "joined Facebook in 2015, no ratings, 3 active listings",
        }
    )
    assert "not verified" not in backend.get_prompt(checked, item, market)
    # nothing about the seller without seller information
    plain = backend.get_prompt(_listing(), item, market)
    assert "About the seller" not in plain
    # but bait prices are always flagged, also with a custom prompt
    custom = FacebookItemConfig(name="ipad", search_phrases=["ipad"], prompt="Is it a deal?")
    for text in (plain, backend.get_prompt(_listing(), custom, market)):
        assert '"financing available"' in text and "Rate such a listing 1" in text


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


def test_an_unread_profile_is_logged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import MagicMock

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
    mp.logger = MagicMock()
    listing = _listing(seller_id="9", seller_info={"seller": {"id": "9", "joined_year": 2015}})
    mp.add_seller_info(listing, _item_config())
    assert mp.exclusion_reason(listing, _item_config()) is None
    logged = " ".join(str(c) for c in mp.logger.info.call_args_list)
    assert "Could not read the profile of seller 9" in logged
    assert "not verified (profile could not be read)" in logged


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


def test_a_month_old_profile_is_read_again(
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
            return Seller(id=seller_id, active_listings=3, profile_checked=True)

    monkeypatch.setattr(facebook, "FacebookSellerProfilePage", FakeProfile)
    old = time.time() - 31 * 24 * 3600
    local.set(
        ("seller-info", "9"),
        {"id": "9", "active_listings": 1, "profile_checked": True, "checked_at": old},
    )
    mp = _marketplace(local)
    listing = _listing(seller_id="9", seller_info={"seller": {"id": "9"}})
    mp.add_seller_info(listing, _item_config())
    assert opened == ["9"] and listing.seller_info["seller"]["active_listings"] == 3
    assert listing.seller_info["seller"]["checked_at"] > old


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


_NEW_SELLER = {
    "seller": {"id": "9", "name": "Sam Roe", "joined_year": 2026},
    "warnings": ["new account (joined Facebook in 2026)"],
}
_STATUS = (
    "Sam Roe: joined Facebook in 2026, no ratings; not verified (profile could not be read). "
    "Warning signs: new account (joined Facebook in 2026)"
)


@pytest.mark.parametrize(
    "fmt, line",
    [
        ("plain_text", f"\nSeller: {_STATUS}"),
        ("markdown", f"\n**Seller**: {_STATUS}"),
        ("html", f"<br><b>Seller</b>: {_STATUS}"),
    ],
)
def test_notifications_show_the_seller_status(fmt: str, line: str) -> None:
    from ai_marketplace_monitor.ai import AIResponse
    from ai_marketplace_monitor.notification import NotificationStatus
    from ai_marketplace_monitor.pushbullet import PushbulletNotificationConfig

    config = PushbulletNotificationConfig(name="pb", pushbullet_token="x" * 34)
    config.message_format = fmt  # Pushbullet itself sends plain text
    sent: list = []
    config.send_message_with_retry = lambda *a, **k: sent.append(a) or True  # type: ignore
    listing = _listing(seller_info=_NEW_SELLER)
    rating = AIResponse(name="ai", score=2, comment="New account; be careful.")
    config.notify([listing], [rating], [NotificationStatus.NOT_NOTIFIED])
    assert sent and any(line in str(part) for part in sent[0])


def test_the_seller_status_always_says_something() -> None:
    checked_at = time.mktime((2026, 10, 1, 12, 0, 0, 0, 0, -1))
    checked = {
        "seller": {
            "id": "1",
            "name": "Pat Doe",
            "joined_year": 2009,
            "rating": 4.6,
            "rating_count": 182,
            "active_listings": 3,
            "sold_listings": 40,
            "reviews": ["Great seller."],
            "profile_checked": True,
            "checked_at": checked_at,
        },
        "warnings": [],
    }
    # reviews are left to the AI
    assert seller_status(checked) == (
        "Pat Doe: joined Facebook in 2009, rated 4.6 out of 5 by 182 buyers, 3 active "
        "listings, 40 sold listings, profile checked 2026-10-01"
    )
    assert seller_status(_NEW_SELLER) == _STATUS
    # not logged in, or a listing from before seller information
    assert seller_status({}) == "not verified (no seller information)"
    assert seller_status({"warnings": ["new account"]}) == (
        "not verified (no seller information). Warning signs: new account"
    )


def test_emails_show_the_seller_status() -> None:
    from ai_marketplace_monitor.ai import AIResponse
    from ai_marketplace_monitor.email_notify import EmailNotificationConfig
    from ai_marketplace_monitor.notification import NotificationStatus

    config = EmailNotificationConfig(name="mail", email=["a@example.com"])
    listing = _listing(seller_info=_NEW_SELLER)
    rating = AIResponse(name="ai", score=2, comment="New account; be careful.")
    status = [NotificationStatus.NOT_NOTIFIED]
    assert f"\nSeller: {_STATUS}" in config.get_text_message([listing], [rating], status)
    html, _ = config.get_html_message([listing], [rating], status)
    assert "Seller:" in html and "not verified (profile could not be read)" in html
    assert "#FFF4E5" in html  # highlighted


# --- the review of #437: legacy caches, AI answers, the sold grid, `aimm check`
def test_listings_cached_before_seller_reading_are_read_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ai_marketplace_monitor.listing as listing_module
    from ai_marketplace_monitor import facebook

    local = Cache(str(tmp_path))
    monkeypatch.setattr(listing_module, "cache", local)
    url = "https://www.facebook.com/marketplace/item/1/"
    read: list = []

    def fake_parse(page: Any, post_url: str, *args: Any) -> Listing:
        read.append(post_url)
        return _listing(seller_parsed=True)  # e.g. a page without a seller panel

    monkeypatch.setattr(facebook, "parse_listing", fake_parse)
    mp = _marketplace(local)
    monkeypatch.setattr(mp, "goto_url", lambda url: None)
    item = _item_config()

    _listing().to_cache(url, local)  # cached by an earlier aimm: seller_parsed is False
    details, from_cache = mp.get_listing_details(url, item, price="$200", title="iPad")
    assert not from_cache and read == [url]
    # read once: a page without seller information is not read again
    details, from_cache = mp.get_listing_details(url, item, price="$200", title="iPad")
    assert from_cache and read == [url]


def test_an_answer_before_the_profile_is_not_reused_after_it(tmp_path: Path) -> None:
    from ai_marketplace_monitor.ai import AIResponse
    from ai_marketplace_monitor.facebook import FacebookMarketplaceConfig

    local = Cache(str(tmp_path))
    item = _item_config()
    market = FacebookMarketplaceConfig(name="facebook", search_city=["houston"])
    partial = _listing(seller_info={"seller": {"id": "1", "joined_year": 2015}})
    complete = _listing(
        seller_info={"seller": {"id": "1", "joined_year": 2015, "profile_checked": True}}
    )
    AIResponse(name="ai", score=5, comment="great").to_cache(partial, item, market, local)
    assert AIResponse.from_cache(partial, item, market, local) is not None
    assert AIResponse.from_cache(complete, item, market, local) is None
    # once the profile was read, a later change in it keeps the answer
    AIResponse(name="ai", score=2, comment="risky").to_cache(complete, item, market, local)
    changed = _listing(
        seller_info={
            "seller": {"id": "1", "joined_year": 2015, "profile_checked": True, "rating": 3.0}
        }
    )
    cached = AIResponse.from_cache(changed, item, market, local)
    assert cached is not None and cached.score == 2
    # listings without seller information keep the key they always had
    AIResponse(name="ai", score=4, comment="ok").to_cache(_listing(), item, market, local)
    assert local.get(("ai-inquiries", item.hash, market.hash, _listing().hash)) is not None


class _FakeSoldPage:
    """A profile page whose grid goes through ``states`` (text, tile first lines)."""

    def __init__(self, states: list) -> None:
        from unittest.mock import MagicMock

        self.states = list(states)
        self.locator = MagicMock()

    def get_by_role(self, *args: Any, **kwargs: Any) -> Any:
        return self.locator

    def get_by_text(self, *args: Any, **kwargs: Any) -> Any:
        return self.locator

    def wait_for_timeout(self, ms: int) -> None:
        pass

    def evaluate(self, script: str, *args: Any) -> Any:
        text, tiles = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return {"text": text, "tiles": tiles}


@pytest.mark.parametrize(
    "states, expected",
    [
        # active tiles first, then the sold ones, the same twice
        ([("$499", ["$499", "$419"]), ("Sold", ["Sold"] * 3), ("Sold", ["Sold"] * 3)], 3),
        ([("$499", ["$499"]), ("Sort by\nNo listings found", [])], 0),
        # never loads: unknown, not "none sold"
        ([("Sort by", [])], None),
        ([("$499", ["$499"])], None),
    ],
)
def test_the_sold_grid_is_read_once_loaded(states: list, expected: Any) -> None:
    from ai_marketplace_monitor.facebook import FacebookSellerProfilePage

    page = FacebookSellerProfilePage(_FakeSoldPage(states))  # type: ignore[arg-type]
    assert page.get_sold_listings() == expected


def test_aimm_check_opens_facebook_when_the_seller_is_due(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ai_marketplace_monitor.listing as listing_module
    import ai_marketplace_monitor.seller as seller_module
    from ai_marketplace_monitor.monitor import listing_needs_browser

    local = Cache(str(tmp_path))
    monkeypatch.setattr(listing_module, "cache", local)
    monkeypatch.setattr(seller_module, "cache", local)
    url = "https://www.facebook.com/marketplace/item/1/"
    assert listing_needs_browser(url)  # never read
    _listing().to_cache(url, local)
    assert listing_needs_browser(url)  # read before aimm read sellers
    _listing(seller_parsed=True).to_cache(url, local)
    assert not listing_needs_browser(url)  # no seller panel
    _listing(seller_parsed=True, seller_id="9").to_cache(url, local)
    assert listing_needs_browser(url)  # the seller's profile was never read
    Seller(id="9", profile_checked=True, checked_at=time.time()).to_cache(local)
    assert not listing_needs_browser(url)
