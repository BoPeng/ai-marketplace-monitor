import datetime
import os
import re
import time
from dataclasses import asdict, dataclass
from enum import Enum
from itertools import repeat
from logging import Logger
from typing import TYPE_CHECKING, Any, Generator, List, Tuple, Type, cast
from urllib.parse import quote, urlparse

from currency_converter import CurrencyConverter  # type: ignore
from rich.pretty import pretty_repr

from .control import control
from .evaluations import (
    AVAILABLE,
    EXCLUDED,
    PENDING,
    SOLD,
    EvaluationRecord,
    record_evaluation,
    record_seen,
    update_evaluation,
)
from .listing import Listing
from .marketplace import (
    Fallback,
    ItemConfig,
    Marketplace,
    MarketplaceConfig,
    WebPage,
    option,
    resolve_option,
)
from .seller import (
    MIN_RATINGS_FOR_RATING,
    Seller,
    count_listing_tiles,
    parse_seller_panel,
    parse_seller_profile,
    seller_id_from_url,
    seller_warnings,
)
from .utils import (
    BaseConfig,
    CounterItem,
    KeyboardMonitor,
    Translator,
    aimm_event,
    convert_to_seconds,
    counter,
    extract_price,
    hilight,
    is_substring,
)

if TYPE_CHECKING:
    from playwright.sync_api import Browser, ElementHandle, Page  # type: ignore


# pages Facebook shows instead of the one asked for, until the user logs in
LOGIN_PATHS = ("/login", "/checkpoint", "/two_step_verification", "/recover")
LOGIN_CHECK_EVERY = 5  # seconds
LOGIN_REMINDER_EVERY = 5 * 60  # seconds
# seconds between listing pages when checking their status, as between search results
STATUS_CHECK_DELAY = 5


def listing_state(title: str, translator: Translator | None = None) -> Tuple[str, str]:
    """The state a listing page's title shows, and the title without it.

    Facebook puts "Sold" or "Pending" before the title of such a listing:
    ``"Sold · 2018 Honda accord"``.
    """
    t = translator or Translator()
    for state, label in ((SOLD, t("Sold")), (PENDING, t("Pending"))):
        matched = re.match(rf"\s*{re.escape(label)}[\s\xa0]*·\s*(.*)$", title, re.DOTALL)
        if matched:
            return state, matched.group(1).strip()
    return AVAILABLE, title


class Condition(Enum):
    NEW = "new"
    USED_LIKE_NEW = "used_like_new"
    USED_GOOD = "used_good"
    USED_FAIR = "used_fair"


class DateListed(Enum):
    ANYTIME = 0
    PAST_24_HOURS = 1
    PAST_WEEK = 7
    PAST_MONTH = 30


class DeliveryMethod(Enum):
    LOCAL_PICK_UP = "local_pick_up"
    SHIPPING = "shipping"
    ALL = "all"


class Availability(Enum):
    ALL = "all"
    INSTOCK = "in"
    OUTSTOCK = "out"


class Category(Enum):
    VEHICLES = "vehicles"
    PROPERTY_RENTALS = "propertyrentals"
    APPAREL = "apparel"
    ELECTRONICS = "electronics"
    ENTERTAINMENT = "entertainment"
    FAMILY = "family"
    FREE_STUFF = "freestuff"
    FREE = "free"
    GARDEN = "garden"
    HOBBIES = "hobbies"
    HOME_GOODS = "homegoods"
    HOME_IMPROVEMENT = "homeimprovement"
    HOME_SALES = "homesales"
    MUSICAL_INSTRUMENTS = "musicalinstruments"
    OFFICE_SUPPLIES = "officesupplies"
    PET_SUPPLIES = "petsupplies"
    SPORTING_GOODS = "sportinggoods"
    TICKETS = "tickets"
    TOYS = "toys"
    VIDEO_GAMES = "videogames"


class SortBy(Enum):
    SUGGESTED = "suggested"
    NEW = "new"
    PRICE_ASCEND = "price_ascend"
    PRICE_DESCEND = "price_descend"
    DISTANCE_ASCEND = "distance_ascend"


# facebook's `sortBy` query values, keyed by the accepted config value. `suggested`
# is the marketplace default and is expressed by omitting the parameter altogether.
SORT_BY_PARAM = {
    SortBy.NEW.value: "creation_time_descend",
    SortBy.PRICE_ASCEND.value: "price_ascend",
    SortBy.PRICE_DESCEND.value: "price_descend",
    SortBy.DISTANCE_ASCEND.value: "distance_ascend",
}


_FACEBOOK_INLINE_STYLE_RE = re.compile(r"\.[A-Za-z0-9_-]+\{[^{}]*inline-size:[^{}]*\}")
_FACEBOOK_AD_BLOCK_RE = re.compile(
    r"(?:^|\s)Ads\s*" + _FACEBOOK_INLINE_STYLE_RE.pattern + r".*$",
    re.IGNORECASE | re.DOTALL,
)


def _clean_facebook_description(text: str) -> str:
    """Remove Facebook-injected ad/video text from listing descriptions."""
    text = text.replace("\xa0", " ").strip()
    text = _FACEBOOK_AD_BLOCK_RE.sub("", text)
    text = _FACEBOOK_INLINE_STYLE_RE.sub(" ", text)
    text = text.replace("Sorry, we're having trouble playing this video.", " ")
    text = text.replace("Learn more", " ")
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


@dataclass
class FacebookMarketItemCommonConfig(BaseConfig):
    """Item options that can be defined in marketplace

    This class defines and processes options that can be specified
    in both marketplace and item sections, specific to facebook marketplace
    """

    seller_locations: List[str] | None = option(Fallback.NOT_NONE)
    availability: List[str] | None = option(Fallback.TRUTHY)
    condition: List[str] | None = option(Fallback.TRUTHY)
    date_listed: List[int] | None = option(Fallback.TRUTHY)
    delivery_method: List[str] | None = option(Fallback.TRUTHY)
    category: str | None = option(Fallback.TRUTHY)
    sort_by: str | None = option(Fallback.TRUTHY)
    # seller information: whether to open seller profiles, and a minimal seller rating
    seller_profile: bool | None = option(Fallback.NOT_NONE)
    seller_min_rating: float | None = option(Fallback.NOT_NONE)

    def handle_seller_profile(self: "FacebookMarketItemCommonConfig") -> None:
        if self.seller_profile is not None and not isinstance(self.seller_profile, bool):
            raise ValueError(f"Item {hilight(self.name)} seller_profile must be true or false.")

    def handle_seller_min_rating(self: "FacebookMarketItemCommonConfig") -> None:
        value = self.seller_min_rating
        if value is None:
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 5:
            raise ValueError(
                f"Item {hilight(self.name)} seller_min_rating must be a number from 0 to 5."
            )
        self.seller_min_rating = float(value)

    def handle_seller_locations(self: "FacebookMarketItemCommonConfig") -> None:
        if self.seller_locations is None:
            return

        if isinstance(self.seller_locations, str):
            self.seller_locations = [self.seller_locations]
        if not isinstance(self.seller_locations, list) or not all(
            isinstance(x, str) for x in self.seller_locations
        ):
            raise ValueError(f"Item {hilight(self.name)} seller_locations must be a list.")

    def handle_availability(self: "FacebookMarketItemCommonConfig") -> None:
        if self.availability is None:
            return

        if isinstance(self.availability, str):
            self.availability = [self.availability]
        if not all(val in [x.value for x in Availability] for val in self.availability):
            raise ValueError(
                f"Item {hilight(self.name)} availability must be one or two values of 'all', 'in', and 'out'."
            )
        if len(self.availability) > 2:
            raise ValueError(
                f"Item {hilight(self.name)} availability must be one or two values of 'all', 'in', and 'out'."
            )

    def handle_condition(self: "FacebookMarketItemCommonConfig") -> None:
        if self.condition is None:
            return
        if isinstance(self.condition, Condition):
            self.condition = [self.condition]
        if not isinstance(self.condition, list) or not all(
            isinstance(x, str) and x in [cond.value for cond in Condition] for x in self.condition
        ):
            raise ValueError(
                f"Item {hilight(self.name)} condition must be one or more of that can be one of 'new', 'used_like_new', 'used_good', 'used_fair'."
            )

    def handle_date_listed(self: "FacebookMarketItemCommonConfig") -> None:
        if self.date_listed is None:
            return
        if not isinstance(self.date_listed, list):
            self.date_listed = [self.date_listed]
        #
        new_values: List[int] = []
        for val in self.date_listed:
            if isinstance(val, str):
                if val.isdigit():
                    new_values.append(int(val))
                elif val.lower() == "all":
                    new_values.append(DateListed.ANYTIME.value)
                elif val.lower() == "last 24 hours":
                    new_values.append(DateListed.PAST_24_HOURS.value)
                elif val.lower() == "last 7 days":
                    new_values.append(DateListed.PAST_WEEK.value)
                elif val.lower() == "last 30 days":
                    new_values.append(DateListed.PAST_MONTH.value)
                else:
                    raise ValueError(
                        f"""Item {hilight(self.name)} date_listed must be one of 1, 7, and 30, or All, Last 24 hours, Last 7 days, Last 30 days.: {self.date_listed} provided."""
                    )
            elif isinstance(val, (int, float)):
                if int(val) not in [x.value for x in DateListed]:
                    raise ValueError(
                        f"""Item {hilight(self.name)} date_listed must be one of 1, 7, and 30, or All, Last 24 hours, Last 7 days, Last 30 days.: {self.date_listed} provided."""
                    )
                new_values.append(int(val))
            else:
                raise ValueError(
                    f"""Item {hilight(self.name)} date_listed must be one of 1, 7, and 30, or All, Last 24 hours, Last 7 days, Last 30 days.: {self.date_listed} provided."""
                )
        # new_values should have length 1 or 2
        if len(new_values) > 2:
            raise ValueError(
                f"""Item {hilight(self.name)} date_listed must have one or two values."""
            )
        self.date_listed = new_values

    def handle_delivery_method(self: "FacebookMarketItemCommonConfig") -> None:
        if self.delivery_method is None:
            return

        if isinstance(self.delivery_method, str):
            self.delivery_method = [self.delivery_method]

        if len(self.delivery_method) > 2:
            raise ValueError(
                f"Item {hilight(self.name)} delivery_method must be one or two values of 'local_pick_up' and 'shipping'."
            )

        if not isinstance(self.delivery_method, list) or not all(
            val in [x.value for x in DeliveryMethod] for val in self.delivery_method
        ):
            raise ValueError(
                f"Item {hilight(self.name)} delivery_method must be one of 'local_pick_up' and 'shipping'."
            )

    def handle_category(self: "FacebookMarketItemCommonConfig") -> None:
        if self.category is None:
            return

        if not isinstance(self.category, str) or self.category not in [x.value for x in Category]:
            raise ValueError(
                f"Item {hilight(self.name)} category must be one of {', '.join(x.value for x in Category)}."
            )

    def handle_sort_by(self: "FacebookMarketItemCommonConfig") -> None:
        if self.sort_by is None:
            return

        if not isinstance(self.sort_by, str) or self.sort_by not in [x.value for x in SortBy]:
            raise ValueError(
                f"Item {hilight(self.name)} sort_by must be one of {', '.join(x.value for x in SortBy)}."
            )


@dataclass
class FacebookMarketplaceConfig(MarketplaceConfig, FacebookMarketItemCommonConfig):
    """Options specific to facebook marketplace

    This class defines and processes options that can be specified
    in the marketplace.facebook section only. None of the options are required.
    """

    login_wait_time: int | None = None  # deprecated and ignored: aimm waits for the login
    password: str | None = None
    username: str | None = None

    def handle_username(self: "FacebookMarketplaceConfig") -> None:
        if self.username is None:
            self.username = os.environ.get("FACEBOOK_USERNAME")
        if self.username is None:
            return

        if not isinstance(self.username, str):
            raise ValueError(f"Marketplace {self.name} username must be a string.")

    def handle_password(self: "FacebookMarketplaceConfig") -> None:
        if self.password is None:
            self.password = os.environ.get("FACEBOOK_PASSWORD")
        if self.password is None:
            return

        if not isinstance(self.password, str):
            raise ValueError(f"Marketplace {self.name} password must be a string.")

    def handle_login_wait_time(self: "FacebookMarketplaceConfig") -> None:
        if self.login_wait_time is None:
            return
        if isinstance(self.login_wait_time, str):
            try:
                self.login_wait_time = convert_to_seconds(self.login_wait_time)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                raise ValueError(
                    f"Marketplace {self.name} login_wait_time {self.login_wait_time} is not recognized."
                ) from e
        if not isinstance(self.login_wait_time, int) or self.login_wait_time < 0:
            raise ValueError(
                f"Marketplace {self.name} login_wait_time should be a non-negative number."
            )


@dataclass
class FacebookItemConfig(ItemConfig, FacebookMarketItemCommonConfig):
    pass


class FacebookMarketplace(Marketplace):
    initial_url = "https://www.facebook.com/login/device-based/regular/login/"

    name = "facebook"

    def __init__(
        self: "FacebookMarketplace",
        name: str,
        browser: "Browser | None",
        keyboard_monitor: KeyboardMonitor | None = None,
        logger: Logger | None = None,
    ) -> None:
        assert name == self.name
        super().__init__(name, browser, keyboard_monitor, logger)
        self.page: Page | None = None

    @classmethod
    def get_config(cls: Type["FacebookMarketplace"], **kwargs: Any) -> FacebookMarketplaceConfig:
        return FacebookMarketplaceConfig(**kwargs)

    @classmethod
    def get_item_config(cls: Type["FacebookMarketplace"], **kwargs: Any) -> FacebookItemConfig:
        return FacebookItemConfig(**kwargs)

    def login(self: "FacebookMarketplace") -> None:
        assert self.browser is not None

        self.page = self.create_page(swap_proxy=True)

        # Navigate to the URL, no timeout
        self.goto_url(self.initial_url)

        if self.logger:
            self.logger.debug("[Login] Checking for cookie consent pop-up...")
        try:
            allow_button_locator = self.page.get_by_role(
                "button",
                name=re.compile(r"Allow all cookies|Allow cookies|Accept All", re.IGNORECASE),
            )

            if allow_button_locator.is_visible():
                allow_button_locator.click()
                self.page.wait_for_timeout(2000)  # 2 seconds
                if self.logger:
                    self.logger.debug(
                        f"""{hilight("[Login]", "succ")} Allow all cookies' button clicked."""
                    )
            elif self.logger:
                self.logger.debug(
                    f"{hilight('[Login]', 'succ')} Cookie consent pop-up not found or not visible within timeout."
                )
        except Exception as e:
            if self.logger:
                self.logger.warning(
                    f"{hilight('[Login]', 'fail')} Could not handle cookie pop-up (or it was not present): {e!s}"
                )

        self.config: FacebookMarketplaceConfig
        try:
            if self.config.username:
                time.sleep(2)
                selector = self.page.wait_for_selector('input[name="email"]')
                if selector is not None:
                    selector.type(self.config.username, delay=250)
            if self.config.password:
                time.sleep(2)
                selector = self.page.wait_for_selector('input[name="pass"]')
                if selector is not None:
                    selector.type(self.config.password, delay=250)
            if self.config.username and self.config.password:
                time.sleep(2)
                # Facebook removed the <button name="login"> — press Enter to submit the form
                self.page.keyboard.press("Enter")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.error(f"""{hilight("[Login]", "fail")} {e}""")

        if self.config.login_wait_time is not None and self.logger:
            self.logger.warning(
                f"""{hilight("[Login]", "fail")} login_wait_time is deprecated and ignored: aimm """
                "now waits until the Facebook login has finished. Remove it from "
                f"[marketplace.{self.config.name}]."
            )
        # Facebook may ask for a CAPTCHA or a code first, which can take a while
        self.wait_for_login()

    def on_login_page(self: "FacebookMarketplace") -> bool:
        """Whether Facebook is showing a login, CAPTCHA or verification page."""
        assert self.page is not None
        path = urlparse(self.page.url).path
        return any(part in path for part in LOGIN_PATHS)

    def logged_in(self: "FacebookMarketplace") -> bool:
        assert self.page is not None
        cookies = self.page.context.cookies("https://www.facebook.com")
        return any(c.get("name") == "c_user" for c in cookies) and not self.on_login_page()

    def wait_for_login(self: "FacebookMarketplace") -> None:
        """Wait, however long it takes, until the user has finished logging in to Facebook.

        Searching with a half-finished login only gets more pages redirected to the login page.
        """
        if self.logged_in():
            return
        control.login_hint = self.login_hint()
        message = f"""{hilight("[Login]", "fail")} {control.login_hint}"""
        if self.logger:
            self.logger.warning(message, extra=aimm_event("credentials_wait", status="waiting"))
        control.waiting_for_login = True
        try:
            reminded = time.monotonic()
            while not self.logged_in():
                assert self.page is not None
                self.page.wait_for_timeout(LOGIN_CHECK_EVERY * 1000)
                if time.monotonic() - reminded > LOGIN_REMINDER_EVERY:
                    reminded = time.monotonic()
                    if self.logger:
                        self.logger.warning(
                            message, extra=aimm_event("credentials_wait", status="waiting")
                        )
        finally:
            control.waiting_for_login = False
        if self.logger:
            self.logger.info(
                f"""{hilight("[Login]", "succ")} Logged in to Facebook.""",
                extra=aimm_event("credentials_wait", status="found"),
            )

    def login_hint(self: "FacebookMarketplace") -> str:
        """Where the user finishes logging in: it depends on where aimm runs."""
        waiting = (
            "Waiting for you to finish logging in to Facebook: aimm entered your username and "
            "password, and Facebook may ask for a CAPTCHA or a security code. "
        )
        if os.environ.get("AIMM_DOCKER") == "1":
            return (
                waiting + "Click Open browser in the web UI (or Browser in its header) and "
                "complete it there. Searches start once you are logged in."
            )
        return (
            waiting + "Complete it in the browser window aimm opened. Searches start once you "
            "are logged in."
        )

    def recover_login(self: "FacebookMarketplace") -> bool:
        """After a page failed: if Facebook logged aimm out, wait for the login; True to retry."""
        if self.page is None or not self.on_login_page():
            return False
        if self.logger:
            self.logger.warning(
                f"""{hilight("[Login]", "fail")} Facebook redirected to its login page."""
            )
        self.wait_for_login()
        return True

    def search(
        self: "FacebookMarketplace", item_config: FacebookItemConfig
    ) -> Generator[Listing, None, None]:
        if not self.page:
            self.login()
            assert self.page is not None

        options = []

        condition = resolve_option("condition", item_config, self.config)
        if condition:
            options.append(f"itemCondition={'%2C'.join(condition)}")

        # availability can take values from item_config, or marketplace config and will
        # use the first or second value depending on how many times the item has been searched.
        date_listed_values = resolve_option("date_listed", item_config, self.config)
        date_listed = (
            date_listed_values[0 if item_config.searched_count == 0 else -1]
            if date_listed_values
            else DateListed.ANYTIME.value
        )
        if date_listed is not None and date_listed != DateListed.ANYTIME.value:
            options.append(f"daysSinceListed={date_listed}")

        # delivery_method can take values from item_config, or marketplace config and will
        # use the first or second value depending on how many times the item has been searched.
        delivery_values = resolve_option("delivery_method", item_config, self.config)
        delivery_method = (
            delivery_values[0 if item_config.searched_count == 0 else -1]
            if delivery_values
            else DeliveryMethod.ALL.value
        )
        if delivery_method is not None and delivery_method != DeliveryMethod.ALL.value:
            options.append(f"deliveryMethod={delivery_method}")

        # availability can take values from item_config, or marketplace config and will
        # use the first or second value depending on how many times the item has been searched.
        availability_values = resolve_option("availability", item_config, self.config)
        availability = (
            availability_values[0 if item_config.searched_count == 0 else -1]
            if availability_values
            else Availability.ALL.value
        )
        if availability is not None and availability != Availability.ALL.value:
            options.append(f"availability={availability}")

        # sort order does not depend on the search city, so it is appended once here.
        # `suggested` is facebook's default and needs no parameter.
        sort_by = resolve_option("sort_by", item_config, self.config)
        if sort_by and sort_by != SortBy.SUGGESTED.value:
            options.append(f"sortBy={SORT_BY_PARAM[sort_by]}")

        # search multiple keywords and cities
        # there is a small chance that search by different keywords and city will return the same items.
        found = {}
        search_city = resolve_option("search_city", item_config, self.config) or []
        city_name = resolve_option("city_name", item_config, self.config) or []
        radiuses = resolve_option("radius", item_config, self.config)
        currencies = resolve_option("currency", item_config, self.config)

        # this should not happen because `Config.validate_items` has checked this
        if not search_city:
            if self.logger:
                self.logger.error(
                    f"""{hilight("[Search]", "fail")} No search city provided for {item_config.name}"""
                )
        # increase the searched_count to differentiate first and subsequent searches
        item_config.searched_count += 1
        for city, cname, radius, currency in zip(
            search_city,
            repeat(None) if city_name is None else city_name,
            repeat(None) if radiuses is None else radiuses,
            repeat(None) if currencies is None else currencies,
        ):
            marketplace_url = f"https://www.facebook.com/marketplace/{city}/search?"

            if radius:
                # avoid specifying radius more than once
                if options and options[-1].startswith("radius"):
                    options.pop()
                options.append(f"radius={radius}")

            max_price = resolve_option("max_price", item_config, self.config)
            if max_price:
                if max_price.isdigit():
                    options.append(f"maxPrice={max_price}")
                else:
                    price, cur = max_price.split(" ", 1)
                    if currency and cur != currency:
                        c = CurrencyConverter()
                        price = str(int(c.convert(int(price), cur, currency)))
                        if self.logger:
                            self.logger.debug(
                                f"""{hilight("[Search]", "info")} Converting price {max_price} {cur} to {price} {currency}"""
                            )
                    options.append(f"maxPrice={price}")

            min_price = resolve_option("min_price", item_config, self.config)
            if min_price:
                if min_price.isdigit():
                    options.append(f"minPrice={min_price}")
                else:
                    price, cur = min_price.split(" ", 1)
                    if currency and cur != currency:
                        c = CurrencyConverter()
                        price = str(int(c.convert(int(price), cur, currency)))
                        if self.logger:
                            self.logger.debug(
                                f"""{hilight("[Search]", "info")} Converting price {max_price} {cur} to {price} {currency}"""
                            )
                    options.append(f"minPrice={price}")

            category = resolve_option("category", item_config, self.config)
            if category:
                options.append(f"category={category}")
                if category == Category.FREE_STUFF.value or category == Category.FREE.value:
                    # find min_price= and max_price= in options and remove them
                    options = [
                        x
                        for x in options
                        if not x.startswith("minPrice=") and not x.startswith("maxPrice=")
                    ]

            for search_phrase in item_config.search_phrases:
                if self.logger:
                    self.logger.info(
                        f"""{hilight("[Search]", "info")} Searching {item_config.marketplace} for """
                        f"""{hilight(item_config.name)} from {hilight(cname or city)}"""
                        + (f" with radius={radius}" if radius else " with default radius")
                    )

                if control.is_paused():
                    return
                search_url = marketplace_url + "&".join(
                    [f"query={quote(search_phrase)}", *options]
                )
                self.goto_url(search_url)

                found_listings = FacebookSearchResultPage(
                    self.page, self.translator, self.logger
                ).get_listings()
                if not found_listings and self.recover_login():
                    self.goto_url(search_url)
                    found_listings = FacebookSearchResultPage(
                        self.page, self.translator, self.logger
                    ).get_listings()
                time.sleep(5)
                if not found_listings and self.logger:
                    self.logger.warning(
                        f"""{hilight("[Search]", "fail")} No search results for {search_phrase} from {city}"""
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
                    record_seen("facebook", listing.id, item_config.name, listing.price)
                    # filter by title and location; skip keyword filtering since we do not have description yet.
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
                            time.sleep(5)
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
                        yield listing

    def get_listing_details(
        self: "FacebookMarketplace",
        post_url: str,
        item_config: ItemConfig,
        price: str | None = None,
        title: str | None = None,
    ) -> Tuple[Listing, bool]:
        assert post_url.startswith("https://www.facebook.com")
        details = Listing.from_cache(post_url)
        if (
            details is not None
            and (price is None or details.price == price)
            and (title is None or details.title == title)
        ):
            # if the price and title are the same, we assume everything else is unchanged.
            return details, True

        if not self.page:
            self.login()

        assert self.page is not None
        self.goto_url(post_url)
        counter.increment(CounterItem.LISTING_QUERY, item_config.name)
        details = parse_listing(self.page, post_url, self.translator, self.logger)
        if details is None and self.recover_login():
            self.goto_url(post_url)
            details = parse_listing(self.page, post_url, self.translator, self.logger)
        if details is None and self.on_login_page():
            raise ValueError(f"Facebook showed its login page instead of listing {post_url}.")
        if details is None:
            raise ValueError(
                f"Failed to get item details of listing {post_url}. "
                "The listing might be missing key information (e.g. seller) or not in English."
                "Please add option language to your marketplace configuration is the latter is the case. See https://github.com/BoPeng/ai-marketplace-monitor?tab=readme-ov-file#support-for-non-english-languages for details."
            )
        details.to_cache(post_url)
        return details, False

    def add_seller_info(
        self: "FacebookMarketplace", listing: Listing, item_config: FacebookItemConfig
    ) -> None:
        """Complete what the listing page showed about the seller, and list warning signs.

        The seller's profile (active and sold listings) is opened only for listings that
        passed the other filters, and at most once a week per seller (see Seller.to_cache).
        """
        if not listing.seller_id:
            return
        seller = Seller.from_cache(listing.seller_id) or Seller(id=listing.seller_id)
        seller.update(Seller(**(listing.seller_info.get("seller") or {"id": listing.seller_id})))
        if (
            resolve_option("seller_profile", item_config, self.config) is not False
            and not seller.profile_checked
        ):
            try:
                assert self.page is not None
                self.goto_url(f"https://www.facebook.com/marketplace/profile/{seller.id}/")
                counter.increment(CounterItem.LISTING_QUERY, item_config.name)
                profile = FacebookSellerProfilePage(self.page, self.translator, self.logger).parse(
                    seller.id
                )
                seller.update(profile)
                seller.profile_checked = True
                time.sleep(5)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                if self.logger:
                    self.logger.debug(
                        f"""{hilight("[Retrieve]", "fail")} Could not read the profile of seller {seller.id}: {e}"""
                    )
        seller.to_cache()
        warnings = seller_warnings(seller)
        listing.seller_info = {
            "seller": asdict(seller),
            "summary": seller.summary(),
            "warnings": warnings,
        }
        if warnings and self.logger:
            self.logger.info(
                f"""{hilight("[Seller]", "fail")} {hilight(listing.title)} is sold by {listing.seller}: {"; ".join(warnings)}"""
            )

    def check_listing(
        self: "FacebookMarketplace",
        item: Listing,
        item_config: FacebookItemConfig,
        description_available: bool = True,
    ) -> bool:
        return self.exclusion_reason(item, item_config, description_available) is None

    def exclusion_reason(
        self: "FacebookMarketplace",
        item: Listing,
        item_config: FacebookItemConfig,
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
        self: "FacebookMarketplace", records: List[EvaluationRecord], as_of: float | None = None
    ) -> int:
        """Open each listing's page and record whether it is sold, pending or available.

        ``as_of`` is the cutoff of the digest the check is for: a change found after it is
        dated at the cutoff, so that it is reported in that digest rather than the next one.

        Nothing is opened before the browser has a page (no search has run yet). A page
        that cannot be read leaves the record as it was.
        """
        if self.page is None:
            return 0
        read = 0
        opened = 0
        for record in records:
            if control.is_paused() or (
                self.keyboard_monitor is not None and self.keyboard_monitor.is_paused()
            ):
                break
            if opened:
                time.sleep(STATUS_CHECK_DELAY)
            opened += 1
            try:
                self.goto_url(record.url)
                details = parse_listing(self.page, record.url, self.translator, self.logger)
                if details is None and self.recover_login():
                    self.goto_url(record.url)
                    details = parse_listing(self.page, record.url, self.translator, self.logger)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                if self.logger:
                    self.logger.debug(f"{hilight('[Status]', 'fail')} {record.url}: {e}")
                continue
            if details is None:
                if self.logger:
                    self.logger.debug(
                        f"{hilight('[Status]', 'fail')} Could not read {record.url}; keeping its status."
                    )
                continue
            state, _ = listing_state(details.title, self.translator)
            now = time.time()
            update_evaluation(
                record.marketplace,
                record.id,
                record.item,
                state=state,
                checked=now,
                now=now if as_of is None else min(now, as_of),
            )
            read += 1
            if self.logger:
                self.logger.info(f"""{hilight("[Status]", "info")} {record.title}: {state}""")
        return read

    def _exclude(
        self: "FacebookMarketplace",
        listing: Listing,
        item_config: FacebookItemConfig,
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


class FacebookSearchResultPage(WebPage):
    def _get_listings_elements_by_children_counts(self: "FacebookSearchResultPage"):
        parent: ElementHandle | None = self.page.locator("img").first.element_handle()
        # look for parent of parent until it has more than 10 children
        children = []
        while parent:
            children = parent.query_selector_all(":scope > *")
            if len(children) > 10:
                break
            parent = parent.query_selector("xpath=..")
        # find each listing
        valid_listings = []
        try:
            for listing in children:
                if not listing.text_content():
                    continue
                valid_listings.append(listing)
        except Exception as e:
            # this error should be tolerated
            if self.logger:
                self.logger.debug(
                    f"{hilight('[Retrieve]', 'fail')} Some grid item cannot be read: {e}"
                )
        return valid_listings

    def _get_listing_elements_by_traversing_header(self: "FacebookSearchResultPage"):
        heading = self.page.locator(
            f'[aria-label="{self.translator("Collection of Marketplace items")}"]'
        )
        if not heading:
            return []

        grid_items = heading.locator(
            ":scope > :first-child > :first-child > :nth-child(3) > :first-child > :nth-child(2) > div"
        )
        # find each listing
        valid_listings = []
        try:
            for listing in grid_items.all():
                if not listing.text_content():
                    continue
                valid_listings.append(listing.element_handle())
        except Exception as e:
            # this error should be tolerated
            if self.logger:
                self.logger.debug(
                    f"{hilight('[Retrieve]', 'fail')} Some grid item cannot be read: {e}"
                )
        return valid_listings

    def get_listings(self: "FacebookSearchResultPage") -> List[Listing]:
        # if no result is found
        btn = self.page.locator(f"""span:has-text('{self.translator("Browse Marketplace")}')""")
        if btn.count() > 0:
            if self.logger:
                msg = self._parent_with_cond(
                    btn.first,
                    lambda x: len(x) == 3
                    and self.translator("Browse Marketplace") in (x[-1].text_content() or ""),
                    1,
                )
                self.logger.info(f"{hilight('[Retrieve]', 'dim')} {msg}")
            return []

        # find the grid box
        try:
            valid_listings = (
                self._get_listing_elements_by_traversing_header()
                or self._get_listings_elements_by_children_counts()
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            filename = datetime.datetime.now().strftime("debug_%Y%m%d_%H%M%S.html")
            if self.logger:
                self.logger.error(
                    f"{hilight('[Retrieve]', 'fail')} failed to parse searching result. Page saved to {filename}: {e}"
                )
            with open(filename, "w", encoding="utf-8") as f:
                f.write(self.page.content())
            return []

        listings: List[Listing] = []
        for idx, listing in enumerate(valid_listings):
            try:
                atag = listing.query_selector(
                    ":scope > :first-child > :first-child > :first-child > :first-child > :first-child > :first-child > :first-child > :first-child"
                )
                if not atag:
                    continue
                post_url = atag.get_attribute("href") or ""
                details_divs = atag.query_selector_all(":scope > :first-child > div")
                if not details_divs:
                    continue
                details = details_divs[1]
                divs = details.query_selector_all(":scope > div")
                raw_price = "" if len(divs) < 1 else divs[0].text_content() or ""
                title = "" if len(divs) < 2 else divs[1].text_content() or ""
                # location can be empty in some rare cases
                location = "" if len(divs) < 3 else (divs[2].text_content() or "")

                # get image
                img = listing.query_selector("img")
                image = img.get_attribute("src") if img else ""
                price = extract_price(raw_price)

                if post_url.startswith("/"):
                    post_url = f"https://www.facebook.com{post_url}"

                if image.startswith("/"):
                    image = f"https://www.facebook.com{image}"

                listings.append(
                    Listing(
                        marketplace="facebook",
                        name="",
                        id=post_url.split("?")[0].rstrip("/").split("/")[-1],
                        title=title,
                        image=image,
                        price=price,
                        # all the ?referral_code&referral_sotry_type etc
                        # could be helpful for live navigation, but will be stripped
                        # for caching item details.
                        post_url=post_url,
                        location=location,
                        condition="",
                        seller="",
                        description="",
                    )
                )
            except KeyboardInterrupt:
                raise
            except Exception as e:
                if self.logger:
                    self.logger.error(
                        f"{hilight('[Retrieve]', 'fail')} Failed to parse search results {idx + 1} listing: {e}"
                    )
                continue
        return listings


_SELLER_PANEL_JS = """// the seller panel: the smallest element around one of the seller's links that also
// says when they joined
(joined) => {
    const links = [...document.querySelectorAll('a[href*="/marketplace/profile/"]')];
    if (!links.length) return null;
    let best = null, bestDepth = 99;
    for (const link of links) {
        let node = link;
        for (let depth = 0; depth < 25 && node; depth++, node = node.parentElement) {
            if ((node.innerText || "").includes(joined)) {
                if (depth < bestDepth) { best = node; bestDepth = depth; }
                break;
            }
        }
    }
    const scope = best || links[links.length - 1].parentElement;
    return {
        href: links[0].getAttribute("href") || "",
        text: scope ? scope.innerText : "",
        labels: scope ? [...scope.querySelectorAll("[aria-label]")].map(e => e.getAttribute("aria-label")) : [],
    };
}"""


class FacebookItemPage(WebPage):
    def verify_layout(self: "FacebookItemPage") -> bool:
        return True

    def get_title(self: "FacebookItemPage") -> str:
        raise NotImplementedError("get_title is not implemented for this page")

    def get_price(self: "FacebookItemPage") -> str:
        raise NotImplementedError("get_price is not implemented for this page")

    def get_image_url(self: "FacebookItemPage") -> str:
        raise NotImplementedError("get_image_url is not implemented for this page")

    def get_seller(self: "FacebookItemPage") -> str:
        raise NotImplementedError("get_seller is not implemented for this page")

    def get_description(self: "FacebookItemPage") -> str:
        raise NotImplementedError("get_description is not implemented for this page")

    def get_location(self: "FacebookItemPage") -> str:
        raise NotImplementedError("get_location is not implemented for this page")

    def get_condition(self: "FacebookItemPage") -> str:
        raise NotImplementedError("get_condition is not implemented for this page")

    def get_seller_info(self: "FacebookItemPage", name: str = "") -> Seller | None:
        """The seller as the page's "Seller information" panel shows them, if it does."""
        try:
            panel = self.page.evaluate(_SELLER_PANEL_JS, self.translator("Joined Facebook in"))
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} seller panel: {e}")
            return None
        if not panel:
            return None
        seller_id = seller_id_from_url(panel.get("href", ""))
        if not seller_id:
            return None
        return parse_seller_panel(
            panel.get("text") or "",
            [x for x in panel.get("labels") or [] if x],
            seller_id,
            name=name,
            translator=self.translator,
        )

    def _expand_see_more(self: "FacebookItemPage") -> None:
        """Click any 'See more' disclosure links to expand truncated descriptions."""
        try:
            see_more_buttons = self.page.locator(
                f'div[role="button"]:has(span:text("{self.translator("See more")}"))'
            )
            # wait briefly for "See more" buttons to appear in the DOM
            see_more_buttons.first.wait_for(state="visible", timeout=8000)
            for i in range(see_more_buttons.count()):
                see_more_buttons.nth(i).click(timeout=2000)
            # allow the DOM to update after clicking
            self.page.wait_for_timeout(500)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} See more expansion: {e}")

    def parse(self: "FacebookItemPage", post_url: str) -> Listing:
        if not self.verify_layout():
            raise ValueError("Layout mismatch")

        # expand any truncated description sections before extracting text
        self._expand_see_more()

        # title
        title = self.get_title()
        price = self.get_price()
        description = _clean_facebook_description(self.get_description())
        # strip disclosure button text left over after expanding "See more"
        for label in (self.translator("See more"), self.translator("See less")):
            description = description.replace(label, "").strip()

        if not title or not price:
            raise ValueError(f"Failed to parse {post_url}")

        if self.logger:
            self.logger.info(f"{hilight('[Retrieve]', 'succ')} Parsing {hilight(title)}")
        res = Listing(
            marketplace="facebook",
            name="",
            id=post_url.split("?")[0].rstrip("/").split("/")[-1],
            title=title,
            image=self.get_image_url(),
            price=extract_price(price),
            post_url=post_url,
            location=self.get_location(),
            condition=self.get_condition(),
            description=description,
            seller=self.get_seller(),
        )
        seller = self.get_seller_info(res.seller)
        if seller is not None:
            res.seller_id = seller.id
            res.seller_info = {"seller": asdict(seller)}
        if self.logger:
            self.logger.debug(f"{hilight('[Retrieve]', 'succ')} {pretty_repr(res)}")
        return cast(Listing, res)


class FacebookRegularItemPage(FacebookItemPage):
    def verify_layout(self: "FacebookRegularItemPage") -> bool:
        return any(
            self.translator("Condition") in (x.text_content() or "")
            for x in self.page.query_selector_all("li")
        )

    def get_title(self: "FacebookRegularItemPage") -> str:
        try:
            h1_element = self.page.query_selector_all("h1")[-1]
            return h1_element.text_content() or self.translator("**unspecified**")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_price(self: "FacebookRegularItemPage") -> str:
        try:
            price_element = self.page.locator("h1 + *")
            return price_element.text_content() or self.translator("**unspecified**")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_image_url(self: "FacebookRegularItemPage") -> str:
        try:
            image_url = self.page.locator("img").first.get_attribute("src") or ""
            return image_url
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_seller(self: "FacebookRegularItemPage") -> str:
        try:
            seller_locator = self.page.locator("//a[contains(@href, '/marketplace/profile')]")
            if seller_locator.count() == 0:
                # Try an alternative pattern — Facebook sometimes uses
                # different link structures for the seller name.
                seller_locator = self.page.locator("//a[contains(@href, '/profile')]")
            if seller_locator.count() == 0:
                return self.translator("**unspecified**")
            # Use a short timeout to avoid a 30s delay when seller data is not
            # present (e.g. in anonymous/not-logged-in mode). See #289.
            return seller_locator.last.text_content(timeout=3000) or self.translator(
                "**unspecified**"
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(
                    f"{hilight('[Retrieve]', 'fail')} get_seller failed: {type(e).__name__}: {e}"
                )
            return self.translator("**unspecified**")

    def get_description(self: "FacebookRegularItemPage") -> str:
        try:
            # Find the span with text "condition", then parent, then next...
            description_element = self.page.locator(
                f'span:text("{self.translator("Condition")}") >> xpath=ancestor::ul[1] >> xpath=following-sibling::*[1]'
            )
            return description_element.text_content() or self.translator("**unspecified**")
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_condition(self: "FacebookRegularItemPage") -> str:
        try:
            if self.logger:
                self.logger.debug(f"{hilight('[Debug]', 'info')} Getting condition info...")
            # Find the span with text "condition", then parent, then next...
            condition_text = self.translator("Condition")

            # Use .first property to avoid strict mode violation when multiple elements match
            # This handles cases where "Condition" appears in both the label and description text
            condition_locator = self.page.locator(f'span:text("{condition_text}")')
            condition_element = condition_locator.first

            result = self._parent_with_cond(
                condition_element,
                lambda x: len(x) >= 2
                and self.translator("Condition") in (x[0].text_content() or ""),
                1,
            )
            return result
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.error(
                    f"{hilight('[Error]', 'fail')} get_condition failed: {type(e).__name__}: {e}"
                )
            return ""

    def get_location(self: "FacebookRegularItemPage") -> str:
        try:
            # look for "Location is approximate", then find its neighbor
            approximate_element = self.page.locator(
                f'span:text("{self.translator("Location is approximate")}")'
            )
            return self._parent_with_cond(
                approximate_element,
                lambda x: len(x) == 2
                and self.translator("Location is approximate") in (x[1].text_content() or ""),
                0,
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""


class FacebookFlexItemPage(FacebookRegularItemPage):
    """Layout observed since mid-2026.

    The Details section renders Condition, condition value, and description in
    nested span/div structures instead of the previous ul/li lists. See #326.
    """

    def verify_layout(self: "FacebookFlexItemPage") -> bool:
        return (
            self.page.locator(f'span:text-is("{self.translator("Condition")}")').count() > 0
            and len(self.page.query_selector_all("h1")) > 0
        )

    def _condition_and_description(self: "FacebookFlexItemPage") -> List[str]:
        """Extract the condition value and description from the Details section.

        Climb from the Condition label; the first non-empty next-sibling text
        is the condition value, the second is the description. Some categories
        list more attributes after Condition (e.g. "Has Bluetooth: Yes"), in rows
        built like the Condition row; such siblings are skipped, so the
        description is the text that follows the block of attribute rows.
        """
        label = self.page.query_selector(f'span:text-is("{self.translator("Condition")}")')
        if label is None:
            return []
        return label.evaluate(
            """(el) => {
              const shape = (e) => e.tagName + '(' + [...e.children].map(shape).join(',') + ')';
              const hits = [];
              let n = el;
              for (let i = 0; i < 16 && n && hits.length < 2; i++) {
                let sib = n.nextElementSibling;
                if (hits.length) {
                  // after the condition: skip more attribute rows built like this one
                  const row = shape(n);
                  while (sib && shape(sib) === row) sib = sib.nextElementSibling;
                }
                const t = sib && sib.textContent ? sib.textContent.trim() : '';
                if (t) hits.push(t);
                n = n.parentElement;
              }
              return hits;
            }"""
        )

    def get_condition(self: "FacebookFlexItemPage") -> str:
        try:
            hits = self._condition_and_description()
            return hits[0] if hits else ""
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_description(self: "FacebookFlexItemPage") -> str:
        try:
            hits = self._condition_and_description()
            return hits[1] if len(hits) > 1 else ""
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_location(self: "FacebookFlexItemPage") -> str:
        try:
            phrase = self.translator("Location is approximate")
            label = self.page.query_selector(f'span:text("{phrase}")')
            if label is None:
                return ""
            text = label.evaluate(
                """(el, phrase) => {
                  let n = el;
                  for (let i = 0; i < 10 && n; i++) {
                    const t = (n.textContent || '').trim();
                    if (t.split(phrase).join('').split('\\u00b7').join('').trim()) return t;
                    n = n.parentElement;
                  }
                  return '';
                }""",
                phrase,
            )
            return text.replace(phrase, "").replace("·", "").strip()
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""


class FacebookRentalItemPage(FacebookRegularItemPage):
    def verify_layout(self: "FacebookRentalItemPage") -> bool:
        # there is a header h2 with text Description
        return any(
            self.translator("Description") in (x.text_content() or "")
            for x in self.page.query_selector_all("h2")
        )

    def get_description(self: "FacebookRentalItemPage") -> str:
        # some pages do not have a condition box and appears to have a "Description" header
        # See https://github.com/BoPeng/ai-marketplace-monitor/issues/29 for details.
        try:
            description_header = self.page.query_selector(
                f'h2:has(span:text("{self.translator("Description")}"))'
            )
            return self._parent_with_cond(
                description_header,
                lambda x: len(x) > 1 and x[0].text_content() == self.translator("Description"),
                1,
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_condition(self: "FacebookRentalItemPage") -> str:
        # no condition information for rental items
        return self.translator("**unspecified**")


_VEHICLE_EMOJI_PATTERNS = [
    ("Driven", "🚗"),
    ("transmission", "⚙️"),
    ("color", "🎨"),
    ("safety rating", "⭐"),
    ("NHTSA", "⭐"),
    ("Fuel type", "⛽"),
    ("MPG", "⛽"),
    ("owner", "👤"),
    ("paid off", "💰"),
    ("Clean title", "✅"),
    ("no significant damage", "✅"),
    ("Salvage", "⚠️"),
    ("accident", "⚠️"),
]


def _add_vehicle_emojis(text: str) -> str:
    """Prepend emoji indicators to known vehicle attribute lines."""
    lines = text.split("\n")
    result = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        emoji = ""
        for pattern, icon in _VEHICLE_EMOJI_PATTERNS:
            if pattern.lower() in stripped.lower():
                emoji = icon + " "
                break
        result.append(emoji + stripped)
    return "\n".join(result)


class FacebookAutoItemWithAboutAndDescriptionPage(FacebookRegularItemPage):
    def _has_about_this_vehicle(self: "FacebookAutoItemWithAboutAndDescriptionPage") -> bool:
        return any(
            self.translator("About this vehicle") in (x.text_content() or "")
            for x in self.page.query_selector_all("h2")
        )

    def _has_seller_description(self: "FacebookAutoItemWithAboutAndDescriptionPage") -> bool:
        return any(
            self.translator("Seller's description") in (x.text_content() or "")
            for x in self.page.query_selector_all("h2")
        )

    def _get_about_this_vehicle(self: "FacebookAutoItemWithAboutAndDescriptionPage") -> str:
        try:
            about_element = self.page.locator(
                f'h2:has(span:text("{self.translator("About this vehicle")}"))'
            )
            return self._parent_with_cond(
                # start from About this vehicle
                about_element,
                # find an array of elements with the first one being "About this vehicle"
                # and the second child has actual content (not just whitespace)
                lambda x: len(x) > 1
                and self.translator("About this vehicle") in (x[0].text_content() or "")
                and (x[1].text_content() or "").replace("\xa0", "").strip(),
                # Extract all texts, using inner_text to preserve line breaks, and add emojis
                lambda x: _add_vehicle_emojis(
                    "\n".join([child.inner_text() or "" for child in x])
                ),
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def _get_seller_description(self: "FacebookAutoItemWithAboutAndDescriptionPage") -> str:
        try:
            description_header = self.page.query_selector(
                f"""h2:has(span:text("{self.translator("Seller's description")}"))"""
            )

            return self._parent_with_cond(
                # start from the description header
                description_header,
                # find an array of elements with the first one being "Seller's description"
                # and the second child has actual content (not just whitespace)
                lambda x: len(x) > 1
                and self.translator("Seller's description") in (x[0].text_content() or "")
                and (x[1].text_content() or "").replace("\xa0", "").strip(),
                # then, drill down from the second child
                lambda x: self._children_with_cond(
                    x[1],
                    # find the an array of elements
                    lambda y: len(y) > 1,
                    # and return the texts.
                    lambda y: f"""\n\n{self.translator("Seller's description")}\n\n{y[0].text_content() or self.translator("**unspecified**")}""",
                ),
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def verify_layout(self: "FacebookAutoItemWithAboutAndDescriptionPage") -> bool:
        # there is a header h2 with text "About this vehicle"
        return self._has_about_this_vehicle() and self._has_seller_description()

    def get_description(self: "FacebookAutoItemWithAboutAndDescriptionPage") -> str:
        return self._get_about_this_vehicle() + self._get_seller_description()

    def get_price(self: "FacebookAutoItemWithAboutAndDescriptionPage") -> str:
        description = self.get_description()
        # using regular expression to find text that looks like price in the description
        price_pattern = r"\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?(?:,\d{2})?"
        match = re.search(price_pattern, description)
        return match.group(0) if match else self.translator("**unspecified**")

    def get_condition(self: "FacebookAutoItemWithAboutAndDescriptionPage") -> str:
        # no condition information for auto items
        return self.translator("**unspecified**")


class FacebookAutoItemWithDescriptionPage(FacebookAutoItemWithAboutAndDescriptionPage):
    def verify_layout(self: "FacebookAutoItemWithDescriptionPage") -> bool:
        return self._has_seller_description() and not self._has_about_this_vehicle()

    def get_description(self: "FacebookAutoItemWithDescriptionPage") -> str:
        try:
            description_header = self.page.query_selector(
                f"""h2:has(span:text("{self.translator("Seller's description")}"))"""
            )

            return self._parent_with_cond(
                # start from the description header
                description_header,
                # find an array of elements with the first one being "Seller's description"
                # and the second child has actual content (not just whitespace)
                lambda x: len(x) > 1
                and self.translator("Seller's description") in (x[0].text_content() or "")
                and (x[1].text_content() or "").replace("\xa0", "").strip(),
                # then, drill down from the second child
                lambda x: self._children_with_cond(
                    x[1],
                    # find the an array of elements
                    lambda y: len(y) > 2,
                    # and return the texts.
                    lambda y: f"""\n\n{self.translator("Seller's description")}\n\n{y[1].text_content() or self.translator("**unspecified**")}""",
                ),
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_condition(self: "FacebookAutoItemWithDescriptionPage") -> str:
        try:
            description_header = self.page.query_selector(
                f"""h2:has(span:text("{self.translator("Seller's description")}"))"""
            )

            res = self._parent_with_cond(
                # start from the description header
                description_header,
                # find an array of elements with the first one being "Seller's description"
                # and the second child has actual content (not just whitespace)
                lambda x: len(x) > 1
                and self.translator("Seller's description") in (x[0].text_content() or "")
                and (x[1].text_content() or "").replace("\xa0", "").strip(),
                # then, drill down from the second child
                lambda x: self._children_with_cond(
                    x[1],
                    # find the an array of elements
                    lambda y: len(y) > 2,
                    # and return the texts after seller's description.
                    lambda y: y[0].text_content() or self.translator("**unspecified**"),
                ),
            )
            if res.startswith(self.translator("Condition")):
                res = res[len(self.translator("Condition")) :]
            return res.strip()
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""

    def get_price(self: "FacebookAutoItemWithDescriptionPage") -> str:
        # for this page, price is after header
        try:
            h1_element = self.page.query_selector_all("h1")[-1]
            header = h1_element.text_content()
            return self._parent_with_cond(
                # start from the header
                h1_element,
                # find an array of elements with the first one being "Seller's description"
                lambda x: len(x) > 1 and header in (x[0].text_content() or ""),
                # then, find the element after header
                1,
            )
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} {e}")
            return ""


_SELLER_PROFILE_JS = """// the profile opens as a dialog over the Marketplace feed
(joined) => {
    const dialog = [...document.querySelectorAll('[role="dialog"]')].find(
        d => (d.innerText || "").includes(joined));
    if (!dialog) return null;
    return {
        text: dialog.innerText,
        labels: [...dialog.querySelectorAll("[aria-label]")].map(e => e.getAttribute("aria-label")),
    };
}"""


class FacebookSellerProfilePage(WebPage):
    """A seller's Marketplace profile, /marketplace/profile/<id>/."""

    def _read(self: "FacebookSellerProfilePage") -> dict | None:
        joined = self.translator("Joined Facebook in")
        for _ in range(10):
            content = self.page.evaluate(_SELLER_PROFILE_JS, joined)
            if content:
                return cast(dict, content)
            self.page.wait_for_timeout(1000)
        return None

    def get_sold_listings(self: "FacebookSellerProfilePage") -> int | None:
        """Switch the profile to its "Sold & out of stock" listings and count them."""
        try:
            self.page.get_by_role(
                "combobox", name=self.translator("Inventory availability status")
            ).click(timeout=5000)
            self.page.get_by_text(self.translator("Sold & out of stock"), exact=True).last.click(
                timeout=5000
            )
            self.page.wait_for_timeout(3000)
            content = self._read()
            if content is None:
                return None
            return count_listing_tiles([x for x in content.get("labels") or [] if x])
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.debug(f"{hilight('[Retrieve]', 'fail')} sold listings: {e}")
            return None

    def parse(self: "FacebookSellerProfilePage", seller_id: str) -> Seller:
        content = self._read()
        if content is None:
            raise ValueError(f"No seller profile found for {seller_id}")
        seller = parse_seller_profile(
            content.get("text") or "",
            [x for x in content.get("labels") or [] if x],
            seller_id,
            translator=self.translator,
        )
        if seller.active_listings:
            seller.sold_listings = self.get_sold_listings()
        if self.logger:
            self.logger.debug(f"{hilight('[Retrieve]', 'succ')} seller {pretty_repr(seller)}")
        return seller


def parse_listing(
    page: "Page", post_url: str, translator: Translator | None = None, logger: Logger | None = None
) -> Listing | None:
    supported_facebook_item_layouts = [
        FacebookRentalItemPage,
        FacebookAutoItemWithAboutAndDescriptionPage,
        FacebookAutoItemWithDescriptionPage,
        # the specific (ul/li) layout before the generic one: Flex also matches the older
        # pages, where it may pick up a wrong description; if Regular finds none, Flex is next
        FacebookRegularItemPage,
        FacebookFlexItemPage,
    ]

    # a layout that matches but fails to extract a description is kept only as a
    # fallback, so that a later layout that does extract the description is preferred
    fallback: Listing | None = None
    for page_model in supported_facebook_item_layouts:
        try:
            listing = page_model(page, translator, logger).parse(post_url)
        except KeyboardInterrupt:
            raise
        except Exception:
            # try next page ayout
            continue
        if listing.description:
            return listing
        if fallback is None:
            fallback = listing
    return fallback
