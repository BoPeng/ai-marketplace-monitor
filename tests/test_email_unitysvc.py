from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from ai_marketplace_monitor import email_notify
from ai_marketplace_monitor.email_notify import EmailNotificationConfig
from ai_marketplace_monitor.notification import NotificationConfig

KEY = "svcpass_" + "b2" * 26


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    """Record how the email backend talks to the SMTP server."""
    sent: Dict[str, Any] = {"messages": []}
    server = MagicMock()
    server.__enter__.return_value = server
    server.login.side_effect = lambda user, password: sent.update(user=user, password=password)
    server.send_message.side_effect = lambda msg: sent["messages"].append(msg)

    def connect(host: str, port: int) -> MagicMock:
        sent.update(host=host, port=port)
        return server

    monkeypatch.setattr(email_notify.smtplib, "SMTP", connect)
    return sent


def send(config: EmailNotificationConfig) -> bool:
    return config.send_email_message("Found 1 new bike listing", "text", "<p>html</p>", [])


def test_unitysvc_preset_needs_only_server_and_key(smtp: Dict[str, Any]) -> None:
    config = EmailNotificationConfig(
        name="unitysvc_email", smtp_server="smtp.svcpass.com", smtp_password=KEY
    )

    assert config.uses_unitysvc_smtp
    assert config._has_required_fields()
    assert send(config) is True
    assert (smtp["host"], smtp["port"]) == ("smtp.svcpass.com", 587)
    assert (smtp["user"], smtp["password"]) == ("smtp-to-mailbox", KEY)
    (msg,) = smtp["messages"]
    assert "notify@svcpass.com" in msg["From"]
    assert msg["To"] == "notify@svcpass.com"


def test_unitysvc_preset_from_key_alone(smtp: Dict[str, Any]) -> None:
    config = EmailNotificationConfig(name="u", smtp_password=KEY)

    assert config.uses_unitysvc_smtp
    assert send(config) is True
    assert smtp["host"] == "smtp.svcpass.com"
    assert smtp["user"] == "smtp-to-mailbox"


def test_unitysvc_preset_keeps_explicit_settings(smtp: Dict[str, Any]) -> None:
    config = EmailNotificationConfig(
        name="u",
        smtp_server="SMTP.svcpass.com",
        smtp_password=KEY,
        smtp_username="notify",
        smtp_from="me@example.com",
        email=["me@example.com"],
    )

    assert send(config) is True
    assert smtp["user"] == "notify"
    (msg,) = smtp["messages"]
    assert "me@example.com" in msg["From"]
    assert msg["To"] == "me@example.com"


def test_other_servers_still_need_a_recipient(smtp: Dict[str, Any]) -> None:
    config = EmailNotificationConfig(name="u", smtp_server="smtp.gmail.com", smtp_password="pw")

    assert not config.uses_unitysvc_smtp
    assert not config._has_required_fields()
    assert send(config) is False
    assert smtp["messages"] == []


def test_gmail_inference_is_unchanged(smtp: Dict[str, Any]) -> None:
    config = EmailNotificationConfig(name="g", email=["me@gmail.com"], smtp_password="app-pw")

    assert not config.uses_unitysvc_smtp
    assert send(config) is True
    assert smtp["host"] == "smtp.gmail.com"
    assert smtp["user"] == "me@gmail.com"


def test_preset_section_is_detected_as_email() -> None:
    config = NotificationConfig.get_config(
        name="unitysvc_email", smtp_server="smtp.svcpass.com", smtp_password=KEY
    )
    assert isinstance(config, EmailNotificationConfig)


@pytest.mark.parametrize("missing", [{}, {"smtp_server": "smtp.svcpass.com"}])
def test_preset_without_key_is_not_used(missing: Dict[str, Any]) -> None:
    config = EmailNotificationConfig(name="u", **missing)
    assert not config._has_required_fields()


def test_key_from_environment(monkeypatch: pytest.MonkeyPatch, smtp: Dict[str, Any]) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", KEY)
    config = EmailNotificationConfig(name="u", smtp_password="${UNITYSVC_API_KEY}")
    assert config.uses_unitysvc_smtp
    assert send(config) is True
    assert smtp["password"] == KEY
