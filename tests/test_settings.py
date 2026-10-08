"""Test notifications (CLI, web UI and aimm configure) and clearing the cache from the web UI."""

from __future__ import annotations

import asyncio
import smtplib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Coroutine, Dict, Iterator, List, Tuple, TypeVar

import pytest
import requests  # type: ignore
from diskcache import Cache  # type: ignore
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from ai_marketplace_monitor import cli, user, utils
from ai_marketplace_monitor.commands import admin
from ai_marketplace_monitor.configure.notify import NotificationToolkit, UserToolkit
from ai_marketplace_monitor.configure.tools import ToolExecutor
from ai_marketplace_monitor.email_notify import EmailNotificationConfig
from ai_marketplace_monitor.notification import (
    SAMPLE_IMAGE,
    TEST_LISTING_URL,
    NotificationConfig,
    NotificationStatus,
    sample_listing,
)
from ai_marketplace_monitor.ntfy import NtfyNotificationConfig
from ai_marketplace_monitor.pushbullet import PushbulletNotificationConfig
from ai_marketplace_monitor.unitysvc_notify import UnitySVCNotificationConfig
from ai_marketplace_monitor.user import UserConfig
from ai_marketplace_monitor.utils import CacheType
from ai_marketplace_monitor.webui import server as webui_server
from ai_marketplace_monitor.webui.auth import AuthConfig, hash_password
from ai_marketplace_monitor.webui.config_api import ConfigFileService
from ai_marketplace_monitor.webui.log_handler import LogBroadcastHandler
from ai_marketplace_monitor.webui.server import AuthState, WebUIConfig, create_app
from tests.configure_util import make_ws, ui_of

runner = CliRunner()
T = TypeVar("T")

CONFIG = """
[marketplace.facebook]
username = "u"
password = "p"
search_city = "houston"

[item.bike]
search_phrases = "bike"

[notification.pb]
pushbullet_token = "token"

[notification.mail]
smtp_server = "smtp.example.com"
smtp_password = "secret"

[user.me]
email = "me@example.com"

[user.off]
enabled = false
notify_with = ["pb"]
"""


class FakeSMTP:
    """An SMTP server that does not support STARTTLS."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "FakeSMTP":  # noqa: D105
        return self

    def __exit__(self, *args: Any) -> None:  # noqa: D105
        pass

    def ehlo(self) -> None:
        pass

    def starttls(self, **kwargs: Any) -> None:
        raise smtplib.SMTPNotSupportedError("STARTTLS extension not supported by server.")


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    """Pushbullet sends; email fails (no STARTTLS); every attempt is recorded."""
    calls: List[str] = []

    def push(self: Any, title: str, message: str, logger: Any = None) -> bool:
        calls.append(f"pushbullet: {title}\n{message}")
        return True

    class SMTP(FakeSMTP):
        def starttls(self, **kwargs: Any) -> None:
            calls.append("email")
            super().starttls(**kwargs)

    monkeypatch.setattr(PushbulletNotificationConfig, "send_message", push)
    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    return calls


@pytest.fixture
def temp_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Cache]:
    """A cache of its own for every place that writes notified listings and counters."""
    cache = Cache(str(tmp_path / "cache"))
    monkeypatch.setattr(user, "cache", cache)
    monkeypatch.setattr(utils, "cache", cache)
    monkeypatch.setattr(webui_server, "cache", cache)
    yield cache
    cache.close()


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(admin, "amm_home", tmp_path)  # no default config
    path = tmp_path / "config.toml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


# --- sending a test -----------------------------------------------------------------------
def test_test_all_reports_each_channel_once(
    sent: List[str], temp_cache: Cache, config_path: Path
) -> None:
    from ai_marketplace_monitor.config import Config

    config = Config([config_path])
    results = {r.channel: r for r in NotificationConfig.test_all(config.user["me"])}
    assert results["pushbullet"].ok and results["pushbullet"].error is None
    assert not results["email"].ok
    assert results["email"].error == "STARTTLS extension not supported by server."
    # one attempt each (the default would retry 5 times, 60 seconds apart)
    assert sorted(c.split(":")[0] for c in sent) == ["email", "pushbullet"]
    # nothing recorded: no notified listing, no counter
    assert list(temp_cache.iterkeys()) == []


def test_the_sample_listing_is_marked_as_a_test(sent: List[str], config_path: Path) -> None:
    from ai_marketplace_monitor.config import Config

    NotificationConfig.test_all(Config([config_path]).user["me"], channels=["pushbullet"])
    [message] = sent
    assert "aimm test notification" in message
    assert "https://github.com/BoPeng/ai-marketplace-monitor" in message
    assert "facebook.com" not in message


def test_a_channel_that_does_not_answer_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    release = threading.Event()

    def hang(self: Any, *args: Any, **kwargs: Any) -> bool:
        release.wait(5)
        return True

    monkeypatch.setattr(NtfyNotificationConfig, "send_message", hang)
    config = NtfyNotificationConfig(name="me", ntfy_server="https://ntfy.example", ntfy_topic="t")
    try:
        [result] = NotificationConfig.test_all(config, timeout=0.1)
    finally:
        release.set()
    assert not result.ok and result.error == "No answer in 0.1 seconds."


def test_a_channel_error_is_one_short_line(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(self: Any, *args: Any, **kwargs: Any) -> bool:
        raise RuntimeError("first line " + "x" * 400 + "\nTraceback (most recent call last):")

    monkeypatch.setattr(NtfyNotificationConfig, "notify", fail)
    config = NtfyNotificationConfig(name="me", ntfy_server="https://ntfy.example", ntfy_topic="t")
    [result] = NotificationConfig.test_all(config)
    assert not result.ok and result.error is not None
    assert result.error.startswith("Failed to send: first line")
    assert "\n" not in result.error and len(result.error) <= 300


def test_web_does_not_return_config_errors(
    tmp_path: Path, config_path: Path, sent: List[str]
) -> None:
    config_path.write_text("[user.me]\nremind = 'whenever'\n", encoding="utf-8")
    client = make_client(config_path)
    data = client.get("/api/notifications/users").json()
    assert data == {
        "ok": False,
        "error": "The configuration cannot be loaded; see the log for the error.",
        "users": [],
    }
    out = client.post("/api/notifications/test", json={"user": "me"})
    assert out.status_code == 409 and "whenever" not in out.text


def test_email_without_recipient_is_not_a_channel() -> None:
    config = EmailNotificationConfig(name="me", smtp_password="x")
    assert NotificationConfig.channels(config) == []


# --- aimm admin --test-notification -----------------------------------------------------------
def test_cli_prints_a_line_per_channel_and_fails(
    sent: List[str], temp_cache: Cache, config_path: Path
) -> None:
    result = runner.invoke(cli.app, ["admin", "-r", str(config_path), "--test-notification"])
    assert result.exit_code == 1, result.output
    assert "✓ me: pushbullet" in result.output
    assert "✗ me: email: STARTTLS extension not supported by server." in result.output
    assert "off" not in result.output  # a disabled user is not tested
    assert list(temp_cache.iterkeys()) == []


def test_cli_tests_one_user_and_succeeds(
    sent: List[str], temp_cache: Cache, config_path: Path
) -> None:
    result = runner.invoke(
        cli.app, ["admin", "-r", str(config_path), "--test-notification", "off"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip().splitlines()[-1] == "✓ off: pushbullet"


def test_cli_reports_an_unknown_user(config_path: Path) -> None:
    result = runner.invoke(
        cli.app, ["admin", "-r", str(config_path), "--test-notification", "nobody"]
    )
    assert result.exit_code == 1


def test_cli_user_needs_test_notification(config_path: Path) -> None:
    result = runner.invoke(cli.app, ["admin", "-r", str(config_path), "--expand", "me"])
    assert result.exit_code == 1


# --- web UI -------------------------------------------------------------------------------
def make_client(config_path: Path, exposed: bool = False) -> TestClient:
    handler = LogBroadcastHandler()
    state = AuthState()
    state.exposed = exposed
    if exposed:
        state.auth = AuthConfig("admin", hash_password("pw"), "secret")
    app = create_app(
        WebUIConfig(config_files=[config_path], log_handler=handler),
        state,
        ConfigFileService([config_path]),
        handler,
    )
    return TestClient(app)


def test_web_lists_users_and_tests_one(
    sent: List[str], temp_cache: Cache, config_path: Path
) -> None:
    client = make_client(config_path)
    users = {u["name"]: u for u in client.get("/api/notifications/users").json()["users"]}
    assert sorted(users["me"]["channels"]) == ["email", "pushbullet"]
    assert users["off"] == {"name": "off", "enabled": False, "channels": ["pushbullet"]}
    data = client.post("/api/notifications/test", json={"user": "me"}).json()
    assert data["ok"] is False
    results = {r["channel"]: r for r in data["results"]}
    assert results["pushbullet"] == {"channel": "pushbullet", "ok": True, "error": None}
    assert "STARTTLS" in results["email"]["error"]
    assert client.post("/api/notifications/test", json={"user": "nobody"}).status_code == 404
    assert client.post("/api/notifications/test", json={}).status_code == 400
    assert list(temp_cache.iterkeys()) == []


def test_web_settings_need_a_session_and_csrf(
    sent: List[str], temp_cache: Cache, config_path: Path
) -> None:
    client = make_client(config_path, exposed=True)
    assert client.get("/api/notifications/users").status_code == 401
    assert client.post("/api/notifications/test", json={"user": "me"}).status_code == 401
    assert client.get("/api/cache").status_code == 401
    assert client.post("/api/cache/clear", json={"type": "all"}).status_code == 401
    csrf = client.post("/api/login", data={"username": "admin", "password": "pw"}).json()["csrf"]
    assert client.post("/api/notifications/test", json={"user": "off"}).status_code == 403
    assert client.post("/api/cache/clear", json={"type": "all"}).status_code == 403
    headers = {"X-CSRF-Token": csrf}
    out = client.post("/api/notifications/test", json={"user": "off"}, headers=headers)
    assert out.json()["ok"] is True
    assert client.post("/api/cache/clear", json={"type": "all"}, headers=headers).json()["ok"]


def test_web_counts_and_clears_the_cache(temp_cache: Cache, config_path: Path) -> None:
    temp_cache.set((CacheType.AI_INQUIRY.value, "a"), 1, tag=CacheType.AI_INQUIRY.value)
    temp_cache.set((CacheType.AI_INQUIRY.value, "b"), 1, tag=CacheType.AI_INQUIRY.value)
    temp_cache.set((CacheType.COUNTERS.value, "c"), 1, tag=CacheType.COUNTERS.value)
    client = make_client(config_path)
    status: Dict[str, Any] = client.get("/api/cache").json()
    assert status["broken"] is False
    assert status["counts"][CacheType.AI_INQUIRY.value] == 2
    assert status["counts"][CacheType.COUNTERS.value] == 1
    out = client.post("/api/cache/clear", json={"type": CacheType.AI_INQUIRY.value}).json()
    assert out == {"ok": True, "message": "Cache cleared.", "restart": None}
    counts = client.get("/api/cache").json()["counts"]
    assert counts[CacheType.AI_INQUIRY.value] == 0 and counts[CacheType.COUNTERS.value] == 1
    assert client.post("/api/cache/clear", json={"type": "nope"}).status_code == 400
    assert client.post("/api/cache/clear", json={"type": "all"}).json()["restart"] is None
    assert list(temp_cache.iterkeys()) == []


@pytest.fixture
def corrupted(tmp_path: Path) -> Path:
    directory = tmp_path / "broken"
    directory.mkdir()
    (directory / "cache.db").write_bytes(b"this is not a database" * 200)
    return directory


@pytest.mark.parametrize("docker", [False, True])
def test_web_clears_a_corrupted_cache(
    docker: bool, corrupted: Path, config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(webui_server, "cache", utils.open_cache(corrupted))
    restarts: List[bool] = []
    monkeypatch.setattr(webui_server, "restart_later", lambda logger: restarts.append(True))
    if docker:
        monkeypatch.setenv("AIMM_DOCKER", "1")
    else:
        monkeypatch.delenv("AIMM_DOCKER", raising=False)
    client = make_client(config_path)
    status = client.get("/api/cache").json()
    assert status["broken"] is True
    assert status["error"] == "The cache database cannot be read; see the log for the error."
    # only all of it can be cleared
    out = client.post("/api/cache/clear", json={"type": CacheType.AI_INQUIRY.value})
    assert out.status_code == 400 and "clear all" in out.json()["detail"]
    out = client.post("/api/cache/clear", json={"type": "all"}).json()
    assert out["ok"] and not (corrupted / "cache.db").exists()
    assert out["message"].startswith("The cache could not be read, so its files were removed.")
    assert out["restart"] == ("restarting" if docker else "needed")
    assert restarts == ([True] if docker else [])


# --- aimm configure -------------------------------------------------------------------------
KITS: Dict[str, Any] = {"notification": NotificationToolkit(), "user": UserToolkit()}
AI_ONLY = '[ai.unitysvc]\napi_key = "svcpass_testkey"\n'


def in_new_loop(coro: Coroutine[Any, Any, T]) -> T:
    """Run a configure session in a thread with an event loop of its own.

    pytest-playwright's session-wide Playwright (started by test_facebook.py) leaves the main
    thread's event loop running on Python 3.10 and 3.11, so pytest-asyncio cannot run async
    tests after it. aimm configure itself runs in its own loop, as here.
    """
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


async def saved_pushbullet(tmp_path: Path) -> ToolExecutor:
    """A session that has just saved a Pushbullet notification for [user.me]."""
    ws = await make_ws(tmp_path, AI_ONLY, ["yes"], toolkits=KITS)
    ex = ToolExecutor(ws)
    ex.guides_read.update(["notification", "user"])
    for section_type, name, values in (
        ("notification", "pb", {"pushbullet_token": "${PB_TOKEN}"}),
        ("user", "me", {"notify_with": ["pb"]}),
    ):
        out = await ex.call(
            "section_update", {"section_type": section_type, "name": name, "values": values}
        )
        assert out["ok"], out
    saved = await ex.call("save", {"message": "Saving Pushbullet."})
    assert saved["saved"], saved
    assert saved["test_notification"]["sections"] == [
        {"section_type": "notification", "name": "pb"},
        {"section_type": "user", "name": "me"},
    ]
    assert "real message" in saved["test_notification"]["note"]
    return ex


def test_configure_offers_and_runs_a_test(
    tmp_path: Path, sent: List[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PB_TOKEN", "token")

    async def session() -> Tuple[ToolExecutor, Dict[str, Any]]:
        ex = await saved_pushbullet(tmp_path)
        assert "test_notification" in [fn.__name__ for fn in ex.tools_for_model()]
        test = {"section_type": "notification", "name": "pb"}
        return ex, await ex.call("test_notification", test)

    ex, out = in_new_loop(session())
    assert out["sent"] is True
    assert out["results"] == [{"user": "me", "channel": "pushbullet", "ok": True, "error": None}]
    assert "✓ pushbullet to [user.me]" in ui_of(ex.ws).said()
    assert len(sent) == 1


def test_configure_tests_only_the_saved_channel(
    tmp_path: Path, sent: List[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """[user.me] also has an email channel; testing [notification.pb] sends no email."""
    monkeypatch.setenv("PB_TOKEN", "token")

    async def session() -> Dict[str, Any]:
        ws = await make_ws(
            tmp_path,
            AI_ONLY
            + '[notification.mail]\nsmtp_password = "secret"\n'
            + '[user.me]\nemail = "me@example.com"\nnotify_with = ["mail"]\n',
            ["yes"],
            toolkits=KITS,
        )
        ex = ToolExecutor(ws)
        ex.guides_read.update(["notification", "user"])
        await ex.call(
            "section_update",
            {
                "section_type": "notification",
                "name": "pb",
                "values": {"pushbullet_token": "${PB_TOKEN}"},
            },
        )
        await ex.call(
            "section_update",
            {"section_type": "user", "name": "me", "values": {"notify_with": ["mail", "pb"]}},
        )
        await ex.call("save", {"message": "Saving."})
        return await ex.call("test_notification", {"section_type": "notification", "name": "pb"})

    out = in_new_loop(session())
    assert [r["channel"] for r in out["results"]] == ["pushbullet"]
    assert sent == [s for s in sent if s.startswith("pushbullet")]


def test_configure_does_not_test_with_unset_variables(
    tmp_path: Path, sent: List[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PB_TOKEN", raising=False)

    async def session() -> Dict[str, Any]:
        ex = await saved_pushbullet(tmp_path)
        return await ex.call("test_notification", {"section_type": "notification", "name": "pb"})

    out = in_new_loop(session())
    assert out["sent"] is False and out["can_run_here"] is False
    assert "PB_TOKEN" in out["reason"]
    assert sent == []


def test_configure_tests_only_offered_sections(tmp_path: Path, sent: List[str]) -> None:
    async def session() -> Dict[str, Any]:
        ex = ToolExecutor(await make_ws(tmp_path, AI_ONLY, toolkits=KITS))
        return await ex.call("test_notification", {"section_type": "notification", "name": "pb"})

    out = in_new_loop(session())
    assert out["ok"] is False and "No test is offered" in out["errors"][0]
    assert sent == []


# --- the test looks like a real notification --------------------------------------------------
@pytest.mark.parametrize("message_format", ["plain_text", "markdown", "html"])
def test_a_push_test_is_a_real_notification(
    message_format: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages: List[Tuple[str, str]] = []

    def capture(self: Any, title: str, message: str, logger: Any = None) -> bool:
        messages.append((title, message))
        return True

    monkeypatch.setattr(UnitySVCNotificationConfig, "send_message", capture)
    # a user, as the monitor notifies it
    config = UserConfig(name="me", unitysvc_api_key="svcpass_test", message_format=message_format)
    [result] = NotificationConfig.test_all(config)
    assert result.ok
    # what aimm sends for the same listing when a search finds it (User.notify)
    listing, rating = sample_listing()
    assert NotificationConfig.notify_all(
        config, [listing], [rating], [NotificationStatus.NOT_NOTIFIED]
    )
    test, real = messages
    assert test == real
    title, body = test
    assert title == "Found 1 new test notification from aimm"
    for part in ("aimm test notification", "$100", "Houston, TX", "not a real listing"):
        assert part in body
    assert "Great deal (5)" in body and rating.comment in body
    assert TEST_LISTING_URL in body


def test_an_email_test_is_the_real_email_with_its_photo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages: List[Any] = []

    class SMTP(FakeSMTP):
        def starttls(self, **kwargs: Any) -> None:
            pass

        def login(self, *args: Any) -> None:
            pass

        def send_message(self, msg: Any) -> None:
            sent_messages.append(msg)

    def no_download(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("the sample photo is bundled, not downloaded")

    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    monkeypatch.setattr(requests, "get", no_download)
    config = UserConfig(name="me", email=["me@example.com"], smtp_password="x")
    [result] = NotificationConfig.test_all(config)
    assert result.ok, result.error
    listing, rating = sample_listing()
    assert NotificationConfig.notify_all(
        config, [listing], [rating], [NotificationStatus.NOT_NOTIFIED]
    )
    test, real = sent_messages
    assert test["Subject"] == real["Subject"] == "Found 1 new test notification listing from aimm"
    [image] = [p for p in test.walk() if p.get_content_maintype() == "image"]
    assert image["Content-ID"] == f"<image_{hash(listing.image)}>"
    assert image.get_payload(decode=True)[:2] == b"\xff\xd8"  # a JPEG
    html = next(p for p in test.walk() if p.get_content_type() == "text/html")
    text = html.get_payload(decode=True).decode()
    assert f"cid:image_{hash(listing.image)}" in text
    for part in ("aimm test notification", "Houston, TX", "not a real listing", "★"):
        assert part in text
    real_html = next(p for p in real.walk() if p.get_content_type() == "text/html")
    assert real_html.get_payload(decode=True).decode() == text


def test_only_bundled_files_are_read_as_photos(tmp_path: Path) -> None:
    assert SAMPLE_IMAGE.is_file() and SAMPLE_IMAGE.stat().st_size < 20_000
    data = utils.fetch_image(SAMPLE_IMAGE.as_uri())
    assert data is not None and data[1] == "image/jpeg"
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(b"not for email")
    assert utils.fetch_image(secret.as_uri()) is None
