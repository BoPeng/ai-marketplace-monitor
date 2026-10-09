"""Tests for the evaluation history: recording decisions, reading them back, and the web API."""

from __future__ import annotations

import csv
import io
import time
from pathlib import Path
from typing import Any, Iterator, List
from unittest.mock import MagicMock, patch

import pytest
from diskcache import Cache  # type: ignore
from fastapi.testclient import TestClient

from ai_marketplace_monitor import evaluations
from ai_marketplace_monitor.ai import AIResponse
from ai_marketplace_monitor.evaluations import (
    EXCLUDED,
    NOTIFIED,
    PENDING,
    REJECTED,
    SOLD,
    UNKNOWN,
    EvaluationRecord,
    apply_price,
    filter_evaluations,
    iter_evaluations,
    record_evaluation,
    record_seen,
    update_evaluation,
)
from ai_marketplace_monitor.facebook import (
    FacebookItemConfig,
    FacebookMarketplace,
    FacebookMarketplaceConfig,
)
from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.monitor import MarketplaceMonitor
from ai_marketplace_monitor.user import User
from ai_marketplace_monitor.utils import BrokenCache, CacheType, MonitorConfig
from ai_marketplace_monitor.webui import server as webui_server
from ai_marketplace_monitor.webui.config_api import ConfigFileService
from ai_marketplace_monitor.webui.evaluations_export import EVALUATION_CSV_COLUMNS
from ai_marketplace_monitor.webui.log_handler import LogBroadcastHandler
from ai_marketplace_monitor.webui.server import AuthState, WebUIConfig, create_app


@pytest.fixture
def eval_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Cache]:
    """A private cache that the recording hooks write to."""
    c = Cache(str(tmp_path / "cache"))
    monkeypatch.setattr(evaluations, "cache", c)
    yield c
    c.close()


def _listing(listing_id: str = "1", title: str = "Road bike", **kwargs: Any) -> Listing:
    values = {
        "marketplace": "facebook",
        "name": "bike",
        "id": listing_id,
        "title": title,
        "image": "",
        "price": "$100",
        "post_url": f"https://www.facebook.com/marketplace/item/{listing_id}/?ref=search",
        "location": "Houston, TX",
        "seller": "Jane",
        "condition": "used_good",
        "description": "a fine bike",
    }
    values.update(kwargs)
    return Listing(**values)


def _record(
    listing_id: str = "1",
    *,
    item: str = "bike",
    stage: str = EXCLUDED,
    rating: int | None = None,
    when: float | None = None,
    **kwargs: Any,
) -> EvaluationRecord:
    record = EvaluationRecord.from_listing(
        _listing(listing_id, **kwargs), item=item, stage=stage, rating=rating
    )
    if when is not None:
        record.time = when
    return record


def _all(c: Cache, **kwargs: Any) -> List[EvaluationRecord]:
    return list(iter_evaluations(local_cache=c, **kwargs))


# ---------------------------------------------------------------- storage


def test_record_round_trip(eval_cache: Cache) -> None:
    record = _record(stage=REJECTED, rating=2)
    record.ai_comment = "too far"
    record.reason = "rating 2 < 3: too far"
    record_evaluation(record, local_cache=eval_cache)
    key = (CacheType.EVALUATIONS.value, "facebook", "1", "bike")
    assert key in eval_cache
    [back] = _all(eval_cache)
    assert back == record
    assert back.url == "https://www.facebook.com/marketplace/item/1/"


def test_later_decision_overwrites_earlier(eval_cache: Cache) -> None:
    record_evaluation(_record(stage=REJECTED, rating=2), local_cache=eval_cache)
    record_evaluation(_record(stage=NOTIFIED, rating=5), local_cache=eval_cache)
    # another item keeps its own record of the same listing
    record_evaluation(_record(item="cycle", stage=EXCLUDED), local_cache=eval_cache)
    records = {r.item: r for r in _all(eval_cache)}
    assert len(records) == 2
    assert records["bike"].stage == NOTIFIED
    assert records["bike"].rating == 5
    assert records["cycle"].stage == EXCLUDED


def test_records_expire(eval_cache: Cache, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(evaluations, "_history_days", 0.1 / 86400)  # 0.1 seconds
    record_evaluation(_record(), local_cache=eval_cache)
    assert len(_all(eval_cache)) == 1
    time.sleep(0.3)
    assert _all(eval_cache) == []


def test_set_history_days(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(evaluations, "_history_days", evaluations.DEFAULT_HISTORY_DAYS)
    evaluations.set_history_days(7)
    assert evaluations._history_days == 7
    evaluations.set_history_days(None)
    assert evaluations._history_days == evaluations.DEFAULT_HISTORY_DAYS


def test_iter_filters(eval_cache: Cache) -> None:
    now = time.time()
    record_evaluation(_record("1", stage=EXCLUDED, when=now - 3600), local_cache=eval_cache)
    record_evaluation(_record("2", stage=NOTIFIED, when=now), local_cache=eval_cache)
    record_evaluation(_record("3", item="tv", stage=NOTIFIED, when=now), local_cache=eval_cache)
    assert {r.id for r in _all(eval_cache, stage=NOTIFIED)} == {"2", "3"}
    assert {r.id for r in _all(eval_cache, item="bike")} == {"1", "2"}
    assert {r.id for r in _all(eval_cache, since=now - 60)} == {"2", "3"}
    assert [r.id for r in _all(eval_cache, item="bike", stage=NOTIFIED)] == ["2"]


def test_iter_skips_other_and_malformed_entries(eval_cache: Cache) -> None:
    eval_cache.set((CacheType.EVALUATIONS.value, "facebook", "9", "bike"), "not a dict")
    eval_cache.set((CacheType.LISTING_DETAILS.value, "url"), {"id": "x"})
    # an older record without some fields still loads
    eval_cache.set(
        (CacheType.EVALUATIONS.value, "facebook", "8", "bike"),
        {"time": time.time(), "item": "bike", "id": "8", "stage": "excluded", "extra": 1},
    )
    [record] = _all(eval_cache)
    assert record.id == "8"
    assert record.rating is None
    assert record.title == ""


def test_broken_cache_records_and_yields_nothing(tmp_path: Path) -> None:
    broken: Any = BrokenCache(tmp_path, Exception("database disk image is malformed"))
    record_evaluation(_record(), local_cache=broken)
    assert list(iter_evaluations(local_cache=broken)) == []


def test_lower_history_days_hides_and_evicts_old_records(
    eval_cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(evaluations, "_history_days", 30)
    now = time.time()
    record_evaluation(_record("old", when=now - 3 * 86400), local_cache=eval_cache)
    record_evaluation(_record("new", when=now - 3600), local_cache=eval_cache)
    assert {r.id for r in _all(eval_cache)} == {"old", "new"}
    # saved with a 30-day expiry; lowering the setting still applies to them
    evaluations.set_history_days(1)
    assert [r.id for r in _all(eval_cache)] == ["new"]
    assert (CacheType.EVALUATIONS.value, "facebook", "old", "bike") not in eval_cache
    assert (CacheType.EVALUATIONS.value, "facebook", "new", "bike") in eval_cache
    # filtered reads evict too
    record_evaluation(_record("old", item="tv", when=now - 3 * 86400), local_cache=eval_cache)
    assert _all(eval_cache, item="bike", stage=EXCLUDED)[0].id == "new"
    assert (CacheType.EVALUATIONS.value, "facebook", "old", "tv") not in eval_cache


def test_api_applies_history_cutoff(
    tmp_path: Path, eval_cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(evaluations, "_history_days", 1)
    now = time.time()
    record_evaluation(_record("old", when=now - 3 * 86400), local_cache=eval_cache)
    record_evaluation(_record("new", when=now - 60), local_cache=eval_cache)
    client = _client(tmp_path, eval_cache, monkeypatch)
    assert [r["id"] for r in client.get("/api/evaluations").json()["records"]] == ["new"]
    record_evaluation(_record("old", when=now - 3 * 86400), local_cache=eval_cache)
    rows = list(csv.DictReader(io.StringIO(client.get("/api/evaluations.csv").text)))
    assert [r["url"] for r in rows] == ["https://www.facebook.com/marketplace/item/new/"]


def test_old_records_load_with_status_defaults() -> None:
    value = _record().to_dict()
    for key in (
        "last_seen",
        "previous_price",
        "price_changed",
        "state",
        "state_changed",
        "checked",
    ):
        del value[key]
    record = EvaluationRecord.from_dict(value)
    assert (record.state, record.previous_price, record.last_seen) == (UNKNOWN, "", 0.0)


@pytest.mark.parametrize(
    ("old", "new", "price", "previous"),
    [
        ("$100", "$80", "$80", "$100"),  # a changed price
        ("$100", "$80 | $100", "$80 | $100", "$100"),  # the card shows the drop
        ("", "$80 | $100", "$80 | $100", "$100"),  # first sighting of a reduced listing
        ("$100", "$100", "$100", ""),  # unchanged
    ],
)
def test_apply_price(old: str, new: str, price: str, previous: str) -> None:
    record = _record(price=old) if old else _record(price="")
    apply_price(record, new, 1000.0)
    assert (record.price, record.previous_price) == (price, previous)
    assert record.price_changed == (1000.0 if previous else 0.0)


# decisions must fall inside the history, so the tests count from now
T = time.time()


def test_record_seen_updates_status_but_not_the_decision(eval_cache: Cache) -> None:
    record_evaluation(_record(stage=NOTIFIED, rating=5, when=T + 100), local_cache=eval_cache)
    record_seen("facebook", "1", "bike", "$80", now=T + 500, local_cache=eval_cache)
    (saved,) = _all(eval_cache)
    assert (saved.time, saved.stage, saved.rating) == (T + 100, NOTIFIED, 5)
    assert (saved.last_seen, saved.price, saved.previous_price) == (T + 500, "$80", "$100")


def test_record_seen_ignores_listings_without_a_record(eval_cache: Cache) -> None:
    record_seen("facebook", "1", "bike", "$80", now=T + 500, local_cache=eval_cache)
    assert _all(eval_cache) == []


def test_update_evaluation_sets_state_and_its_time(eval_cache: Cache) -> None:
    record_evaluation(_record(stage=NOTIFIED, when=T + 100), local_cache=eval_cache)
    update_evaluation(
        "facebook",
        "1",
        "bike",
        state=PENDING,
        checked=T + 200,
        now=T + 200,
        local_cache=eval_cache,
    )
    update_evaluation(
        "facebook",
        "1",
        "bike",
        state=PENDING,
        checked=T + 300,
        now=T + 300,
        local_cache=eval_cache,
    )
    (saved,) = _all(eval_cache)
    assert (saved.state, saved.state_changed, saved.checked, saved.time) == (
        PENDING,
        T + 200,
        T + 300,
        T + 100,
    )
    assert update_evaluation("facebook", "2", "bike", state=SOLD, local_cache=eval_cache) is None


def test_record_evaluation_keeps_the_status(eval_cache: Cache) -> None:
    record_evaluation(_record(stage=REJECTED, when=T + 100), local_cache=eval_cache)
    update_evaluation(
        "facebook", "1", "bike", state=SOLD, checked=T + 150, now=T + 150, local_cache=eval_cache
    )
    # decided again on the next search, at a lower price
    record_evaluation(_record(stage=REJECTED, when=T + 200, price="$90"), local_cache=eval_cache)
    (saved,) = _all(eval_cache)
    assert (saved.time, saved.state, saved.checked) == (T + 200, SOLD, T + 150)
    assert (saved.price, saved.previous_price) == ("$90", "$100")
    assert saved.last_seen == T + 200


def test_filter_evaluations_sort() -> None:
    now = time.time()
    records = [
        _record("a", rating=None, when=now - 50),
        _record("b", rating=3, when=now - 40),
        _record("c", rating=5, when=now - 30),
        _record("d", rating=3, when=now - 20),
        _record("e", rating=None, when=now - 10),
    ]
    assert [r.id for r in filter_evaluations(records, sort="time")] == list("edcba")
    assert [r.id for r in filter_evaluations(records, sort="time", descending=False)] == list(
        "abcde"
    )
    # unrated last either way; equal ratings newest first
    assert [r.id for r in filter_evaluations(records, sort="rating")] == list("cdbea")
    assert [r.id for r in filter_evaluations(records, sort="rating", descending=False)] == list(
        "dbcea"
    )
    with pytest.raises(ValueError, match="sort"):
        filter_evaluations(records, sort="price")


def test_filter_evaluations() -> None:
    now = time.time()
    records = [
        _record("1", stage=EXCLUDED, when=now - 30),
        _record("2", stage=REJECTED, rating=2, when=now - 20, seller="Bob's Bikes"),
        _record("3", stage=NOTIFIED, rating=5, when=now - 10, title="Carbon frame"),
    ]
    assert [r.id for r in filter_evaluations(records)] == ["3", "2", "1"]  # newest first
    assert [r.id for r in filter_evaluations(records, min_rating=3)] == ["3"]
    assert [r.id for r in filter_evaluations(records, text="CARBON")] == ["3"]
    assert [r.id for r in filter_evaluations(records, text="bob")] == ["2"]
    assert [r.id for r in filter_evaluations(records, stage=REJECTED)] == ["2"]


# ---------------------------------------------------------------- config


def test_monitor_config_evaluation_history_days() -> None:
    assert MonitorConfig(name="monitor", evaluation_history_days=7).evaluation_history_days == 7
    assert MonitorConfig(name="monitor").evaluation_history_days is None
    for bad in (0, -1, "30", True, 1.5):
        with pytest.raises(ValueError, match="evaluation_history_days"):
            MonitorConfig(name="monitor", evaluation_history_days=bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------- decision points


def _marketplace(**kwargs: Any) -> FacebookMarketplace:
    kwargs.setdefault("search_city", ["houston"])
    mp = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=None)
    mp.configure(FacebookMarketplaceConfig(name="facebook", **kwargs))
    return mp


def _item(**kwargs: Any) -> FacebookItemConfig:
    return FacebookItemConfig(name="bike", search_phrases=["bike"], **kwargs)


@pytest.mark.parametrize(
    ("item_kwargs", "market_kwargs", "listing_kwargs", "reason"),
    [
        (
            {"antikeywords": ["broken", "parts"]},
            {},
            {"title": "Broken bike"},
            "excluded keyword: broken",
        ),
        ({"keywords": ["carbon"]}, {}, {}, "missing required keywords: carbon"),
        ({}, {"seller_locations": ["dallas"]}, {"location": "Katy, TX"}, "out of area: Katy, TX"),
        ({}, {"exclude_sellers": ["jane"]}, {}, "banned seller: Jane"),
        ({}, {}, {}, None),
    ],
)
def test_exclusion_reason(
    item_kwargs: Any, market_kwargs: Any, listing_kwargs: Any, reason: str | None
) -> None:
    mp = _marketplace(**market_kwargs)
    item = _item(**item_kwargs)
    listing = _listing(**listing_kwargs)
    assert mp.exclusion_reason(listing, item) == reason
    assert mp.check_listing(listing, item) is (reason is None)


def test_search_records_excluded_listings(eval_cache: Cache) -> None:
    mp = _marketplace(seller_locations=["houston"])
    mp.page = MagicMock()
    mp.page.url = "https://www.facebook.com/marketplace/houston/search"
    far = _listing("1", location="Katy, TX")
    near = _listing("2")
    with (
        patch.object(mp, "goto_url"),
        patch("ai_marketplace_monitor.facebook.FacebookSearchResultPage") as page_cls,
        patch("ai_marketplace_monitor.facebook.time.sleep"),
        patch("ai_marketplace_monitor.facebook.counter"),
        patch.object(mp, "get_listing_details", return_value=(near, True)),
    ):
        page_cls.return_value.get_listings.return_value = [far, near]
        found = list(mp.search(_item()))
    assert [x.id for x in found] == ["2"]
    [record] = _all(eval_cache)
    assert (record.id, record.item, record.stage) == ("1", "bike", EXCLUDED)
    assert record.reason == "out of area: Katy, TX"
    assert record.rating is None


def test_search_item_records_rejected_listings(eval_cache: Cache) -> None:
    monitor = MarketplaceMonitor.__new__(MarketplaceMonitor)
    monitor.logger = None
    monitor.config = MagicMock()
    monitor.config.user = {"me": MagicMock()}
    marketplace = MagicMock()
    marketplace.search.return_value = [_listing("1")]
    with (
        patch.object(monitor, "evaluate_by_ai", return_value=AIResponse(2, "too old")),
        patch("ai_marketplace_monitor.monitor.User") as user_cls,
        patch("ai_marketplace_monitor.monitor.counter"),
        patch("ai_marketplace_monitor.monitor.time.sleep"),
    ):
        user_cls.return_value.notification_status.return_value = None
        monitor.search_item(
            FacebookMarketplaceConfig(name="facebook", search_city=["houston"]),
            marketplace,
            _item(rating=[4]),
        )
    [record] = _all(eval_cache)
    assert (record.stage, record.rating, record.ai_comment) == (REJECTED, 2, "too old")
    assert record.reason == "rating 2 < 4: too old"


def test_notify_records_notified_listings(
    eval_cache: Cache, user: User, item_config: FacebookItemConfig
) -> None:
    rated, unrated = _listing("1"), _listing("2")
    ratings = [AIResponse(5, "great"), AIResponse(5, AIResponse.NOT_EVALUATED)]
    with patch("ai_marketplace_monitor.user.NotificationConfig.notify_all", return_value=True):
        user.notify([rated, unrated], ratings, item_config, local_cache=eval_cache)
    records = {r.id: r for r in _all(eval_cache)}
    assert records["1"].stage == NOTIFIED
    assert (records["1"].rating, records["1"].ai_comment) == (5, "great")
    assert (records["2"].rating, records["2"].ai_comment) == (None, "")
    assert records["1"].item == item_config.name


def test_failed_notification_records_nothing(
    eval_cache: Cache, user: User, item_config: FacebookItemConfig
) -> None:
    with patch("ai_marketplace_monitor.user.NotificationConfig.notify_all", return_value=False):
        user.notify([_listing()], [AIResponse(5, "great")], item_config, local_cache=eval_cache)
    assert _all(eval_cache) == []


# ---------------------------------------------------------------- web API


def _client(
    tmp_path: Path, c: Cache, monkeypatch: pytest.MonkeyPatch, exposed: bool = False
) -> TestClient:
    monkeypatch.setattr(webui_server, "cache", c)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[marketplace.facebook]\nsearch_city = 'dallas'\n", encoding="utf-8")
    handler = LogBroadcastHandler()
    state = AuthState()
    state.exposed = exposed
    app = create_app(
        WebUIConfig(config_files=[cfg_file], log_handler=handler),
        state,
        ConfigFileService([cfg_file]),
        handler,
    )
    return TestClient(app)


def _seed(c: Cache) -> None:
    now = time.time()
    record_evaluation(_record("1", stage=EXCLUDED, when=now - 30), local_cache=c)
    record_evaluation(
        _record("2", stage=REJECTED, rating=2, when=now - 20, title="=cmd"), local_cache=c
    )
    record_evaluation(_record("3", item="tv", stage=NOTIFIED, rating=5, when=now), local_cache=c)


def test_api_evaluations(
    tmp_path: Path, eval_cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(eval_cache)
    client = _client(tmp_path, eval_cache, monkeypatch)
    data = client.get("/api/evaluations").json()
    assert [r["id"] for r in data["records"]] == ["3", "2", "1"]
    assert data["total"] == 3
    assert data["items"] == ["bike", "tv"]

    def ids(query: str) -> List[str]:
        return [r["id"] for r in client.get(f"/api/evaluations?{query}").json()["records"]]

    assert ids("item=bike") == ["2", "1"]
    assert ids("stage=rejected") == ["2"]
    assert ids("min_rating=3") == ["3"]
    assert ids("q=CMD") == ["2"]
    assert ids(f"since={time.time() - 25}") == ["3", "2"]
    assert ids("item=&stage=") == ["3", "2", "1"]  # empty filters are ignored
    limited = client.get("/api/evaluations?limit=1").json()
    assert ([r["id"] for r in limited["records"]], limited["total"]) == (["3"], 3)
    assert client.get("/api/evaluations?stage=bogus").status_code == 400


def test_api_sorts_before_limit(
    tmp_path: Path, eval_cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = time.time()
    # the best-rated listing is the oldest, so a newest-first limit would drop it
    record_evaluation(
        _record("best", stage=NOTIFIED, rating=5, when=now - 500), local_cache=eval_cache
    )
    for i in range(5):
        record_evaluation(
            _record(f"n{i}", stage=REJECTED, rating=2, when=now - i), local_cache=eval_cache
        )
    client = _client(tmp_path, eval_cache, monkeypatch)

    def ids(query: str) -> List[str]:
        return [r["id"] for r in client.get(f"/api/evaluations?{query}").json()["records"]]

    assert ids("sort=rating&limit=1") == ["best"]
    assert ids("sort=rating&order=asc&limit=2") == ["n0", "n1"]
    assert ids("limit=2") == ["n0", "n1"]
    assert ids("order=asc&limit=1") == ["best"]
    assert client.get("/api/evaluations?sort=price").status_code == 400
    assert client.get("/api/evaluations?order=up").status_code == 400
    rows = list(csv.DictReader(io.StringIO(client.get("/api/evaluations.csv?sort=rating").text)))
    assert [r["rating"] for r in rows] == ["5", "2", "2", "2", "2", "2"]
    assert client.get("/api/evaluations.csv?sort=price").status_code == 400


def test_api_evaluations_csv(
    tmp_path: Path, eval_cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(eval_cache)
    client = _client(tmp_path, eval_cache, monkeypatch)
    resp = client.get("/api/evaluations.csv?item=bike")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.text.splitlines()[0].split(",") == EVALUATION_CSV_COLUMNS
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert [r["stage"] for r in rows] == [REJECTED, EXCLUDED]
    assert rows[0]["title"] == "'=cmd"  # formula injection neutralized
    assert rows[0]["rating"] == "2"
    assert rows[1]["rating"] == ""


def test_api_evaluations_broken_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    broken: Any = BrokenCache(tmp_path, Exception("malformed"))
    client = _client(tmp_path, broken, monkeypatch)
    assert client.get("/api/evaluations").json() == {"records": [], "total": 0, "items": []}


def test_api_evaluations_require_session_when_exposed(
    tmp_path: Path, eval_cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, eval_cache, monkeypatch, exposed=True)
    assert client.get("/api/evaluations").status_code == 401
    assert client.get("/api/evaluations.csv").status_code == 401
