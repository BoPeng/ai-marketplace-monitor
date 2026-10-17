import time
from dataclasses import asdict, dataclass, field, fields
from enum import Enum
from functools import lru_cache
from logging import Logger
from types import MappingProxyType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ClassVar,
    Generator,
    Generic,
    List,
    Mapping,
    Tuple,
    Type,
    TypeVar,
    cast,
)

from ..control import control
from ..evaluations import EXCLUDED, EvaluationRecord, record_evaluation, record_seen
from ..listing import Listing
from ..seller import MIN_RATINGS_FOR_RATING, Seller, seller_status, seller_warnings
from ..shared_browser import BrowserBusyError, navigation_slot
from ..utils import (
    BaseConfig,
    CounterItem,
    Currency,
    KeyboardMonitor,
    MonitorConfig,
    Translator,
    convert_to_seconds,
    counter,
    hilight,
    is_substring,
)

if TYPE_CHECKING:
    from playwright.sync_api import (  # type: ignore
        Browser,
        BrowserContext,
        ElementHandle,
        Locator,
        Page,
        StorageState,
    )


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
    title_keywords: List[str] | None = None
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

    def handle_title_keywords(self: "ItemConfig") -> None:
        if self.title_keywords is None:
            return

        if isinstance(self.title_keywords, str):
            self.title_keywords = [self.title_keywords]

        if not isinstance(self.title_keywords, list) or not all(
            isinstance(x, str) for x in self.title_keywords
        ):
            raise ValueError(f"Item {hilight(self.name)} title_keywords must be a list.")

    def handle_description(self: "ItemConfig") -> None:
        if self.description is None:
            return
        if not isinstance(self.description, str):
            raise ValueError(f"Item {hilight(self.name)} description must be a string.")


TMarketplaceConfig = TypeVar("TMarketplaceConfig", bound=MarketplaceConfig)
TItemConfig = TypeVar("TItemConfig", bound=ItemConfig)


@dataclass
class SearchPage:
    """One search of an item: a phrase in a city, with its URL."""

    city: str
    city_name: str | None
    radius: int | None
    phrase: str
    url: str


class Marketplace(Generic[TMarketplaceConfig, TItemConfig]):
    # the market_type of the marketplace sections this class searches
    market_type: ClassVar[str] = ""
    # seconds to wait after a search page, a listing page and a seller's profile
    search_page_delay: ClassVar[float] = 5
    listing_page_delay: ClassVar[float] = 5
    profile_page_delay: ClassVar[float] = 5
    # whether searching needs aimm's browser; the monitor starts it only if an enabled
    # marketplace does (or when the web UI's browser view is opened). A marketplace that is
    # searched over HTTP sets False and is given no browser.
    needs_browser: ClassVar[bool] = True

    def __init__(
        self: "Marketplace",
        name: str,
        browser: "Browser | BrowserContext | None",
        keyboard_monitor: KeyboardMonitor | None = None,
        logger: Logger | None = None,
    ) -> None:
        self.name = name
        # a browser, or the shared browser's context (see shared_browser.py)
        self.browser = browser
        # page loads: 0 waits as long as it takes; the chat sets a limit, and fewer retries
        self.navigation_timeout_ms = 0
        self.navigation_retries = 10
        # seconds to wait for the shared browser's other user; None waits as long as it takes
        self.navigation_wait: float | None = None
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

    def set_browser(
        self: "Marketplace", browser: "Browser | BrowserContext | None" = None
    ) -> None:
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
            and not self.shared_context  # its proxy was set at launch
            and self.config.monitor_config is not None
            and isinstance(self.config.monitor_config.proxy_server, list)
            and len(self.config.monitor_config.proxy_server) > 1
        ):
            self.page.close()
            self.page = None

        if self.page is None and self.shared_context:
            self.page = self._shared_page()
        if self.page is None:
            proxy = (
                None
                if self.config.monitor_config is None
                else self.config.monitor_config.get_proxy_options()
            )
            session = self.saved_session()
            browser = cast("Browser", self.browser)
            try:
                context = browser.new_context(proxy=proxy, storage_state=session)
            except Exception as e:
                if session is None:
                    raise
                # the saved session is at fault only if the browser works without it
                context = browser.new_context(proxy=proxy)
                if self.logger:
                    self.logger.warning(
                        f"""{hilight("[Login]", "fail")} The saved {self.name} session cannot be used ({e}), logging in again."""
                    )
                self.discard_session()
            self.page = context.new_page()
        return self.page

    @property
    def shared_context(self: "Marketplace") -> bool:
        """Whether ``browser`` is the shared browser's context (see shared_browser.py)."""
        return self.browser is not None and not hasattr(self.browser, "new_context")

    def _shared_page(self: "Marketplace") -> "Page":
        """A page in the shared context, with the saved session's cookies if not logged in."""
        context = cast("BrowserContext", self.browser)
        session = self.saved_session()
        if session is not None and not self.has_login_cookie(context):
            try:
                context.add_cookies(cast(Any, session.get("cookies") or []))
            except Exception as e:
                if self.logger:
                    self.logger.warning(
                        f"""{hilight("[Login]", "fail")} The saved {self.name} session cannot be used ({e}), logging in again."""
                    )
                self.discard_session()
        # the window opens with a blank page: use it rather than open another
        for page in context.pages:
            if page.url == "about:blank":
                return page
        return context.new_page()

    def has_login_cookie(self: "Marketplace", context: "BrowserContext") -> bool:
        """Whether the context holds this marketplace's login cookie."""
        return False

    def saved_session(self: "Marketplace") -> "StorageState | None":
        """The browser state (cookies, local storage) saved by a previous login, if any."""
        return None

    def discard_session(self: "Marketplace") -> None:
        """Remove the saved session, which cannot be used."""

    def goto_url(self: "Marketplace", url: str, attempt: int = 0) -> None:
        try:
            assert self.page is not None
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'info')} Navigating to {url}")
            with navigation_slot(self.navigation_wait):
                self.page.goto(url, timeout=self.navigation_timeout_ms)
                self.page.wait_for_load_state("domcontentloaded")
        except (KeyboardInterrupt, BrowserBusyError):
            raise
        except Exception as e:
            if attempt >= self.navigation_retries:
                raise RuntimeError(
                    f"Failed to navigate to {url} after {attempt} attempts. {e}"
                ) from e
            time.sleep(5)
            self.goto_url(url, attempt + 1)

    def prepare_search(self: "Marketplace") -> None:
        """Get ready to search, e.g. log in; nothing by default."""

    def search_pages(self: "Marketplace", item_config: TItemConfig) -> List[SearchPage]:
        """The search pages of an item, in search order."""
        raise NotImplementedError("search_pages must be implemented by subclasses.")

    def read_search_page(self: "Marketplace", search: SearchPage) -> List[Listing]:
        """The listings a search page shows (title, price, location, link)."""
        raise NotImplementedError("read_search_page must be implemented by subclasses.")

    def get_listing_details(
        self: "Marketplace",
        post_url: str,
        item_config: TItemConfig,
        price: str | None = None,
        title: str | None = None,
    ) -> Tuple[Listing, bool]:
        """A listing's details, and whether they came from the cache."""
        raise NotImplementedError("get_listing_details must be implemented by subclasses.")

    def read_seller_profile(
        self: "Marketplace", seller_id: str, item_config: TItemConfig | None = None
    ) -> Seller:
        """What the seller's profile shows (counted as a listing query of ``item_config``)."""
        raise NotImplementedError("read_seller_profile must be implemented by subclasses.")

    @classmethod
    def listing_url(cls: Type["Marketplace"], listing_id: str) -> str:
        """The URL of a listing."""
        raise NotImplementedError("listing_url must be implemented by subclasses.")

    @classmethod
    def listing_id(cls: Type["Marketplace"], listing: str) -> str:
        """The listing id of a listing URL (or of an id), or '' if it is not one of ours."""
        return ""

    @classmethod
    def seller_url(cls: Type["Marketplace"], seller_id: str) -> str:
        """The URL of a seller's profile."""
        raise NotImplementedError("seller_url must be implemented by subclasses.")

    def search(self: "Marketplace", item_config: TItemConfig) -> Generator[Listing, None, None]:
        """Search for an item: its search pages, then each new listing that passes the filters.

        The same steps for every marketplace; each implements reading its own pages
        (``search_pages``, ``read_search_page``, ``get_listing_details``,
        ``read_seller_profile``).
        """
        self.prepare_search()
        pages = self.search_pages(item_config)
        # increase the searched_count to differentiate first and subsequent searches
        item_config.searched_count += 1
        # there is a small chance that search by different keywords and city will return the same items.
        found = {}
        for search in pages:
            if self.logger:
                self.logger.info(
                    f"""{hilight("[Search]", "info")} Searching {item_config.marketplace} for """
                    f"""{hilight(item_config.name)} from {hilight(search.city_name or search.city)}"""
                    + (
                        f" with radius={search.radius}"
                        if search.radius
                        else " with default radius"
                    )
                )

            if control.is_paused():
                return
            found_listings = self.read_search_page(search)
            time.sleep(self.search_page_delay)
            if not found_listings and self.logger:
                self.logger.warning(
                    f"""{hilight("[Search]", "fail")} No search results for {search.phrase} from {search.city}"""
                )

            counter.increment(CounterItem.SEARCH_PERFORMED, item_config.name)

            # go to each item and get the description
            # if we have not done that before
            for listing in found_listings:
                if listing.post_url.split("?")[0] in found:
                    continue
                if control.is_paused() or (
                    self.keyboard_monitor is not None and self.keyboard_monitor.is_paused()
                ):
                    return
                counter.increment(CounterItem.LISTING_EXAMINED, item_config.name)
                found[listing.post_url.split("?")[0]] = True
                # a listing aimm decided on before: still listed, maybe at a new price
                record_seen(self.market_type, listing.id, item_config.name, listing.price)
                # filter by title (title_keywords, antikeywords) and location before opening the
                # listing; keywords wait for the description.
                if self._exclude(listing, item_config, description_available=False):
                    continue
                try:
                    details, from_cache = self.get_listing_details(
                        listing.post_url,
                        item_config,
                        price=listing.price,
                        title=listing.title,
                    )
                    if not from_cache:
                        time.sleep(self.listing_page_delay)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    if self.logger:
                        self.logger.error(
                            f"""{hilight("[Retrieve]", "fail")} Failed to get item details: {e}"""
                        )
                    continue
                # currently we trust the other items from summary page a bit better
                # so we do not copy title, description etc from the detailed result
                for attr in ("condition", "seller", "description", "seller_id", "seller_info"):
                    # other attributes should be consistent
                    setattr(listing, attr, getattr(details, attr))
                listing.name = item_config.name
                if self.logger:
                    self.logger.debug(
                        f"""{hilight("[Retrieve]", "succ")} New item "{listing.title}" from {listing.post_url} is sold by "{listing.seller}" and with description "{listing.description[:100]}..." """
                    )

                # Warn if we never managed to extract a description for keyword-based filtering
                if (
                    (not listing.description or len(listing.description.strip()) == 0)
                    and item_config.keywords
                    and len(item_config.keywords) > 0
                    and self.logger
                ):
                    self.logger.debug(
                        f"""{hilight("[Error]", "fail")} Failed to extract description for {hilight(listing.title)} at {listing.post_url}. Keyword filtering will only apply to title."""
                    )

                if not self._exclude(listing, item_config):
                    self.add_seller_info(listing, item_config)
                    # the cached or profile rating may exclude the seller (seller_min_rating)
                    if not self._exclude(listing, item_config):
                        yield listing

    def add_seller_info(
        self: "Marketplace",
        listing: Listing,
        item_config: TItemConfig,
        refresh: bool = False,
    ) -> None:
        """Complete what the listing page showed about the seller, and list warning signs.

        The seller's profile (active and sold listings) is opened only for listings that
        passed the other filters, and at most once a month per seller (see Seller.to_cache),
        unless ``refresh`` asks to read it again.
        """
        if not listing.seller_id:
            return
        seller = Seller.from_cache(listing.seller_id) or Seller(id=listing.seller_id)
        seller.update(Seller(**(listing.seller_info.get("seller") or {"id": listing.seller_id})))
        if refresh or seller.needs_profile():
            try:
                profile = self.read_seller_profile(seller.id, item_config)
                seller.update(profile)
                seller.profile_checked = True
                seller.checked_at = time.time()
                time.sleep(self.profile_page_delay)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                if self.logger:
                    self.logger.info(
                        f"""{hilight("[Seller]", "fail")} Could not read the profile of seller {seller.id}, who is not verified: {e}"""
                    )
        seller.to_cache()
        warnings = seller_warnings(seller)
        listing.seller_info = {
            "seller": asdict(seller),
            "summary": seller.summary(),
            "warnings": warnings,
        }
        if self.logger:
            self.logger.info(
                f"""{hilight("[Seller]", "fail" if warnings or not seller.profile_checked else "succ")} {hilight(listing.title)}, seller {seller_status(listing.seller_info)}"""
            )

    def check_listing(
        self: "Marketplace",
        item: Listing,
        item_config: TItemConfig,
        description_available: bool = True,
    ) -> bool:
        return self.exclusion_reason(item, item_config, description_available) is None

    def exclusion_reason(
        self: "Marketplace",
        item: Listing,
        item_config: TItemConfig,
        description_available: bool = True,
    ) -> str | None:
        """Why the listing is excluded before the AI sees it, or None if it is not."""
        # get antikeywords from both item_config or config
        antikeywords = item_config.antikeywords
        text = item.title + " " + item.description
        if antikeywords and (is_substring(antikeywords, text, logger=self.logger)):
            if self.logger:
                self.logger.info(
                    f"""{hilight("[Skip]", "fail")} Exclude {hilight(item.title)} due to {hilight("excluded keywords", "fail")}: {", ".join(antikeywords)}"""
                )
            matched = [x for x in antikeywords if is_substring(x, text)] or antikeywords
            return f"excluded keyword: {', '.join(matched)}"

        # title_keywords need only the title, so they also apply before the listing is opened
        title_keywords = item_config.title_keywords
        if title_keywords and not is_substring(title_keywords, item.title, logger=self.logger):
            if self.logger:
                self.logger.info(
                    f"""{hilight("[Skip]", "fail")} Exclude {hilight(item.title)} {hilight("without required title keywords", "fail")}."""
                )
            return f"missing required title keywords: {', '.join(title_keywords)}"

        # if the return description does not contain any of the search keywords
        keywords = item_config.keywords
        if (
            description_available
            and keywords
            and not (
                is_substring(keywords, item.title + "  " + item.description, logger=self.logger)
            )
        ):
            if self.logger:
                self.logger.info(
                    f"""{hilight("[Skip]", "fail")} Exclude {hilight(item.title)} {hilight("without required keywords", "fail")} in title and description."""
                )
            return f"missing required keywords: {', '.join(keywords)}"

        # get locations from either marketplace config or item config
        allowed_locations = resolve_option("seller_locations", item_config, self.config) or []
        if allowed_locations and not is_substring(
            allowed_locations, item.location, logger=self.logger
        ):
            if self.logger:
                self.logger.info(
                    f"""{hilight("[Skip]", "fail")} Exclude {hilight("out of area", "fail")} item {hilight(item.title)} from location {hilight(item.location)}"""
                )
            return f"out of area: {item.location}"

        # get exclude_sellers from both item_config or config
        exclude_sellers = resolve_option("exclude_sellers", item_config, self.config) or []
        if (
            item.seller
            and exclude_sellers
            and is_substring(exclude_sellers, item.seller, logger=self.logger)
        ):
            if self.logger:
                self.logger.info(
                    f"""{hilight("[Skip]", "fail")} Exclude {hilight(item.title)} sold by {hilight("banned seller", "failed")} {hilight(item.seller)}"""
                )
            return f"banned seller: {item.seller}"

        # the listing page shows the seller's rating; one or two ratings are not held against them
        min_rating = resolve_option("seller_min_rating", item_config, self.config)
        seller = (item.seller_info or {}).get("seller") or {}
        rating, count = seller.get("rating"), seller.get("rating_count") or 0
        if (
            min_rating
            and rating is not None
            and count >= MIN_RATINGS_FOR_RATING
            and rating < min_rating
        ):
            if self.logger:
                self.logger.info(
                    f"""{hilight("[Skip]", "fail")} Exclude {hilight(item.title)} sold by {hilight(item.seller)}, {hilight("rated", "fail")} {rating:g} out of 5 by {count} buyers"""
                )
            return f"seller rated {rating:g} out of 5"

        return None

    def check_status(
        self: "Marketplace", records: List["EvaluationRecord"], as_of: float | None = None
    ) -> int:
        """Open the pages of these listings to update their status; the number read.

        A change found after ``as_of`` (a digest cutoff) is dated at it.

        Marketplaces that cannot tell whether a listing sold read none.
        """
        return 0

    def _exclude(
        self: "Marketplace",
        listing: Listing,
        item_config: TItemConfig,
        description_available: bool = True,
    ) -> bool:
        """Check the listing; record and count it if it is excluded."""
        reason = self.exclusion_reason(listing, item_config, description_available)
        if reason is None:
            return False
        counter.increment(CounterItem.EXCLUDED_LISTING, item_config.name)
        record_evaluation(
            EvaluationRecord.from_listing(
                listing, item=item_config.name, stage=EXCLUDED, reason=reason
            )
        )
        return True


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
