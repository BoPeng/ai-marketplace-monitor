"""The marketplaces an item is searched in (#469): its `marketplace`, else every one."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any, List

import pytest
import schedule  # type: ignore

from ai_marketplace_monitor.config import Config

TWO_MARKETS = """
[marketplace.houston]
search_city = "houston"
username = "u"
password = "p"

[marketplace.dallas]
search_city = "dallas"
username = "u"
password = "p"

[user.me]
pushbullet_token = "x"
"""


def _config(tmp_path: Path, items: str) -> Config:
    path = tmp_path / "config.toml"
    path.write_text(textwrap.dedent(TWO_MARKETS + items), encoding="utf-8")
    return Config([path])


def test_an_item_without_marketplace_is_searched_in_every_marketplace(tmp_path: Path) -> None:
    config = _config(tmp_path, '[item.bike]\nsearch_phrases = "bike"\n')
    targets = config.item_targets["bike"]
    assert list(targets) == ["houston", "dallas"]
    # a config for each, with its own marketplace and search count
    assert [t.marketplace for t in targets.values()] == ["houston", "dallas"]
    assert targets["houston"] is not targets["dallas"]
    assert config.item["bike"] is targets["houston"]


@pytest.mark.parametrize(
    ("marketplace", "expected"),
    [
        ('"dallas"', ["dallas"]),
        ('["dallas", "houston"]', ["dallas", "houston"]),
        ('["dallas", "dallas"]', ["dallas"]),
    ],
)
def test_an_item_names_its_marketplaces(
    tmp_path: Path, marketplace: str, expected: List[str]
) -> None:
    config = _config(
        tmp_path, f'[item.bike]\nsearch_phrases = "bike"\nmarketplace = {marketplace}\n'
    )
    assert list(config.item_targets["bike"]) == expected


@pytest.mark.parametrize(
    ("marketplace", "error"),
    [
        ('"austin"', "does not exist: .*austin"),
        ("[]", "a marketplace name or a list"),
        ("3", "a marketplace name or a list"),
    ],
)
def test_an_item_names_existing_marketplaces(tmp_path: Path, marketplace: str, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        _config(tmp_path, f'[item.bike]\nsearch_phrases = "bike"\nmarketplace = {marketplace}\n')


def test_an_item_of_several_marketplaces_cannot_set_its_own_location(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sets search_city but is searched in marketplaces"):
        _config(tmp_path, '[item.bike]\nsearch_phrases = "bike"\nsearch_city = "austin"\n')
    # with one marketplace it can
    config = _config(
        tmp_path,
        '[item.bike]\nsearch_phrases = "bike"\nsearch_city = "austin"\nmarketplace = "dallas"\n',
    )
    assert config.item_targets["bike"]["dallas"].search_city == ["austin"]


def test_the_monitor_schedules_an_item_in_each_of_its_marketplaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_marketplace_monitor import monitor as mon

    config = _config(tmp_path, '[item.bike]\nsearch_phrases = "bike"\n')
    monitor = mon.MarketplaceMonitor.__new__(mon.MarketplaceMonitor)
    monitor.config = config
    monitor.browser = "the browser"  # type: ignore[assignment]
    monitor.logger = None
    monitor.keyboard_monitor = None
    monkeypatch.setattr(mon.MarketplaceMonitor, "active_marketplaces", {})
    monkeypatch.setattr(monitor, "load_config_file", lambda: config)
    monkeypatch.setattr(monitor, "load_ai_agents", lambda: None)
    scheduled: List[Any] = []
    monkeypatch.setattr(
        monitor, "search_item", lambda *args: scheduled.append(args)  # type: ignore[arg-type]
    )
    schedule.clear()
    try:
        monitor.schedule_jobs()
        jobs = [job for job in schedule.get_jobs() if "bike" in job.tags]
        assert len(jobs) == 2
        for job in jobs:
            job.run()
    finally:
        schedule.clear()
    assert sorted(item.marketplace for _, _, item in scheduled) == ["dallas", "houston"]
    assert all(m.name == item.marketplace for m, _, item in scheduled)


# ------------------------------------------------------------------ options per marketplace type


class HttpMarketplace:
    """A marketplace type with only the shared options (no availability, category, login)."""

    from ai_marketplace_monitor.marketplaces.base import ItemConfig, MarketplaceConfig

    market_type = "http"
    config_class = MarketplaceConfig
    item_config_class = ItemConfig
    supports_regions = False

    @classmethod
    def get_config(cls, **kwargs: Any) -> Any:
        return cls.config_class(**kwargs)

    @classmethod
    def get_item_config(cls, **kwargs: Any) -> Any:
        return cls.item_config_class(**kwargs)


MIXED = """
[marketplace.facebook]
search_city = "houston"
username = "u"
password = "p"

[marketplace.other]
market_type = "http"
search_city = "houston"

[user.me]
pushbullet_token = "x"
"""


def _mixed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: str) -> Config:
    from ai_marketplace_monitor.marketplaces import supported_marketplaces

    monkeypatch.setitem(supported_marketplaces, "http", HttpMarketplace)  # type: ignore[arg-type]
    path = tmp_path / "config.toml"
    path.write_text(textwrap.dedent(MIXED + extra), encoding="utf-8")
    return Config([path])


def test_an_option_a_marketplace_does_not_have_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sets colour, which facebook marketplaces do not have"):
        _config(
            tmp_path,
            '[marketplace.austin]\nsearch_city = "austin"\ncolour = "red"\n'
            '[item.bike]\nsearch_phrases = "bike"\nmarketplace = "dallas"\n',
        )
    with pytest.raises(ValueError, match="Item .*bike.* sets colour, which facebook"):
        _config(tmp_path, '[item.bike]\nsearch_phrases = "bike"\ncolour = "red"\n')


def test_an_option_only_some_marketplaces_have_is_used_where_it_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.warns(UserWarning, match="availability not used in marketplace other"):
        config = _mixed(
            tmp_path, monkeypatch, '[item.bike]\nsearch_phrases = "bike"\navailability = "in"\n'
        )
    targets = config.item_targets["bike"]
    assert targets["facebook"].availability == ["in"]
    assert not hasattr(targets["other"], "availability")
    # no login for a marketplace that has none
    assert not hasattr(config.marketplace["other"], "username")


def test_an_option_no_marketplace_of_the_item_has_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValueError, match="sets colour, which facebook and http marketplaces"):
        _mixed(tmp_path, monkeypatch, '[item.bike]\nsearch_phrases = "bike"\ncolour = "red"\n')


def test_regions_are_for_facebook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_marketplace_monitor.marketplaces import supported_marketplaces

    monkeypatch.setitem(supported_marketplaces, "http", HttpMarketplace)  # type: ignore[arg-type]
    path = tmp_path / "config.toml"
    path.write_text(
        textwrap.dedent(
            MIXED.replace(
                'market_type = "http"\nsearch_city = "houston"',
                'market_type = "http"\nsearch_region = "usa"',
            )
            + '[item.bike]\nsearch_phrases = "bike"\nmarketplace = "facebook"\n'
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        ValueError, match="search_region, but \\[region.\\*\\] sections are for Facebook"
    ):
        Config([path])
