from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Optional, Type

from .utils import BaseConfig


class NotificationStatus(Enum):
    NOT_NOTIFIED = 0
    EXPIRED = 1
    NOTIFIED = 2
    LISTING_CHANGED = 3


@dataclass
class NotificationConfig(BaseConfig):

    @classmethod
    def get_config(
        cls: Type["NotificationConfig"], **kwargs: Any
    ) -> Optional["NotificationConfig"]:
        """Get the specific subclass name from the specified keys, for validation purposes"""
        for subclass in cls.__subclasses__():
            acceptable_keys = {field.name for field in fields(subclass)}
            if all(name in acceptable_keys for name in kwargs.keys()):
                return subclass(**{k: v for k, v in kwargs.items() if k != "type"})
            res = subclass.get_config(**kwargs)
            if res is not None:
                return res
        return None

    @classmethod
    def notify_all(
        cls: type["NotificationConfig"], config: "NotificationConfig", *args, **kwargs: Any
    ) -> bool:
        """Call the notify method of all subclasses"""
        succ = []
        for subclass in cls.__subclasses__():
            if hasattr(subclass, "notify") and subclass.__name__ != "UserConfig":
                succ.append(subclass.notify(config, *args, **kwargs))
            # subclases
            succ.append(subclass.notify_all(config, *args, **kwargs))
        return any(succ)
