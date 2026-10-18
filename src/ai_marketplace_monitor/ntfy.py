import time
from dataclasses import dataclass
from logging import Logger
from typing import Any, ClassVar, Dict, List

import requests  # type: ignore

from .ai import AIResponse  # type: ignore
from .listing import Listing
from .notification import (
    CHANNEL,
    COMMON,
    RECIPIENT,
    NotificationStatus,
    PushNotificationConfig,
    notification_field,
)
from .seller import seller_status
from .utils import hilight

# the fields of a listing that ntfy_actions may use, as {name}
ACTION_PLACEHOLDERS = ("url", "id", "title", "price", "location")
ACTION_TYPES = ("view", "http", "broadcast", "copy")
# the field each action type needs besides its label (https://docs.ntfy.sh/publish/#action-buttons)
ACTION_REQUIRED = {"view": "url", "http": "url", "copy": "value"}
LOCAL_HOSTS = ("localhost", "127.0.0.1", "[::1]")
# ntfy shows at most three action buttons
MAX_ACTIONS = 3


def _listing_values(listing: Listing) -> Dict[str, str]:
    return {
        "url": listing.post_url.split("?")[0],
        "id": str(listing.id),
        "title": listing.title,
        "price": listing.price,
        "location": listing.location,
    }


def fill_placeholders(value: Any, values: Dict[str, str]) -> Any:
    """``value`` with each ``{name}`` of ACTION_PLACEHOLDERS replaced; other braces are kept.

    Plain replacement rather than ``str.format``, so that a JSON body needs no doubled braces.
    """
    if isinstance(value, str):
        for name, replacement in values.items():
            value = value.replace(f"{{{name}}}", replacement)
        return value
    if isinstance(value, dict):
        return {k: fill_placeholders(v, values) for k, v in value.items()}
    return value


@dataclass
class NtfyNotificationConfig(PushNotificationConfig):
    notify_method = "ntfy"
    required_fields: ClassVar[List[str]] = ["ntfy_server", "ntfy_topic"]

    message_format: str | None = notification_field(COMMON)
    ntfy_server: str | None = notification_field(CHANNEL)
    ntfy_topic: str | None = notification_field(RECIPIENT)
    # an access token for a protected topic, sent as "Authorization: Bearer <token>"
    ntfy_token: str | None = notification_field(CHANNEL)
    # one notification per listing, with its photo, opening the listing when tapped
    ntfy_per_listing: bool | None = notification_field(CHANNEL)
    # action buttons of each listing's notification (implies ntfy_per_listing)
    ntfy_actions: List[Dict[str, Any]] | None = notification_field(CHANNEL)

    def handle_ntfy_server(self: "NtfyNotificationConfig") -> None:
        if self.ntfy_server is None:
            return
        if not isinstance(self.ntfy_server, str) or not self.ntfy_server:
            raise ValueError("An non-empty ntfy_server is needed.")

        if not self.ntfy_server.startswith("https://") and not self.ntfy_server.startswith(
            "http://"
        ):
            raise ValueError("ntfy_server must start with https:// or http://")

    def handle_ntfy_topic(self: "NtfyNotificationConfig") -> None:
        if self.ntfy_topic is None:
            return

        if not isinstance(self.ntfy_topic, str) or not self.ntfy_topic:
            raise ValueError("user requires an non-empty ntfy_topic.")

        self.ntfy_topic = self.ntfy_topic.strip()

    def handle_ntfy_token(self: "NtfyNotificationConfig") -> None:
        if self.ntfy_token is None:
            return
        if not isinstance(self.ntfy_token, str) or not self.ntfy_token.strip():
            raise ValueError("ntfy_token must be a non-empty string.")
        self.ntfy_token = self.ntfy_token.strip()

    def handle_ntfy_per_listing(self: "NtfyNotificationConfig") -> None:
        if self.ntfy_per_listing is not None and not isinstance(self.ntfy_per_listing, bool):
            raise ValueError("ntfy_per_listing must be true or false.")

    def handle_ntfy_actions(self: "NtfyNotificationConfig") -> None:
        if self.ntfy_actions is None:
            return
        if not isinstance(self.ntfy_actions, list) or len(self.ntfy_actions) > MAX_ACTIONS:
            raise ValueError(f"ntfy_actions must be a list of at most {MAX_ACTIONS} actions.")
        for action in self.ntfy_actions:
            if (
                not isinstance(action, dict)
                or action.get("action") not in ACTION_TYPES
                or not isinstance(action.get("label"), str)
            ):
                raise ValueError(
                    "Each of ntfy_actions needs an action "
                    f"({', '.join(ACTION_TYPES)}) and a label, e.g. "
                    '{ action = "view", label = "Open", url = "{url}" }.'
                )
            required = ACTION_REQUIRED.get(action["action"])
            if required and not isinstance(action.get(required), str):
                raise ValueError(
                    f'The {action["action"]} action "{action["label"]}" of ntfy_actions needs '
                    f"a {required}."
                )

    def __post_init__(self: "NtfyNotificationConfig") -> None:
        """Validate the fields, then refuse a token that would be sent unencrypted."""
        super().__post_init__()
        # a token is a password: never send it unencrypted, except to this machine
        if self.ntfy_token and self.ntfy_server and self.ntfy_server.startswith("http://"):
            host = self.ntfy_server[len("http://") :].split("/")[0].rsplit(":", 1)[0]
            if host not in LOCAL_HOSTS:
                raise ValueError(
                    "ntfy_token is sent only over https:// (or to localhost); "
                    f"use an https:// ntfy_server instead of {self.ntfy_server}."
                )

    def _headers(self: "NtfyNotificationConfig") -> Dict[str, str]:
        if self.ntfy_token:
            return {"Authorization": f"Bearer {self.ntfy_token}"}
        return {}

    def send_message(
        self: "NtfyNotificationConfig",
        title: str,
        message: str,
        logger: Logger | None = None,
    ) -> bool:
        msg = f"{message}\n\nSent by https://github.com/BoPeng/ai-marketplace-monitor"
        assert self.ntfy_server is not None
        assert self.ntfy_topic is not None
        response = requests.post(
            f"{self.ntfy_server.rstrip('/')}/{self.ntfy_topic}",
            msg.encode("utf-8"),
            headers={
                "Title": title,
                "Markdown": "yes" if self.message_format == "markdown" else "no",
                **self._headers(),
            },
            timeout=10,
        )
        # a rejected message (e.g. a protected topic without its token) is retried, then failed
        response.raise_for_status()

        if logger:
            logger.info(
                f"""{hilight("[Notify]", "succ")} Sent {self.name} a message {hilight(msg)}"""
            )
        return True

    @property
    def per_listing(self: "NtfyNotificationConfig") -> bool:
        return bool(self.ntfy_per_listing or self.ntfy_actions)

    def notify(
        self: "NtfyNotificationConfig",
        listings: List[Listing],
        ratings: List[AIResponse],
        notification_status: List[NotificationStatus],
        force: bool = False,
        logger: Logger | None = None,
    ) -> bool:
        if not self.per_listing:
            return super().notify(listings, ratings, notification_status, force, logger)
        if not self._has_required_fields():
            return False
        sent = False
        for listing, rating, ns in zip(listings, ratings, notification_status):
            if ns == NotificationStatus.NOTIFIED and not force:
                continue
            if not self._notify_listing(listing, rating, ns, logger):
                return False
            sent = True
        if not sent and logger:
            logger.debug("No new listings to notify.")
        return sent

    def listing_message(
        self: "NtfyNotificationConfig",
        listing: Listing,
        rating: AIResponse,
        ns: NotificationStatus,
    ) -> Dict[str, Any]:
        """The JSON message (https://docs.ntfy.sh/publish/#publish-as-json) for one listing."""
        status = {
            NotificationStatus.LISTING_CHANGED: "Updated: ",
            NotificationStatus.LISTING_DISCOUNTED: "Price drop: ",
            NotificationStatus.EXPIRED: "Another look: ",
        }.get(ns, "")
        lines = [f"{listing.price}, {listing.location}"]
        if rating.comment != AIResponse.NOT_EVALUATED:
            lines.append(f"AI: {rating.conclusion} ({rating.score}) - {rating.comment}")
        lines.append(f"Seller: {seller_status(listing.seller_info)}")
        if self.with_description != 0 and listing.description:
            limit = self.with_description if (self.with_description or 0) > 1 else None
            desc = listing.description
            lines.append(desc[:limit] + "..." if limit and len(desc) > limit else desc)
        values = _listing_values(listing)
        message: Dict[str, Any] = {
            "topic": self.ntfy_topic,
            "title": f"{status}{listing.title}",
            "message": "\n".join(lines),
            "click": values["url"],
            "tags": ["shopping_cart"],
            "markdown": self.message_format == "markdown",
        }
        if listing.image:
            message["attach"] = listing.image
            message["filename"] = f"{listing.id}.jpg"
        if self.ntfy_actions:
            message["actions"] = [fill_placeholders(a, values) for a in self.ntfy_actions]
        return message

    def _notify_listing(
        self: "NtfyNotificationConfig",
        listing: Listing,
        rating: AIResponse,
        ns: NotificationStatus,
        logger: Logger | None,
    ) -> bool:
        message = self.listing_message(listing, rating, ns)
        assert self.ntfy_server is not None
        for attempt in range(self.max_retries):
            if self.rate_limit_enabled:
                self._wait_for_rate_limit_sync(logger)
            try:
                # JSON goes to the server's root URL; the topic is in the message
                response = requests.post(
                    self.ntfy_server.rstrip("/"),
                    json=message,
                    headers=self._headers(),
                    timeout=10,
                )
                response.raise_for_status()
            except KeyboardInterrupt:
                raise
            except Exception as e:
                if logger:
                    # ntfy says what it rejected (e.g. an invalid action) in the response body
                    body = getattr(getattr(e, "response", None), "text", "") or ""
                    detail = f" ({body.strip()[:300]})" if body.strip() else ""
                    logger.debug(
                        f"""{hilight("[Notify]", "fail")} Attempt {attempt + 1} failed: {e}{detail}"""
                    )
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                continue
            if logger:
                logger.info(
                    f"""{hilight("[Notify]", "succ")} Sent {self.name} {hilight(listing.title)}"""
                )
            return True
        if logger:
            logger.error(
                f"""{hilight("[Notify]", "fail")} Max retries reached. Failed to push note to {self.name}."""
            )
        return False
