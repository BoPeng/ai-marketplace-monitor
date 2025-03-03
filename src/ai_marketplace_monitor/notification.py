from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Type

from .utils import BaseConfig


class NotificationStatus(Enum):
    NOT_NOTIFIED = 0
    EXPIRED = 1
    NOTIFIED = 2
    LISTING_CHANGED = 3


class NotificationType(Enum):
    EMAIL = "email"
    PUSHBULLET = "pushbullet"


@dataclass
class NotificationConfig(BaseConfig):
    type: str | None = None

    def handle_type(self: "NotificationConfig") -> None:
        """Handle the type of the notification"""
        if self.type is None:
            return None
        # if specified, it should be one of the values from NotificationType
        if self.type not in [notification_type.value for notification_type in NotificationType]:
            raise ValueError("Invalid notification type")

    @classmethod
    def get_config(cls: Type["NotificationConfig"], **kwargs: Any) -> "NotificationConfig":
        """Get the specific subclass name from the specified keys, for validation purposes"""
        from .email_notify import EmailNotificationConfig
        from .pushbullet import PushbulletNotificationConfig

        acceptable_notification_classes = {
            NotificationType.EMAIL.value: EmailNotificationConfig,
            NotificationType.PUSHBULLET.value: PushbulletNotificationConfig,
        }

        for subclass_name, subclass in acceptable_notification_classes.items():
            acceptable_keys = {field.name for field in fields(subclass)}
            if subclass_name == kwargs.get("type", None):
                if not all(name in kwargs.keys() for name in acceptable_keys):
                    raise ValueError("Invalid notification config for type {subclass_name}")
                return subclass(**kwargs)
            if all(name in acceptable_keys for name in kwargs.keys()):
                return subclass(
                    type=subclass_name, **{k: v for k, v in kwargs.items() if k != "type"}
                )
        raise ValueError("Invalid notification config")
