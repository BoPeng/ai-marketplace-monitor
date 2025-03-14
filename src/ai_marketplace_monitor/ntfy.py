from dataclasses import dataclass
from logging import Logger
from typing import ClassVar, List

import requests  # type: ignore

from .notification import PushNotificationConfig
from .utils import hilight


@dataclass
class NtfyNotificationConfig(PushNotificationConfig):
    required_fields: ClassVar[List[str]] = ["ntfy_server", "ntfy_topic"]
    message_format: ClassVar[str] = "markdown"

    ntfy_server: str | None = None
    ntfy_topic: str | None = None

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

    def send_message(
        self: "NtfyNotificationConfig",
        title: str,
        message: str,
        logger: Logger | None = None,
    ) -> bool:
        msg = f"{message}\n\nSent by https://github.com/BoPeng/ai-marketplace-monitor"
        assert self.ntfy_server is not None
        assert self.ntfy_topic is not None
        requests.post(
            f'{self.ntfy_server.rstrip("/")}/{self.ntfy_topic}',
            msg,
            headers={
                "Title": title,
                "Markdown": "yes" if self.message_format == "markdown" else "no",
            },
            timeout=10,
        )

        if logger:
            logger.info(
                f"""{hilight("[Notify]", "succ")} Sent {self.name} a message {hilight(msg)}"""
            )
        return True
