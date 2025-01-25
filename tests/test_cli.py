"""Tests for `ai_marketplace_monitor`.cli module."""

from typing import Callable, List

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
search_city = 'houston'
"""

full_marketplace_cfg = """
[marketplace.facebook]
search_city = 'houston'
username = "username"
password = "password"
login_wait_time = 50
search_interval = 10
max_search_interval = 40
acceptable_locations = "city"
exclude_sellers = "seller"
min_price = 200
max_price = 300
notify = 'user1'
"""

base_item_cfg = """
[item.name]
keywords = 'search word one'
"""

full_item_cfg = """
[item.name]
keywords = 'search word one'
search_city = 'houston'
description = 'long description'
marketplace = 'facebook'
exclude_keywords = ['exclude1', 'exclude2']
exclude_sellers = ['name1', 'name2']
enabled = true
min_price = 200
max_price = 300
notify = 'user1'
exclude_by_description = ['some exclude1', 'some exclude2']
"""

base_user_cfg = """
[user.user1]
pushbullet_token = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
"""

full_user_cfg = """
[user.user1]
pushbullet_token = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'

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


@pytest.mark.parametrize(
    "config_content,acceptable",
    [
        (base_marketplace_cfg, False),
        (base_item_cfg, False),
        (base_user_cfg, False),
        (base_marketplace_cfg + base_item_cfg + base_user_cfg, True),
        (base_marketplace_cfg + base_item_cfg + base_user_cfg + base_ai_cfg, True),
        (full_marketplace_cfg + full_item_cfg + full_user_cfg + full_ai_cfg, True),
        (base_marketplace_cfg + full_item_cfg + base_user_cfg, True),
        # user should match
        (
            base_marketplace_cfg + full_item_cfg.replace("user1", "unknown_user") + base_user_cfg,
            False,
        ),
        # no additional keys
        (base_marketplace_cfg + "\na=1\n" + base_item_cfg + base_user_cfg, False),
        (base_marketplace_cfg + base_item_cfg + "\na=1\n" + base_user_cfg, False),
        (base_marketplace_cfg + base_item_cfg + base_user_cfg + "\na=1\n", False),
    ],
)
def test_config(config_file, config_content, acceptable) -> None:
    """Test the config command."""
    cfg = config_file(config_content)
    if acceptable:
        print(config_content)
        Config([cfg])
    else:
        with pytest.raises(Exception):
            Config([cfg])
