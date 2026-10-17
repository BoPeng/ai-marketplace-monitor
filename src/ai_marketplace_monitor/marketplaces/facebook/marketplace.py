"""Facebook Marketplace: login, search, listings and sellers in aimm's browser."""

import json
import os
import re
import tempfile
import time
from itertools import repeat
from logging import Logger
from typing import TYPE_CHECKING, Any, List, Tuple, Type, cast
from urllib.parse import quote, urlparse, urlsplit

from currency_converter import CurrencyConverter  # type: ignore

from ...control import control
from ...evaluations import (
    EvaluationRecord,
    update_evaluation,
)
from ...listing import Listing
from ...seller import (
    Seller,
)
from ...shared_browser import search_slot
from ...utils import (
    CounterItem,
    KeyboardMonitor,
    aimm_event,
    amm_home,
    counter,
    hilight,
)
from ..base import (
    ItemConfig,
    Marketplace,
    SearchPage,
    resolve_option,
)

if TYPE_CHECKING:
    from playwright.sync_api import (  # type: ignore
        Browser,
        BrowserContext,
        Page,
        StorageState,
    )


from ..base import DateListed, DeliveryMethod, SortBy
from .config import (
    SORT_BY_PARAM,
    Availability,
    Category,
    FacebookItemConfig,
    FacebookMarketplaceConfig,
)
from .pages import (
    FacebookLocationDialog,
    FacebookSearchResultPage,
    FacebookSellerProfilePage,
    listing_state,
    nearest_radius,
    parse_listing,
    radius_from_label,
)

# pages Facebook shows instead of the one asked for, until the user logs in
LOGIN_PATHS = ("/login", "/checkpoint", "/two_step_verification", "/recover")
LOGIN_CHECK_EVERY = 5  # seconds
LOGIN_REMINDER_EVERY = 5 * 60  # seconds
# added to the reminders: users found that a login approved on the phone ends repeated CAPTCHAs
LOGIN_TWO_FACTOR_TIP = (
    "If Facebook keeps asking for a CAPTCHA, turn on two-factor authentication for your "
    "Facebook account (Accounts Center, Password and security): Facebook then asks you to "
    "confirm the login on your phone, which users found ends the repeated CAPTCHAs."
)
# the browser state of the last login, so that a restart does not log in again: Facebook
# asks for a CAPTCHA or to approve the login on each new login. It is a live session,
# readable only by the user, like the password in the config.
SESSION_FILE = amm_home / "facebook-session.json"
# seconds between listing pages when checking their status, as between search results
STATUS_CHECK_DELAY = 5


class FacebookMarketplace(Marketplace):
    initial_url = "https://www.facebook.com/login/device-based/regular/login/"
    home_url = "https://www.facebook.com/"

    market_type = "facebook"

    @classmethod
    def listing_url(cls: Type["FacebookMarketplace"], listing_id: str) -> str:
        return f"https://www.facebook.com/marketplace/item/{listing_id}/"

    @classmethod
    def listing_id(cls: Type["FacebookMarketplace"], listing: str) -> str:
        """The listing id of a Facebook Marketplace item URL or of an id, or '' if there is none."""
        listing = listing.strip()
        if listing.isdigit():
            return listing
        url = urlsplit(listing if "://" in listing else f"https://{listing}")
        host = (url.hostname or "").lower()
        if url.scheme not in ("http", "https") or not (
            host == "facebook.com" or host.endswith(".facebook.com")
        ):
            return ""
        match = re.fullmatch(r"/marketplace/item/(\d+)/?", url.path)
        return match.group(1) if match else ""

    @classmethod
    def seller_url(cls: Type["FacebookMarketplace"], seller_id: str) -> str:
        return f"https://www.facebook.com/marketplace/profile/{seller_id}/"

    def __init__(
        self: "FacebookMarketplace",
        name: str,
        browser: "Browser | BrowserContext | None",
        keyboard_monitor: KeyboardMonitor | None = None,
        logger: Logger | None = None,
    ) -> None:
        # name is the section's: [marketplace.mymarket] can be a Facebook marketplace
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
        if self.resume_session():
            return

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
        self.save_session()

    def resume_session(self: "FacebookMarketplace") -> bool:
        """Whether the session saved by a previous run is still logged in.

        Its ``c_user`` cookie can outlive a session that Facebook has ended, so a page that
        requires the login tells.
        """
        assert self.page is not None
        cookies = self.page.context.cookies("https://www.facebook.com")
        if not any(c.get("name") == "c_user" for c in cookies):
            return False
        self.goto_url(self.home_url)
        if not self.logged_in() or self.page.query_selector('input[name="pass"]') is not None:
            if self.logger:
                self.logger.info(
                    f"""{hilight("[Login]", "info")} The saved Facebook session has ended, logging in again."""
                )
            return False
        if self.logger:
            self.logger.info(
                f"""{hilight("[Login]", "succ")} Logged in to Facebook with the saved session."""
            )
        self.save_session()  # with the cookies Facebook has renewed
        return True

    def saved_session(self: "FacebookMarketplace") -> "StorageState | None":
        """The browser state saved by the last login with this account."""
        try:
            saved = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as e:
            if self.logger:
                self.logger.warning(
                    f"""{hilight("[Login]", "fail")} The saved Facebook session {SESSION_FILE} cannot be read ({e}), logging in again."""
                )
            self.discard_session()
            return None
        if (
            not isinstance(saved, dict)
            or saved.get("username") != self.config.username
            or not isinstance(saved.get("storage_state"), dict)
        ):
            return None  # another account's: replaced after this login
        return cast("StorageState", saved["storage_state"])

    def save_session(self: "FacebookMarketplace") -> None:
        """Save the browser state of this login for the next run, readable only by the user."""
        assert self.page is not None
        tmp = None
        try:
            state = self.page.context.storage_state()
            # a new file of a unique name, created with mode 0600, never one planted there
            fd, tmp = tempfile.mkstemp(dir=SESSION_FILE.parent, prefix=SESSION_FILE.name)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"username": self.config.username, "storage_state": state}, f)
            os.replace(tmp, SESSION_FILE)  # another aimm never reads half a file
        except Exception as e:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
            if self.logger:
                self.logger.warning(
                    f"""{hilight("[Login]", "fail")} Could not save the Facebook session: {e}"""
                )

    def discard_session(self: "FacebookMarketplace") -> None:
        try:
            SESSION_FILE.unlink(missing_ok=True)
        except OSError:
            pass

    def has_login_cookie(self: "FacebookMarketplace", context: "BrowserContext") -> bool:
        return any(c.get("name") == "c_user" for c in context.cookies("https://www.facebook.com"))

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
                    # the login is taking long: suggest what helps with repeated CAPTCHAs
                    control.login_hint = f"{self.login_hint()} {LOGIN_TWO_FACTOR_TIP}"
                    message = f"""{hilight("[Login]", "fail")} {control.login_hint}"""
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
        self.save_session()
        return True

    def set_search_radius(self: "FacebookMarketplace", radius: int) -> bool:
        """Set the radius saved on the Facebook account to the choice nearest ``radius``.

        Facebook ignores a radius in the search URL and searches with the radius saved on the
        account, which only its location dialog changes. ``radius`` is in the unit Facebook
        shows (miles in the US). True if the radius was changed, so the search must be
        reloaded; False if it already matched or could not be set.
        """
        assert self.page is not None
        dialog = FacebookLocationDialog(self.page, self.translator, self.logger)
        try:
            current = dialog.current_radius()
            if current is not None and current == nearest_radius(radius):
                return False
            dialog.open()
            chosen = dialog.choose_radius(radius)
            if radius_from_label(chosen) == current:
                dialog.close()
                return False
            dialog.apply()
            if self.logger:
                self.logger.info(
                    f"""{hilight("[Search]", "info")} Set the search radius to {chosen}"""
                    + (
                        f" (closest to radius={radius})"
                        if radius_from_label(chosen) != radius
                        else ""
                    )
                )
            return True
        except KeyboardInterrupt:
            raise
        except Exception as e:
            if self.logger:
                self.logger.warning(
                    f"""{hilight("[Search]", "fail")} Could not set the search radius to {radius}, searching with the radius saved on the Facebook account: {e}"""
                )
            dialog.close()
            return False

    def search_pages(
        self: "FacebookMarketplace", item_config: FacebookItemConfig
    ) -> List[SearchPage]:
        """The search pages of an item, one per city and search phrase, in search order.

        The options follow the item's first search or later ones (``searched_count``), as the
        search does.
        """
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
        pages: List[SearchPage] = []
        for city, cname, radius, currency in zip(
            search_city,
            repeat(None) if city_name is None else city_name,
            repeat(None) if radiuses is None else radiuses,
            repeat(None) if currencies is None else currencies,
        ):
            marketplace_url = f"https://www.facebook.com/marketplace/{city}/search?"
            # the options of this city: prices and category follow the shared ones. Facebook
            # ignores a radius in the URL; set_search_radius sets it in the location dialog.
            city_options = list(options)

            max_price = resolve_option("max_price", item_config, self.config)
            if max_price:
                if max_price.isdigit():
                    city_options.append(f"maxPrice={max_price}")
                else:
                    price, cur = max_price.split(" ", 1)
                    if currency and cur != currency:
                        c = CurrencyConverter()
                        price = str(int(c.convert(int(price), cur, currency)))
                        if self.logger:
                            self.logger.debug(
                                f"""{hilight("[Search]", "info")} Converting price {max_price} {cur} to {price} {currency}"""
                            )
                    city_options.append(f"maxPrice={price}")

            min_price = resolve_option("min_price", item_config, self.config)
            if min_price:
                if min_price.isdigit():
                    city_options.append(f"minPrice={min_price}")
                else:
                    price, cur = min_price.split(" ", 1)
                    if currency and cur != currency:
                        c = CurrencyConverter()
                        price = str(int(c.convert(int(price), cur, currency)))
                        if self.logger:
                            self.logger.debug(
                                f"""{hilight("[Search]", "info")} Converting price {max_price} {cur} to {price} {currency}"""
                            )
                    city_options.append(f"minPrice={price}")

            category = resolve_option("category", item_config, self.config)
            if category:
                city_options.append(f"category={category}")
                if category == Category.FREE_STUFF.value or category == Category.FREE.value:
                    # find min_price= and max_price= in options and remove them
                    city_options = [
                        x
                        for x in city_options
                        if not x.startswith("minPrice=") and not x.startswith("maxPrice=")
                    ]

            for search_phrase in item_config.search_phrases:
                pages.append(
                    SearchPage(
                        city=city,
                        city_name=cname,
                        radius=radius,
                        phrase=search_phrase,
                        url=marketplace_url
                        + "&".join([f"query={quote(search_phrase)}", *city_options]),
                    )
                )
        return pages

    def read_search_page(self: "FacebookMarketplace", search: SearchPage) -> List[Listing]:
        """Open a search page, with the item's radius, and read the listings it shows.

        The radius update, the reload and the reading happen in one ``search_slot``, so that
        another search in this process cannot change the account's radius in between.
        """
        assert self.page is not None
        with search_slot(self.navigation_wait):
            self.goto_url(search.url)
            if search.radius and self.set_search_radius(search.radius):
                self.goto_url(search.url)  # the results follow a new radius after a reload
            found_listings = FacebookSearchResultPage(
                self.page, self.translator, self.logger
            ).get_listings()
            if not found_listings and self.recover_login():
                self.goto_url(search.url)
                if search.radius and self.set_search_radius(search.radius):
                    self.goto_url(search.url)
                found_listings = FacebookSearchResultPage(
                    self.page, self.translator, self.logger
                ).get_listings()
            return found_listings

    def prepare_search(self: "FacebookMarketplace") -> None:
        if not self.page:
            self.login()
            assert self.page is not None

    def read_seller_profile(
        self: "FacebookMarketplace", seller_id: str, item_config: ItemConfig | None = None
    ) -> Seller:
        """Open the seller's Marketplace profile and read it."""
        if self.page is None:
            self.login()
        assert self.page is not None
        self.goto_url(self.seller_url(seller_id))
        if item_config is not None:
            counter.increment(CounterItem.LISTING_QUERY, item_config.name)
        return FacebookSellerProfilePage(self.page, self.translator, self.logger).parse(seller_id)

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
            and details.seller_parsed
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
