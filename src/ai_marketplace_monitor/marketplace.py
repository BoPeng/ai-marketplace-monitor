from logging import Logger
from typing import Any, ClassVar, Dict, List

from playwright.sync_api import Browser

from .items import SearchedItem


class Marketplace:
    allowed_config_keys: ClassVar = {}

    def __init__(
        self: "Marketplace", name: str, config: Dict[str, Any], browser: Browser, logger: Logger
    ) -> None:
        self.name = name
        self.config = config
        self.browser = browser
        self.logger = logger
        self.page = None

    @classmethod
    def validate(cls, config: Dict[str, Any]) -> None:
        # if there are other keys in config, raise an error
        for key in config:
            if key not in cls.allowed_config_keys:
                raise ValueError(f"Marketplace contains an invalid key {key}.")

    def reset(self):
        # ask to re-login
        self.page = None

    def search(self, item: Dict[str, Any]) -> List[SearchedItem]:
        raise NotImplementedError("Search method must be implemented by subclasses.")
