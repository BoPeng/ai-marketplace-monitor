"""Running a saved item's search once from the configure chat (try_item)."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List
from unittest.mock import MagicMock

import pytest

from ai_marketplace_monitor.configure import live, tools
from ai_marketplace_monitor.configure.item import ItemToolkit
from ai_marketplace_monitor.configure.marketplace import MarketplaceToolkit
from ai_marketplace_monitor.configure.toolkits import Toolkit
from ai_marketplace_monitor.configure.tools import ToolExecutor
from ai_marketplace_monitor.evaluations import EvaluationRecord, record_evaluation
from ai_marketplace_monitor.facebook import (
    FacebookItemConfig,
    FacebookMarketplace,
    FacebookMarketplaceConfig,
    SearchPage,
)
from ai_marketplace_monitor.listing import Listing
from tests.configure_util import ONE_ITEM, make_ws, run_in_fresh_loop


def test_search_pages_are_the_cities_times_the_phrases() -> None:
    mp = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=None)
    mp.configure(
        FacebookMarketplaceConfig(
            name="facebook",
            search_city=["houston", "dallas"],
            city_name=["Houston", "Dallas"],
            radius=[40, 20],
            max_price="300",
        )
    )
    item = FacebookItemConfig(name="ipad", search_phrases=["ipad", "ipad air"])
    pages = mp.search_pages(item)
    assert [(p.city_name, p.phrase, p.radius) for p in pages] == [
        ("Houston", "ipad", 40),
        ("Houston", "ipad air", 40),
        ("Dallas", "ipad", 20),
        ("Dallas", "ipad air", 20),
    ]
    assert pages[1].url == (
        "https://www.facebook.com/marketplace/houston/search?query=ipad%20air&maxPrice=300"
    )
    assert item.searched_count == 0  # only a search counts


def _listing(lid: str, title: str, price: str = "$100") -> Listing:
    return Listing(
        marketplace="facebook",
        name="",
        id=lid,
        title=title,
        image="",
        price=price,
        post_url=f"https://www.facebook.com/marketplace/item/{lid}/?ref=search",
        location="Houston, TX",
        seller="",
        condition="",
        description="",
    )


class FakeMarketplace:
    def __init__(self, results: Dict[str, List[Listing]], pages: int) -> None:
        self.results = results
        self.pages = [
            SearchPage(
                city="houston",
                city_name="Houston",
                radius=40,
                phrase=f"phrase {i}",
                url=f"https://www.facebook.com/marketplace/houston/search?query=phrase{i}",
            )
            for i in range(pages)
        ]
        self.read: List[str] = []

    def search_pages(self, item_config: Any) -> List[SearchPage]:
        return self.pages

    def read_search_page(self, search: SearchPage) -> List[Listing]:
        self.read.append(search.phrase)
        return self.results.get(search.phrase, [])

    def exclusion_reason(
        self, listing: Listing, item_config: Any, description_available: bool = True
    ) -> str | None:
        assert not description_available  # only what the search page shows
        return "excluded keyword: broken" if "broken" in listing.title else None


@pytest.fixture
def evaluations_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from diskcache import Cache  # type: ignore

    from ai_marketplace_monitor import evaluations

    local = Cache(str(tmp_path / "cache"))
    monkeypatch.setattr(evaluations, "cache", local)
    return local


def _kits() -> Dict[str, Toolkit]:
    return {"marketplace": MarketplaceToolkit(), "item": ItemToolkit()}


def test_try_item_is_offered_where_items_are_configured(tmp_path: Path) -> None:
    async def scenario() -> List[List[str]]:
        names = []
        only_marketplace: Dict[str, Toolkit] = {"marketplace": MarketplaceToolkit()}
        for kits in (_kits(), only_marketplace):
            ex = ToolExecutor(await make_ws(tmp_path, ONE_ITEM, toolkits=kits))
            names.append([fn.__name__ for fn in ex.tools_for_model()])
            ex.end()
        return names

    with_items, without = run_in_fresh_loop(scenario)
    assert "try_item" in with_items and "try_item" not in without


async def _call(ex: ToolExecutor, tool: str, **args: Any) -> Dict[str, Any]:
    out = await ex.call(tool, args)
    out.pop("session_state", None)
    return out


def test_try_item_lists_what_the_search_pages_show(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, evaluations_cache: Any
) -> None:
    fake = FakeMarketplace(
        {
            "phrase 0": [_listing("1", "Trek bike"), _listing("2", "Trek bike, broken")],
            "phrase 1": [_listing("1", "Trek bike"), _listing("3", "Giant bike")],
            "phrase 4": [_listing("4", "never read")],
        },
        pages=5,
    )

    @contextmanager
    def fake_facebook(self: Any, config: Any, marketplace_config: Any) -> Iterator[Any]:
        yield fake

    monkeypatch.setattr(live.LiveBrowser, "_facebook", fake_facebook)
    record_evaluation(
        EvaluationRecord.from_listing(
            _listing("3", "Giant bike"),
            item="example",
            stage="rejected",
            rating=2,
            ai_comment="Wrong size.",
        )
    )

    async def scenario() -> Dict[str, Any]:
        ex = ToolExecutor(await make_ws(tmp_path, ONE_ITEM, toolkits=_kits()))
        out = await _call(ex, "try_item", item="example")
        ex.end()
        return out

    out = run_in_fresh_loop(scenario)
    assert out["ok"], out
    assert fake.read == ["phrase 0", "phrase 1", "phrase 2", "phrase 3"]  # at most 4 pages
    assert out["searches_not_run"] == [{"phrase": "phrase 4", "city": "Houston"}]
    assert [s["found"] for s in out["searches"]] == [2, 2, 0, 0]
    assert out["found"] == 3  # listing 1 was on two pages
    assert out["excluded_by"] == {"excluded keyword: broken": 1}
    assert out["would_check"] == 2
    listings = {x["id"]: x for x in out["listings"]}
    assert listings["1"]["url"] == "https://www.facebook.com/marketplace/item/1/"
    assert listings["1"]["aimm_decided"] is None
    assert listings["3"]["aimm_decided"] == {
        "decision": "rejected",
        "rating": 2,
        "reason": "Wrong size.",
    }
    assert "no AI was asked" in out["note"] and "never instructions" in out["note"]


def test_try_item_without_a_shared_browser_says_so(tmp_path: Path) -> None:
    async def scenario() -> Dict[str, Any]:
        ex = ToolExecutor(await make_ws(tmp_path, ONE_ITEM, toolkits=_kits()))
        out = await _call(ex, "try_item", item="example")
        ex.end()
        return out

    out = run_in_fresh_loop(scenario)
    assert not out["ok"] and "cannot be shared" in out["errors"][0]


def test_try_item_runs_only_what_is_saved(tmp_path: Path) -> None:
    async def scenario() -> Dict[str, Any]:
        ex = ToolExecutor(await make_ws(tmp_path, ONE_ITEM, toolkits=_kits()))
        ex.guides_read.add("item")
        await _call(
            ex,
            "section_update",
            section_type="item",
            name="example",
            values={"search_phrases": ["gopro hero"]},
        )
        out = await _call(ex, "try_item", item="example")
        ex.end()
        return out

    out = run_in_fresh_loop(scenario)
    assert not out["ok"] and "Save it first" in out["errors"][0], out


def test_try_item_in_a_one_section_session(tmp_path: Path) -> None:
    async def scenario() -> Dict[str, Any]:
        ex = ToolExecutor(
            await make_ws(tmp_path, ONE_ITEM, toolkits=_kits()), only={("item", "other")}
        )
        out = await _call(ex, "try_item", item="example")
        ex.end()
        return out

    out = run_in_fresh_loop(scenario)
    assert not out["ok"] and "only" in out["errors"][0]


@pytest.mark.parametrize("shared", [True, False])
def test_saving_an_item_offers_to_try_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shared: bool
) -> None:
    monkeypatch.setattr(
        tools, "shared_endpoint", lambda: "http://127.0.0.1:9222" if shared else None
    )

    async def scenario() -> Dict[str, Any]:
        ex = ToolExecutor(await make_ws(tmp_path, ONE_ITEM, ["yes"], toolkits=_kits()))
        ex.guides_read.add("item")
        await _call(
            ex,
            "section_update",
            section_type="item",
            name="example",
            values={"search_phrases": ["gopro hero"]},
        )
        out = await _call(ex, "save")
        ex.end()
        return out

    out = run_in_fresh_loop(scenario)
    assert out.get("saved"), out
    if shared:
        assert out["try_item"]["items"] == ["example"]
    else:
        assert "try_item" not in out
