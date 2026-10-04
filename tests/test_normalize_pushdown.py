import pytest

from ai_marketplace_monitor.normalize import NormalizeError, expand
from tests.normalize_util import parse, system_cfg

USERS = """
[user.alice]
pushbullet_token = "a"

[user.bob]
pushbullet_token = "b"
"""


def _expand(text: str) -> dict:
    return expand(parse(text), system_cfg()).config


def test_common_options_move_into_items_and_lists_become_explicit() -> None:
    cfg = _expand(USERS + """
    [ai.openai]
    api_key = "sk-test"

    [marketplace.facebook]
    search_city = "houston"
    search_interval = "1h"
    username = "me"
    login_wait_time = 60

    [item.bike]
    search_phrases = "bike"
    """)
    assert cfg["marketplace"]["facebook"] == {"login_wait_time": 60, "username": "me"}
    bike = cfg["item"]["bike"]
    assert bike["search_city"] == "houston"
    assert bike["search_interval"] == "1h"
    assert bike["notify"] == ["alice", "bob"]
    assert bike["ai"] == ["openai"]


def test_no_ai_sections_means_no_ai_key() -> None:
    cfg = _expand(
        USERS
        + '[marketplace.facebook]\nsearch_city = "houston"\n[item.bike]\nsearch_phrases = "bike"\n'
    )
    assert "ai" not in cfg["item"]["bike"]


def test_marketplace_empty_notify_means_all_users() -> None:
    cfg = _expand(
        USERS
        + '[marketplace.facebook]\nsearch_city = "houston"\nnotify = []\n'
        + '[item.bike]\nsearch_phrases = "bike"\n'
    )
    assert cfg["item"]["bike"]["notify"] == ["alice", "bob"]


def test_truthy_rule_replaces_empty_item_value() -> None:
    cfg = _expand(USERS + """
    [marketplace.facebook]
    search_city = "houston"
    notify = "alice"

    [item.bike]
    search_phrases = "bike"
    notify = []
    """)
    assert cfg["item"]["bike"]["notify"] == "alice"


def test_not_none_rule_keeps_empty_item_value() -> None:
    cfg = _expand(USERS + """
    [ai.openai]
    api_key = "sk-test"

    [marketplace.facebook]
    search_city = "houston"
    seller_locations = ["houston"]
    ai = ["openai"]

    [item.bike]
    search_phrases = "bike"
    seller_locations = []
    ai = []
    """)
    assert cfg["item"]["bike"]["seller_locations"] == []
    assert cfg["item"]["bike"]["ai"] == []


def test_marketplace_price_reaches_ai_prompt_and_is_reported() -> None:
    result = expand(parse(USERS + """
    [marketplace.facebook]
    search_city = "houston"
    max_price = "300"

    [item.bike]
    search_phrases = "bike"
    """), system_cfg())
    assert result.config["item"]["bike"]["max_price"] == "300"
    details = [
        c.detail for c in result.changes if c.key == "max_price" and c.section == "item.bike"
    ]
    assert details and "AI prompt" in details[0]


def test_bundled_region_is_referenced_not_copied() -> None:
    cfg = _expand(
        USERS
        + '[marketplace.facebook]\nsearch_region = "usa"\n[item.bike]\nsearch_phrases = "bike"\n'
    )
    assert cfg["item"]["bike"]["search_region"] == "usa"
    assert "region" not in cfg


def test_item_with_own_region_gets_no_location_keys() -> None:
    cfg = _expand(USERS + """
    [marketplace.facebook]
    search_city = "houston"
    radius = 50

    [item.bike]
    search_phrases = "bike"
    search_region = "usa"
    """)
    bike = cfg["item"]["bike"]
    assert "search_city" not in bike and "radius" not in bike


def test_own_city_inheriting_region_radius_raises() -> None:
    with pytest.raises(NormalizeError, match="bike"):
        _expand(USERS + """
        [marketplace.facebook]
        search_region = "usa"

        [item.bike]
        search_phrases = "bike"
        search_city = "dallas"
        """)


def test_item_binds_to_first_marketplace() -> None:
    cfg = _expand(USERS + """
    [marketplace.facebook]
    search_city = "houston"

    [marketplace.second]
    search_city = "dallas"

    [item.bike]
    search_phrases = "bike"
    """)
    assert cfg["item"]["bike"]["search_city"] == "houston"


def test_translation_passes_through() -> None:
    cfg = _expand(USERS + """
    [marketplace.facebook]
    search_city = "houston"

    [item.bike]
    search_phrases = "bike"

    [translation.de]
    locale = "de_DE"
    Condition = "Zustand"
    """)
    assert cfg["translation"] == {"de": {"locale": "de_DE", "Condition": "Zustand"}}


def test_invalid_input_raises() -> None:
    with pytest.raises(NormalizeError, match="not valid"):
        _expand(USERS + '[marketplace.facebook]\n[item.bike]\nsearch_phrases = "bike"\n')


def test_marketplace_region_overrides_its_own_city() -> None:
    result = expand(parse(USERS + """
    [marketplace.facebook]
    search_region = "usa"
    search_city = "houston"
    radius = 5

    [item.bike]
    search_phrases = "bike"
    """), system_cfg())
    bike = result.config["item"]["bike"]
    assert bike["search_region"] == "usa"
    assert "search_city" not in bike and "radius" not in bike
    details = {c.key: c.detail for c in result.changes if c.section == "marketplace.facebook"}
    assert "overridden by search_region" in details["search_city"]

