"""OfferUp (#467): its client, config, searches, listings, sellers and status, without network."""

from __future__ import annotations

import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qsl, urlsplit

import pytest

from ai_marketplace_monitor.config import Config
from ai_marketplace_monitor.evaluations import EvaluationRecord
from ai_marketplace_monitor.marketplaces import marketplace_class
from ai_marketplace_monitor.marketplaces.offerup import (
    OfferUpBlockedError,
    OfferUpClient,
    OfferUpError,
    OfferUpItemConfig,
    OfferUpMarketplace,
    OfferUpMarketplaceConfig,
    nearest_radius,
)
from ai_marketplace_monitor.marketplaces.offerup import marketplace as offerup_module

LID = "8fd87e4a-8aa6-3b79-8168-26e6abb3353f"


# ------------------------------------------------------------------ the client


class FakeResponse:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code = status
        self._body = body

    def json(self) -> Any:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeSession:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.posts: List[Dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.posts.append({"url": url, **kwargs})
        return self.responses.pop(0)


def test_the_client_sends_a_graphql_search_and_drops_the_ads() -> None:
    body = {
        "data": {
            "modularFeed": {
                "looseTiles": [
                    {"tileType": "AD_1P"},
                    {"tileType": "LISTING", "listing": {"listingId": LID, "title": "Bike"}},
                ]
            }
        }
    }
    session = FakeSession(FakeResponse(200, body))
    client = OfferUpClient(proxies={"https": "http://proxy:8080"}, session=session, min_gap=0)
    assert client.search({"q": "bike", "zipcode": "77002"}) == [
        {"listingId": LID, "title": "Bike"}
    ]
    post = session.posts[0]
    assert post["url"] == "https://offerup.com/api/graphql"
    assert post["json"]["operationName"] == "GetModularFeed"
    assert post["json"]["variables"]["searchParams"] == [
        {"key": "q", "value": "bike"},
        {"key": "zipcode", "value": "77002"},
    ]
    assert post["headers"]["Origin"] == "https://offerup.com"
    assert post["proxies"] == {"https": "http://proxy:8080"}


@pytest.mark.parametrize(
    ("response", "error", "match"),
    [
        (FakeResponse(403, "blocked"), OfferUpBlockedError, "HTTP 403.*US-only"),
        (FakeResponse(429, {}), OfferUpBlockedError, "HTTP 429"),
        (FakeResponse(400, {"errors": [{"message": "no field x"}]}), OfferUpError, "no field x"),
        (FakeResponse(200, ValueError("not json")), OfferUpError, "not JSON"),
        (FakeResponse(500, {}), OfferUpError, "HTTP 500"),
    ],
)
def test_the_client_reports_what_went_wrong(
    response: FakeResponse, error: type, match: str
) -> None:
    client = OfferUpClient(session=FakeSession(response), min_gap=0)
    with pytest.raises(error, match=match):
        client.listing(LID)


def test_the_client_spaces_its_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_marketplace_monitor.marketplaces.offerup import client as client_module

    clock = [100.0]
    slept: List[float] = []
    monkeypatch.setattr(client_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(client_module.time, "sleep", lambda s: slept.append(s))
    ok = {"data": {"listing": None}}
    client = OfferUpClient(
        session=FakeSession(FakeResponse(200, ok), FakeResponse(200, ok)), min_gap=3
    )
    client.listing(LID)
    clock[0] += 1
    client.listing(LID)
    assert slept == [pytest.approx(2.0)]


# ------------------------------------------------------------------ config


@pytest.mark.parametrize(
    ("value", "expected"),
    [('"77002"', ["77002"]), ("77002", ["77002"]), ('["77002", "75201"]', ["77002", "75201"])],
)
def test_search_city_is_a_zip_code(tmp_path: Path, value: str, expected: List[str]) -> None:
    config = _config(tmp_path, f"[marketplace.offerup]\nsearch_city = {value}\n")
    assert config.marketplace["offerup"].search_city == expected


def test_a_facebook_location_code_is_not_a_zip_code(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="'houston' is not a ZIP code"):
        _config(tmp_path, '[marketplace.offerup]\nsearch_city = "houston"\n')


def test_an_offerup_section_needs_no_login_and_rejects_facebook_options(tmp_path: Path) -> None:
    config = _config(tmp_path, '[marketplace.offerup]\nsearch_city = "77002"\n')
    assert marketplace_class(config.marketplace["offerup"]) is OfferUpMarketplace
    assert not OfferUpMarketplace.needs_browser
    with pytest.raises(
        ValueError, match="sets availability, which offerup marketplaces do not have"
    ):
        _config(tmp_path, '[marketplace.offerup]\nsearch_city = "77002"\navailability = "in"\n')
    # a built-in region lists Facebook's codes only: the error names the region
    with pytest.raises(ValueError, match="Region .*usa.*, used by .*mine.*: .*not a ZIP code"):
        _config(tmp_path, '[marketplace.mine]\nmarket_type = "offerup"\nsearch_region = "usa"\n')


def _config(tmp_path: Path, markets: str, item: str = "") -> Config:
    path = tmp_path / "config.toml"
    path.write_text(
        textwrap.dedent(
            markets
            + (item or '[item.bike]\nsearch_phrases = "road bike"\n')
            + '[user.me]\npushbullet_token = "x"\n'
        ),
        encoding="utf-8",
    )
    return Config([path])


# ------------------------------------------------------------------ searching


def _marketplace(tmp_path: Path, market: str = "", item: str = "") -> tuple:
    config = _config(
        tmp_path,
        '[marketplace.offerup]\nsearch_city = ["77002", "75201"]\nradius = [25, 60]\n' + market,
        item,
    )
    marketplace = OfferUpMarketplace("offerup", None)
    marketplace.configure(config.marketplace["offerup"])
    return marketplace, config.item_targets["bike"]["offerup"]


def _params(url: str) -> Dict[str, str]:
    return dict(parse_qsl(urlsplit(url).query))


def test_search_pages_are_zip_codes_times_phrases(tmp_path: Path) -> None:
    marketplace, item = _marketplace(
        tmp_path,
        item='[item.bike]\nsearch_phrases = ["road bike", "trek"]\nmin_price = 100\nmax_price = 800\n',
    )
    pages = marketplace.search_pages(item)
    assert [(p.city, p.phrase, p.radius) for p in pages] == [
        ("77002", "road bike", 30),
        ("77002", "trek", 30),
        ("75201", "road bike", 50),
        ("75201", "trek", 50),
    ]
    assert _params(pages[0].url) == {
        "q": "road bike",
        "zipcode": "77002",
        "radius": "30",
        "SORT": "-posted",  # newest first unless sort_by says otherwise
        "PRICE_MIN": "100",
        "PRICE_MAX": "800",
    }
    assert pages[0].url.startswith("https://offerup.com/search?")


@pytest.mark.parametrize(
    ("option", "param", "value"),
    [
        ('sort_by = "price_ascend"', "SORT", "price"),
        ('sort_by = "suggested"', "SORT", "best_match"),
        ('condition = ["new", "used_like_new"]', "CONDITION", "NEW,OPEN_BOX,USED"),
        ('condition = ["used_fair"]', "CONDITION", "USED"),
    ],
)
def test_options_become_search_parameters(
    tmp_path: Path, option: str, param: str, value: str
) -> None:
    marketplace, item = _marketplace(tmp_path, market=option + "\n")
    assert _params(marketplace.search_pages(item)[0].url)[param] == value


def test_a_price_in_another_currency_is_converted_to_dollars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Converter:
        def convert(self, amount: int, frm: str, to: str) -> float:
            assert (frm, to) == ("EUR", "USD")
            return amount * 1.1

    monkeypatch.setattr(offerup_module, "CurrencyConverter", Converter)
    marketplace, item = _marketplace(
        tmp_path, item='[item.bike]\nsearch_phrases = "bike"\nmax_price = "300 EUR"\n'
    )
    assert _params(marketplace.search_pages(item)[0].url)["PRICE_MAX"] == "330"


@pytest.mark.parametrize(("radius", "expected"), [(1, 5), (25, 30), (40, 50), (100, 50), (15, 20)])
def test_the_nearest_radius_offerup_offers(radius: int, expected: int) -> None:
    assert nearest_radius(radius) == expected


def test_listing_and_seller_urls() -> None:
    assert OfferUpMarketplace.listing_url(LID) == f"https://offerup.com/item/detail/{LID}"
    for value in (
        LID,
        f"https://offerup.com/item/detail/{LID}",
        f"offerup.com/item/detail/{LID}/",
    ):
        assert OfferUpMarketplace.listing_id(value) == LID
    assert OfferUpMarketplace.listing_id("https://www.facebook.com/marketplace/item/123/") == ""
    assert OfferUpMarketplace.listing_id("123") == ""  # a Facebook id
    assert OfferUpMarketplace.seller_url("offerup:44") == "https://offerup.com/p/44/"


# ------------------------------------------------------------------ listings and sellers


class FakeClient:
    def __init__(self) -> None:
        self.cards: List[Dict[str, Any]] = []
        self.listings: Dict[str, Any] = {}
        self.profiles: Dict[str, Any] = {}
        self.calls: List[str] = []

    def search(self, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        self.calls.append(f"search {params['q']}")
        return self.cards

    def listing(self, listing_id: str) -> Any:
        self.calls.append(f"listing {listing_id}")
        value = self.listings.get(listing_id)
        if isinstance(value, Exception):
            raise value
        return value

    def profile(self, user_id: str) -> Any:
        self.calls.append(f"profile {user_id}")
        return self.profiles.get(user_id)


def _details(lid: str = LID, **kw: Any) -> Dict[str, Any]:
    data = {
        "listingId": lid,
        "title": "Trek Domane",
        "price": "850",
        "condition": 40,
        "description": "Good condition.",
        "postDate": datetime.now(timezone.utc).isoformat(),
        "state": "LISTED",
        "isRemoved": False,
        "locationDetails": {"locationName": "Irving, TX"},
        "fulfillmentDetails": {"localPickupEnabled": True, "shippingEnabled": False},
        "photos": [{"detail": {"url": "https://images.offerup.com/1.jpg"}}],
        "owner": {"id": 44, "profile": {"name": "Pat"}},
    }
    data.update(kw)
    return data


@pytest.fixture(autouse=True)
def aimm_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from diskcache import Cache  # type: ignore

    from ai_marketplace_monitor import evaluations, listing, seller

    local = Cache(str(tmp_path / "cache"))
    for module in (evaluations, listing, seller):
        monkeypatch.setattr(module, "cache", local)
    return local


def test_a_search_reads_cards_listings_and_sellers(tmp_path: Path) -> None:
    marketplace, item = _marketplace(tmp_path)
    fake = FakeClient()
    fake.cards = [
        {
            "listingId": LID,
            "title": "Trek Domane",
            "price": "850",
            "locationName": "Irving, TX",
            "image": {"url": "u"},
        }
    ]
    fake.listings[LID] = _details()
    fake.profiles["44"] = {
        "name": "Pat",
        "dateJoined": "2018-05-13T00:51:13Z",
        "itemsSold": "276",
        "ratingSummary": {"count": 27, "average": 5},
        "ratingAttributes": [{"count": 22, "value": "Reliable"}],
        "badges": [{"label": "Confirmed phone"}],
        "isTruyouVerified": True,
    }
    marketplace.client = fake  # type: ignore[assignment]
    found = list(marketplace.search(item))
    assert len(found) == 1  # once, although both ZIP codes and phrases found it
    listing = found[0]
    assert listing.post_url == f"https://offerup.com/item/detail/{LID}"
    assert (listing.price, listing.location, listing.condition) == ("$850", "Irving, TX", "Used")
    assert listing.seller == "Pat" and listing.seller_id == "offerup:44"
    assert listing.delivery == "local_pick_up" and listing.post_date
    seller = listing.seller_info["seller"]
    assert seller["platform"] == "OfferUp" and seller["sold_listings"] == 276
    assert seller["badges"] == ["Confirmed phone", "TruYou verified"]
    assert "joined OfferUp in 2018" in listing.seller_info["summary"]
    # the listing and the seller were read once each; the cache answers the second search
    assert fake.calls.count(f"listing {LID}") == 1 and fake.calls.count("profile 44") == 1


def test_a_removed_listing_is_not_read(tmp_path: Path) -> None:
    marketplace, item = _marketplace(tmp_path)
    fake = FakeClient()
    fake.listings[LID] = _details(isRemoved=True)
    marketplace.client = fake  # type: ignore[assignment]
    with pytest.raises(ValueError, match="no longer has listing"):
        marketplace.get_listing_details(OfferUpMarketplace.listing_url(LID), item)


@pytest.mark.parametrize(
    ("option", "details", "reason"),
    [
        (
            "date_listed = 7",
            {"postDate": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()},
            "listed more than 7 days ago",
        ),
        (
            "date_listed = 30",
            {"postDate": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()},
            None,
        ),
        ('delivery_method = "shipping"', {}, "local pickup only"),
        (
            'delivery_method = "local_pick_up"',
            {"fulfillmentDetails": {"localPickupEnabled": False, "shippingEnabled": True}},
            "shipping only",
        ),
        (
            'delivery_method = "local_pick_up"',
            {"fulfillmentDetails": {"localPickupEnabled": True, "shippingEnabled": True}},
            None,
        ),
    ],
)
def test_what_the_search_cannot_filter_is_checked_after_reading(
    tmp_path: Path, option: str, details: Dict[str, Any], reason: str | None
) -> None:
    marketplace, item = _marketplace(
        tmp_path, item=f'[item.bike]\nsearch_phrases = "bike"\n{option}\n'
    )
    item.searched_count = 1  # the first search
    listing = marketplace._listing(_details(**details), OfferUpMarketplace.listing_url(LID))
    assert marketplace.exclusion_reason(listing, item) == reason
    # not before the listing is read
    assert marketplace.exclusion_reason(listing, item, description_available=False) is None


# ------------------------------------------------------------------ status and proxies


def test_check_status_reads_whether_listings_sold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    updates: List[Dict[str, Any]] = []
    monkeypatch.setattr(
        offerup_module, "update_evaluation", lambda *a, **k: updates.append({"id": a[1], **k})
    )
    marketplace, _ = _marketplace(tmp_path)
    fake = FakeClient()
    ids = ["a" * 8 + "-0000-0000-0000-" + str(i) * 12 for i in range(4)]
    fake.listings = {
        ids[0]: {"state": "SOLD"},
        ids[1]: {"state": "LISTED"},
        ids[2]: {"state": "REMOVED"},  # kept as it was
        ids[3]: OfferUpBlockedError("blocked"),  # stops the check
    }
    marketplace.client = fake  # type: ignore[assignment]
    records = [
        EvaluationRecord(
            time=0,
            item="bike",
            marketplace="offerup",
            id=i,
            url=OfferUpMarketplace.listing_url(i),
            title="t",
            price="$1",
            location="",
            seller="",
            condition="",
            stage="notified",
            rating=5,
            ai_comment="",
            reason="",
        )
        for i in ids
    ]
    assert marketplace.check_status(records) == 2
    assert [(u["id"], u["state"]) for u in updates] == [(ids[0], "sold"), (ids[1], "available")]


def test_the_monitor_proxy_is_used(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        '[monitor]\nproxy_server = "http://proxy.example:8080"\nproxy_username = "u"\nproxy_password = "p"\n'
        '[marketplace.offerup]\nsearch_city = "77002"\n',
    )
    marketplace = OfferUpMarketplace("offerup", None)
    marketplace.configure(config.marketplace["offerup"])
    assert marketplace.client.proxies == {
        "http": "http://u:p@proxy.example:8080",
        "https": "http://u:p@proxy.example:8080",
    }


def test_offerup_config_classes() -> None:
    assert OfferUpMarketplace.config_class is OfferUpMarketplaceConfig
    assert OfferUpMarketplace.item_config_class is OfferUpItemConfig


# ------------------------------------------------------------------ review fixes (#480)


def test_a_zip_code_has_ascii_digits(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="is not a ZIP code"):
        _config(tmp_path, '[marketplace.offerup]\nsearch_city = "٧٧٠٠٢"\n')


def test_proxy_credentials_are_quoted(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        '[monitor]\nproxy_server = "http://proxy.example:8080"\nproxy_username = "me@home"\n'
        'proxy_password = "p:a/s@s"\n[marketplace.offerup]\nsearch_city = "77002"\n',
    )
    marketplace = OfferUpMarketplace("offerup", None)
    marketplace.configure(config.marketplace["offerup"])
    assert (
        marketplace.client.proxies["https"] == "http://me%40home:p%3Aa%2Fs%40s@proxy.example:8080"
    )


@pytest.mark.parametrize(
    ("post_date", "excluded"),
    [
        ("not a date", False),  # unreadable: not held against the listing
        ((datetime.now() - timedelta(days=10)).isoformat(), True),  # naive: read as UTC
        ("", False),
    ],
)
def test_an_unreadable_or_naive_post_date(tmp_path: Path, post_date: str, excluded: bool) -> None:
    marketplace, item = _marketplace(
        tmp_path, item='[item.bike]\nsearch_phrases = "bike"\ndate_listed = 7\n'
    )
    item.searched_count = 1
    listing = marketplace._listing(
        _details(postDate=post_date), OfferUpMarketplace.listing_url(LID)
    )
    assert (marketplace.exclusion_reason(listing, item) is not None) is excluded


def test_an_offerup_config_can_be_normalized() -> None:
    from ai_marketplace_monitor.normalize import expand, normalize
    from tests.normalize_util import parse, system_cfg

    text = '[marketplace.offerup]\nsearch_city = "77002"\n[item.bike]\nsearch_phrases = "bike"\n[user.me]\npushbullet_token = "x"\n'
    assert (
        expand(parse(text), system_cfg()).config["marketplace"]["offerup"]["search_city"]
        == "77002"
    )
    normalize(parse(text), system_cfg())
    bound = text.replace(
        'search_phrases = "bike"', 'search_phrases = "bike"\nmarketplace = "offerup"'
    )
    assert expand(parse(bound), system_cfg()).config["item"]["bike"]["search_city"] == "77002"


def test_aimm_check_uses_the_marketplace_of_the_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_marketplace_monitor import monitor as mon

    path = tmp_path / "config.toml"
    path.write_text(
        textwrap.dedent(
            '[marketplace.facebook]\nsearch_city = "houston"\nusername = "u"\npassword = "p"\n'
            '[marketplace.offerup]\nsearch_city = "77002"\n'
            '[item.bike]\nsearch_phrases = "bike"\n[user.me]\npushbullet_token = "x"\n'
        ),
        encoding="utf-8",
    )
    config = Config([path])
    monitor = mon.MarketplaceMonitor.__new__(mon.MarketplaceMonitor)
    monitor.config = config
    monitor.browser = None
    monitor.logger = None
    monitor.keyboard_monitor = None
    monitor.ai_agents = []
    monkeypatch.setattr(mon.MarketplaceMonitor, "active_marketplaces", {})
    monkeypatch.setattr(monitor, "load_config_file", lambda: config)
    monkeypatch.setattr(monitor, "load_ai_agents", lambda: None)
    monkeypatch.setattr(monitor, "_launch_browser", lambda: pytest.fail("no browser for OfferUp"))
    checked: List[str] = []

    def inspect(marketplace: Any, url: str, item: Any, market: Any, *args: Any) -> Any:
        from ai_marketplace_monitor.ai import AIResponse

        checked.append(f"{type(marketplace).__name__} {item.marketplace}")
        listing = (
            marketplace._listing(_details(), url) if hasattr(marketplace, "_listing") else None
        )
        return listing, False, None, AIResponse(5, AIResponse.NOT_EVALUATED)

    monkeypatch.setattr(mon, "inspect_listing", inspect)
    monkeypatch.setattr(mon.User, "notification_status", lambda self, listing: None)
    monitor.check_items([f"https://offerup.com/item/detail/{LID}"], for_item="bike")
    assert checked == ["OfferUpMarketplace offerup"]  # not the Facebook section first


def test_offerup_takes_its_values_from_tables_and_regions(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        '[region.texas]\nsearch_city = [{ facebook = "houston", offerup = "77002" }, '
        '{ facebook = "dallas", offerup = 75201 }]\n'
        '[marketplace.offerup]\nsearch_region = "texas"\n'
        '[marketplace.near]\nmarket_type = "offerup"\n'
        'search_city = { facebook = "houston", offerup = "77096" }\n',
        '[item.bike]\nsearch_phrases = "bike"\n',
    )
    assert config.marketplace["offerup"].search_city == ["77002", "75201"]
    assert config.marketplace["near"].search_city == ["77096"]


@pytest.mark.parametrize(
    ("value", "where"),
    [
        ('"29.7604,-95.3698"', {"lat": "29.7604", "lon": "-95.3698"}),
        ('"29.7604, -95.3698"', {"lat": "29.7604", "lon": "-95.3698"}),
        ('"77002"', {"zipcode": "77002"}),
    ],
)
def test_search_city_can_be_coordinates(tmp_path: Path, value: str, where: Dict[str, str]) -> None:
    config = _config(tmp_path, f"[marketplace.offerup]\nsearch_city = {value}\n")
    marketplace = OfferUpMarketplace("offerup", None)
    marketplace.configure(config.marketplace["offerup"])
    item = config.item_targets["bike"]["offerup"]
    params = _params(marketplace.search_pages(item)[0].url)
    assert {k: params[k] for k in where} == where
    assert not ({"lat", "zipcode"} - set(where)) & set(params)


@pytest.mark.parametrize("value", ['"houston"', '"95.1,200"', '"1234"'])
def test_search_city_that_is_neither(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValueError, match="is not a ZIP code or coordinates"):
        _config(tmp_path, f"[marketplace.offerup]\nsearch_city = {value}\n")
