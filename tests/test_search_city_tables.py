"""search_city as a table of values by marketplace type, in sections and regions."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

import pytest

from ai_marketplace_monitor.config import Config
from ai_marketplace_monitor.marketplaces.base import (
    ItemConfig,
    MarketplaceConfig,
    is_location,
    location_value,
)

USER = '[user.me]\npushbullet_token = "x"\n'
FACEBOOK = '[marketplace.facebook]\nusername = "u"\npassword = "p"\n'


def _config(tmp_path: Path, text: str) -> Config:
    path = tmp_path / "config.toml"
    path.write_text(textwrap.dedent(text + USER), encoding="utf-8")
    return Config([path])


def test_values_of_a_table_by_marketplace_type() -> None:
    assert location_value("houston", "facebook") == "houston"
    assert location_value({"facebook": "houston", "offerup": "77096"}, "offerup") == "77096"
    assert location_value({"Facebook": "houston"}, "facebook") == "houston"
    assert location_value({"offerup": "77096"}, "facebook") is None
    assert is_location({"facebook": "houston"}) and is_location("houston")
    assert not is_location({}) and not is_location({"facebook": 3}) and not is_location(3)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('{ facebook = "houston", offerup = "77096" }', ["houston"]),
        ('["dallas", { facebook = "houston", offerup = "77096" }]', ["dallas", "houston"]),
        ('"houston"', ["houston"]),
    ],
)
def test_a_facebook_section_takes_its_value(tmp_path: Path, value: str, expected: list) -> None:
    config = _config(
        tmp_path, FACEBOOK + f"search_city = {value}\n" + '[item.bike]\nsearch_phrases = "bike"\n'
    )
    market = config.marketplace["facebook"]
    assert market.search_city == expected
    assert market.city_name == [c.capitalize() for c in expected]  # named by its own value


def test_a_table_without_the_sections_type_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="has no value for facebook marketplaces"):
        _config(
            tmp_path,
            FACEBOOK + 'search_city = { offerup = "77096" }\n[item.bike]\nsearch_phrases = "b"\n',
        )


def test_a_tables_value_is_checked_in_the_marketplaces_format(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="'Houston' has incorrect format"):
        _config(
            tmp_path,
            FACEBOOK
            + 'search_city = { facebook = "Houston" }\n[item.bike]\nsearch_phrases = "b"\n',
        )


REGION = """
[region.texas]
search_city = [{ facebook = "houston", offerup = "77002" }, { facebook = "dallas", offerup = "75201" }]
radius = 50
"""


def test_a_region_lists_its_cities_by_type(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        REGION + FACEBOOK + 'search_region = "texas"\n[item.bike]\nsearch_phrases = "bike"\n',
    )
    market = config.marketplace["facebook"]
    assert market.search_city == ["houston", "dallas"]
    assert market.city_name == ["Houston", "Dallas"]
    assert config.region["texas"].search_city[0] == {"facebook": "houston", "offerup": "77002"}


def test_a_region_without_the_sections_type_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Region .*texas.* has no facebook value"):
        _config(
            tmp_path,
            '[region.texas]\nsearch_city = [{ offerup = "77002" }]\n'
            + FACEBOOK
            + 'search_region = "texas"\n[item.bike]\nsearch_phrases = "bike"\n',
        )


# ------------------------------------------------------------------ items of several types


@dataclass
class HttpMarketplaceConfig(MarketplaceConfig):
    location_type: ClassVar[str] = "http"


@dataclass
class HttpItemConfig(ItemConfig):
    location_type: ClassVar[str] = "http"


class HttpMarketplace:
    market_type = "http"
    config_class = HttpMarketplaceConfig
    item_config_class = HttpItemConfig
    supports_regions = False

    @classmethod
    def get_config(cls, **kwargs: Any) -> Any:
        return cls.config_class(**kwargs)

    @classmethod
    def get_item_config(cls, **kwargs: Any) -> Any:
        return cls.item_config_class(**kwargs)


@pytest.fixture
def http_type(monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_marketplace_monitor.marketplaces import supported_marketplaces

    monkeypatch.setitem(supported_marketplaces, "http", HttpMarketplace)  # type: ignore[arg-type]


def test_an_item_of_two_types_sets_a_place_for_each(tmp_path: Path, http_type: None) -> None:
    config = _config(
        tmp_path,
        FACEBOOK
        + '[marketplace.other]\nmarket_type = "http"\n'
        + '[item.bike]\nsearch_phrases = "bike"\nradius = 30\n'
        + 'search_city = { facebook = "houston", http = "77096" }\n',
    )
    targets = config.item_targets["bike"]
    assert targets["facebook"].search_city == ["houston"]
    assert targets["other"].search_city == ["77096"]
    assert targets["facebook"].radius == targets["other"].radius == [30]


def test_an_item_of_two_sections_of_one_type_still_cannot(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sets search_city but is searched in marketplaces"):
        _config(
            tmp_path,
            FACEBOOK
            + 'search_city = "houston"\n[marketplace.dallas]\nsearch_city = "dallas"\n'
            + 'username = "u"\npassword = "p"\n'
            + '[item.bike]\nsearch_phrases = "bike"\nsearch_city = { facebook = "austin" }\n',
        )


# ------------------------------------------------------------------ the configure chat


def test_the_chat_reads_the_facebook_codes_and_shows_tables() -> None:
    from ai_marketplace_monitor.configure.toolkits import listed
    from ai_marketplace_monitor.configure.workspace import _codes

    value = ["dallas", {"facebook": "houston", "offerup": "77096"}, {"offerup": "75201"}]
    assert _codes(value) == {"dallas", "houston"}
    assert listed(value) == ["dallas", "houston / 77096", "75201"]


def test_a_config_with_tables_can_be_normalized() -> None:
    from ai_marketplace_monitor.normalize import expand, normalize
    from tests.normalize_util import parse, system_cfg

    text = (
        REGION
        + FACEBOOK
        + 'search_city = { facebook = "houston", offerup = "77096" }\n'
        + '[item.bike]\nsearch_phrases = "bike"\nmarketplace = "facebook"\n'
        + USER
    )
    expanded = expand(parse(text), system_cfg()).config
    assert expanded["item"]["bike"]["search_city"] == {"facebook": "houston", "offerup": "77096"}
    normalize(parse(text), system_cfg())


def test_a_region_without_currency_still_has_its_cities(tmp_path: Path) -> None:
    """Only the built-in regions set currency; zip() with an empty list dropped every city."""
    config = _config(
        tmp_path,
        '[region.mine]\nsearch_city = ["houston", "dallas"]\n'
        + FACEBOOK
        + 'search_region = "mine"\n[item.bike]\nsearch_phrases = "bike"\n',
    )
    assert config.marketplace["facebook"].search_city == ["houston", "dallas"]
