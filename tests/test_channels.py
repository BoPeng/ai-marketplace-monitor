"""Each email and notification section a user receives is a channel of its own."""

from pathlib import Path
from typing import Any, Dict, List

import pytest
from diskcache import Cache  # type: ignore

from ai_marketplace_monitor.config import Config, load_config_dicts
from ai_marketplace_monitor.digest import digest_channels
from ai_marketplace_monitor.email_notify import EmailNotificationConfig
from ai_marketplace_monitor.notification import sample_listing
from ai_marketplace_monitor.pushbullet import PushbulletNotificationConfig
from ai_marketplace_monitor.telegram import TelegramNotificationConfig
from ai_marketplace_monitor.user import User, UserConfig

HEAD = """
[marketplace.facebook]
search_city = "houston"

[item.bike]
search_phrases = "bike"
"""


def _load(tmp_path: Path, text: str) -> Config:
    path = tmp_path / "config.toml"
    path.write_text(HEAD + text, encoding="utf-8")
    return Config([path])


def test_two_email_sections_are_two_channels(tmp_path: Path) -> None:
    config = _load(
        tmp_path,
        """
    [user.me]
    email = "me@example.com"

    [email.unitysvc]
    smtp_username = "smtp-to-mailbox"
    smtp_password = "svcpass_key"

    [email.gmail]
    smtp_username = "me@gmail.com"
    smtp_password = "app-password"
    """,
    )
    unitysvc, gmail = config.user["me"].channels()
    assert (unitysvc.name, unitysvc.section, gmail.name) == (
        "email.unitysvc",
        "email.unitysvc",
        "email.gmail",
    )
    assert isinstance(unitysvc.config, EmailNotificationConfig)
    assert isinstance(gmail.config, EmailNotificationConfig)
    # each from its preset, with its own password, and the user's address
    assert (unitysvc.config.smtp_server, unitysvc.config.smtp_username) == (  # preset, set
        "smtp.svcpass.com",
        "smtp-to-mailbox",
    )
    assert unitysvc.config.smtp_password == "svcpass_key"
    assert (gmail.config.smtp_server, gmail.config.smtp_port) == ("smtp.gmail.com", 587)
    assert gmail.config.smtp_password == "app-password"
    assert unitysvc.config.email == gmail.config.email == ["me@example.com"]


def test_the_unitysvc_preset_reads_the_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_from_env")
    config = _load(tmp_path, '[user.me]\n[email.unitysvc]\nsmtp_username = "smtp-to-mailbox"\n')
    [channel] = config.user["me"].channels()
    assert isinstance(channel.config, EmailNotificationConfig)
    assert channel.config.smtp_password == "svcpass_from_env"


def test_a_section_value_wins_over_the_users(tmp_path: Path) -> None:
    config = _load(
        tmp_path,
        """
    [user.me]
    telegram_chat_id = "1"

    [notification.group]
    telegram_token = "1:bot"
    telegram_chat_id = "-100"
    """,
    )
    [channel] = config.user["me"].channels()
    assert isinstance(channel.config, TelegramNotificationConfig)
    assert (channel.config.telegram_token, channel.config.telegram_chat_id) == ("1:bot", "-100")


def test_only_values_a_section_sets_replace_the_users(tmp_path: Path) -> None:
    config = _load(
        tmp_path,
        """
    [user.me]
    email = "me@example.com"
    max_retries = 1
    retry_delay = 0

    [email.mail]
    smtp_password = "pw"

    [email.slow]
    smtp_password = "pw2"
    max_retries = 5
    """,
    )
    mail, slow = config.user["me"].channels()
    # the section's defaults (5 retries, 60 seconds apart) are not its values
    assert (mail.config.max_retries, mail.config.retry_delay) == (1, 0)
    # a value the section sets wins, even when it equals the default
    assert (slow.config.max_retries, slow.config.retry_delay) == (5, 0)


def test_identical_sections_send_once(tmp_path: Path) -> None:
    config = _load(
        tmp_path,
        """
    [user.me]
    notify_with = ["alerts", "daily"]

    [notification.alerts]
    pushbullet_token = "same"

    [notification.daily]
    pushbullet_token = "same"
    """,
    )
    [channel] = config.user["me"].channels()
    assert channel.sections == ("notification.alerts", "notification.daily")


def test_the_digest_goes_through_sections_with_digest_at(tmp_path: Path) -> None:
    config = _load(
        tmp_path,
        """
    [user.me]
    email = "me@example.com"

    [email.mail]
    smtp_password = "pw"
    digest_at = "08:00"

    [notification.pb]
    pushbullet_token = "t"
    """,
    )
    assert list(digest_channels(config.user["me"])) == ["email.mail"]


def test_disabled_and_incomplete_sections_are_left_out(tmp_path: Path) -> None:
    config = _load(
        tmp_path,
        """
    [user.me]
    notify_with = ["a", "off", "no_token"]

    [notification.a]
    pushbullet_token = "same"

    [notification.off]
    enabled = false
    pushbullet_token = "other"

    [notification.no_token]
    telegram_chat_id = "1"
    """,
    )
    assert [c.name for c in config.user["me"].channels()] == ["notification.a"]


def test_a_user_without_a_config_has_no_channels() -> None:
    assert UserConfig(name="me", email=["me@example.com"]).channels() == []


@pytest.mark.parametrize(
    "misplaced",
    [{"pushbullet_token": "t"}, {"smtp_password": "pw"}, {"digest_at": "08:00"}],
)
def test_a_user_names_who_receives_not_how(misplaced: Dict[str, Any]) -> None:
    system, _ = load_config_dicts([])
    user = {
        "marketplace": {"facebook": {"search_city": "houston"}},
        "item": {"bike": {"search_phrases": "bike"}},
        "user": {"me": misplaced},
    }
    with pytest.raises(ValueError, match=r"belong in email\.\* and notification\.\* sections"):
        Config.from_dicts(system, user)


def test_email_settings_are_not_a_notification() -> None:
    with pytest.raises(ValueError, match="email is sent by an email section"):
        Config.from_dicts(
            load_config_dicts([])[0],
            {
                "marketplace": {"facebook": {"search_city": "houston"}},
                "item": {"bike": {"search_phrases": "bike"}},
                "user": {"me": {}},
                "notification": {"mail": {"smtp_password": "pw"}},
            },
        )


def test_a_listing_is_sent_through_every_channel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokens: List[str] = []

    def send(self: PushbulletNotificationConfig, *args: Any, **kwargs: Any) -> bool:
        tokens.append(str(self.pushbullet_token))
        return True

    monkeypatch.setattr(PushbulletNotificationConfig, "send_message", send)
    config = _load(
        tmp_path,
        """
    [user.me]
    notify_with = ["pb1", "pb2"]

    [notification.pb1]
    pushbullet_token = "first"

    [notification.pb2]
    pushbullet_token = "second"
    """,
    )
    listing, rating = sample_listing()
    item = config.item["bike"]
    with Cache(str(tmp_path / "cache")) as cache:
        User(config.user["me"]).notify([listing], [rating], item, local_cache=cache, force=True)
    assert tokens == ["first", "second"]


def test_email_unitysvc_names_its_service(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="needs smtp_username: the UnitySVC service"):
        _load(tmp_path, "[user.me]\n[email.unitysvc]\n")


@pytest.mark.parametrize("user_format", [None, "plain_text", "markdown"])
def test_shared_format_and_channel_overrides(tmp_path: Path, user_format: str | None) -> None:
    setting = f'message_format = "{user_format}"' if user_format else ""
    config = _load(
        tmp_path,
        f"""
    [user.me]
    {setting}
    pushover_user_key = "user"

    [notification.unitysvc]
    unitysvc_api_key = "svcpass_test"

    [notification.specific]
    unitysvc_api_key = "svcpass_test"
    unitysvc_service = "labs/msg-to-ntfy"

    [notification.plain]
    unitysvc_api_key = "svcpass_test"
    message_format = "plain_text"

    [notification.markdown]
    unitysvc_api_key = "svcpass_test"
    message_format = "markdown"

    [notification.telegram]
    telegram_token = "1:bot"
    telegram_chat_id = "1"

    [notification.pushbullet]
    pushbullet_token = "token"

    [notification.pushover]
    pushover_api_token = "token"
    """,
    )
    expected = user_format or "markdown"
    assert config.user["me"].message_format == expected
    formats = {
        section: channel.config.message_format
        for channel in config.user["me"].channels()
        for section in channel.sections
    }
    assert formats == {
        "notification.unitysvc": expected,
        "notification.specific": expected,
        "notification.plain": "plain_text",
        "notification.markdown": "markdown",
        "notification.telegram": expected,
        "notification.pushbullet": "plain_text",
        "notification.pushover": "html",
    }
