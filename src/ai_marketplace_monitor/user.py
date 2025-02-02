import time
from dataclasses import dataclass
from logging import Logger
from typing import Any, ClassVar, Type

from pushbullet import Pushbullet  # type: ignore

from .utils import DataClassWithHandleFunc, hilight


@dataclass
class UserConfig(DataClassWithHandleFunc):
    # this argument is required
    pushbullet_token: str

    def handle_pushbullet_token(self: "UserConfig") -> None:
        if not isinstance(self.pushbullet_token, str) or not self.pushbullet_token:
            raise ValueError("user requires an non-empty pushbullet_token.")
        self.pushbullet_token = self.pushbullet_token.strip()


class User:
    allowed_config_keys: ClassVar = {"pushbullet_token"}

    def __init__(self: "User", name: str, config: UserConfig, logger: Logger) -> None:
        self.name = name
        self.config = config
        self.push_bullet_token = None
        self.logger = logger

    @classmethod
    def get_config(cls: Type["User"], **kwargs: Any) -> UserConfig:
        return UserConfig(**kwargs)

    def notify(
        self: "User", title: str, message: str, max_retries: int = 6, delay: int = 10
    ) -> bool:
        pb = Pushbullet(self.config.pushbullet_token)

        for attempt in range(max_retries):
            try:
                pb.push_note(title, message)
                return True
            except Exception as e:
                self.logger.debug(
                    f"""{hilight("[Notify]", "fail")} Attempt {attempt + 1} failed: {e}"""
                )
                if attempt < max_retries - 1:
                    self.logger.debug(
                        f"""{hilight("[Notify]", "fail")} Retrying in {delay} seconds..."""
                    )
                    time.sleep(delay)
                else:
                    self.logger.error(
                        f"""{hilight("[Notify]", "fail")} Max retries reached. Failed to push note to {self.name}."""
                    )
                    return False
        return True
