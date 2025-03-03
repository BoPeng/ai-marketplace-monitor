from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Type

from .utils import BaseConfig


class NotificationStatus(Enum):
    NOT_NOTIFIED = 0
    EXPIRED = 1
    NOTIFIED = 2
    LISTING_CHANGED = 3


@dataclass
class NotificationConfig(BaseConfig):

    @classmethod
    def get_config(cls: Type["NotificationConfig"], **kwargs: Any) -> "NotificationConfig":
        """Get the specific subclass name from the specified keys, for validation purposes"""
        for subclass in NotificationConfig.__subclasses__():
            acceptable_keys = {field.name for field in fields(subclass)}
            if all(name in acceptable_keys for name in kwargs.keys()):
                return subclass(**{k: v for k, v in kwargs.items() if k != "type"})
        raise ValueError("Invalid notification config")
