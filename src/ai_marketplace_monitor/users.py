import time
from logging import Logger
from typing import Any, ClassVar, Dict

from pushbullet import Pushbullet  # type: ignore


class User:
    allowed_config_keys: ClassVar = {"pushbullet_token"}

    def __init__(self, name: str, config: Dict[str, Any], logger: Logger) -> None:
        self.name = name
        self.config = config
        self.push_bullet_token = None
        self.logger = logger
        self.validate(name, config)

    @classmethod
    def validate(cls, username: str, config: Dict[str, Any]) -> None:
        if "pushbullet_token" not in config:
            raise ValueError("User {username} must have a pushbullet_token")
        if not isinstance(config["pushbullet_token"], str):
            raise ValueError("User {username} pushbullet_token must be a string")

        for key in config:
            if key not in cls.allowed_config_keys:
                raise ValueError(f"User {username} contains an invalid key {key}")

    def notify(self, title: str, message: str, max_retries: int = 6, delay: int = 10) -> bool:
        pb = Pushbullet(self.config["pushbullet_token"])

        for attempt in range(max_retries):
            try:
                pb.push_note(title, message)
                return True
            except Exception as e:
                self.logger.debug(f"Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    self.logger.debug(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    self.logger.error(f"Max retries reached. Failed to push note to {self.name}.")
                    return False
        return True
