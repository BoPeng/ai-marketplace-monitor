"""AI summaries of each item in the daily digest."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator, List, Tuple
from unittest.mock import MagicMock

import pytest
from diskcache import Cache  # type: ignore

from ai_marketplace_monitor import digest as dg
from ai_marketplace_monitor import digest_summary as ds
from ai_marketplace_monitor import monitor as mon
from ai_marketplace_monitor.facebook import FacebookItemConfig, FacebookMarketplaceConfig

UNTIL = datetime(2026, 10, 8, 8, 0).timestamp()
SINCE = UNTIL - dg.DIGEST_PERIOD


@pytest.fixture
def local_cache(tmp_path: Path) -> Iterator[Cache]:
    c = Cache(str(tmp_path / "cache"))
    yield c
    c.close()


def listing(title: str, rating: int | None = None, **kwargs: str) -> dg.DigestListing:
    return dg.DigestListing(
        title=title,
        price=kwargs.get("price", "$200"),
        url=f"https://x/{title}",
        location="Houston, TX",
        item="ipad",
        time=UNTIL - 60,
        rating=rating,
        comment=kwargs.get("comment", ""),
        state=kwargs.get("state", ""),
    )


def make_digest() -> dg.Digest:
    ipad = dg.ItemDigest(
        name="ipad",
        searches=12,
        notified=[listing("iPad Air", 5, comment="great price", state="pending")],
        rejected=[listing("iPad mini", 2, comment="too old")],
        updates=[listing("iPad Pro", 4, price="$250 (was $300)", state="sold")],
    )
    quiet = dg.ItemDigest(name="gopro", searches=5)
    return dg.Digest(
        since=SINCE, until=UNTIL, total=dg.ItemDigest(name="Total"), items=[ipad, quiet]
    )


def test_nothing_new() -> None:
    digest = make_digest()
    ipad, gopro = digest.items
    assert ds.nothing_new(ipad, digest) is None
    assert ds.nothing_new(gopro, digest) == "Nothing new in the last 24 hours (5 searches)."


def test_summary_prompt() -> None:
    digest = make_digest()
    config = SimpleNamespace(
        search_phrases=["ipad air", "ipad pro"],
        description="an iPad for drawing",
        min_price="100",
        max_price="300",
    )
    prompt = ds.summary_prompt(digest.items[0], digest, config)
    for text in (
        "ipad air, ipad pro",
        "an iPad for drawing",
        "100 to 300",
        "12 searches",
        "[rating 5] iPad Air, $200, pending: great price",
        "iPad Pro, $250 (was $300), sold",
        "[rating 2] iPad mini, $200: too old",
        f"at most {ds.SUMMARY_MAX_WORDS} words",
    ):
        assert text in prompt


def test_add_summaries_calls_the_ai_once_per_item_and_window(local_cache: Cache) -> None:
    calls: List[Tuple[str, str]] = []

    def summarize(item: str, prompt: str) -> str:
        calls.append((item, prompt))
        return "  The iPad Air   looks promising.\n"

    digest = make_digest()
    ds.add_summaries(digest, summarize, local_cache=local_cache)
    assert [i.summary for i in digest.items] == [
        "The iPad Air looks promising.",
        "Nothing new in the last 24 hours (5 searches).",
    ]
    assert [item for item, _ in calls] == ["ipad"]  # no AI call for "nothing new"

    again = make_digest()  # another user or channel, same window
    ds.add_summaries(again, summarize, local_cache=local_cache)
    assert again.items[0].summary == "The iPad Air looks promising."
    assert len(calls) == 1


def test_add_summaries_without_an_answer(local_cache: Cache) -> None:
    digest = make_digest()
    ds.add_summaries(digest, lambda item, prompt: None, local_cache=local_cache)
    assert digest.items[0].summary == ""
    assert local_cache.get(ds.summary_key("ipad", SINCE, UNTIL)) is None  # not cached: tried again


def test_add_summaries_survives_a_failing_summarizer(local_cache: Cache) -> None:
    def summarize(item: str, prompt: str) -> str:
        raise RuntimeError("AI down")

    digest = make_digest()
    ds.add_summaries(digest, summarize, local_cache=local_cache)
    assert digest.items[0].summary == ""
    assert digest.items[1].summary.startswith("Nothing new")


def test_long_answers_are_cut(local_cache: Cache) -> None:
    digest = make_digest()
    ds.add_summaries(digest, lambda item, prompt: "word " * 200, local_cache=local_cache)
    summary = digest.items[0].summary
    assert len(summary) <= ds.SUMMARY_MAX_CHARS and summary.endswith("…")


def test_monitor_summarize_item_tries_the_item_ai_services_in_order() -> None:
    monitor = mon.MarketplaceMonitor.__new__(mon.MarketplaceMonitor)
    monitor.logger = None
    down, up, other = MagicMock(), MagicMock(), MagicMock()
    down.config.name, up.config.name, other.config.name = "down", "up", "other"
    down.summarize.side_effect = RuntimeError("503")
    up.summarize.return_value = "Fine."
    other.summarize.return_value = "Other."
    monitor.ai_agents = [other, down, up]
    item = FacebookItemConfig(
        name="ipad", search_phrases=["ipad"], ai=["down", "up"], marketplace="facebook"
    )
    market = FacebookMarketplaceConfig(name="facebook", search_city=["houston"])
    monitor.config = SimpleNamespace(  # type: ignore[assignment]
        item={"ipad": item}, marketplace={"facebook": market}
    )

    assert monitor.summarize_item("ipad", "prompt") == "Fine."
    other.summarize.assert_not_called()
    # an item no longer in the config: any AI service
    assert monitor.summarize_item("removed", "prompt") == "Other."


def test_summaries_are_cached_per_window(local_cache: Cache) -> None:
    calls: List[str] = []

    def summarize(item: str, prompt: str) -> str:
        calls.append(item)
        return f"Answer {len(calls)}."

    daily = make_digest()
    catch_up = make_digest()
    catch_up.since = SINCE - dg.DIGEST_PERIOD  # same end, 48 hours
    ds.add_summaries(daily, summarize, local_cache=local_cache)
    ds.add_summaries(catch_up, summarize, local_cache=local_cache)
    assert calls == ["ipad", "ipad"]
    assert daily.items[0].summary == "Answer 1."
    assert catch_up.items[0].summary == "Answer 2."


def active_item(name: str) -> dg.ItemDigest:
    return dg.ItemDigest(name=name, searches=2, notified=[listing(name)])


def test_add_summaries_stops_asking_after_the_ai_fails(local_cache: Cache) -> None:
    calls: List[str] = []

    def summarize(item: str, prompt: str) -> None:
        calls.append(item)
        return None

    digest = make_digest()
    digest.items.insert(1, active_item("bike"))
    logger = MagicMock()
    ds.add_summaries(digest, summarize, logger=logger, local_cache=local_cache)
    assert calls == ["ipad"]
    assert [i.summary for i in digest.items][:2] == ["", ""]
    assert digest.items[2].summary.startswith("Nothing new")
    logger.warning.assert_called_once()
    message = logger.warning.call_args.args[0]
    assert "ipad" in message and "bike" in message


def test_add_summaries_stops_asking_after_an_exception(local_cache: Cache) -> None:
    calls: List[str] = []

    def summarize(item: str, prompt: str) -> str:
        calls.append(item)
        raise RuntimeError("AI down")

    digest = make_digest()
    digest.items.insert(1, active_item("bike"))
    logger = MagicMock()
    ds.add_summaries(digest, summarize, logger=logger, local_cache=local_cache)
    assert calls == ["ipad"]
    logger.debug.assert_called()
    logger.warning.assert_called_once()


def test_monitor_summarize_item_follows_the_item_ai_order() -> None:
    monitor = mon.MarketplaceMonitor.__new__(mon.MarketplaceMonitor)
    monitor.logger = None
    first, second = MagicMock(), MagicMock()
    first.config.name, second.config.name = "first", "second"
    first.summarize.return_value = "From first."
    second.summarize.return_value = "From second."
    monitor.ai_agents = [first, second]  # the order of the [ai.*] sections
    item = FacebookItemConfig(
        name="ipad", search_phrases=["ipad"], ai=["second", "first"], marketplace="facebook"
    )
    market = FacebookMarketplaceConfig(name="facebook", search_city=["houston"])
    monitor.config = SimpleNamespace(  # type: ignore[assignment]
        item={"ipad": item}, marketplace={"facebook": market}
    )
    assert monitor.summarize_item("ipad", "prompt") == "From second."
    first.summarize.assert_not_called()
