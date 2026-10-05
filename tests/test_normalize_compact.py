import pytest

from ai_marketplace_monitor.normalize import NormalizeError, normalize
from tests.normalize_util import parse, system_cfg

USERS = """
[user.alice]
pushbullet_token = "a"
"""


def _normalize(text: str) -> dict:
    return normalize(parse(USERS + text), system_cfg()).config


def test_hoists_values_shared_by_all_items() -> None:
    cfg = _normalize(
        """
    [marketplace.facebook]
    search_city = "houston"
    search_interval = "1h"

    [item.a]
    search_phrases = "a"

    [item.b]
    search_phrases = "b"
    """
    )
    assert cfg["marketplace"]["facebook"] == {
        "search_city": "houston",
        "search_interval": "1h",
    }
    assert cfg["item"]["a"] == {"search_phrases": "a"}


def test_differing_values_stay_on_items() -> None:
    cfg = _normalize(
        """
    [marketplace.facebook]
    search_city = "houston"

    [item.a]
    search_phrases = "a"
    search_interval = "1h"

    [item.b]
    search_phrases = "b"
    search_interval = "2h"
    """
    )
    assert "search_interval" not in cfg["marketplace"]["facebook"]
    assert cfg["item"]["b"]["search_interval"] == "2h"


def test_hand_written_marketplace_value_moves_down_when_an_item_differs() -> None:
    # disk always holds normalize() output, so a value shared by all but one item
    # does not stay on the marketplace with an override
    cfg = _normalize(
        """
    [marketplace.facebook]
    search_city = "houston"
    search_interval = "1h"

    [item.a]
    search_phrases = "a"

    [item.b]
    search_phrases = "b"
    search_interval = "2h"
    """
    )
    assert "search_interval" not in cfg["marketplace"]["facebook"]
    assert cfg["item"]["a"]["search_interval"] == "1h"


def test_single_item_is_not_hoisted() -> None:
    cfg = _normalize(
        '[marketplace.facebook]\nsearch_city = "houston"\n[item.a]\nsearch_phrases = "a"\n'
    )
    assert cfg["marketplace"]["facebook"] == {}
    assert cfg["item"]["a"]["search_city"] == "houston"


def test_disabled_item_blocks_hoist_when_it_differs() -> None:
    cfg = _normalize(
        """
    [marketplace.facebook]
    search_city = "houston"

    [item.a]
    search_phrases = "a"
    search_interval = "1h"

    [item.b]
    search_phrases = "b"
    search_interval = "1h"

    [item.c]
    enabled = false
    search_phrases = "c"
    search_interval = "3h"
    """
    )
    assert "search_interval" not in cfg["marketplace"]["facebook"]
    assert cfg["item"]["a"]["search_interval"] == "1h"
    assert cfg["item"]["b"]["search_interval"] == "1h"


def test_prices_never_hoisted() -> None:
    cfg = _normalize(
        """
    [marketplace.facebook]
    search_city = "houston"
    max_price = "300"

    [item.a]
    search_phrases = "a"

    [item.b]
    search_phrases = "b"
    """
    )
    assert "max_price" not in cfg["marketplace"]["facebook"]
    assert cfg["item"]["a"]["max_price"] == "300"


def test_location_keys_hoisted_only_as_a_unit() -> None:
    cfg = _normalize(
        """
    [marketplace.facebook]
    search_city = "houston"
    radius = 50

    [item.a]
    search_phrases = "a"

    [item.b]
    search_phrases = "b"
    search_city = "dallas"
    radius = 50
    """
    )
    market = cfg["marketplace"]["facebook"]
    assert "radius" not in market and "search_city" not in market


def test_identical_leftover_notification_sections_are_merged() -> None:
    cfg = normalize(
        parse(
            """
    [marketplace.facebook]
    search_city = "houston"

    [user.alice]
    notify_with = "gmail1"
    email = "alice@example.com"

    [user.bob]
    notify_with = "gmail2"
    email = "bob@example.com"

    [notification.gmail1]
    smtp_password = "pw"

    [notification.gmail2]
    smtp_password = "pw"

    [item.a]
    search_phrases = "a"
    """
        ),
        system_cfg(),
    ).config
    assert list(cfg["notification"]) == ["gmail1"]
    assert "notify_with" not in cfg["user"]["bob"]


def test_sections_with_different_request_are_not_merged() -> None:
    cfg = normalize(
        parse(
            """
    [marketplace.facebook]
    search_city = "houston"

    [user.alice]
    notify_with = "gmail1"
    email = "alice@example.com"

    [notification.gmail1]
    smtp_password = "pw"

    [notification.gmail2]
    request = "spare account"
    smtp_password = "pw"

    [item.a]
    search_phrases = "a"
    """
        ),
        system_cfg(),
    ).config
    assert set(cfg["notification"]) == {"gmail1", "gmail2"}


def test_changes_are_relative_to_the_input() -> None:
    text = (
        USERS + '[marketplace.facebook]\nsearch_city = "houston"\n[item.a]\nsearch_phrases = "a"\n'
    )
    result = normalize(parse(text), system_cfg())
    sections = {c.section for c in result.changes}
    assert "item.a" in sections  # search_city and notify moved into the item


TWO_ITEMS = """
[marketplace.facebook]
search_city = "houston"

[item.a]
search_phrases = "a"
{extra}

[item.b]
search_phrases = "b"
{extra}
"""


def test_falsy_value_of_truthy_option_is_not_hoisted() -> None:
    cfg = _normalize(TWO_ITEMS.format(extra="rating = []"))
    assert "rating" not in cfg["marketplace"]["facebook"]
    assert cfg["item"]["a"]["rating"] == []


def test_falsy_value_of_not_none_option_is_hoisted() -> None:
    cfg = _normalize(TWO_ITEMS.format(extra="seller_locations = []"))
    assert cfg["marketplace"]["facebook"]["seller_locations"] == []
    assert "seller_locations" not in cfg["item"]["a"]


def test_default_ai_list_is_hoisted_then_removed() -> None:
    cfg = normalize(
        parse(
            """
            [ai.openai]
            api_key = "k1"
            [ai.deepseek]
            api_key = "k2"
            """
            + USERS
            + TWO_ITEMS.format(extra="")
        ),
        system_cfg(),
    ).config
    assert "ai" not in cfg["marketplace"]["facebook"]
    assert "ai" not in cfg["item"]["a"] and "ai" not in cfg["item"]["b"]


def test_default_notify_and_ai_lists_are_removed() -> None:
    cfg = normalize(
        parse(
            """
    [ai.openai]
    api_key = "k1"

    [marketplace.facebook]
    search_city = "houston"
    notify = ["alice", "bob"]
    ai = ["openai"]

    [user.alice]
    pushbullet_token = "a"

    [user.bob]
    pushbullet_token = "b"

    [item.a]
    search_phrases = "a"
    notify = ["alice", "bob"]
    ai = ["openai"]
    """
        ),
        system_cfg(),
    ).config
    assert "notify" not in cfg["marketplace"]["facebook"]
    assert "ai" not in cfg["marketplace"]["facebook"]
    assert "notify" not in cfg["item"]["a"]
    assert "ai" not in cfg["item"]["a"]


def test_notify_and_ai_overrides_are_kept_when_not_defaults() -> None:
    cfg = normalize(
        parse(
            """
    [ai.openai]
    api_key = "k1"
    [ai.deepseek]
    api_key = "k2"

    [marketplace.facebook]
    search_city = "houston"

    [user.alice]
    pushbullet_token = "a"

    [user.bob]
    pushbullet_token = "b"

    [item.a]
    search_phrases = "a"
    notify = ["alice"]
    ai = ["openai"]
    """
        ),
        system_cfg(),
    ).config
    assert cfg["item"]["a"]["notify"] == ["alice"]
    assert cfg["item"]["a"]["ai"] == ["openai"]


def test_default_notify_with_is_removed() -> None:
    cfg = normalize(
        parse(
            """
    [marketplace.facebook]
    search_city = "houston"

    [user.alice]
    notify_with = ["gmail", "pushbullet"]
    email = "alice@example.com"

    [notification.gmail]
    smtp_password = "pw"

    [notification.pushbullet]
    pushbullet_token = "a"

    [item.a]
    search_phrases = "a"
    """
        ),
        system_cfg(),
    ).config
    assert "notify_with" not in cfg["user"]["alice"]


def test_notify_with_override_is_kept_when_not_all_notifications() -> None:
    cfg = normalize(
        parse(
            """
    [marketplace.facebook]
    search_city = "houston"

    [user.alice]
    notify_with = "pushbullet"

    [notification.gmail]
    smtp_password = "pw"

    [notification.pushbullet]
    pushbullet_token = "a"

    [item.a]
    search_phrases = "a"
    """
        ),
        system_cfg(),
    ).config
    assert cfg["user"]["alice"]["notify_with"] == ["pushbullet"]


def test_default_marketplace_binding_is_compacted() -> None:
    implicit = normalize(
        parse(
            USERS
            + """
    [marketplace.facebook]
    search_city = "houston"

    [marketplace.second]
    search_city = "dallas"

    [item.a]
    search_phrases = "a"
    """
        ),
        system_cfg(),
    ).config
    explicit = normalize(
        parse(
            USERS
            + """
    [marketplace.facebook]
    search_city = "houston"

    [marketplace.second]
    search_city = "dallas"

    [item.a]
    marketplace = "facebook"
    search_phrases = "a"
    """
        ),
        system_cfg(),
    ).config
    assert explicit == implicit
    assert "marketplace" not in explicit["item"]["a"]


def test_non_default_marketplace_binding_is_kept() -> None:
    cfg = normalize(
        parse(
            USERS
            + """
    [marketplace.facebook]
    search_city = "houston"

    [marketplace.second]
    search_city = "dallas"

    [item.a]
    marketplace = "second"
    search_phrases = "a"
    """
        ),
        system_cfg(),
    ).config
    assert cfg["item"]["a"]["marketplace"] == "second"


def test_explicit_section_defaults_are_removed() -> None:
    cfg = normalize(
        parse(
            """
    [ai.openai]
    api_key = "sk-test"
    enabled = true
    max_retries = 10

    [marketplace.facebook]
    enabled = true
    market_type = "facebook"
    search_city = "houston"

    [user.alice]
    enabled = true
    pushbullet_token = "a"

    [notification.unused]
    enabled = true
    pushbullet_token = "b"

    [item.a]
    enabled = true
    search_phrases = "a"
    """
        ),
        system_cfg(),
    ).config
    assert cfg["ai"]["openai"] == {"api_key": "sk-test"}
    assert "enabled" not in cfg["marketplace"]["facebook"]
    assert "market_type" not in cfg["marketplace"]["facebook"]
    assert "enabled" not in cfg["user"]["alice"]
    assert "enabled" not in cfg["notification"]["unused"]
    assert "enabled" not in cfg["item"]["a"]


def test_normalize_error_has_no_rich_markup() -> None:
    cfg = parse(
        USERS
        + """
    [marketplace.facebook]
    search_city = "houston"

    [item.a]
    search_phrases = "a"
    notify = "zz"
    """
    )
    with pytest.raises(NormalizeError) as exc:
        normalize(cfg, system_cfg())
    assert "[cyan]" not in str(exc.value)
    assert "zz" in str(exc.value)


def test_normalize_change_list_keeps_expand_notes() -> None:
    result = normalize(
        parse(
            USERS
            + """
    [marketplace.facebook]
    search_city = "houston"
    max_price = 100

    [item.a]
    search_phrases = "a"
    """
        ),
        system_cfg(),
    )
    changes = [c for c in result.changes if c.section == "item.a" and c.key == "max_price"]
    assert changes
    assert "AI prompt" in changes[0].detail
