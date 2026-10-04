import copy

import pytest

from ai_marketplace_monitor.config import Config
from ai_marketplace_monitor.normalize import NormalizeError, check_equivalent, effective_view
from tests.normalize_util import parse, system_cfg

BASE = """
[ai.openai]
api_key = "sk-test"

[marketplace.facebook]
search_city = "houston"
max_price = "300"

[user.alice]
email = "alice@example.com"
smtp_password = "s3cret"

[user.bob]
pushbullet_token = "abc"

[item.bike]
search_phrases = "bike"
"""


def test_effective_view_resolves_defaults() -> None:
    view = effective_view(Config.from_dicts(system_cfg(), parse(BASE)))
    bike = view["item"]["bike"]
    assert bike["marketplace"] == "facebook"
    assert bike["search_city"] == ["houston"]
    assert set(bike["notify"]) == {"alice", "bob"}
    assert bike["ai"] == ["openai"]
    assert bike["max_price"] == "300"
    assert bike["ai_prompt:max_price"] is None
    assert "name" not in bike["notify"]["alice"]
    assert bike["notify"]["alice"]["email"] == ["alice@example.com"]


def test_identical_configs_are_equivalent() -> None:
    assert check_equivalent(system_cfg(), parse(BASE), parse(BASE)) == []


def test_behavior_change_raises_with_path() -> None:
    after = parse(BASE)
    after["item"]["bike"]["notify"] = ["alice"]
    with pytest.raises(NormalizeError, match=r"item\.bike\.notify"):
        check_equivalent(system_cfg(), parse(BASE), after)


def test_secret_values_are_masked_in_errors() -> None:
    after = parse(BASE)
    after["user"]["alice"]["smtp_password"] = "other-secret"
    with pytest.raises(NormalizeError) as info:
        check_equivalent(system_cfg(), parse(BASE), after)
    assert "s3cret" not in str(info.value)
    assert "other-secret" not in str(info.value)
    assert "<REDACTED>" in str(info.value)


def test_ai_prompt_price_difference_is_allowed_when_it_matches_search() -> None:
    after = parse(BASE)
    after["item"]["bike"]["max_price"] = "300"
    allowed = check_equivalent(system_cfg(), parse(BASE), after)
    assert allowed == ["item.bike.ai_prompt:max_price"]


def test_ai_prompt_price_difference_not_matching_search_raises() -> None:
    after = parse(BASE)
    after["item"]["bike"]["max_price"] = "250"
    with pytest.raises(NormalizeError):
        check_equivalent(system_cfg(), parse(BASE), after)


def test_invalid_after_config_raises() -> None:
    after = copy.deepcopy(parse(BASE))
    after["item"]["bike"]["search_city"] = "Not Valid"
    with pytest.raises(NormalizeError, match="does not load"):
        check_equivalent(system_cfg(), parse(BASE), after)
