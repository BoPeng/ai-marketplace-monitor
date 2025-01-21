from typing import Any, ClassVar, Dict

from pushbullet import Pushbullet


class User:
    allowed_config_keys: ClassVar = {"pushbullet_token"}

    def __init__(self, name: str, config: Dict[str, Any]) -> None:
        self.name = name
        self.config = config
        self.push_bullet_token = None
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

    def notify(self, title: str, message: str) -> None:
        pb = Pushbullet(self.config["pushbullet_token"])
        pb.push_note(title, message)
