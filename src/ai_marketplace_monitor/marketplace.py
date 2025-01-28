from logging import Logger
import time
from typing import Any, ClassVar, Dict, Generator, Type

from playwright.sync_api import Browser, Page

from .items import SearchedItem


class Marketplace:
    allowed_config_keys: ClassVar = {}

    def __init__(self: "Marketplace", name: str, browser: Browser | None, logger: Logger) -> None:
        self.name = name
        self.browser = browser
        self.logger = logger
        self.page: Page | None = None

    def configure(self: "Marketplace", config: Dict[str, Any]) -> None:
        self.config = config

    def set_browser(self: "Marketplace", browser: Browser) -> None:
        self.browser = browser
        self.page = None

    def stop(self: "Marketplace") -> None:
        if self.browser is not None:
            self.browser.close()
            self.browser = None
            self.page = None

    def goto_url(self: "Marketplace", url: str, attempt=0) -> None:
        try:
            self.page.goto(url, timeout=0)
            self.page.wait_for_load_state("domcontentloaded")
        except Exception as e:
            if attempt == 10:
                raise RuntimeError(f"Failed to navigate to {url} after 10 attempts. {e}")
            time.sleep(5)
            self.goto_url(url, attempt + 1)
        except KeyboardInterrupt:
            raise

    @classmethod
    def validate(cls: Type["Marketplace"], config: Dict[str, Any]) -> None:
        # if there are other keys in config, raise an error
        for key in config:
            if key not in cls.allowed_config_keys:
                raise ValueError(f"Marketplace contains an invalid key {key}.")

    def search(self: "Marketplace", item: Dict[str, Any]) -> Generator[SearchedItem, None, None]:
        raise NotImplementedError("Search method must be implemented by subclasses.")
