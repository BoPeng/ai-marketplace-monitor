"""Tests for `ai_marketplace_monitor`.cli module."""

from dataclasses import asdict
from typing import Callable, List, Tuple, Type, Union

import pytest
from pytest import TempPathFactory
from typer.testing import CliRunner

import ai_marketplace_monitor
from ai_marketplace_monitor import cli
from ai_marketplace_monitor.config import Config

runner = CliRunner()


@pytest.mark.parametrize(
    "options,expected",
    [
        # ([], "ai_marketplace_monitor.cli.main"),
        (["--help"], "Usage: "),
        (
            ["--version"],
            f"AI Marketplace Monitor, version { ai_marketplace_monitor.__version__ }\n",
        ),
    ],
)
def test_command_line_interface(options: List[str], expected: str) -> None:
    """Test the CLI."""
    result = runner.invoke(cli.app, options)
    assert result.exit_code == 0
    assert expected in result.stdout


@pytest.fixture(scope="session")
def config_file(tmp_path_factory: TempPathFactory) -> Callable:
    def generate_config_file(content: str) -> str:
        fn = tmp_path_factory.mktemp("config") / "test.toml"
        with open(fn, "w") as f:
            f.write(content)
        return str(fn)

    return generate_config_file


base_marketplace_cfg = """
[marketplace.facebook]
search_city = 'dallas'
"""

full_marketplace_cfg = """
[marketplace.facebook]
login_wait_time = 50
password = "password"
search_city = ['houston']
username = "username"
# the following are common options
seller_locations = "city"
condition = ['new', 'used_good']
date_listed = 7
delivery_method = 'local_pick_up'
exclude_sellers = "seller"
ai = []
max_price = 300
min_price = 200
rating = 4
max_search_interval = 40
notify = 'user1'
radius = 100
search_interval = 10
search_region = 'usa'
"""

base_item_cfg = """
[item.name]
search_phrases = 'search word one'
"""

full_item_cfg = """
[item.name]
antikeywords = ['exclude1', 'exclude2']
description = 'long description'
enabled = true
keywords = ['exclude1', 'exclude2']
search_phrases = 'search word one'
marketplace = 'facebook'
search_city = 'houston'
# the following are common options
seller_locations = "city"
condition = ['new', 'used_good']
date_listed = 7
ai = 'openai'
availability = ['out', 'all']
delivery_method = 'local_pick_up'
exclude_sellers = "seller"
max_price = 300
rating = 4
max_search_interval = '1d'
search_interval = '12h'
min_price = 200
notify = 'user1'
radius = 100
search_region = 'usa'
"""

base_user_cfg = """
[user.user1]
pushbullet_token = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
"""

full_user_cfg = """
[user.user1]
pushbullet_token = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
remind = '1 day'

[user.user2]
pushbullet_token = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
"""


base_ai_cfg = """
[ai.openai]
api_key = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
"""

full_ai_cfg = """
[ai.openai]
api_key = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
model = 'gpt'
"""

base_pushbullet_cfg = """
[notification.pushbullet1]
pushbullet_token = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
"""

base_pushover_cfg = """
[notification.pushover]
pushover_user_id = "xxxxxx"
pushover_api_token = "dfafdafd"
"""


base_ntfy_cfg = """
[notification.ntfy]
ntfy_server = "https://xxxxxx"
ntfy_topic = "dfafdafd"
"""

base_email_cfg = """
[notification.gmail]
smtp_password = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
"""

notify_user_cfg = """
[user.user1]
notify_with = ['pushbullet1', 'gmail']
"""

notify_user_pushover_cfg = """
[user.user1]
notify_with = 'pushover'
"""

notify_user_ntfy_cfg = """
[user.user1]
notify_with = 'ntfy'
"""

monitor_cfg = """
[monitor]
proxy_server = 'https://fdaf.fadfd.com'
proxy_username = 'adfa'
proxy_password = 'fadfadf'
"""

monitor_invalid_proxy_server_cfg = """
[monitor]
subscription_id = 'dfafadfs'
proxy_server = 'fdaf.fadfd.com'
proxy_username = 'adfa'
proxy_password = 'fadfadf'
"""

licensed_monitor_cfg = """
[monitor]
subscription_id = 'dfafadfs'
proxy_server = 'https://fdaf.fadfd.com'
proxy_username = 'adfa'
proxy_password = 'fadfadf'
"""


@pytest.mark.parametrize(
    "config_content,acceptable",
    [
        (base_marketplace_cfg, False),
        (base_item_cfg, False),
        (base_user_cfg, False),
        (base_marketplace_cfg + base_item_cfg + base_user_cfg, True),
        (base_marketplace_cfg + base_item_cfg + base_user_cfg + base_ai_cfg, True),
        (full_marketplace_cfg + full_item_cfg + full_user_cfg + full_ai_cfg, True),
        (base_marketplace_cfg + full_item_cfg + base_user_cfg + base_ai_cfg, True),
        # notification should match
        (
            base_marketplace_cfg + full_item_cfg + notify_user_cfg,
            False,
        ),
        # pushbullet
        (
            base_marketplace_cfg
            + base_item_cfg
            + notify_user_cfg
            + base_pushbullet_cfg
            + base_email_cfg,
            True,
        ),
        (
            base_marketplace_cfg
            + base_item_cfg
            + notify_user_cfg
            + base_pushbullet_cfg.replace("pushbullet1", "somethingelse")
            + base_email_cfg,
            False,
        ),
        # pushover
        (
            base_marketplace_cfg + base_item_cfg + notify_user_pushover_cfg + base_pushover_cfg,
            True,
        ),
        (
            base_marketplace_cfg
            + base_item_cfg
            + notify_user_pushover_cfg
            + base_pushover_cfg.replace("pushover", "somethingelse"),
            False,
        ),
        # ntfy
        (
            base_marketplace_cfg + base_item_cfg + notify_user_ntfy_cfg + base_ntfy_cfg,
            True,
        ),
        (
            base_marketplace_cfg
            + base_item_cfg
            + notify_user_ntfy_cfg
            + base_ntfy_cfg.replace("ntfy", "somethingelse"),
            False,
        ),
        # user should match
        (
            base_marketplace_cfg + full_item_cfg.replace("user1", "unknown_user") + base_user_cfg,
            False,
        ),
        # no additional keys
        (base_marketplace_cfg + "\na=1\n" + base_item_cfg + base_user_cfg, False),
        (base_marketplace_cfg + base_item_cfg + "\na=1\n" + base_user_cfg, False),
        (base_marketplace_cfg + base_item_cfg + base_user_cfg + "\na=1\n", False),
        (base_marketplace_cfg + base_item_cfg + base_user_cfg + monitor_cfg, False),
        (base_marketplace_cfg + base_item_cfg + base_user_cfg + licensed_monitor_cfg, True),
        (
            base_marketplace_cfg
            + base_item_cfg
            + base_user_cfg
            + monitor_invalid_proxy_server_cfg,
            False,
        ),
    ],
)
def test_config(config_file: Callable, config_content: str, acceptable: bool) -> None:
    """Test the config command."""
    cfg = config_file(config_content)
    key_types: dict[str, Union[Type, Tuple[Type, ...]]] = {
        "seller_locations": (list, type(None)),
        "ai": (list, type(None)),
        "availability": (list, type(None)),
        "api_key": str,
        "city_name": (list, type(None)),
        "condition": (list, type(None)),
        "date_listed": (list, type(None)),
        "delivery_method": (list, type(None)),
        "description": (str, type(None)),
        "enabled": (bool, type(None)),
        "antikeywords": (list, type(None)),
        "exclude_sellers": (list, type(None)),
        "keywords": (list, type(None)),
        "language": (str, type(None)),
        "login_wait_time": (int, type(None)),
        "marketplace": (str, type(None)),
        "max_price": (int, type(None)),
        "max_search_interval": (int, type(None)),
        "market_type": (str, type(None)),
        "min_price": (int, type(None)),
        "model": (str, type(None)),
        "name": (str, type(None)),
        "notify": (list, type(None)),
        "password": (str, type(None)),
        "prompt": (str, type(None)),
        "extra_prompt": (str, type(None)),
        "rating_prompt": (str, type(None)),
        "pushbullet_token": str,
        "radius": (list, type(None)),
        "rating": (list, type(None)),
        "remind": (int, type(None)),
        "search_city": (list, type(None)),
        "search_interval": (int, type(None)),
        "search_phrases": list,
        "search_region": (list, type(None)),
        "searched_count": int,
        "start_at": (list, type(None)),
        "username": (str, type(None)),
    }
    if acceptable:
        # print(config_content)
        config = Config([cfg])
        # assert the types
        for key, value in asdict(config.marketplace["facebook"]).items():
            assert isinstance(value, key_types[key]), f"{key} must be of type {key_types[key]}"

        for item_cfg in config.item.values():
            for key, value in asdict(item_cfg).items():
                assert isinstance(value, key_types[key]), f"{key} must be of type {key_types[key]}"
        # test if all elements can be frozen
        for attr in ("item", "ai", "user", "marketplae"):
            for item_cfg in getattr(config, attr, {}).values():
                assert item_cfg.hash
    else:
        with pytest.raises(Exception):
            Config([cfg])


alt_marketplace_cfg = """
[marketplace.houston]
search_city = 'houston'
"""

alt_item_cfg = """
[item.whatever]
marketplace = "houston"
search_phrases = "search word two"
"""


def test_support_multiple_marketplaces(config_file: Callable) -> None:
    """Test the config command."""
    cfg = config_file(
        base_marketplace_cfg + alt_marketplace_cfg + alt_item_cfg + base_item_cfg + base_user_cfg
    )
    config = Config([cfg])

    assert len(config.marketplace) == 2
    assert len(config.item) == 2
    assert len(config.user) == 1

    assert config.item["name"].marketplace == "facebook"
    assert config.item["whatever"].marketplace == "houston"
    assert config.marketplace["facebook"].search_city == ["dallas"]
    assert config.marketplace["houston"].search_city == ["houston"]


alt_ai_cfg = """
[ai.some_ai]
provider = 'OpenAI'
api_key = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
model = 'gpt_none'
base_url = 'http://someother.com'
"""


def test_multiplace_ai_agent(config_file: Callable) -> None:
    """Test the config command."""
    cfg = config_file(
        base_marketplace_cfg + base_ai_cfg + base_item_cfg + alt_ai_cfg + base_user_cfg
    )
    config = Config([cfg])

    assert len(config.marketplace) == 1
    assert len(config.ai) == 2

    assert config.ai["openai"].api_key == "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
    assert config.ai["some_ai"].model == "gpt_none"
