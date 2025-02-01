import re
import time
from dataclasses import dataclass
from enum import Enum
from itertools import repeat
from logging import Logger
from typing import Any, Generator, List, Type, Union, cast
from urllib.parse import quote

import humanize
import rich
from bs4 import BeautifulSoup, element  # type: ignore
from playwright.sync_api import Browser, Page  # type: ignore
from rich.pretty import pretty_repr

from .item import SearchedItem
from .marketplace import ItemConfig, Marketplace, MarketplaceConfig
from .utils import (
    CacheType,
    DataClassWithHandleFunc,
    cache,
    convert_to_seconds,
    extract_price,
    hilight,
    is_substring,
)


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
    INSTOCK = "in"
    OUTSTOCK = "out"


@dataclass
class FacebookMarketItemCommonConfig(DataClassWithHandleFunc):
    """Item options that can be defined in marketplace

    This class defines and processes options that can be specified
    in both marketplace and item sections, specific to facebook marketplace
    """

    seller_locations: List[str] | None = None
    acceptable_locations: List[str] | None = None
    availability: str | None = None
    condition: List[str] | None = None
    date_listed: int | None = None
    delivery_method: str | None = None

    def handle_seller_locations(self: "FacebookMarketItemCommonConfig") -> None:
        if self.seller_locations is None:
            return

        if isinstance(self.seller_locations, str):
            self.seller_locations = [self.seller_locations]
        if not isinstance(self.seller_locations, list) or not all(
            isinstance(x, str) for x in self.seller_locations
        ):
            raise ValueError(f"Item {hilight(self.name)} seller_locations must be a list.")

    def handle_acceptable_locations(self: "FacebookMarketItemCommonConfig") -> None:
        if self.acceptable_locations is None:
            return

        rich.print(
            hilight(
                "Option acceptable_locations is renamed to seller_locations.",
                "fail",
            )
        )
        if self.seller_locations is None:
            self.seller_locations = self.acceptable_locations
            self.acceptable_locations = None

        self.handle_seller_locations()

    def handle_availability(self: "FacebookMarketItemCommonConfig") -> None:
        if self.availability is None:
            return
        if not isinstance(self.availability, str) or self.availability not in [
            x.value for x in Availability
        ]:
            raise ValueError(
                f"Item {hilight(self.name)} availability must be one of 'in' and 'out'."
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

        if self.date_listed == "All":
            self.date_listed = DateListed.ANYTIME.value
        elif self.date_listed == "Last 24 hours":
            self.date_listed = DateListed.PAST_24_HOURS.value
        elif self.date_listed == "Last 7 days":
            self.date_listed = DateListed.PAST_WEEK.value
        elif self.date_listed == "Last 30 days":
            self.date_listed = DateListed.PAST_MONTH.value

        if not isinstance(self.date_listed, int) or self.date_listed not in [
            x.value for x in DateListed
        ]:
            raise ValueError(
                f"""Item {hilight(self.name)} date_listed must be one of 1, 7, and 30, or All, Last 24 hours, Last 7 days, Last 30 days."""
            )

    def handle_delivery_method(self: "FacebookMarketItemCommonConfig") -> None:
        if self.delivery_method is None:
            return
        if not isinstance(self.delivery_method, str) or self.delivery_method not in [
            x.value for x in DeliveryMethod
        ]:
            raise ValueError(
                f"Item {hilight(self.name)} delivery_method must be one of 'local_pick_up' and 'shipping'."
            )


@dataclass
class FacebookMarketplaceConfig(MarketplaceConfig, FacebookMarketItemCommonConfig):
    """Options specific to facebook marketplace

    This class defines and processes options that can be specified
    in the marketplace.facebook section only. None of the options are required.
    """

    login_wait_time: int | None = None
    password: str | None = None
    username: str | None = None

    def handle_username(self: "FacebookMarketplaceConfig") -> None:
        if self.username is None:
            return
        if not isinstance(self.username, str):
            raise ValueError(f"Marketplace {self.name} username must be a string.")

    def handle_password(self: "FacebookMarketplaceConfig") -> None:
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
            except Exception as e:
                raise ValueError(
                    f"Marketplace {self.name} login_wait_time {self.login_wait_time} is not recognized."
                ) from e
        if not isinstance(self.login_wait_time, int) or self.login_wait_time < 10:
            raise ValueError(
                f"Marketplace {self.name} login_wait_time must be at least 10 second."
            )


@dataclass
class FacebookItemConfig(ItemConfig, FacebookMarketItemCommonConfig):
    pass


class FacebookMarketplace(Marketplace):
    initial_url = "https://www.facebook.com/login/device-based/regular/login/"

    name = "facebook"

    def __init__(
        self: "FacebookMarketplace", name: str, browser: Browser | None, logger: Logger
    ) -> None:
        assert name == self.name
        super().__init__(name, browser, logger)
        self.page: Page | None = None

    @classmethod
    def get_config(cls: Type["FacebookMarketplace"], **kwargs: Any) -> FacebookMarketplaceConfig:
        return FacebookMarketplaceConfig(**kwargs)

    @classmethod
    def get_item_config(cls: Type["FacebookMarketplace"], **kwargs: Any) -> FacebookItemConfig:
        return FacebookItemConfig(**kwargs)

    def login(self: "FacebookMarketplace") -> None:
        assert self.browser is not None
        context = self.browser.new_context(
            java_script_enabled=not self.disable_javascript
        )  # create a new incognite window
        self.page = context.new_page()
        assert self.page is not None
        # Navigate to the URL, no timeout
        self.page.goto(self.initial_url, timeout=0)
        self.page.wait_for_load_state("domcontentloaded")

        self.config: FacebookMarketplaceConfig
        try:
            if self.config.username is not None:
                selector = self.page.wait_for_selector('input[name="email"]')
                if selector is not None:
                    selector.fill(self.config.username)
                time.sleep(1)
            if self.config.password is not None:
                selector = self.page.wait_for_selector('input[name="pass"]')
                if selector is not None:
                    selector.fill(self.config.password)
                time.sleep(1)
            if self.config.username is not None and self.config.password is not None:
                selector = self.page.wait_for_selector('button[name="login"]')
                if selector is not None:
                    selector.click()
        except Exception as e:
            self.logger.error(f"An error occurred during logging: {e}")

        # in case there is a need to enter additional information
        login_wait_time = self.config.login_wait_time or 60
        self.logger.info(
            f"Logged into facebook, waiting {humanize.naturaldelta(login_wait_time)} to get ready."
        )
        time.sleep(login_wait_time)

    def search(
        self: "FacebookMarketplace", item_config: FacebookItemConfig
    ) -> Generator[SearchedItem, None, None]:
        if not self.page:
            self.login()
            assert self.page is not None

        options = []

        max_price = item_config.max_price or self.config.max_price
        if max_price:
            options.append(f"maxPrice={max_price}")

        min_price = item_config.min_price or self.config.min_price
        if min_price:
            options.append(f"minPrice={min_price}")

        condition = item_config.condition or self.config.condition
        if condition:
            options.append(f"itemCondition={'%2C'.join(condition)}")

        date_listed = item_config.date_listed or self.config.date_listed
        if date_listed and date_listed != DateListed.ANYTIME:
            options.append(f"daysSinceListed={date_listed}")

        delivery_method = item_config.delivery_method or self.config.delivery_method
        if delivery_method and delivery_method != DeliveryMethod.ALL:
            options.append(f"deliveryMethod={delivery_method}")

        availability = item_config.availability or self.config.availability
        if availability:
            options.append(f"availability={availability}")

        # search multiple keywords and cities
        # there is a small chance that search by different keywords and city will return the same items.
        found = {}
        search_city = item_config.search_city or self.config.search_city or []
        radiuses = item_config.radius or self.config.radius
        for city, radius in zip(search_city, repeat(None) if radiuses is None else radiuses):
            marketplace_url = f"https://www.facebook.com/marketplace/{city}/search?"

            if radius:
                # avoid specifying radius more than once
                if options and options[-1].startswith("radius"):
                    options.pop()
                options.append(f"radius={radius}")

            for keyword in item_config.keywords or []:
                self.goto_url(marketplace_url + "&".join([f"query={quote(keyword)}", *options]))

                found_items = FacebookSearchResultPage(
                    self.page.content(), self.logger
                ).get_listings()
                time.sleep(5)
                # go to each item and get the description
                # if we have not done that before
                for item in found_items:
                    if item.post_url in found:
                        continue
                    found[item.post_url] = True
                    # filter by title and location since we do not have description and seller yet.
                    if not self.filter_item(item, item_config):
                        continue
                    try:
                        details = self.get_item_details(f"https://www.facebook.com{item.post_url}")
                        time.sleep(5)
                    except Exception as e:
                        self.logger.error(f"Error getting item details: {e}")
                        continue
                    # currently we trust the other items from summary page a bit better
                    # so we do not copy title, description etc from the detailed result
                    item.description = details.description
                    item.seller = details.seller
                    item.name = item_config.name
                    self.logger.debug(
                        f"""New item "{item.title}" from https://www.facebook.com{item.post_url} is sold by "{item.seller}" and with description "{item.description[:100]}..." """
                    )
                    if self.filter_item(item, item_config):
                        yield item

    def get_item_details(self: "FacebookMarketplace", post_url: str) -> SearchedItem:
        details = cache.get((CacheType.ITEM_DETAILS.value, post_url.split("?")[0]))
        if details is not None:
            return details

        if not self.page:
            self.login()

        assert self.page is not None
        self.goto_url(post_url)
        details = FacebookItemPage(self.page.content(), self.logger).parse(post_url)
        cache.set(
            (CacheType.ITEM_DETAILS.value, post_url.split("?")[0]), details, tag="item_details"
        )
        return details

    def filter_item(
        self: "FacebookMarketplace", item: SearchedItem, item_config: FacebookItemConfig
    ) -> bool:
        # get exclude_keywords from both item_config or config
        exclude_keywords = item_config.exclude_keywords
        if exclude_keywords and is_substring(exclude_keywords, item.title):
            self.logger.info(
                f"""Exclude {hilight(item.title)} due to {hilight("excluded keywords", "fail")}: {', '.join(exclude_keywords)}"""
            )
            return False

        # if the return description does not contain any of the search keywords
        include_keywords = item_config.include_keywords
        if include_keywords and not is_substring(include_keywords, item.title):
            self.logger.info(
                f"""Exclude {hilight(item.title)} {hilight("without required keywords", "fail")} in title."""
            )
            return False

        # get locations from either marketplace config or item config
        if item_config.seller_locations is not None:
            allowed_locations = item_config.seller_locations
        else:
            allowed_locations = self.config.seller_locations or []
        if allowed_locations and not is_substring(allowed_locations, item.location):
            self.logger.info(
                f"""Exclude {hilight("out of area", "fail")} item {hilight(item.title)} from location {hilight(item.location)}"""
            )
            return False

        # get exclude_keywords from both item_config or config
        exclude_by_description = item_config.exclude_by_description or []
        if (
            item.description
            and exclude_by_description
            and is_substring(exclude_by_description, item.description)
        ):
            self.logger.info(
                f"""Exclude {hilight(item.title)} by {hilight("description", "fail")}.\n{hilight(item.description[:100])}..."""
            )
            return False

        # get exclude_sellers from both item_config or config
        if item_config.exclude_sellers is not None:
            exclude_sellers = item_config.exclude_sellers
        else:
            exclude_sellers = self.config.exclude_sellers or []
        if item.seller and exclude_sellers and is_substring(exclude_sellers, item.seller):
            self.logger.info(
                f"""Exclude {hilight(item.title)} sold by {hilight("banned seller", "failed")} {hilight(item.seller)}"""
            )
            return False

        return True


class WebPage:

    def __init__(self: "WebPage", html: str, logger: Logger) -> None:
        self.html = html
        self.soup = BeautifulSoup(self.html, "html.parser")
        self.logger = logger


class FacebookSearchResultPage(WebPage):

    def get_listings_from_structure(
        self: "FacebookSearchResultPage",
    ) -> List[Union[element.Tag, element.NavigableString]]:
        heading = self.soup.find(attrs={"aria-label": "Collection of Marketplace items"})
        child1 = next(heading.children)
        child2 = next(child1.children)
        grid_parent = list(child2.children)[2]  # groups of listings
        for group in grid_parent.children:
            grid_child2 = list(group.children)[1]  # the actual grid container
            return list(grid_child2.children)
        return []

    def get_listing_from_css(
        self: "FacebookSearchResultPage",
    ) -> List[Union[element.Tag, element.NavigableString]]:
        return self.soup.find_all(
            "div",
            class_="x9f619 x78zum5 x1r8uery xdt5ytf x1iyjqo2 xs83m0k x1e558r4 x150jy0e x1iorvi4 xjkvuk6 xnpuxes x291uyu x1uepa24",
        )

    def parse_listing(
        self: "FacebookSearchResultPage", listing: Union[element.Tag, element.NavigableString]
    ) -> SearchedItem | None:
        # if the element has no text (only image etc)
        if not listing.get_text().strip():
            return None

        child1 = next(listing.children)
        child2 = next(child1.children)
        child3 = next(child2.children)  # span class class="x1lliihq x1iyjqo2"
        child4 = next(child3.children)  # div
        child5 = next(child4.children)  # div class="x78zum5 xdt5ytf"
        child5 = next(child5.children)  # div class="x9f619 x1n2onr6 x1ja2u2z"
        child6 = next(child5.children)  # div class="x3ct3a4" (real data here)
        atag = next(child6.children)  # a tag
        post_url = atag["href"]
        atag_child1 = next(atag.children)
        atag_child2 = list(atag_child1.children)  # 2 divs here
        # Get the item image.
        image = listing.find("img")["src"]

        details = list(
            atag_child2[1].children
        )  # x9f619 x78zum5 xdt5ytf x1qughib x1rdy4ex xz9dl7a xsag5q8 xh8yej3 xp0eagm x1nrcals
        # There are 4 divs in 'details', in this order: price, title, location, distance
        price = extract_price(details[0].contents[-1].text)

        title = details[1].contents[-1].text
        location = details[2].contents[-1].text

        # Append the parsed data to the list.
        return SearchedItem(
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
            seller="",
            description="",
        )

    def get_listings(self: "FacebookSearchResultPage") -> List[SearchedItem]:
        try:
            listings = self.get_listings_from_structure()
        except Exception as e1:
            try:
                listings = self.get_listing_from_css()
            except Exception as e2:
                self.logger.debug(f"No listings found from structure and css: {e1}, {e2}")
                self.logger.debug("Saving html to test.html")

                with open("test.html", "w") as f:
                    f.write(self.html)

                return []

        result = [self.parse_listing(listing) for listing in listings]
        # case from SearchedItem|None to SearchedItem
        return [cast(SearchedItem, x) for x in result if x is not None]


class FacebookItemPage(WebPage):

    def get_image_url(self: "FacebookItemPage") -> str:
        try:
            return self.soup.find("img")["src"]
        except Exception as e:
            self.logger.debug(e)
            return ""

    def get_title_and_price(self: "FacebookItemPage") -> List[str]:
        title = ""
        price = ""
        try:
            title_element = self.soup.find("h1")
            title = title_element.get_text(strip=True)
            price = extract_price(title_element.next_sibling.get_text())
        except Exception as e:
            self.logger.debug(e)

        return [title, price]

    def get_description_and_location(self: "FacebookItemPage") -> List[str]:
        description = ""
        location = ""
        try:
            cond = self.soup.find("span", string="Condition")
            if cond is None:
                raise ValueError("No span for condition is fond")
            ul = cond.find_parent("ul")
            if ul is None:
                raise ValueError("No ul as parent for condition is fond")
            description_div = ul.find_next_sibling()
            description = description_div.get_text(strip=True)
            #
            location_element = description_div.find_next_siblings()[-1]
            location = location_element.find("span").get_text()
        except Exception as e:
            self.logger.debug(e)

        return [description, location]

    def get_seller(self: "FacebookItemPage") -> str:
        seller = ""
        try:
            profiles = self.soup.find_all("a", href=re.compile(r"/marketplace/profile"))
            seller = profiles[-1].get_text()
        except Exception as e:
            self.logger.debug(e)
        return seller

    def parse(self: "FacebookItemPage", post_url: str) -> SearchedItem:
        # title
        item_id = post_url.split("?")[0].rstrip("/").split("/")[-1]
        title, price = self.get_title_and_price()
        description, location = self.get_description_and_location()

        # if not title or not price:
        #     with open(f"{item_id}.html", "w") as f:
        #         f.write(self.html)

        if not title:
            raise ValueError(
                f"""No title was found for item {post_url}, which is most likely caused by a network issue. Please report the issue to the developer if the problem persists."""
            )
        if not price:
            # with open(f"{item_id}.html", "w") as f:
            #     f.write(self.html)
            raise ValueError(
                f"""No price was found for item {post_url}, which is most likely caused by a network issue. Consider running with option --disable-javascript"""
            )

        if not description:
            # with open(f"{item_id}.html", "w") as f:
            #     f.write(self.html)
            raise ValueError(
                f"""No description was found for item {post_url}, which is most likely caused by a network issue. Consider running with option --disable-javascript"""
            )

        self.logger.info(f"Parsing item {hilight(title)}")
        res = SearchedItem(
            marketplace="facebook",
            name="",
            id=item_id,
            title=title,
            image=self.get_image_url(),
            price=price,
            post_url=post_url,
            location=location,
            description=description,
            seller=self.get_seller(),
        )
        self.logger.debug(pretty_repr(res))
        return cast(SearchedItem, res)
