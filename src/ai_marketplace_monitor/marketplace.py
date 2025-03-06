import time
from dataclasses import dataclass, field
from enum import Enum
from logging import Logger
from typing import Any, Generator, Generic, List, Type, TypeVar

from playwright.sync_api import Browser, Page

from .listing import Listing
from .utils import BaseConfig, KeyboardMonitor, convert_to_seconds, hilight


class MarketPlace(Enum):
    FACEBOOK = "facebook"


@dataclass
class MarketItemCommonConfig(BaseConfig):
    """Item options that can be specified in market (non-marketplace specifc)

    This class defines and processes options that can be specified
    in both marketplace and item sections, generic to all marketplaces
    """

    ai: List[str] | None = None
    exclude_sellers: List[str] | None = None
    notify: List[str] | None = None
    search_city: List[str] | None = None
    city_name: List[str] | None = None
    # radius must be processed after search_city
    radius: List[int] | None = None
    search_interval: int | None = None
    max_search_interval: int | None = None
    start_at: List[str] | None = None
    search_region: List[str] | None = None
    max_price: int | None = None
    min_price: int | None = None
    rating: List[int] | None = None
    prompt: str | None = None
    extra_prompt: str | None = None
    rating_prompt: str | None = None

    def handle_ai(self: "MarketItemCommonConfig") -> None:
        if self.ai is None:
            return

        if isinstance(self.ai, str):
            self.ai = [self.ai]
        if not all(isinstance(x, str) for x in self.ai):
            raise ValueError(f"Item {hilight(self.name)} ai must be a string or list.")

    def handle_exclude_sellers(self: "MarketItemCommonConfig") -> None:
        if self.exclude_sellers is None:
            return

        if isinstance(self.exclude_sellers, str):
            self.exclude_sellers = [self.exclude_sellers]
        if not isinstance(self.exclude_sellers, list) or not all(
            isinstance(x, str) for x in self.exclude_sellers
        ):
            raise ValueError(f"Item {hilight(self.name)} exclude_sellers must be a list.")

    def handle_max_search_interval(self: "MarketItemCommonConfig") -> None:
        if self.max_search_interval is None:
            return

        if isinstance(self.max_search_interval, str):
            try:
                self.max_search_interval = convert_to_seconds(self.max_search_interval)
            except Exception as e:
                raise ValueError(
                    f"Marketplace {self.name} max_search_interval {self.max_search_interval} is not recognized."
                ) from e
        if not isinstance(self.max_search_interval, int) or self.max_search_interval < 1:
            raise ValueError(
                f"Item {hilight(self.name)} max_search_interval must be at least 1 second."
            )

    def handle_notify(self: "MarketItemCommonConfig") -> None:
        if self.notify is None:
            return

        if isinstance(self.notify, str):
            self.notify = [self.notify]
        if not all(isinstance(x, str) for x in self.notify):
            raise ValueError(
                f"Item {hilight(self.name)} notify must be a string or list of string."
            )

    def handle_radius(self: "MarketItemCommonConfig") -> None:
        if self.radius is None:
            return

        if self.search_city is None:
            raise ValueError(
                f"Item {hilight(self.name)} radius must be None if search_city is None."
            )

        if isinstance(self.radius, int):
            self.radius = [self.radius]

        if not all(isinstance(x, int) for x in self.radius):
            raise ValueError(
                f"Item {hilight(self.name)} radius must be one or a list of integers."
            )

        if len(self.radius) != len(self.search_city):
            raise ValueError(
                f"Item {hilight(self.name)} radius must be the same length as search_city."
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
                f"Item {hilight(self.name)} search_city must be a string or list of string."
            )

    def handle_city_name(self: "MarketItemCommonConfig") -> None:
        if self.city_name is None:
            if self.search_city is None:
                return
            self.city_name = [x.capitalize() for x in self.search_city]
            return

        if self.search_city is None:
            raise ValueError(
                f"Item {hilight(self.name)} city_name must be None if search_city is None."
            )
        if isinstance(self.city_name, str):
            self.city_name = [self.city_name]
        # check if city_name is a list of strings
        if not isinstance(self.city_name, list) or not all(
            isinstance(x, str) for x in self.city_name
        ):
            raise ValueError(f"Region {self.name} city_name must be a list of strings.")

        if len(self.city_name) != len(self.search_city):
            raise ValueError(
                f"Region {self.name} city_name ({self.city_name}) must be the same length as search_city ({self.search_city})."
            )

    def handle_search_interval(self: "MarketItemCommonConfig") -> None:
        if self.search_interval is None:
            return

        if isinstance(self.search_interval, str):
            try:
                self.search_interval = convert_to_seconds(self.search_interval)
            except Exception as e:
                raise ValueError(
                    f"Marketplace {self.name} search_interval {self.search_interval} is not recognized."
                ) from e
        if not isinstance(self.search_interval, int) or self.search_interval < 1:
            raise ValueError(
                f"Item {hilight(self.name)} search_interval must be at least 1 second."
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
                f"Item {hilight(self.name)} search_region must be one or a list of string."
            )

    def handle_max_price(self: "MarketItemCommonConfig") -> None:
        if self.max_price is None:
            return
        if not isinstance(self.max_price, int):
            raise ValueError(f"Item {hilight(self.name)} max_price must be an integer.")

    def handle_min_price(self: "MarketItemCommonConfig") -> None:
        if self.min_price is None:
            return

        if not isinstance(self.min_price, int):
            raise ValueError(f"Item {hilight(self.name)} min_price must be an integer.")

    def handle_start_at(self: "MarketItemCommonConfig") -> None:
        if self.start_at is None:
            return

        if isinstance(self.start_at, str):
            self.start_at = [self.start_at]

        if not isinstance(self.start_at, list) or not all(
            isinstance(x, str) for x in self.start_at
        ):
            raise ValueError(
                f"Item {hilight(self.name)} start_at must be a string or list of string."
            )

        # start_at should be in one of the format of
        # HH:MM:SS, HH:MM, *:MM:SS, or *:MM, or *:*:SS
        # where HH, MM, SS are hour, minutes and seconds
        # and * can be any number
        # if not, raise ValueError
        for val in self.start_at:
            if (
                val.count(":") not in (1, 2)
                or val.count("*") == 3
                or not all(x == "*" or (x.isdigit() and len(x) == 2) for x in val.split(":"))
            ):
                raise ValueError(f"Item {hilight(self.name)} start_at {val} is not recognized.")
            #
            acceptable = False
            for pattern in ["%H:%M:%S", "%H:%M", "*:%M:%S", "*:%M", "*:*:%S"]:
                try:
                    time.strptime(val, pattern)
                    acceptable = True
                    break
                except ValueError:
                    pass
            if not acceptable:
                raise ValueError(f"Item {hilight(self.name)} start_at {val} is not recognized.")

    def handle_rating(self: "MarketItemCommonConfig") -> None:
        if self.rating is None:
            return
        if isinstance(self.rating, int):
            self.rating = [self.rating]

        if not all(isinstance(x, int) and x >= 1 and x <= 5 for x in self.rating):
            raise ValueError(
                f"Item {hilight(self.name)} rating must be one or a list of integers between 1 and 5 inclusive."
            )

    def handle_prompt(self: "MarketItemCommonConfig") -> None:
        if self.prompt is None:
            return
        if not isinstance(self.prompt, str):
            raise ValueError(f"Item {hilight(self.name)} requires a string prompt, if specified.")

    def handle_extra_prompt(self: "MarketItemCommonConfig") -> None:
        if self.extra_prompt is None:
            return
        if not isinstance(self.extra_prompt, str):
            raise ValueError(
                f"Item {hilight(self.name)} requires a string extra_prompt, if specified."
            )

    def handle_rating_prompt(self: "MarketItemCommonConfig") -> None:
        if self.rating_prompt is None:
            return
        if not isinstance(self.rating_prompt, str):
            raise ValueError(
                f"Item {hilight(self.name)} requires a string rating_prompt, if specified."
            )


@dataclass
class MarketplaceConfig(MarketItemCommonConfig):
    """Generic marketplace config"""

    # name of market, right now facebook is the only supported one
    market_type: str | None = MarketPlace.FACEBOOK.value

    def handle_market_type(self: "MarketplaceConfig") -> None:
        if self.market_type is None:
            return
        if not isinstance(self.market_type, str):
            raise ValueError(f"Marketplace {hilight(self.market_type)} market must be a string.")
        if self.market_type.lower() != MarketPlace.FACEBOOK.value:
            raise ValueError(
                f"Marketplace {hilight(self.market_type)} market must be {MarketPlace.FACEBOOK.value}."
            )


@dataclass
class ItemConfig(MarketItemCommonConfig):
    """This class defined options that can only be specified for items."""

    # the number of times that this item has been searched
    searched_count: int = 0

    # keywords is required, all others are optional
    search_phrases: List[str] = field(default_factory=list)
    keywords: List[str] | None = None
    antikeywords: List[str] | None = None
    description: str | None = None
    marketplace: str | None = None

    def handle_search_phrases(self: "ItemConfig") -> None:
        if isinstance(self.search_phrases, str):
            self.search_phrases = [self.search_phrases]

        if not isinstance(self.search_phrases, list) or not all(
            isinstance(x, str) for x in self.search_phrases
        ):
            raise ValueError(f"Item {hilight(self.name)} search_phrases must be a list.")
        if len(self.search_phrases) == 0:
            raise ValueError(f"Item {hilight(self.name)} search_phrases list is empty.")

    def handle_antikeywords(self: "ItemConfig") -> None:
        if self.antikeywords is None:
            return

        if isinstance(self.antikeywords, str):
            self.antikeywords = [self.antikeywords]

        if not isinstance(self.antikeywords, list) or not all(
            isinstance(x, str) for x in self.antikeywords
        ):
            raise ValueError(f"Item {hilight(self.name)} antikeywords must be a list of strings.")

    def handle_keywords(self: "ItemConfig") -> None:
        if self.keywords is None:
            return

        if isinstance(self.keywords, str):
            self.keywords = [self.keywords]

        if not isinstance(self.keywords, list) or not all(
            isinstance(x, str) for x in self.keywords
        ):
            raise ValueError(f"Item {hilight(self.name)} keywords must be a list.")

    def handle_description(self: "ItemConfig") -> None:
        if self.description is None:
            return
        if not isinstance(self.description, str):
            raise ValueError(f"Item {hilight(self.name)} description must be a string.")


TMarketplaceConfig = TypeVar("TMarketplaceConfig", bound=MarketplaceConfig)
TItemConfig = TypeVar("TItemConfig", bound=ItemConfig)


class Marketplace(Generic[TMarketplaceConfig, TItemConfig]):

    def __init__(
        self: "Marketplace",
        name: str,
        browser: Browser | None,
        keyboard_monitor: KeyboardMonitor | None = None,
        logger: Logger | None = None,
    ) -> None:
        self.name = name
        self.browser = browser
        self.keyboard_monitor = keyboard_monitor
        self.logger = logger
        self.page: Page | None = None

    @classmethod
    def get_config(cls: Type["Marketplace"], **kwargs: Any) -> TMarketplaceConfig:
        raise NotImplementedError("get_config method must be implemented by subclasses.")

    @classmethod
    def get_item_config(cls: Type["Marketplace"], **kwargs: Any) -> TItemConfig:
        raise NotImplementedError("get_config method must be implemented by subclasses.")

    def configure(self: "Marketplace", config: TMarketplaceConfig) -> None:
        self.config = config

    def set_browser(self: "Marketplace", browser: Browser | None = None) -> None:
        if browser is not None:
            self.browser = browser
            self.page = None

    def stop(self: "Marketplace") -> None:
        if self.browser is not None:
            # stop closing the browser since Ctrl-C will kill playwright,
            # leaving browser in a dysfunctional status.
            # see
            #   https://github.com/microsoft/playwright-python/issues/1170
            # for details.
            # self.browser.close()
            self.browser = None
            self.page = None

    def goto_url(self: "Marketplace", url: str, attempt: int = 0) -> None:
        try:
            assert self.page is not None
            self.page.goto(url, timeout=0)
            self.page.wait_for_load_state("domcontentloaded")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if attempt == 10:
                raise RuntimeError(f"Failed to navigate to {url} after 10 attempts. {e}") from e
            time.sleep(5)
            self.goto_url(url, attempt + 1)

    def search(self: "Marketplace", item: TItemConfig) -> Generator[Listing, None, None]:
        raise NotImplementedError("Search method must be implemented by subclasses.")
