import copy
from typing import Any, Dict, List

import pytest

from ai_marketplace_monitor.config import load_config_dicts
from ai_marketplace_monitor.normalize import expand, normalize
from tests.normalize_util import EXAMPLES, dumps, parse, system_cfg

CASES: List[str] = [
    """
    [marketplace.facebook]
    search_city = "houston"
    search_interval = "30m"
    [user.alice]
    email = "alice@example.com"
    smtp_password = "pw"
    [item.bike]
    search_phrases = "bike"
    """,
    """
    [ai.openai]
    api_key = "sk-test"
    [marketplace.facebook]
    search_region = "usa"
    rating = [4, 3]
    notify = "alice"
    [user.alice]
    notify_with = "tg"
    [user.bob]
    email = "bob@example.com"
    [notification.tg]
    telegram_token = "123:abc"
    telegram_chat_id = "-100"
    [notification.gmail]
    smtp_password = "pw"
    [item.bike]
    search_phrases = "bike"
    [item.camera]
    search_phrases = ["gopro", "go pro"]
    notify = "bob"
    min_price = "100"
    """,
]


def _inputs() -> List[Dict[str, Any]]:
    return [parse(c) for c in CASES] + [load_config_dicts([p])[1] for p in EXAMPLES]


@pytest.mark.parametrize("user_cfg", _inputs())
def test_expand_is_idempotent_and_pure(user_cfg: Dict[str, Any]) -> None:
    before = copy.deepcopy(user_cfg)
    first = expand(user_cfg, system_cfg())
    assert user_cfg == before
    second = expand(first.config, system_cfg())
    assert second.changes == []
    assert dumps(second.config) == dumps(first.config)


def _shuffled(cfg: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for section_type in reversed(list(cfg)):
        body = cfg[section_type]
        if section_type == "monitor":
            out[section_type] = dict(reversed(list(body.items())))
        else:
            # keep section order within a type (it is behavior), reverse keys inside
            out[section_type] = {n: dict(reversed(list(s.items()))) for n, s in body.items()}
    return out


@pytest.mark.parametrize("user_cfg", _inputs())
def test_key_order_does_not_matter(user_cfg: Dict[str, Any]) -> None:
    a = expand(user_cfg, system_cfg()).config
    b = expand(_shuffled(user_cfg), system_cfg()).config
    assert dumps(a) == dumps(b)


def test_item_order_is_preserved() -> None:
    cfg = expand(parse(CASES[0] + '[item.alpha]\nsearch_phrases = "a"\n'), system_cfg()).config
    assert list(cfg["item"]) == ["bike", "alpha"]


def test_example_config_expands() -> None:
    result = expand(load_config_dicts([EXAMPLES[1]])[1], system_cfg())
    assert result.config["user"]["user1"]["notify_with"] == ["gmail", "pushbullet", "pushover"]


@pytest.mark.parametrize("user_cfg", _inputs())
def test_normalize_is_idempotent_pure_and_canonical(user_cfg: Dict[str, Any]) -> None:
    before = copy.deepcopy(user_cfg)
    first = normalize(user_cfg, system_cfg())
    assert user_cfg == before
    assert normalize(first.config, system_cfg()).changes == []
    # an untouched expanded form normalizes back to exactly what is on disk
    expanded = expand(user_cfg, system_cfg()).config
    assert dumps(normalize(expanded, system_cfg()).config) == dumps(first.config)


@pytest.mark.parametrize("user_cfg", _inputs())
def test_normalize_ignores_key_order(user_cfg: Dict[str, Any]) -> None:
    a = normalize(user_cfg, system_cfg()).config
    b = normalize(_shuffled(user_cfg), system_cfg()).config
    assert dumps(a) == dumps(b)
