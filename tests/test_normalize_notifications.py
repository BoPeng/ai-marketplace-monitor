import copy
from typing import Any, Dict

import pytest

from ai_marketplace_monitor.config import Config
from ai_marketplace_monitor.normalize import check_equivalent
from ai_marketplace_monitor.normalize.notifications import normalize_notifications
from tests.normalize_util import parse, system_cfg

HEAD = """
[marketplace.facebook]
search_city = "houston"

[item.bike]
search_phrases = "bike"
"""


def _run(text: str) -> Dict[str, Any]:
    raw = parse(HEAD + text)
    cfg = copy.deepcopy(raw)
    normalize_notifications(cfg, Config.from_dicts(system_cfg(), raw))
    check_equivalent(system_cfg(), raw, cfg)
    return cfg


def test_inline_single_user_is_split() -> None:
    cfg = _run(
        """
    [user.alice]
    email = "alice@example.com"
    smtp_server = "smtp.example.com"
    smtp_password = "pw"
    """
    )
    assert cfg["user"]["alice"] == {"email": "alice@example.com", "notify_with": ["email"]}
    assert cfg["notification"]["email"] == {
        "smtp_server": "smtp.example.com",
        "smtp_password": "pw",
    }


def test_shared_smtp_with_per_user_email_keeps_section() -> None:
    cfg = _run(
        """
    [user.alice]
    email = "alice@example.com"
    notify_with = "gmail"

    [user.bob]
    email = "bob@example.com"
    notify_with = "gmail"

    [notification.gmail]
    smtp_username = "me@gmail.com"
    smtp_password = "pw"
    """
    )
    assert cfg["notification"] == {
        "gmail": {"smtp_username": "me@gmail.com", "smtp_password": "pw"}
    }
    assert cfg["user"]["alice"]["notify_with"] == ["gmail"]
    assert cfg["user"]["bob"] == {"email": "bob@example.com", "notify_with": ["gmail"]}


def test_group_chat_id_moves_to_users() -> None:
    cfg = _run(
        """
    [user.alice]
    notify_with = "tg"

    [user.bob]
    notify_with = "tg"

    [notification.tg]
    telegram_token = "123:abc"
    telegram_chat_id = "-100"
    """
    )
    assert cfg["notification"]["tg"] == {"telegram_token": "123:abc"}
    assert cfg["user"]["alice"] == {"telegram_chat_id": "-100", "notify_with": ["tg"]}


def test_notify_with_unset_means_all_sections() -> None:
    cfg = _run(
        """
    [user.alice]
    email = "alice@example.com"

    [notification.gmail]
    smtp_password = "pw"

    [notification.tg]
    telegram_token = "123:abc"
    telegram_chat_id = "1"
    """
    )
    assert cfg["user"]["alice"]["notify_with"] == ["gmail", "tg"]


def test_notify_with_empty_list_means_none() -> None:
    cfg = _run(
        """
    [user.alice]
    email = "alice@example.com"
    notify_with = []

    [notification.gmail]
    smtp_password = "pw"
    """
    )
    assert cfg["user"]["alice"] == {"email": "alice@example.com", "notify_with": []}
    assert cfg["notification"]["gmail"] == {"smtp_password": "pw"}


def test_inline_value_shadowed_by_section_default_is_dropped() -> None:
    cfg = _run(
        """
    [user.alice]
    email = "alice@example.com"
    max_retries = 3
    notify_with = "gmail"

    [notification.gmail]
    smtp_password = "pw"
    """
    )
    assert "max_retries" not in cfg["user"]["alice"]
    assert "max_retries" not in cfg["notification"]["gmail"]


def test_inline_common_value_without_sections_moves_into_channel_section() -> None:
    cfg = _run(
        """
    [user.alice]
    pushbullet_token = "abc"
    max_retries = 3
    """
    )
    assert cfg["notification"]["pushbullet"] == {"max_retries": 3, "pushbullet_token": "abc"}
    assert cfg["user"]["alice"] == {"notify_with": ["pushbullet"]}


def test_same_type_later_section_wins() -> None:
    cfg = _run(
        """
    [user.alice]
    telegram_chat_id = "1"
    notify_with = ["tg1", "tg2"]

    [notification.tg1]
    telegram_token = "1:a"

    [notification.tg2]
    telegram_token = "2:b"
    """
    )
    assert cfg["user"]["alice"]["notify_with"] == ["tg2"]
    assert cfg["notification"]["tg1"] == {"telegram_token": "1:a"}  # leftover kept
    assert cfg["notification"]["tg2"] == {"telegram_token": "2:b"}


def test_disabled_and_unused_sections_are_kept() -> None:
    cfg = _run(
        """
    [user.alice]
    pushbullet_token = "abc"
    notify_with = []

    [notification.old]
    enabled = false
    pushover_user_key = "k"
    pushover_api_token = "t"
    """
    )
    assert cfg["notification"]["old"] == {
        "enabled": False,
        "pushover_user_key": "k",
        "pushover_api_token": "t",
    }


@pytest.mark.filterwarnings("ignore:Environment variable AIMM_TEST_UNSET_TOKEN is not set")
def test_unset_placeholder_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIMM_TEST_UNSET_TOKEN", raising=False)
    cfg = _run(
        """
    [user.alice]
    notify_with = "tg"

    [notification.tg]
    telegram_token = "${AIMM_TEST_UNSET_TOKEN}"
    telegram_chat_id = "1"
    """
    )
    assert cfg["notification"]["tg"] == {"telegram_token": "${AIMM_TEST_UNSET_TOKEN}"}
    assert cfg["user"]["alice"]["telegram_chat_id"] == "1"


def test_user_request_stays_and_section_request_is_kept_on_claim() -> None:
    cfg = _run(
        """
    [user.alice]
    request = "alice wants telegram"
    notify_with = "tg"

    [notification.tg]
    request = "our bot"
    telegram_token = "123:abc"
    telegram_chat_id = "1"
    """
    )
    assert cfg["user"]["alice"]["request"] == "alice wants telegram"
    assert cfg["notification"]["tg"] == {"request": "our bot", "telegram_token": "123:abc"}


def test_type_name_taken_by_leftover_falls_back_to_user_suffix() -> None:
    cfg = _run(
        """
    [user.alice]
    pushbullet_token = "abc"
    notify_with = []

    [notification.pushbullet]
    enabled = false
    pushbullet_token = "zzz"
    """
    )
    # alice's inline token has notify_with = [] so it is never sent; still preserved
    assert cfg["notification"]["pushbullet_alice"] == {"pushbullet_token": "abc"}
    assert cfg["user"]["alice"]["notify_with"] == ["pushbullet_alice"]


def test_inline_value_replaced_by_load_hook_is_dropped() -> None:
    # UserConfig inherits Pushbullet's handle_message_format, which always sets
    # "plain_text", so alice's inline "markdown" never takes effect. Moving it into an
    # ntfy section (which keeps message_format) would change behavior.
    cfg = _run(
        """
    [user.alice]
    ntfy_topic = "x"
    ntfy_server = "https://ntfy.example.com"
    message_format = "markdown"
    """
    )
    assert cfg["notification"]["ntfy"] == {"ntfy_server": "https://ntfy.example.com"}
    assert cfg["user"]["alice"] == {"ntfy_topic": "x", "notify_with": ["ntfy"]}


def test_hook_forcing_section_merges_first() -> None:
    # tg loads as UserConfig, whose hook forces message_format = "plain_text"; nt (ntfy)
    # holds "markdown". tg cannot hold the effective value, so it is listed first.
    cfg = _run(
        """
    [user.alice]
    ntfy_topic = "x"
    telegram_chat_id = "1"
    notify_with = ["tg", "nt"]

    [notification.nt]
    ntfy_server = "https://n.example.com"
    message_format = "markdown"

    [notification.tg]
    telegram_token = "1:t"
    """
    )
    assert cfg["user"]["alice"]["notify_with"] == ["tg", "nt"]
    assert cfg["notification"]["nt"]["message_format"] == "markdown"
    assert cfg["notification"]["tg"] == {"telegram_token": "1:t"}
    # Deterministic: normalizing the output again yields identical output.
    again = copy.deepcopy(cfg)
    normalize_notifications(again, Config.from_dicts(system_cfg(), cfg))
    assert again == cfg


def test_duplicate_notify_with_entries_collapse() -> None:
    cfg = _run(
        """
    [user.alice]
    telegram_chat_id = "1"
    notify_with = ["tg", "tg"]

    [notification.tg]
    telegram_token = "1:t"
    """
    )
    assert cfg["user"]["alice"] == {"telegram_chat_id": "1", "notify_with": ["tg"]}


def test_notify_with_naming_disabled_section_drops_it() -> None:
    cfg = _run(
        """
    [user.alice]
    email = "alice@example.com"
    notify_with = ["gmail", "tg"]

    [notification.gmail]
    smtp_password = "pw"

    [notification.tg]
    enabled = false
    telegram_token = "1:t"
    telegram_chat_id = "1"
    """
    )
    assert cfg["user"]["alice"] == {"email": "alice@example.com", "notify_with": ["gmail"]}
    assert cfg["notification"]["tg"] == {
        "enabled": False,
        "telegram_token": "1:t",
        "telegram_chat_id": "1",
    }


def test_inline_channel_field_overridden_by_same_type_section() -> None:
    cfg = _run(
        """
    [user.alice]
    telegram_chat_id = "1"
    telegram_token = "9:inline"
    notify_with = "tg"

    [notification.tg]
    telegram_token = "1:t"
    """
    )
    assert cfg["user"]["alice"] == {"telegram_chat_id": "1", "notify_with": ["tg"]}
    assert cfg["notification"]["tg"] == {"telegram_token": "1:t"}


def test_group_chat_id_overrides_users_own_values() -> None:
    cfg = _run(
        """
    [user.alice]
    telegram_chat_id = "5"
    notify_with = "tg"

    [user.bob]
    telegram_chat_id = "6"
    notify_with = "tg"

    [notification.tg]
    telegram_token = "1:t"
    telegram_chat_id = "-100"
    """
    )
    assert cfg["user"]["alice"]["telegram_chat_id"] == "-100"
    assert cfg["user"]["bob"]["telegram_chat_id"] == "-100"
    assert cfg["notification"] == {"tg": {"telegram_token": "1:t"}}


def test_disabled_user_is_normalized_and_stays_disabled() -> None:
    cfg = _run(
        """
    [user.alice]
    enabled = false
    email = "alice@example.com"
    smtp_password = "pw"
    """
    )
    assert cfg["user"]["alice"] == {
        "enabled": False,
        "email": "alice@example.com",
        "notify_with": ["email"],
    }
    assert cfg["notification"]["email"] == {"smtp_password": "pw"}


def test_user_digest_options_are_kept() -> None:
    cfg = _run(
        """
    [user.alice]
    email = "alice@example.com"
    smtp_password = "pw"
    digest = "08:00"
    digest_channels = ["email"]
    """
    )
    assert cfg["user"]["alice"]["digest"] == "08:00"
    assert cfg["user"]["alice"]["digest_channels"] == ["email"]
