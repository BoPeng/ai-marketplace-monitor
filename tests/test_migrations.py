"""The one-time migrations of a user's config files to [email.*] sections and section digests."""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
import tomlkit

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ai_marketplace_monitor.config import Config
from ai_marketplace_monitor.migrations import (
    migrate_channels_from_user_to_sections,
    migrate_config_files,
    migrate_digest_from_user_to_notification_and_email,
    migrate_documents,
    migrate_email_from_notification_to_email_section,
)

HEAD = """
[marketplace.facebook]
search_city = "houston"

[item.bike]
search_phrases = "bike"
"""


def _migrate(text: str) -> Dict[str, Any]:
    doc = tomlkit.parse(text)
    assert migrate_documents([doc])
    assert migrate_documents([doc]) == []  # an updated file is not changed again
    return tomllib.loads(tomlkit.dumps(doc))


def test_unitysvc_email_becomes_email_unitysvc() -> None:
    cfg = _migrate(
        """
    [notification.unitysvc_email]
    smtp_server = "smtp.svcpass.com"
    smtp_username = "smtp-to-mailbox"
    smtp_password = "${UNITYSVC_API_KEY}"
    with_description = true

    [notification.unitysvc]
    unitysvc_api_key = "${UNITYSVC_API_KEY}"

    [user.me]
    notify_with = ["unitysvc_email", "unitysvc"]
    """
    )
    # the preset has the server and the password reference; the service stays
    assert cfg["email"] == {"unitysvc": {"smtp_username": "smtp-to-mailbox"}}
    assert cfg["notification"] == {"unitysvc": {"unitysvc_api_key": "${UNITYSVC_API_KEY}"}}
    assert cfg["user"]["me"]["notify_with"] == ["email.unitysvc", "unitysvc"]


def test_gmail_and_other_servers() -> None:
    cfg = _migrate(
        """
    [notification.mail]
    smtp_server = "smtp.gmail.com"
    smtp_username = "me@gmail.com"
    smtp_password = "${GMAIL_APP_PASSWORD}"

    [notification.work]
    smtp_server = "smtp.office365.com"
    smtp_password = "${WORK_PASSWORD}"
    max_retries = 2

    [user.me]
    email = "me@example.com"
    """
    )
    assert cfg["email"]["gmail"] == {
        "smtp_username": "me@gmail.com",
        "smtp_password": "${GMAIL_APP_PASSWORD}",
    }
    assert cfg["email"]["work"] == {
        "smtp_server": "smtp.office365.com",
        "smtp_password": "${WORK_PASSWORD}",
        "max_retries": 2,
    }
    assert "notification" not in cfg
    assert cfg["user"]["me"] == {"email": "me@example.com"}  # still receives all of them


def test_a_section_of_email_and_another_channel_is_split() -> None:
    cfg = _migrate(
        """
    [notification.both]
    smtp_password = "pw"
    pushbullet_token = "t"
    max_retries = 2

    [user.me]
    email = "me@example.com"
    notify_with = "both"
    """
    )
    assert cfg["email"]["both"] == {"smtp_password": "pw", "max_retries": 2}
    assert cfg["notification"]["both"] == {"pushbullet_token": "t", "max_retries": 2}
    assert cfg["user"]["me"]["notify_with"] == ["email.both", "notification.both"]


def test_channels_set_up_in_a_user_move_into_sections() -> None:
    cfg = _migrate(
        """
    [user.me]
    # my phone
    pushbullet_token = "t"
    email = "me@example.com"
    smtp_server = "smtp.gmail.com"
    smtp_username = "me@gmail.com"
    smtp_password = "pw"

    [user.bob]
    telegram_chat_id = "1"

    [notification.tg]
    telegram_token = "1:t"
    """
    )
    assert cfg["email"] == {"gmail": {"smtp_username": "me@gmail.com", "smtp_password": "pw"}}
    assert cfg["notification"]["pushbullet"] == {"pushbullet_token": "t"}
    assert cfg["user"]["me"] == {
        "email": "me@example.com",
        "notify_with": ["notification.tg", "email.gmail", "notification.pushbullet"],
    }
    # bob received every section; he still receives what he did, not the new ones
    assert cfg["user"]["bob"] == {"telegram_chat_id": "1", "notify_with": ["notification.tg"]}


def test_user_values_under_a_shared_section_go_into_a_copy() -> None:
    cfg = _migrate(
        """
    [user.me]
    email = "me@example.com"
    smtp_from = "me@example.com"
    notify_with = "mail"

    [user.bob]
    email = "bob@example.com"
    notify_with = "mail"

    [notification.mail]
    smtp_server = "smtp.example.com"
    smtp_password = "pw"
    """
    )
    assert cfg["email"]["mail"] == {"smtp_server": "smtp.example.com", "smtp_password": "pw"}
    assert cfg["email"]["mail_me"] == {
        "smtp_server": "smtp.example.com",
        "smtp_password": "pw",
        "smtp_from": "me@example.com",
    }
    assert cfg["user"]["me"]["notify_with"] == ["email.mail_me"]
    assert cfg["user"]["bob"]["notify_with"] == ["email.mail"]


def test_the_digest_moves_onto_the_sections() -> None:
    cfg = _migrate(
        """
    [email.unitysvc]
    smtp_username = "smtp-to-mailbox"

    [notification.unitysvc]
    unitysvc_api_key = "k"

    [user.me]
    notify_with = ["email.unitysvc", "notification.unitysvc"]
    digest_at = "08:00"
    digest_with = "email.unitysvc"
    """
    )
    assert cfg["email"]["unitysvc"] == {"smtp_username": "smtp-to-mailbox", "digest_at": "08:00"}
    assert cfg["notification"]["unitysvc"] == {"unitysvc_api_key": "k"}
    assert cfg["user"]["me"] == {"notify_with": ["email.unitysvc", "notification.unitysvc"]}


def test_users_who_differ_in_their_digest_get_a_copy() -> None:
    cfg = _migrate(
        """
    [email.gmail]
    smtp_username = "me@gmail.com"

    [user.me]
    email = "me@example.com"
    notify_with = "gmail"
    digest_at = "08:00"

    [user.bob]
    email = "bob@example.com"
    notify_with = "gmail"
    """
    )
    assert cfg["email"]["gmail"] == {"smtp_username": "me@gmail.com", "digest_at": "08:00"}
    assert cfg["email"]["gmail_bob"] == {"smtp_username": "me@gmail.com"}
    assert cfg["user"]["bob"]["notify_with"] == ["email.gmail_bob"]


def test_each_migration_is_a_function_of_its_own() -> None:
    doc = tomlkit.parse(
        '[user.me]\ndigest_at = "08:00"\n[notification.p]\npushbullet_token = "t"\n'
    )
    assert migrate_email_from_notification_to_email_section([doc]) == []
    assert migrate_channels_from_user_to_sections([doc]) == []
    changes = migrate_digest_from_user_to_notification_and_email([doc])
    assert "[notification.p] sends the digest at 08:00" in changes


OLD = (
    HEAD
    + """
[notification.unitysvc_email]
# full email with photos
smtp_server = "smtp.svcpass.com"
smtp_username = "smtp-to-mailbox"
smtp_password = "${UNITYSVC_API_KEY}"

[user.me]
notify_with = ["unitysvc_email"]
# daily digest
digest_at = "08:00"
"""
)


def test_a_config_file_is_updated_once_with_a_copy_of_the_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_k")
    path = tmp_path / "config.toml"
    path.write_text(OLD, encoding="utf-8")
    config = Config([path])
    [channel] = config.user["me"].channels()
    assert channel.name == "email.unitysvc" and channel.config.digest_at == "08:00"
    assert (tmp_path / "config.toml.bak").read_text(encoding="utf-8") == OLD
    text = path.read_text(encoding="utf-8")
    assert "# daily digest" not in text  # the comment of the key that moved
    assert "[email.unitysvc]" in text and "[notification" not in text
    assert '[marketplace.facebook]\nsearch_city = "houston"' in text
    Config([path])
    assert path.read_text(encoding="utf-8") == text  # not changed again


def test_a_file_is_read_migrated_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(OLD, encoding="utf-8")
    [text] = migrate_config_files([path], write=False).values()
    assert "[email.unitysvc]" in text
    assert path.read_text(encoding="utf-8") == OLD and not (tmp_path / "config.toml.bak").exists()


def test_files_read_together_are_migrated_together(tmp_path: Path) -> None:
    users = tmp_path / "users.toml"
    users.write_text(
        '[user.me]\nemail = "me@example.com"\nnotify_with = ["mail"]\n', encoding="utf-8"
    )
    sections = tmp_path / "sections.toml"
    sections.write_text(
        HEAD + '[notification.mail]\nsmtp_server = "smtp.gmail.com"\nsmtp_password = "pw"\n',
        encoding="utf-8",
    )
    config = Config([users, sections])
    assert [c.name for c in config.user["me"].channels()] == ["email.gmail"]
    assert "email.gmail" in users.read_text(encoding="utf-8")
    assert "[email.gmail]" in sections.read_text(encoding="utf-8")


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="root can write")
def test_a_file_that_cannot_be_written_is_read_migrated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_k")
    path = tmp_path / "config.toml"
    path.write_text(OLD, encoding="utf-8")
    path.chmod(0o444)
    tmp_path.chmod(0o555)
    try:
        logged: List[str] = []

        class Log:
            def info(self, message: str) -> None:
                logged.append(message)

            def warning(self, message: str) -> None:
                logged.append(message)

            def debug(self, message: str) -> None:
                pass

        config = Config([path], Log())  # type: ignore[arg-type]
        assert config.user["me"].channels()[0].name == "email.unitysvc"
        assert any("cannot be updated" in m for m in logged)
        assert path.read_text(encoding="utf-8") == OLD
    finally:
        tmp_path.chmod(0o755)
        path.chmod(0o644)
