import time
from dataclasses import dataclass, field, fields
from enum import Enum
from functools import lru_cache
from logging import Logger
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generator,
    Generic,
    List,
    Mapping,
    Tuple,
    Type,
    TypeVar,
)

from .listing import Listing
from .utils import (
    BaseConfig,
    Currency,
    KeyboardMonitor,
    MonitorConfig,
    Translator,
    convert_to_seconds,
    hilight,
)

if TYPE_CHECKING:
    from playwright.sync_api import Browser, ElementHandle, Locator, Page  # type: ignore

    from .evaluations import EvaluationRecord


class MarketPlace(Enum):
    FACEBOOK = "facebook"


class Fallback(Enum):
    """How an item option falls back to the marketplace option."""

    TRUTHY = "truthy"  # item.x or marketplace.x
    NOT_NONE = "not_none"  # item.x if item.x is not None else marketplace.x
    ITEM_ONLY = "item_only"  # marketplace value ignored


# dataclass metadata keys for options shared by marketplaces and items
FALLBACK = "fallback"  # Fallback rule: how an item value falls back to the marketplace
ITEM_ONLY_IN = "item_only_in"  # use sites that read only the item value
LOCATION = "location"  # option belongs to the search_region / search_city group

# notify listings the AI rates at least this, unless `rating` is set
DEFAULT_RATING = 4


def option(
    fallback: Fallback | None,
    *,
    item_only_in: Tuple[str, ...] = (),
    location: bool = False,
) -> Any:
    """Declare a common option (default None) together with its fallback facts."""
    return field(
        default=None,
        metadata={FALLBACK: fallback, ITEM_ONLY_IN: item_only_in, LOCATION: location},
    )


@lru_cache(maxsize=None)
def option_fallbacks(cls: type) -> Mapping[str, Fallback]:
    """Fallback rule of every common option declared on a config class."""
    return MappingProxyType(
        {f.name: f.metadata[FALLBACK] for f in fields(cls) if f.metadata.get(FALLBACK)}
    )


@lru_cache(maxsize=None)
def site_fallbacks(cls: type) -> Mapping[Tuple[str, str], Fallback]:
    """Use sites whose rule deviates from the option's own fallback rule."""
    return MappingProxyType(
        {
            (site, f.name): Fallback.ITEM_ONLY
            for f in fields(cls)
            for site in f.metadata.get(ITEM_ONLY_IN, ())
        }
    )


@lru_cache(maxsize=None)
def location_keys(cls: type) -> Tuple[str, ...]:
    """Options that make up the search location (region, cities, radius, currency)."""
    return tuple(f.name for f in fields(cls) if f.metadata.get(LOCATION))


def resolve_option(key: str, item: Any, marketplace: Any, site: str = "search") -> Any:
    """Value of a common option for an item, falling back to its marketplace."""
    cls: Any = type(item)  # a dataclass type, hashable for the lru_cache lookups
    rule = site_fallbacks(cls).get((site, key), option_fallbacks(cls)[key])
    value = getattr(item, key)
    if rule is Fallback.ITEM_ONLY:
        return value
    if rule is Fallback.NOT_NONE:
        return value if value is not None else getattr(marketplace, key)
    return value or getattr(marketplace, key)


@dataclass
class MarketItemCommonConfig(BaseConfig):
    """Item options that can be specified in market (non-marketplace specifc)

    This class defines and processes options that can be specified
    in both marketplace and item sections, generic to all marketplaces
    """

    ai: List[str] | None = option(Fallback.NOT_NONE)
    exclude_sellers: List[str] | None = option(Fallback.NOT_NONE)
    notify: List[str] | None = option(Fallback.TRUTHY)
    search_city: List[str] | None = option(Fallback.TRUTHY, location=True)
    city_name: List[str] | None = option(Fallback.TRUTHY, location=True)
    # radius must be processed after search_city
    radius: List[int] | None = option(Fallback.TRUTHY, location=True)
    currency: List[str] | None = option(Fallback.TRUTHY, location=True)
    search_interval: int | None = option(Fallback.TRUTHY)
    max_search_interval: int | None = option(Fallback.TRUTHY)
    start_at: List[str] | None = option(Fallback.TRUTHY)
    # never resolved at runtime: Config.expand_regions turns it into the location keys
    search_region: List[str] | None = option(None, location=True)
    # the AI prompt reads prices from the item only
    max_price: str | None = option(Fallback.TRUTHY, item_only_in=("ai_prompt",))
    min_price: str | None = option(Fallback.TRUTHY, item_only_in=("ai_prompt",))
    rating: List[int] | None = option(Fallback.TRUTHY)
    prompt: str | None = option(Fallback.NOT_NONE)
    extra_prompt: str | None = option(Fallback.NOT_NONE)
    rating_prompt: str | None = option(Fallback.NOT_NONE)

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

        # Validate format of each search_city entry
        for city in self.search_city:
            # Check if the city contains only lowercase letters and numbers
            if not city.replace("_", "").replace("-", "").isalnum() or any(
                c.isupper() for c in city
            ):
                # Provide helpful guidance on obtaining the correct format
                raise ValueError(
                    f"Item {hilight(self.name)} search_city '{city}' has incorrect format.\n"
                    f"Expected: lowercase letters and numbers only (e.g., 'sanfrancisco', 'newyork', 'toronto').\n"
                    f"To get the correct value:\n"
                    f"  1. Visit Facebook Marketplace\n"
                    f"  2. Perform a search in your desired location\n"
                    f"  3. Look at the URL: https://www.facebook.com/marketplace/XXXXX/search?query=...\n"
                    f"  4. Use the XXXXX value (the text after 'marketplace/') as your search_city\n"
                    f"Example: If URL is https://www.facebook.com/marketplace/sanfrancisco/search?query=item\n"
                    f"         Then search_city = 'sanfrancisco'"
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

    def handle_currency(self: "MarketItemCommonConfig") -> None:
        if self.currency is None:
            return

        if self.search_city is None:
            raise ValueError(
                f"Item {hilight(self.name)} currency must be None if search_city is None."
            )

        if isinstance(self.currency, str):
            self.currency = [self.currency] * len(self.search_city)

        if not all(isinstance(x, str) for x in self.currency):
            raise ValueError(
                f"Item {hilight(self.name)} currency must be one or a list of strings."
            )

        for currency in self.currency:
            try:
                Currency(currency)
            except ValueError as e:
                raise ValueError(
                    f"Item {hilight(self.name)} currency {currency} is not recognized."
                ) from e

        if len(self.currency) != len(self.search_city):
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

        if isinstance(self.max_price, int):
            self.max_price = str(self.max_price)

        # the price should be a number followed by currency name (e.g. 100 USD)
        if not isinstance(self.max_price, str):
            raise ValueError(f"Item {hilight(self.name)} max_price must be a string.")

        if " " in self.max_price:
            price, currency = self.max_price.split(" ", 1)
            if not price.isdigit():
                raise ValueError(
                    f"Item {hilight(self.name)} max_price must be a number followed by currency name."
                )
            try:
                Currency(currency)
            except ValueError as e:
                raise ValueError(
                    f"Item {hilight(self.name)} max_price currency {currency} is not recognized."
                ) from e
        elif not self.max_price.isdigit():
            raise ValueError(
                f"Item {hilight(self.name)} max_price must be a number followed by currency name."
            )

    def handle_min_price(self: "MarketItemCommonConfig") -> None:
        if self.min_price is None:
            return

        if isinstance(self.min_price, int):
            self.min_price = str(self.min_price)

        # the price should be a number followed by currency name (e.g. 100 USD)
        if not isinstance(self.min_price, str):
            raise ValueError(f"Item {hilight(self.name)} min_price must be a string.")

        if " " in self.min_price:
            price, currency = self.min_price.split(" ", 1)
            if not price.isdigit():
                raise ValueError(
                    f"Item {hilight(self.name)} min_price must be a number followed by currency name."
                )
            try:
                Currency(currency)
            except ValueError as e:
                raise ValueError(
                    f"Item {hilight(self.name)} min_price currency {currency} is not recognized."
                ) from e
        elif not self.min_price.isdigit():
            raise ValueError(
                f"Item {hilight(self.name)} min_price must be a number followed by currency name."
            )

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
    language: str | None = None
    monitor_config: MonitorConfig | None = None

    def handle_market_type(self: "MarketplaceConfig") -> None:
        if self.market_type is None:
            return
        if not isinstance(self.market_type, str):
            raise ValueError(f"Marketplace {hilight(self.market_type)} market must be a string.")
        if self.market_type.lower() != MarketPlace.FACEBOOK.value:
            raise ValueError(
                f"Marketplace {hilight(self.market_type)} market must be {MarketPlace.FACEBOOK.value}."
            )

    def handle_language(self: "MarketplaceConfig") -> None:
        if self.language is None:
            return
        if not isinstance(self.language, str):
            raise ValueError(
                f"Marketplace {hilight(self.market_type)} language, if specified, must be a string."
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
        browser: "Browser | None",
        keyboard_monitor: KeyboardMonitor | None = None,
        logger: Logger | None = None,
    ) -> None:
        self.name = name
        self.browser = browser
        self.keyboard_monitor = keyboard_monitor
        self.translator = Translator()
        self.logger = logger
        self.page: Page | None = None

    @classmethod
    def get_config(cls: Type["Marketplace"], **kwargs: Any) -> TMarketplaceConfig:
        raise NotImplementedError("get_config method must be implemented by subclasses.")

    @classmethod
    def get_item_config(cls: Type["Marketplace"], **kwargs: Any) -> TItemConfig:
        raise NotImplementedError("get_config method must be implemented by subclasses.")

    def configure(
        self: "Marketplace", config: TMarketplaceConfig, translator: Translator | None = None
    ) -> None:
        self.config = config
        if translator is not None:
            self.translator = translator

    def set_browser(self: "Marketplace", browser: "Browser | None" = None) -> None:
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

    def create_page(self: "Marketplace", swap_proxy: bool = False) -> "Page":
        assert self.browser is not None

        # if there is an existing page, asked to swap_proxy, and there is an proxy_server
        # setting with multiple proxies
        if (
            self.page
            and swap_proxy
            and self.config.monitor_config is not None
            and isinstance(self.config.monitor_config.proxy_server, list)
            and len(self.config.monitor_config.proxy_server) > 1
        ):
            self.page.close()
            self.page = None

        if self.page is None:
            context = self.browser.new_context(
                proxy=(
                    None
                    if self.config.monitor_config is None
                    else self.config.monitor_config.get_proxy_options()
                )
            )
            self.page = context.new_page()
        return self.page

    def goto_url(self: "Marketplace", url: str, attempt: int = 0) -> None:
        try:
            assert self.page is not None
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'info')} Navigating to {url}")
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

    def check_status(self: "Marketplace", records: List["EvaluationRecord"]) -> int:
        """Open the pages of these listings to update their status; the number read.

        Marketplaces that cannot tell whether a listing sold read none.
        """
        return 0


class WebPage:
    def __init__(
        self: "WebPage",
        page: "Page",
        translator: Translator | None = None,
        logger: Logger | None = None,
    ) -> None:
        self.page = page
        self.translator: Translator = Translator() if translator is None else translator
        self.logger = logger

    def _parent_with_cond(
        self: "WebPage",
        element: "Locator | ElementHandle | None",
        cond: Callable,
        ret: Callable | int,
    ) -> str:
        """Finding a parent element

        Starting from `element`, finding its parents, until `cond` matches, then return the `ret`th children,
        or a callable.
        """
        if element is None:
            return ""
        # get up at the DOM level, testing the children elements with cond,
        # apply the res callable to return a string
        from playwright.sync_api import Locator  # type: ignore

        parent: ElementHandle | None = (
            element.element_handle() if isinstance(element, Locator) else element
        )
        # look for parent of approximate_element until it has two children and the first child is the heading
        while parent:
            children = parent.query_selector_all(":scope > *")
            if cond(children):
                if isinstance(ret, int):
                    return children[ret].text_content() or self.translator("**unspecified**")
                else:
                    return ret(children)
            parent = parent.query_selector("xpath=..")
        raise ValueError("Could not find parent element with condition.")

    def _children_with_cond(
        self: "WebPage",
        element: "Locator | ElementHandle | None",
        cond: Callable,
        ret: Callable | int,
    ) -> str:
        if element is None:
            return ""
        # Getting the children of an element, test condition, return the `index` or apply res
        from playwright.sync_api import Locator  # type: ignore

        # on the children element if the condition is met. Otherwise locate the first child and repeat the process.
        child: ElementHandle | None = (
            element.element_handle() if isinstance(element, Locator) else element
        )
        # look for parent of approximate_element until it has two children and the first child is the heading
        while child:
            children = child.query_selector_all(":scope > *")
            if cond(children):
                if isinstance(ret, int):
                    return children[ret].text_content() or self.translator("**unspecified**")
                return ret(children)
            if not children:
                raise ValueError("Could not find child element with condition.")
            # or we could use query_selector("./*[1]")
            child = children[0]
        raise ValueError("Could not find child element with condition.")
