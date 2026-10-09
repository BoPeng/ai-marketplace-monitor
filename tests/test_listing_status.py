"""Listing status from listing pages and search results."""

import time
from pathlib import Path
from typing import Any, Dict, Iterator, List
from unittest.mock import MagicMock

import pytest
from diskcache import Cache  # type: ignore

from ai_marketplace_monitor import evaluations
from ai_marketplace_monitor import facebook as fb
from ai_marketplace_monitor import monitor as mon
from ai_marketplace_monitor.evaluations import (
    AVAILABLE,
    NOTIFIED,
    PENDING,
    REJECTED,
    SOLD,
    EvaluationRecord,
    iter_evaluations,
    record_evaluation,
)
from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.utils import Translator


@pytest.fixture
def eval_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Cache]:
    c = Cache(str(tmp_path / "cache"))
    monkeypatch.setattr(evaluations, "cache", c)
    yield c
    c.close()


@pytest.mark.parametrize(
    ("title", "state", "rest"),
    [
        ("Sold  \u00a0· 2018 Honda accord EX Sedan 4D", SOLD, "2018 Honda accord EX Sedan 4D"),
        ("Sold  · 2018 Honda accord EX Sedan 4D", SOLD, "2018 Honda accord EX Sedan 4D"),
        ("Pending · iPad Air", PENDING, "iPad Air"),
        # the h1 text of a pending listing on Facebook (2004231520294090, October 2026)
        (
            "Pending\u00a0 · Oval solid wood frame mirror 43x30",
            PENDING,
            "Oval solid wood frame mirror 43x30",
        ),
        ("iPad Air", AVAILABLE, "iPad Air"),
        ("Sold out iPad case", AVAILABLE, "Sold out iPad case"),
    ],
)
def test_listing_state(title: str, state: str, rest: str) -> None:
    assert fb.listing_state(title) == (state, rest)


def test_listing_state_translated() -> None:
    translator = Translator(dictionary={"Sold": "Vendu"})
    assert fb.listing_state("Vendu · Vélo", translator) == (SOLD, "Vélo")


def _record(listing_id: str, stage: str = NOTIFIED) -> EvaluationRecord:
    return EvaluationRecord(
        time=time.time() - 60,
        item="bike",
        marketplace="facebook",
        id=listing_id,
        url=f"https://www.facebook.com/marketplace/item/{listing_id}/",
        title="Bike",
        price="$100",
        location="",
        seller="",
        condition="",
        stage=stage,
        rating=5,
        ai_comment="",
        reason="",
    )


def _page_listing(title: str, price: str) -> Listing:
    return Listing(
        marketplace="facebook",
        name="",
        id="",
        title=title,
        image="",
        price=price,
        post_url="",
        location="",
        seller="Jane",
        condition="",
        description="",
    )


def test_check_status_reads_each_page(eval_cache: Cache, monkeypatch: pytest.MonkeyPatch) -> None:
    for listing_id in ("1", "2", "3"):
        record_evaluation(_record(listing_id), local_cache=eval_cache)
    pages = {
        "https://www.facebook.com/marketplace/item/1/": _page_listing("Sold · Bike", "$100"),
        "https://www.facebook.com/marketplace/item/2/": _page_listing("Bike", "$80"),
        # 3: the page cannot be parsed
    }
    mp = fb.FacebookMarketplace(name="facebook", browser=MagicMock(), logger=None)
    mp.page = MagicMock()
    visited: List[str] = []
    monkeypatch.setattr(mp, "goto_url", lambda url: visited.append(url))
    monkeypatch.setattr(fb, "parse_listing", lambda page, url, *a, **k: pages.get(url))
    monkeypatch.setattr(mp, "recover_login", lambda: False)
    monkeypatch.setattr(fb.time, "sleep", lambda s: None)

    records = [_record(i) for i in ("1", "2", "3")]
    assert mp.check_status(records) == 2
    assert len(visited) == 3
    saved = {r.id: r for r in iter_evaluations(local_cache=eval_cache)}
    assert (saved["1"].state, saved["2"].state, saved["3"].state) == (SOLD, AVAILABLE, "unknown")
    assert (saved["2"].price, saved["2"].previous_price) == ("$100", "")
    assert saved["1"].checked > 0 and saved["3"].checked == 0


def _status_marketplace(monkeypatch: pytest.MonkeyPatch, pages: Dict[str, Any]) -> Any:
    mp = fb.FacebookMarketplace(name="facebook", browser=MagicMock(), logger=None)
    mp.page = MagicMock()
    monkeypatch.setattr(mp, "goto_url", lambda url: None)
    monkeypatch.setattr(fb, "parse_listing", lambda page, url, *a, **k: pages.get(url))
    monkeypatch.setattr(mp, "recover_login", lambda: False)
    return mp


def test_check_status_paces_every_page_opened(
    eval_cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    mp = _status_marketplace(monkeypatch, {})  # no page can be read
    sleeps: List[float] = []
    monkeypatch.setattr(fb.time, "sleep", lambda s: sleeps.append(s))
    assert mp.check_status([_record(i) for i in ("1", "2", "3")]) == 0
    assert sleeps == [fb.STATUS_CHECK_DELAY] * 2


def test_check_status_stops_when_the_keyboard_monitor_pauses(
    eval_cache: Cache, monkeypatch: pytest.MonkeyPatch
) -> None:
    mp = _status_marketplace(monkeypatch, {})
    mp.keyboard_monitor = MagicMock()
    mp.keyboard_monitor.is_paused.return_value = True
    visited: List[str] = []
    monkeypatch.setattr(mp, "goto_url", lambda url: visited.append(url))
    assert mp.check_status([_record("1")]) == 0
    assert visited == []


def test_check_status_without_a_browser_page_opens_nothing() -> None:
    mp = fb.FacebookMarketplace(name="facebook", browser=MagicMock(), logger=None)
    assert mp.check_status([_record("1")]) == 0


DAY = 24 * 60 * 60
NOW = 1_800_000_000.0


def _at(listing_id: str, when: float, **kwargs: Any) -> EvaluationRecord:
    record = _record(listing_id, kwargs.pop("stage", NOTIFIED))
    record.time = when
    for name, value in kwargs.items():
        setattr(record, name, value)
    return record


def test_status_candidates() -> None:
    records = [
        _at("new", NOW - 3600),
        _at("old", NOW - 8 * DAY),  # notified more than 7 days ago
        _at("rejected", NOW - 3600, stage=REJECTED),
        _at("fresh", NOW - 3600, checked=NOW - 3600),  # checked in the last 20 hours
        _at("sold", NOW - 3600, state=SOLD),
        _at("stale", NOW - 2 * DAY, checked=NOW - DAY),
    ]
    assert [r.id for r in mon.status_candidates(records, NOW)["facebook"]] == ["new", "stale"]


def test_status_candidates_are_capped_per_item() -> None:
    records = [_at(str(i), NOW - i * 60) for i in range(15)]
    records += [_at(f"c{i}", NOW - i * 60, item="car") for i in range(3)]
    picked = mon.status_candidates(records, NOW)["facebook"]
    assert len(picked) == mon.STATUS_MAX_PER_ITEM + 3
    assert [r.id for r in picked if r.item == "bike"] == [str(i) for i in range(10)]


def test_refresh_listing_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monitor = mon.MarketplaceMonitor.__new__(mon.MarketplaceMonitor)
    monitor.logger = None
    marketplace = MagicMock()
    marketplace.check_status.return_value = 1
    monkeypatch.setattr(mon.MarketplaceMonitor, "active_marketplaces", {"facebook": marketplace})
    monkeypatch.setattr(mon, "iter_evaluations", lambda **kwargs: [_at("1", NOW - 60)])
    monkeypatch.setattr(mon.time, "time", lambda: NOW)
    monitor.refresh_listing_status()
    (records,), _ = marketplace.check_status.call_args
    assert [r.id for r in records] == ["1"]


def test_refresh_listing_status_skipped_while_paused(monkeypatch: pytest.MonkeyPatch) -> None:
    monitor = mon.MarketplaceMonitor.__new__(mon.MarketplaceMonitor)
    monitor.logger = None
    marketplace = MagicMock()
    monkeypatch.setattr(mon.MarketplaceMonitor, "active_marketplaces", {"facebook": marketplace})
    monkeypatch.setattr(mon.control, "is_paused", lambda: True)
    monitor.refresh_listing_status()
    marketplace.check_status.assert_not_called()
