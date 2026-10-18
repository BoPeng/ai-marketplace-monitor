from logging import getLogger
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from ai_marketplace_monitor import unitysvc_notify
from ai_marketplace_monitor.ai import AIResponse
from ai_marketplace_monitor.config import Config
from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.notification import NotificationConfig, NotificationStatus
from ai_marketplace_monitor.unitysvc_notify import UnitySVCNotificationConfig, listing_extras
from ai_marketplace_monitor.user import UserConfig

KEY = "svcpass_" + "a1" * 26


class FakeResponse:
    def __init__(self: "FakeResponse", status_code: int = 202, body: Any = None) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._body = body
        self.text = "" if body is None else str(body)

    def json(self: "FakeResponse") -> Any:
        if self._body is None:
            raise ValueError("no body")
        return self._body


@pytest.fixture
def posts(monkeypatch: pytest.MonkeyPatch) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []

    def fake_post(url: str, **kwargs: Any) -> FakeResponse:
        calls.append({"url": url, **kwargs})
        return FakeResponse()

    monkeypatch.setattr(unitysvc_notify.requests, "post", fake_post)
    monkeypatch.delenv("UNITYSVC_API_BASE_URL", raising=False)
    return calls


def test_default_notify_service_request(posts: List[Dict[str, Any]]) -> None:
    config = UnitySVCNotificationConfig(name="unitysvc", unitysvc_api_key=KEY)

    assert config.send_message("New listing", "A bike for $50") is True

    (call,) = posts
    assert call["url"] == "https://api.svcpass.com/notify"
    assert call["headers"] == {"Authorization": f"Bearer {KEY}"}
    assert call["json"]["title"] == "New listing"
    assert call["json"]["body"].startswith("A bike for $50\n\nSent by ")
    assert call["json"]["type"] == "info"
    assert call["json"]["format"] == "markdown"
    assert call["timeout"] == 10


def test_specific_service_base_url_and_format(posts: List[Dict[str, Any]]) -> None:
    config = UnitySVCNotificationConfig(
        name="discord",
        unitysvc_api_key=f"  {KEY} ",
        unitysvc_service="/labs/msg-to-discord/",
        unitysvc_base_url="https://api.staging.svcpass.com/",
        message_format="markdown",
    )

    config.send_message("t", "**m**")

    assert posts[0]["url"] == "https://api.staging.svcpass.com/labs/msg-to-discord"
    assert posts[0]["headers"]["Authorization"] == f"Bearer {KEY}"
    assert posts[0]["json"]["format"] == "markdown"


def test_base_url_from_environment(
    posts: List[Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNITYSVC_API_BASE_URL", "https://api.staging.svcpass.com")
    UnitySVCNotificationConfig(name="u", unitysvc_api_key=KEY).send_message("t", "m")
    assert posts[0]["url"] == "https://api.staging.svcpass.com/notify"


def test_long_title_is_truncated(posts: List[Dict[str, Any]]) -> None:
    UnitySVCNotificationConfig(name="u", unitysvc_api_key=KEY).send_message("x" * 300, "m")
    assert len(posts[0]["json"]["title"]) == 255


@pytest.mark.parametrize(
    "response, detail",
    [
        (FakeResponse(401, {"error": "Invalid API key format"}), "Invalid API key format"),
        (FakeResponse(422, {"detail": "title too long"}), "title too long"),
        (FakeResponse(502), "502"),
    ],
)
def test_error_response_raises_without_the_key(
    monkeypatch: pytest.MonkeyPatch, response: FakeResponse, detail: str
) -> None:
    monkeypatch.setattr(unitysvc_notify.requests, "post", lambda url, **kwargs: response)
    config = UnitySVCNotificationConfig(name="u", unitysvc_api_key=KEY)

    with pytest.raises(RuntimeError) as e:
        config.send_message("t", "m")

    assert detail in str(e.value)
    assert KEY not in str(e.value)


def test_error_response_redacts_echoed_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    response = FakeResponse(401, {"error": f"token {KEY} rejected"})
    monkeypatch.setattr(unitysvc_notify.requests, "post", lambda url, **kwargs: response)
    config = UnitySVCNotificationConfig(name="u", unitysvc_api_key=KEY)

    with pytest.raises(RuntimeError) as e:
        config.send_message("t", "m")

    assert KEY not in str(e.value)
    assert "svcpass_" not in str(e.value)
    assert "<redacted>" in str(e.value)


def test_text_error_response_redacts_echoed_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    response = FakeResponse(502)
    response.text = f"proxy echoed {KEY}"
    monkeypatch.setattr(unitysvc_notify.requests, "post", lambda url, **kwargs: response)
    config = UnitySVCNotificationConfig(name="u", unitysvc_api_key=KEY)

    with pytest.raises(RuntimeError) as e:
        config.send_message("t", "m")

    assert KEY not in str(e.value)
    assert "svcpass_" not in str(e.value)
    assert "<redacted>" in str(e.value)


def test_failed_send_is_retried_and_reported(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    post = MagicMock(return_value=FakeResponse(502, {"error": "Failed to enqueue notification"}))
    monkeypatch.setattr(unitysvc_notify.requests, "post", post)
    config = UnitySVCNotificationConfig(
        name="u", unitysvc_api_key=KEY, max_retries=2, retry_delay=0
    )

    with caplog.at_level("DEBUG"):
        assert config.send_message_with_retry("t", "m", logger=getLogger("test")) is False

    assert post.call_count == 2
    assert KEY not in caplog.text


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"unitysvc_api_key": "sk-not-unitysvc"}, "svcpass_"),
        ({"unitysvc_api_key": ""}, "non-empty"),
        ({"unitysvc_api_key": KEY, "unitysvc_service": "/"}, "service path"),
        ({"unitysvc_api_key": KEY, "unitysvc_base_url": "api.svcpass.com"}, "https://"),
    ],
)
def test_invalid_settings(fields: Dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message) as e:
        UnitySVCNotificationConfig(name="u", **fields)
    assert "sk-not-unitysvc" not in str(e.value)


def test_section_type_is_detected_from_its_keys() -> None:
    config = NotificationConfig.get_config(
        name="unitysvc", unitysvc_api_key=KEY, unitysvc_service="notify"
    )
    assert isinstance(config, UnitySVCNotificationConfig)


def test_key_from_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", KEY)
    config = UnitySVCNotificationConfig(name="u", unitysvc_api_key="${UNITYSVC_API_KEY}")
    assert config.unitysvc_api_key == KEY


def test_unset_key_variable_disables_the_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNITYSVC_API_KEY", raising=False)
    with pytest.warns(UserWarning, match="UNITYSVC_API_KEY"):
        config = UnitySVCNotificationConfig(name="u", unitysvc_api_key="${UNITYSVC_API_KEY}")
    assert config.send_message_with_retry("t", "m") is False


def test_user_config_accepts_unitysvc_settings() -> None:
    user = UserConfig(name="me", unitysvc_api_key=KEY, unitysvc_service="notify")
    assert user.unitysvc_api_key == KEY
    assert user.unitysvc_service == "notify"


def test_notification_section_delivers_listings_end_to_end(
    tmp_path: Path, posts: List[Dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", KEY)
    path = tmp_path / "config.toml"
    path.write_text(
        """
[marketplace.facebook]
search_city = "houston"

[item.bike]
search_phrases = "bike"

[notification.unitysvc]
unitysvc_api_key = "${UNITYSVC_API_KEY}"

[user.me]
notify_with = "unitysvc"
""",
        encoding="utf-8",
    )
    config = Config([path])
    assert isinstance(config.notification["unitysvc"], UnitySVCNotificationConfig)

    listing = Listing(
        marketplace="facebook",
        name="bike",
        id="1",
        title="Road bike",
        image="",
        price="$50",
        post_url="https://www.facebook.com/marketplace/item/1",
        location="Houston",
        seller="",
        condition="",
        description="",
    )
    sent = any(
        channel.config.notify(  # type: ignore[attr-defined]
            [listing],
            [AIResponse(score=5, comment="Great match")],
            [NotificationStatus.NOT_NOTIFIED],
        )
        for channel in config.user["me"].channels()
    )

    assert sent is True
    (call,) = posts
    assert call["url"] == "https://api.svcpass.com/notify"
    assert call["headers"] == {"Authorization": f"Bearer {KEY}"}
    assert "Road bike" in call["json"]["body"]


def test_html_is_not_a_message_format() -> None:
    with pytest.raises(ValueError, match="message_format must be 'plain_text' or 'markdown'"):
        UnitySVCNotificationConfig(
            name="me", unitysvc_api_key="svcpass_test", message_format="html"
        )


def _listing(lid: str, image: str = "", title: str = "Road bike") -> Listing:
    return Listing(
        marketplace="facebook",
        name="bike",
        id=lid,
        title=title,
        image=image,
        price="$50",
        post_url=f"https://www.facebook.com/marketplace/item/{lid}/?ref=search",
        location="Houston",
        seller="",
        condition="",
        description="",
    )


def test_the_first_listing_is_the_link_and_photos_are_attached() -> None:
    listings = [
        _listing("1", "https://scontent.example/1.jpg", "Trek Domane"),
        _listing("2", "https://scontent.example/2.jpg"),
        _listing("3", ""),  # no photo
        _listing("4", "https://scontent.example/1.jpg"),  # the same photo once
        _listing("5", "file:///etc/passwd"),  # not a web URL
    ]
    assert listing_extras(listings) == {
        # the body links every listing; only the first is the tap target
        "links": [{"url": "https://www.facebook.com/marketplace/item/1/", "label": "Trek Domane"}],
        "attachment": ["https://scontent.example/1.jpg", "https://scontent.example/2.jpg"],
    }


def test_at_most_ten_photos_and_nothing_without_listings() -> None:
    many = [_listing(str(i), f"https://scontent.example/{i}.jpg") for i in range(15)]
    assert len(listing_extras(many)["attachment"]) == 10
    assert listing_extras([]) == {}


@pytest.mark.parametrize(
    ("service", "expected"),
    [
        (None, "markdown"),
        ("notify", "markdown"),
        ("labs/msg-to-ntfy", "markdown"),
        ("/labs/msg-to-telegram/", "markdown"),
    ],
)
def test_markdown_by_default_for_every_service(
    posts: List[Dict[str, Any]], service: str | None, expected: str
) -> None:
    config = UnitySVCNotificationConfig(name="u", unitysvc_api_key=KEY, unitysvc_service=service)
    config.send_message("t", "m")
    assert posts[0]["json"]["format"] == expected


def test_a_message_format_that_is_set_is_kept(posts: List[Dict[str, Any]]) -> None:
    config = UnitySVCNotificationConfig(
        name="u",
        unitysvc_api_key=KEY,
        unitysvc_service="labs/msg-to-ntfy",
        message_format="plain_text",
    )
    config.send_message("t", "m")
    assert posts[0]["json"]["format"] == "text"


def test_a_notification_carries_its_listings_link_and_photo(
    posts: List[Dict[str, Any]],
) -> None:
    config = UnitySVCNotificationConfig(
        name="u", unitysvc_api_key=KEY, unitysvc_service="labs/msg-to-ntfy"
    )
    listing = _listing("7", "https://scontent.example/7.jpg", "Trek Domane")
    assert config.notify(
        [listing], [AIResponse(score=5, comment="Great match")], [NotificationStatus.NOT_NOTIFIED]
    )
    body = posts[0]["json"]
    assert body["format"] == "markdown"
    assert "[**Trek Domane**](https://www.facebook.com/marketplace/item/7/)" in body["body"]
    assert body["links"] == [
        {"url": "https://www.facebook.com/marketplace/item/7/", "label": "Trek Domane"}
    ]
    assert body["attachment"] == ["https://scontent.example/7.jpg"]
