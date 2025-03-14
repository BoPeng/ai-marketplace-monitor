import http.client
import json
import urllib
from dataclasses import dataclass
from logging import Logger
from typing import ClassVar, List

from .notification import PushNotificationConfig
from .utils import hilight


@dataclass
class PushoverNotificationConfig(PushNotificationConfig):
    required_fields: ClassVar[List[str]] = ["pushover_user_id", "pushover_api_token"]

    pushover_user_id: str | None = None
    pushover_api_token: str | None = None

    def handle_pushover_user_id(self: "PushoverNotificationConfig") -> None:
        if self.pushover_user_id is None:
            return
        if not isinstance(self.pushover_user_id, str) or not self.pushover_user_id:
            raise ValueError("An non-empty pushover_user_id is needed.")
        self.pushover_user_id = self.pushover_user_id.strip()

    def handle_pushover_api_token(self: "PushoverNotificationConfig") -> None:
        if self.pushover_api_token is None:
            return

        if not isinstance(self.pushover_api_token, str) or not self.pushover_api_token:
            raise ValueError("user requires an non-empty pushover_api_token.")
        self.pushover_api_token = self.pushover_api_token.strip()

    def send_pus_message(
        self: "PushoverNotificationConfig",
        title: str,
        message: str,
        logger: Logger | None = None,
    ) -> bool:
        msg = f"{title}\n\n{message}\n\nSent by https://github.com/BoPeng/ai-marketplace-monitor"
        conn = http.client.HTTPSConnection("api.pushover.net:443")
        conn.request(
            "POST",
            "/1/messages.json",
            urllib.parse.urlencode(
                {
                    "token": self.pushover_api_token,
                    "user": self.pushover_user_id,
                    "message": msg,
                }
            ),
            {"Content-type": "application/x-www-form-urlencoded"},
        )

        output = conn.getresponse().read().decode("utf-8")
        data = json.loads(output)
        if data["status"] != 1:
            raise RuntimeError(output)
        else:
            if logger:
                logger.info(
                    f"""{hilight("[Notify]", "succ")} Sent {self.name} a message {hilight(msg)}"""
                )
            return True
