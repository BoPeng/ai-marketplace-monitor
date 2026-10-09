"""Listing status from listing pages and search results."""

import time
from pathlib import Path
from typing import Iterator, List
from unittest.mock import MagicMock

import pytest
from diskcache import Cache  # type: ignore

from ai_marketplace_monitor import evaluations
from ai_marketplace_monitor import facebook as fb
from ai_marketplace_monitor.evaluations import (
    AVAILABLE,
    NOTIFIED,
    PENDING,
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
    assert (saved["2"].price, saved["2"].previous_price) == ("$80", "$100")
    assert saved["1"].checked > 0 and saved["3"].checked == 0


def test_check_status_without_a_browser_page_opens_nothing() -> None:
    mp = fb.FacebookMarketplace(name="facebook", browser=MagicMock(), logger=None)
    assert mp.check_status([_record("1")]) == 0
