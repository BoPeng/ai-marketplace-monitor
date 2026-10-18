from types import SimpleNamespace
from typing import Any, List
from unittest.mock import MagicMock

import pytest

from ai_marketplace_monitor import ntfy as ntfy_module
from ai_marketplace_monitor.ai import AIResponse
from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.notification import NotificationStatus
from ai_marketplace_monitor.ntfy import NtfyNotificationConfig, fill_placeholders

CMD = "https://ntfy.sh/my-commands"


@pytest.fixture
def post(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """requests.post for the ntfy module; every message is accepted."""
    post = MagicMock(return_value=SimpleNamespace(raise_for_status=lambda: None))
    monkeypatch.setattr(ntfy_module.requests, "post", post)
    monkeypatch.setattr(ntfy_module.time, "sleep", lambda seconds: None)
    return post


def config(**kwargs: Any) -> NtfyNotificationConfig:
    return NtfyNotificationConfig(
        name="ntfy", ntfy_server="https://ntfy.sh", ntfy_topic="alerts", **kwargs
    )


def notify(ntfy: NtfyNotificationConfig, listings: List[Listing], **kwargs: Any) -> bool:
    ratings = [AIResponse(5, "Great price.", "claude") for _ in listings]
    status = kwargs.pop("status", [NotificationStatus.NOT_NOTIFIED] * len(listings))
    return ntfy.notify(listings, ratings, status, **kwargs)


def test_one_message_for_all_listings_by_default(listing: Listing, post: MagicMock) -> None:
    assert notify(config(), [listing, listing])
    assert post.call_count == 1
    assert post.call_args.args[0] == "https://ntfy.sh/alerts"


def test_per_listing_sends_photo_and_link(listing: Listing, post: MagicMock) -> None:
    listing.image = "https://scontent.example/photo.jpg"
    listing.post_url = "https://www.facebook.com/marketplace/item/42/?ref=search"

    assert notify(config(ntfy_per_listing=True, with_description=5), [listing, listing])
    assert post.call_count == 2
    url, message = post.call_args.args[0], post.call_args.kwargs["json"]
    assert url == "https://ntfy.sh"
    assert message["topic"] == "alerts"
    assert message["title"] == listing.title
    assert message["click"] == "https://www.facebook.com/marketplace/item/42/"
    assert message["attach"] == listing.image
    assert message["message"].splitlines() == [
        "$10, houston, tx",
        "AI: Great deal (5) - Great price.",
        message["message"].splitlines()[2],  # the seller's status
        "somet...",
    ]
    assert "actions" not in message


def test_per_listing_skips_notified_listings(listing: Listing, post: MagicMock) -> None:
    ntfy = config(ntfy_per_listing=True)
    assert not notify(ntfy, [listing], status=[NotificationStatus.NOTIFIED])
    assert post.call_count == 0
    assert notify(ntfy, [listing], status=[NotificationStatus.LISTING_DISCOUNTED])
    assert post.call_args.kwargs["json"]["title"] == f"Price drop: {listing.title}"


def test_actions_are_filled_in_per_listing(listing: Listing, post: MagicMock) -> None:
    actions = [
        {"action": "view", "label": "Open", "url": "{url}"},
        {
            "action": "http",
            "label": "Ask seller",
            "url": CMD,
            "body": '{"cmd": "ask", "url": "{url}", "id": "{id}"}',
        },
    ]
    assert notify(config(ntfy_actions=actions), [listing])
    sent = post.call_args.kwargs["json"]["actions"]
    assert sent[0] == {"action": "view", "label": "Open", "url": listing.post_url}
    assert sent[1]["body"] == f'{{"cmd": "ask", "url": "{listing.post_url}", "id": "111"}}'
    # the configured templates are unchanged
    assert actions[0]["url"] == "{url}"


def test_token_is_sent(listing: Listing, post: MagicMock) -> None:
    assert notify(config(ntfy_token="tk_secret"), [listing])
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer tk_secret"
    assert notify(config(ntfy_token="tk_secret", ntfy_per_listing=True), [listing])
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer tk_secret"}


def test_rejected_message_fails_after_retries(listing: Listing, post: MagicMock) -> None:
    def rejected() -> None:
        raise RuntimeError("403 Forbidden")

    post.return_value = SimpleNamespace(raise_for_status=rejected)
    assert not notify(config(ntfy_per_listing=True, max_retries=2), [listing])
    assert post.call_count == 2
    assert not notify(config(max_retries=2), [listing])
    assert post.call_count == 4


@pytest.mark.parametrize(
    "actions",
    [
        [{"label": "Open", "url": "{url}"}],
        [{"action": "dance", "label": "Open"}],
        [{"action": "view", "label": "x", "url": "{url}"}] * 4,
        [{"action": "view", "label": "Open"}],
        [{"action": "http", "label": "Ask", "body": "{}"}],
        [{"action": "copy", "label": "Copy link"}],
        "view, Open, {url}",
    ],
)
def test_invalid_actions_are_rejected(actions: Any) -> None:
    with pytest.raises(ValueError, match="ntfy_actions"):
        config(ntfy_actions=actions)


def test_placeholders_keep_other_braces() -> None:
    values = {"url": "https://x/1", "id": "1"}
    assert fill_placeholders('{"u": "{url}", "z": "{other}"}', values) == (
        '{"u": "https://x/1", "z": "{other}"}'
    )
    assert fill_placeholders({"a": ["{url}"], "b": 3}, values) == {"a": ["{url}"], "b": 3}


def test_markdown_is_kept_per_listing(listing: Listing, post: MagicMock) -> None:
    assert notify(config(ntfy_per_listing=True, message_format="markdown"), [listing])
    assert post.call_args.kwargs["json"]["markdown"] is True
    assert notify(config(ntfy_per_listing=True), [listing])
    assert post.call_args.kwargs["json"]["markdown"] is False


@pytest.mark.parametrize(
    "server", ["http://localhost:8080", "http://127.0.0.1", "https://ntfy.example"]
)
def test_token_allowed_over_https_or_to_localhost(server: str) -> None:
    assert NtfyNotificationConfig(name="n", ntfy_server=server, ntfy_token="tk").ntfy_token == "tk"


def test_token_refused_over_plain_http() -> None:
    with pytest.raises(ValueError, match="only over https"):
        NtfyNotificationConfig(name="n", ntfy_server="http://ntfy.lan:80", ntfy_token="tk")
    # without a token, plain http stays allowed (e.g. a server on the local network)
    assert NtfyNotificationConfig(name="n", ntfy_server="http://ntfy.lan").ntfy_server


def test_rejection_reason_is_logged(listing: Listing, post: MagicMock) -> None:
    error = RuntimeError("400 Bad Request")
    error.response = SimpleNamespace(text='{"error":"invalid action"}')  # type: ignore[attr-defined]

    def raise_with_body() -> None:
        raise error

    post.return_value = SimpleNamespace(raise_for_status=raise_with_body)
    logger = MagicMock()
    assert not notify(config(ntfy_per_listing=True, max_retries=1), [listing], logger=logger)
    assert any("invalid action" in str(c) for c in logger.debug.call_args_list)
