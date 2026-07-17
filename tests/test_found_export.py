"""Tests for the Web UI found-items CSV export."""

from __future__ import annotations

import csv
import io
from typing import Dict, List

from ai_marketplace_monitor.webui.found_export import CSV_COLUMNS, rows_to_csv


def _parse(text: str) -> List[Dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_rows_to_csv_empty_has_header_only() -> None:
    text = rows_to_csv([])
    lines = text.splitlines()
    assert lines[0].split(",") == CSV_COLUMNS
    # Pin the canonical column order (a binding requirement) against silent drift.
    assert lines[0] == (
        "found_at,item,marketplace,title,price,rating,ai_comment,"
        "location,seller,condition,notified_user,url"
    )
    assert len(lines) == 1


def test_rows_to_csv_writes_row_and_escapes() -> None:
    row = dict.fromkeys(CSV_COLUMNS, "")
    row["title"] = 'Chair, "comfy"'
    row["price"] = "$40"
    text = rows_to_csv([row])
    parsed = _parse(text)
    assert len(parsed) == 1
    assert parsed[0]["title"] == 'Chair, "comfy"'
    assert parsed[0]["price"] == "$40"


def test_rows_to_csv_neutralizes_formula_injection() -> None:
    row = dict.fromkeys(CSV_COLUMNS, "")
    row["title"] = '=HYPERLINK("http://evil")'
    row["seller"] = "+cmd"
    row["ai_comment"] = "@SUM(1)"
    text = rows_to_csv([row])
    parsed = _parse(text)
    assert parsed[0]["title"] == '\'=HYPERLINK("http://evil")'
    assert parsed[0]["seller"] == "'+cmd"
    assert parsed[0]["ai_comment"] == "'@SUM(1)"


from pathlib import Path  # noqa: E402
from typing import Iterator  # noqa: E402

import pytest  # noqa: E402
from diskcache import Cache  # type: ignore  # noqa: E402

from ai_marketplace_monitor.listing import Listing  # noqa: E402
from ai_marketplace_monitor.utils import CacheType  # noqa: E402
from ai_marketplace_monitor.webui.found_export import build_found_rows  # noqa: E402


def _listing(listing_id: str = "123", price: str = "$100") -> Listing:
    return Listing(
        marketplace="facebook",
        name="iphone",
        id=listing_id,
        title="iPhone 13",
        image="http://img/x.jpg",
        price=price,
        post_url=f"https://www.facebook.com/marketplace/item/{listing_id}/?ref=search",
        location="Houston, TX",
        seller="Jane Doe",
        condition="used_good",
        description="great phone",
    )


@pytest.fixture
def temp_cache(tmp_path: Path) -> Iterator[Cache]:
    cache = Cache(str(tmp_path / "cache"))
    yield cache
    cache.close()


def _seed_notified(
    cache: Cache, listing: Listing, user: str = "me", date: str = "2026-07-16 10:00:00"
) -> None:
    cache.set(
        (CacheType.USER_NOTIFIED.value, listing.marketplace, listing.id, user),
        (date, listing.hash, listing.price),
        tag=CacheType.USER_NOTIFIED.value,
    )


def _seed_rating(
    cache: Cache, listing: Listing, score: int = 5, comment: str = "Great deal"
) -> None:
    cache.set(
        (CacheType.AI_INQUIRY.value, "itemhash", "mkthash", listing.hash),
        {"score": score, "comment": comment, "name": ""},
        tag=CacheType.AI_INQUIRY.value,
    )


def test_build_rows_full_join(temp_cache: Cache) -> None:
    listing = _listing()
    listing.to_cache(listing.post_url, local_cache=temp_cache)
    _seed_rating(temp_cache, listing)
    _seed_notified(temp_cache, listing)

    rows = build_found_rows(temp_cache)
    assert len(rows) == 1
    row = rows[0]
    assert row["found_at"] == "2026-07-16 10:00:00"
    assert row["item"] == "iphone"
    assert row["marketplace"] == "facebook"
    assert row["title"] == "iPhone 13"
    assert row["price"] == "$100"
    assert row["rating"] == "5"
    assert row["ai_comment"] == "Great deal"
    assert row["location"] == "Houston, TX"
    assert row["seller"] == "Jane Doe"
    assert row["condition"] == "used_good"
    assert row["notified_user"] == "me"
    assert row["url"] == "https://www.facebook.com/marketplace/item/123/?ref=search"


def test_build_rows_missing_details_uses_fallback_url(temp_cache: Cache) -> None:
    listing = _listing()
    _seed_notified(temp_cache, listing)  # no LISTING_DETAILS, no rating

    rows = build_found_rows(temp_cache)
    assert len(rows) == 1
    assert rows[0]["title"] == ""
    assert rows[0]["rating"] == ""
    assert rows[0]["url"] == "https://www.facebook.com/marketplace/item/123/"


def test_build_rows_legacy_notified_value_shapes(temp_cache: Cache) -> None:
    listing = _listing()
    # legacy: bare date string
    temp_cache.set(
        (CacheType.USER_NOTIFIED.value, "facebook", "aaa", "me"),
        "2026-07-15 09:00:00",
        tag=CacheType.USER_NOTIFIED.value,
    )
    # legacy: 2-tuple (date, hash)
    temp_cache.set(
        (CacheType.USER_NOTIFIED.value, "facebook", "bbb", "me"),
        ("2026-07-15 09:30:00", listing.hash),
        tag=CacheType.USER_NOTIFIED.value,
    )
    rows = build_found_rows(temp_cache)
    assert len(rows) == 2
    assert {r["found_at"] for r in rows} == {"2026-07-15 09:00:00", "2026-07-15 09:30:00"}


def test_build_rows_multi_user_two_rows(temp_cache: Cache) -> None:
    listing = _listing()
    listing.to_cache(listing.post_url, local_cache=temp_cache)
    _seed_notified(temp_cache, listing, user="alice")
    _seed_notified(temp_cache, listing, user="bob")
    rows = build_found_rows(temp_cache)
    assert len(rows) == 2
    assert {r["notified_user"] for r in rows} == {"alice", "bob"}


def test_build_rows_sorted_by_found_at_desc(temp_cache: Cache) -> None:
    old, new = _listing("111"), _listing("222")
    _seed_notified(temp_cache, old, date="2026-07-10 08:00:00")
    _seed_notified(temp_cache, new, date="2026-07-16 08:00:00")
    rows = build_found_rows(temp_cache)
    assert [r["found_at"] for r in rows] == ["2026-07-16 08:00:00", "2026-07-10 08:00:00"]


def test_build_rows_excludes_unnotified_listings(temp_cache: Cache) -> None:
    # One notified listing, fully joined.
    wanted = _listing("111")
    wanted.to_cache(wanted.post_url, local_cache=temp_cache)
    _seed_rating(temp_cache, wanted)
    _seed_notified(temp_cache, wanted)
    # An unrelated scraped listing + rating that was never notified: the two-pass
    # loader must not surface it (and, per the memory design, not even load it).
    other = _listing("222")
    other.to_cache(other.post_url, local_cache=temp_cache)
    _seed_rating(temp_cache, other)

    rows = build_found_rows(temp_cache)
    assert len(rows) == 1
    assert rows[0]["url"] == "https://www.facebook.com/marketplace/item/111/?ref=search"


from fastapi.testclient import TestClient  # noqa: E402

from ai_marketplace_monitor.webui import server as webui_server  # noqa: E402
from ai_marketplace_monitor.webui.config_api import ConfigFileService  # noqa: E402
from ai_marketplace_monitor.webui.log_handler import LogBroadcastHandler  # noqa: E402
from ai_marketplace_monitor.webui.server import AuthState, WebUIConfig, create_app  # noqa: E402


def _make_client(
    tmp_path: Path, temp_cache: Cache, monkeypatch: pytest.MonkeyPatch, exposed: bool = False
) -> TestClient:
    monkeypatch.setattr(webui_server, "cache", temp_cache)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[marketplace.facebook]\nsearch_city = 'dallas'\n", encoding="utf-8")
    handler = LogBroadcastHandler()
    config = WebUIConfig(config_files=[cfg_file], log_handler=handler)
    state = AuthState()
    state.exposed = exposed
    service = ConfigFileService([cfg_file])
    app = create_app(config, state, service, handler)
    return TestClient(app)


def test_endpoint_returns_csv(
    tmp_path: Path, temp_cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing = _listing()
    listing.to_cache(listing.post_url, local_cache=temp_cache)
    _seed_rating(temp_cache, listing)
    _seed_notified(temp_cache, listing)

    client = _make_client(tmp_path, temp_cache, monkeypatch)
    resp = client.get("/api/found.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    parsed = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(parsed) == 1
    assert parsed[0]["rating"] == "5"
    assert parsed[0]["url"].startswith("https://www.facebook.com/marketplace/item/123/")


def test_endpoint_requires_session_when_exposed(
    tmp_path: Path, temp_cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_client(tmp_path, temp_cache, monkeypatch, exposed=True)
    resp = client.get("/api/found.csv")
    assert resp.status_code == 401
