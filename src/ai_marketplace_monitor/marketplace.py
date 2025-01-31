import time
from dataclasses import dataclass
from logging import Logger
from typing import Any, Dict, Generator, List, Type

from playwright.sync_api import Browser, Page

from .item import SearchedItem
from .utils import DataClassWithHandleFunc, convert_to_minutes


@dataclass
class MarketItemCommonConfig(DataClassWithHandleFunc):

    max_search_interval: int | None = None
    notify: List[str] | None = None
    search_city: List[str] | None = None
    # radius must be processed after search_city
    radius: List[int] | None = None
    search_interval: int | None = None
    search_region: List[str] | None = None

    def handle_max_search_interval(self: "MarketItemCommonConfig") -> None:
        if self.max_search_interval is None:
            return

        if isinstance(self.max_search_interval, str):
            try:
                self.max_search_interval = convert_to_minutes(self.max_search_interval)
            except Exception as e:
                raise ValueError(
                    f"Marketplace {self.name} max_search_interval {self.max_search_interval} is not recognized."
                ) from e
        if not isinstance(self.max_search_interval, int) or self.max_search_interval < 1:
            raise ValueError(
                f"Item [magenta]{self.name}[/magenta] max_search_interval must be at least 1 minutes."
            )

    def handle_notify(self: "MarketItemCommonConfig") -> None:
        if self.notify is None:
            return

        if isinstance(self.notify, str):
            self.notify = [self.notify]
        if not all(isinstance(x, str) for x in self.notify):
            raise ValueError(
                f"Item [magenta]{self.name}[/magenta] notify must be a string or list of string."
            )

    def handle_radius(self: "MarketItemCommonConfig") -> None:
        if self.radius is None:
            return

        if self.search_city is None:
            raise ValueError(
                f"Item [magenta]{self.name}[/magenta] radius must be None if search_city is None."
            )

        if isinstance(self.radius, int):
            self.radius = [self.radius]

        if not all(isinstance(x, int) for x in self.radius):
            raise ValueError(
                f"Item [magenta]{self.name}[/magenta] radius must be one or a list of integers."
            )

        if len(self.radius) != len(self.search_city):
            raise ValueError(
                f"Item [magenta]{self.name}[/magenta] radius must be the same length as search_city."
            )

    def handle_search_city(self: "MarketItemCommonConfig") -> None:
        if self.search_city is None:
            return

        if isinstance(self.search_city, str):
            self.search_city = [self.search_city]
        if not isinstance(self.search_city, list) or not all(
            isinstance(x, str) for x in self.search_city
        ):
            raise ValueError(
                f"Item [magenta]{self.name}[/magenta] search_city must be a string or list of string."
            )

    def handle_search_interval(self: "MarketItemCommonConfig") -> None:
        if self.search_interval is None:
            return

        if isinstance(self.search_interval, str):
            try:
                self.search_interval = convert_to_minutes(self.search_interval)
            except Exception as e:
                raise ValueError(
                    f"Marketplace {self.name} search_interval {self.search_interval} is not recognized."
                ) from e
        if not isinstance(self.search_interval, int) or self.search_interval < 1:
            raise ValueError(
                f"Item [magenta]{self.name}[/magenta] search_interval must be at least 1 minutes."
            )

    def handle_search_region(self: "MarketItemCommonConfig") -> None:
        if self.search_region is None:
            return

        if isinstance(self.search_region, str):
            self.search_region = [self.search_region]

        if not isinstance(self.search_region, list) or not all(
            isinstance(x, str) for x in self.search_region
        ):
            raise ValueError(
                f"Item [magenta]{self.name}[/magenta] search_region must be one or a list of string."
            )


@dataclass
class MarketplaceConfig(MarketItemCommonConfig):
    """Generic marketplace config"""

    pass


@dataclass
class ItemConfig(MarketItemCommonConfig):
    """Generic item config"""

    pass


class Marketplace:

    def __init__(self: "Marketplace", name: str, browser: Browser | None, logger: Logger) -> None:
        self.name = name
        self.browser = browser
        self.logger = logger
        self.page: Page | None = None

    @classmethod
    def get_config(cls: Type["Marketplace"], **kwargs: Dict[str, Any]) -> MarketplaceConfig:
        return MarketplaceConfig.from_dict(kwargs)

    @classmethod
    def get_item_config(cls: Type["Marketplace"], **kwargs: Dict[str, Any]) -> ItemConfig:
        return ItemConfig.from_dict(kwargs)

    def configure(self: "Marketplace", config: MarketplaceConfig) -> None:
        self.config = config

    def set_browser(self: "Marketplace", browser: Browser) -> None:
        self.browser = browser
        self.page = None

    def stop(self: "Marketplace") -> None:
        if self.browser is not None:
            self.browser.close()
            self.browser = None
            self.page = None

    def goto_url(self: "Marketplace", url: str, attempt: int = 0) -> None:
        try:
            assert self.page is not None
            self.page.goto(url, timeout=0)
            self.page.wait_for_load_state("domcontentloaded")
        except Exception as e:
            if attempt == 10:
                raise RuntimeError(f"Failed to navigate to {url} after 10 attempts. {e}") from e
            time.sleep(5)
            self.goto_url(url, attempt + 1)
        except KeyboardInterrupt:
            raise

    def search(self: "Marketplace", item: ItemConfig) -> Generator[SearchedItem, None, None]:
        raise NotImplementedError("Search method must be implemented by subclasses.")
