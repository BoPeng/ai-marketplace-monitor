import os
import re
from dataclasses import dataclass
from logging import Logger
from typing import ClassVar, List

import requests  # type: ignore

from .notification import CHANNEL, PushNotificationConfig, notification_field
from .utils import hilight

DEFAULT_UNITYSVC_BASE_URL = "https://api.svcpass.com"
DEFAULT_UNITYSVC_SERVICE = "notify"
# UnitySVC stores notification titles in a 255-character column
MAX_TITLE_LENGTH = 255
MESSAGE_FORMATS = {"plain_text": "text", "markdown": "markdown", "html": "html"}
UNITYSVC_TOKEN_RE = re.compile(r"svcpass_[A-Za-z0-9_-]+")
REDACTED = "<redacted>"


@dataclass
class UnitySVCNotificationConfig(PushNotificationConfig):
    """Send notifications through the UnitySVC gateway.

    The default ``notify`` service delivers to the UnitySVC inbox and to the notification
    destination saved in the user's UnitySVC preferences; any other service path (e.g.
    ``labs/msg-to-discord`` or ``e/<CODE>``) delivers to that service only.
    """

    notify_method = "unitysvc"
    required_fields: ClassVar[List[str]] = ["unitysvc_api_key"]

    unitysvc_api_key: str | None = notification_field(CHANNEL)
    unitysvc_service: str | None = notification_field(CHANNEL)
    unitysvc_base_url: str | None = notification_field(CHANNEL)

    def handle_unitysvc_api_key(self: "UnitySVCNotificationConfig") -> None:
        if self.unitysvc_api_key is None:
            return
        if not isinstance(self.unitysvc_api_key, str) or not self.unitysvc_api_key.strip():
            raise ValueError("A non-empty unitysvc_api_key is needed.")
        self.unitysvc_api_key = self.unitysvc_api_key.strip()
        if not self.unitysvc_api_key.startswith("svcpass_"):
            # never echo the value: it is a credential
            raise ValueError(
                'unitysvc_api_key must be a UnitySVC API key starting with "svcpass_", '
                'e.g. unitysvc_api_key = "${UNITYSVC_API_KEY}".'
            )

    def handle_unitysvc_service(self: "UnitySVCNotificationConfig") -> None:
        if self.unitysvc_service is None:
            return
        if not isinstance(self.unitysvc_service, str) or not self.unitysvc_service.strip("/ "):
            raise ValueError(
                'unitysvc_service must be a non-empty service path such as "notify" or '
                '"labs/msg-to-discord".'
            )
        self.unitysvc_service = self.unitysvc_service.strip("/ ")

    def handle_unitysvc_base_url(self: "UnitySVCNotificationConfig") -> None:
        if self.unitysvc_base_url is None:
            return
        if not isinstance(self.unitysvc_base_url, str) or not self.unitysvc_base_url.startswith(
            ("https://", "http://")
        ):
            raise ValueError("unitysvc_base_url must start with https:// or http://")
        self.unitysvc_base_url = self.unitysvc_base_url.rstrip("/")

    @property
    def unitysvc_url(self: "UnitySVCNotificationConfig") -> str:
        base_url = (
            self.unitysvc_base_url
            or os.environ.get("UNITYSVC_API_BASE_URL")
            or DEFAULT_UNITYSVC_BASE_URL
        )
        return f"{base_url.rstrip('/')}/{self.unitysvc_service or DEFAULT_UNITYSVC_SERVICE}"

    def send_message(
        self: "UnitySVCNotificationConfig",
        title: str,
        message: str,
        logger: Logger | None = None,
    ) -> bool:
        assert self.unitysvc_api_key is not None
        msg = f"{message}\n\nSent by https://github.com/BoPeng/ai-marketplace-monitor"
        response = requests.post(
            self.unitysvc_url,
            json={
                "title": title[:MAX_TITLE_LENGTH],
                "body": msg,
                "type": "info",
                "format": MESSAGE_FORMATS.get(self.message_format or "plain_text", "text"),
            },
            headers={"Authorization": f"Bearer {self.unitysvc_api_key}"},
            timeout=10,
        )
        if not response.ok:
            raise RuntimeError(
                f"UnitySVC {self.unitysvc_url} returned {response.status_code}: "
                f"{_error_detail(response, self.unitysvc_api_key)}"
            )

        if logger:
            logger.info(
                f"""{hilight("[Notify]", "succ")} Sent {self.name} a message with title {hilight(title)} via {self.unitysvc_url}"""
            )
        return True


def _redact_secret(text: str, secret: str | None = None) -> str:
    if secret:
        text = text.replace(secret, REDACTED)
    return UNITYSVC_TOKEN_RE.sub(REDACTED, text)


def _error_detail(response: requests.Response, unitysvc_api_key: str | None = None) -> str:
    """The gateway's ``error`` or the backend's ``detail``, else the start of the body."""
    try:
        data = response.json()
    except ValueError:
        return _redact_secret(response.text, unitysvc_api_key)[:200]
    if isinstance(data, dict):
        return _redact_secret(
            str(data.get("error") or data.get("detail") or data), unitysvc_api_key
        )[:200]
    return _redact_secret(str(data), unitysvc_api_key)[:200]
