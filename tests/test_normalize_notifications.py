import copy
from typing import Any, Dict

import pytest

from ai_marketplace_monitor.config import Config
from ai_marketplace_monitor.normalize import check_equivalent, normalize
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


def test_shared_smtp_with_per_user_email_keeps_section() -> None:
    cfg = _run(
        """
    [user.alice]
    email = "alice@example.com"
    notify_with = "gmail"

    [user.bob]
    email = "bob@example.com"
    notify_with = "gmail"

    [email.gmail]
    smtp_username = "me@gmail.com"
    smtp_password = "pw"
    """
    )
    assert cfg["email"] == {"gmail": {"smtp_username": "me@gmail.com", "smtp_password": "pw"}}
    assert cfg["user"]["alice"]["notify_with"] == ["email.gmail"]
    assert cfg["user"]["bob"] == {"email": "bob@example.com", "notify_with": ["email.gmail"]}


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
    assert cfg["user"]["alice"] == {"telegram_chat_id": "-100", "notify_with": ["notification.tg"]}


def test_a_recipient_stays_where_moving_it_would_change_a_channel() -> None:
    # alice also receives tg2, which has no chat id: hers would apply there
    cfg = _run(
        """
    [user.alice]
    telegram_chat_id = "5"
    notify_with = ["tg1", "tg2"]

    [notification.tg1]
    telegram_token = "1:t"
    telegram_chat_id = "-100"

    [notification.tg2]
    telegram_token = "2:t"
    """
    )
    assert cfg["notification"]["tg1"]["telegram_chat_id"] == "-100"
    assert cfg["user"]["alice"]["telegram_chat_id"] == "5"


def test_notify_with_unset_means_all_sections() -> None:
    cfg = _run(
        """
    [user.alice]
    email = "alice@example.com"

    [email.gmail]
    smtp_password = "pw"

    [notification.tg]
    telegram_token = "123:abc"
    telegram_chat_id = "1"
    """
    )
    assert cfg["user"]["alice"]["notify_with"] == ["email.gmail", "notification.tg"]


def test_notify_with_empty_list_means_none() -> None:
    cfg = _run(
        """
    [user.alice]
    email = "alice@example.com"
    notify_with = []

    [email.gmail]
    smtp_password = "pw"
    """
    )
    assert cfg["user"]["alice"] == {"email": "alice@example.com", "notify_with": []}
    assert cfg["email"]["gmail"] == {"smtp_password": "pw"}


def test_bare_names_become_qualified() -> None:
    cfg = _run(
        """
    [user.alice]
    email = "alice@example.com"
    notify_with = ["gmail", "notification.unitysvc"]

    [email.gmail]
    smtp_password = "pw"

    [notification.unitysvc]
    unitysvc_api_key = "svcpass_k"
    """
    )
    assert cfg["user"]["alice"]["notify_with"] == ["email.gmail", "notification.unitysvc"]


def test_a_bare_name_of_both_kinds_does_not_load() -> None:
    with pytest.raises(ValueError, match="both email.unitysvc and notification.unitysvc"):
        Config.from_dicts(
            system_cfg(),
            parse(
                HEAD
                + """
    [user.alice]
    notify_with = "unitysvc"

    [email.unitysvc]
    smtp_username = "smtp-to-mailbox"

    [notification.unitysvc]
    unitysvc_api_key = "svcpass_k"
    """
            ),
        )


def test_user_delivery_setting_used_by_a_channel_stays() -> None:
    cfg = _run(
        """
    [user.alice]
    email = "alice@example.com"
    max_retries = 3
    notify_with = "gmail"

    [email.gmail]
    smtp_password = "pw"
    """
    )
    # the section does not set it: alice's value applies to her channel
    assert cfg["user"]["alice"]["max_retries"] == 3
    assert "max_retries" not in cfg["email"]["gmail"]


def test_user_delivery_setting_no_channel_uses_is_dropped() -> None:
    cfg = _run(
        """
    [user.alice]
    email = "alice@example.com"
    max_retries = 3
    notify_with = "gmail"

    [email.gmail]
    smtp_password = "pw"
    max_retries = 2
    """
    )
    assert "max_retries" not in cfg["user"]["alice"]
    assert cfg["email"]["gmail"]["max_retries"] == 2


def test_sections_of_one_type_each_send() -> None:
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
    assert cfg["user"]["alice"]["notify_with"] == ["notification.tg1", "notification.tg2"]


def test_disabled_and_unused_sections_are_kept() -> None:
    cfg = _run(
        """
    [user.alice]
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


def test_user_request_stays_and_section_request_is_kept() -> None:
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


def test_duplicate_notify_with_entries_collapse() -> None:
    cfg = _run(
        """
    [user.alice]
    telegram_chat_id = "1"
    notify_with = ["tg", "notification.tg"]

    [notification.tg]
    telegram_token = "1:t"
    """
    )
    assert cfg["user"]["alice"] == {"telegram_chat_id": "1", "notify_with": ["notification.tg"]}


def test_notify_with_naming_disabled_section_drops_it() -> None:
    cfg = _run(
        """
    [user.alice]
    email = "alice@example.com"
    notify_with = ["gmail", "tg"]

    [email.gmail]
    smtp_password = "pw"

    [notification.tg]
    enabled = false
    telegram_token = "1:t"
    telegram_chat_id = "1"
    """
    )
    assert cfg["user"]["alice"] == {"email": "alice@example.com", "notify_with": ["email.gmail"]}


def test_disabled_user_is_normalized_and_stays_disabled() -> None:
    cfg = _run(
        """
    [user.alice]
    enabled = false
    email = "alice@example.com"

    [email.gmail]
    smtp_password = "pw"
    """
    )
    assert cfg["user"]["alice"] == {
        "enabled": False,
        "email": "alice@example.com",
        "notify_with": ["email.gmail"],
    }


def test_merged_sections_are_renamed_in_notify_with() -> None:
    from ai_marketplace_monitor.normalize.compact import compact

    cfg, _ = compact(
        {
            "notification": {
                "a": {"ntfy_server": "s"},
                "b": {"ntfy_server": "s"},
                "c": {"ntfy_server": "other"},
            },
            "user": {"me": {"notify_with": ["notification.a", "notification.b"]}},
        }
    )
    assert cfg["user"]["me"]["notify_with"] == ["notification.a"]


def test_an_old_layout_is_migrated_when_normalized() -> None:
    result = normalize(
        parse(
            HEAD
            + """
    [user.alice]
    email = "alice@example.com"
    digest_at = "08:00"

    [notification.gmail]
    smtp_server = "smtp.gmail.com"
    smtp_username = "me@gmail.com"
    smtp_password = "${GMAIL_SMTP_PASSWORD}"
    """
        ),
        system_cfg(),
    )
    assert result.config["email"] == {
        "gmail": {"smtp_username": "me@gmail.com", "digest_at": "08:00"}
    }
    assert "notification" not in result.config
    assert result.config["user"]["alice"] == {"email": "alice@example.com"}
