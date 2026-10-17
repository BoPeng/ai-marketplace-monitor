"""Each notification section a user receives is a channel of its own."""

from pathlib import Path
from typing import Any, List

import pytest
from diskcache import Cache  # type: ignore

from ai_marketplace_monitor.config import Config
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

    [notification.unitysvc_email]
    smtp_server = "smtp.svcpass.com"
    smtp_password = "svcpass_key"

    [notification.gmail]
    smtp_server = "smtp.gmail.com"
    smtp_username = "me@gmail.com"
    smtp_password = "app-password"
    """,
    )
    unitysvc, gmail = config.user["me"].channels()
    assert (unitysvc.name, unitysvc.section, gmail.name) == (
        "unitysvc_email",
        "unitysvc_email",
        "gmail",
    )
    assert isinstance(unitysvc.config, EmailNotificationConfig)
    assert isinstance(gmail.config, EmailNotificationConfig)
    # each with its own server and password, and the user's address
    assert (unitysvc.config.smtp_server, unitysvc.config.smtp_password) == (
        "smtp.svcpass.com",
        "svcpass_key",
    )
    assert (gmail.config.smtp_server, gmail.config.smtp_password) == (
        "smtp.gmail.com",
        "app-password",
    )
    assert unitysvc.config.email == gmail.config.email == ["me@example.com"]
    assert gmail.label == "gmail (email)" and unitysvc.label == "unitysvc_email"


def test_a_section_value_wins_over_the_users(tmp_path: Path) -> None:
    config = _load(
        tmp_path,
        """
    [user.me]
    telegram_chat_id = "1"
    telegram_token = "9:own"

    [notification.group]
    telegram_token = "1:bot"
    telegram_chat_id = "-100"
    """,
    )
    [channel] = config.user["me"].channels()
    assert isinstance(channel.config, TelegramNotificationConfig)
    assert (channel.config.telegram_token, channel.config.telegram_chat_id) == ("1:bot", "-100")


def test_user_settings_make_a_channel_of_a_type_no_section_sets_up(tmp_path: Path) -> None:
    config = _load(
        tmp_path,
        """
    [user.me]
    email = "me@example.com"
    pushbullet_token = "own"
    notify_with = "mail"

    [notification.mail]
    smtp_password = "pw"

    [notification.pb]
    pushbullet_token = "shared"
    """,
    )
    channels = config.user["me"].channels()
    assert [(c.name, c.section) for c in channels] == [("mail", "mail"), ("pushbullet", None)]
    assert isinstance(channels[1].config, PushbulletNotificationConfig)
    assert channels[1].config.pushbullet_token == "own"


def test_disabled_incomplete_and_repeated_sections_are_left_out(tmp_path: Path) -> None:
    config = _load(
        tmp_path,
        """
    [user.me]
    notify_with = ["a", "b", "off", "no_token"]

    [notification.a]
    pushbullet_token = "same"

    [notification.b]
    pushbullet_token = "same"

    [notification.off]
    enabled = false
    pushbullet_token = "other"

    [notification.no_token]
    telegram_chat_id = "1"
    """,
    )
    assert [c.name for c in config.user["me"].channels()] == ["a"]


def test_a_user_without_a_config_has_its_own_channels() -> None:
    user = UserConfig(name="me", pushbullet_token="t", email=["me@example.com"])
    assert [c.name for c in user.channels()] == ["pushbullet"]  # email needs its SMTP password


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
