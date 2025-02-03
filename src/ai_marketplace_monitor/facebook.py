import re
import time
from dataclasses import dataclass
from enum import Enum
from itertools import repeat
from logging import Logger
from typing import Any, Generator, List, Type, cast
from urllib.parse import quote

import humanize
import rich
from playwright.sync_api import Browser, ElementHandle, Page  # type: ignore
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
    ALL = "all"
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
    availability: List[str] | None = None
    condition: List[str] | None = None
    date_listed: List[int] | None = None
    delivery_method: List[str] | None = None

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
                        f"""Item {hilight(self.name)} date_listed must be one of 1, 7, and 30, or All, Last 24 hours, Last 7 days, Last 30 days."""
                    )
            elif not isinstance(val, int) or val not in [x.value for x in DateListed]:
                raise ValueError(
                    f"""Item {hilight(self.name)} date_listed must be one of 1, 7, and 30, or All, Last 24 hours, Last 7 days, Last 30 days."""
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
                time.sleep(2)
                selector = self.page.wait_for_selector('input[name="email"]')
                if selector is not None:
                    selector.type(self.config.username, delay=250)
            if self.config.password is not None:
                time.sleep(2)
                selector = self.page.wait_for_selector('input[name="pass"]')
                if selector is not None:
                    selector.type(self.config.password, delay=250)
            if self.config.username is not None and self.config.password is not None:
                time.sleep(2)
                selector = self.page.wait_for_selector('button[name="login"]')
                if selector is not None:
                    selector.click()
        except Exception as e:
            self.logger.error(f"""{hilight("[Login]", "fail")} {e}""")

        # in case there is a need to enter additional information
        login_wait_time = self.config.login_wait_time or 60
        self.logger.info(
            f"""{hilight("[Login]", "info")} Waiting {humanize.naturaldelta(login_wait_time)} to get ready."""
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

            # availability can take values from item_config, or marketplace config and will
        # use the first or second value depending on how many times the item has been searched.
        if item_config.date_listed:
            date_listed = item_config.date_listed[0 if item_config.searched_count == 0 else -1]
        elif self.config.date_listed:
            date_listed = self.config.date_listed[0 if item_config.searched_count == 0 else -1]
        else:
            date_listed = DateListed.ANYTIME.value
        if date_listed is not None and date_listed != DateListed.ANYTIME.value:
            options.append(f"daysSinceListed={date_listed}")

        # delivery_method can take values from item_config, or marketplace config and will
        # use the first or second value depending on how many times the item has been searched.
        if item_config.delivery_method:
            delivery_method = item_config.delivery_method[
                0 if item_config.searched_count == 0 else -1
            ]
        elif self.config.delivery_method:
            delivery_method = self.config.delivery_method[
                0 if item_config.searched_count == 0 else -1
            ]
        else:
            delivery_method = DeliveryMethod.ALL.value
        if delivery_method is not None and delivery_method != DeliveryMethod.ALL.value:
            options.append(f"deliveryMethod={delivery_method}")

        # availability can take values from item_config, or marketplace config and will
        # use the first or second value depending on how many times the item has been searched.
        if item_config.availability:
            availability = item_config.availability[0 if item_config.searched_count == 0 else -1]
        elif self.config.availability:
            availability = self.config.availability[0 if item_config.searched_count == 0 else -1]
        else:
            availability = Availability.ALL.value
        if availability is not None and availability != Availability.ALL.value:
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

                found_items = FacebookSearchResultPage(self.page, self.logger).get_listings()
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
                        self.logger.error(
                            f"""{hilight("[Retrieve]", "fail")} Failed to get item details: {e}"""
                        )
                        continue
                    # currently we trust the other items from summary page a bit better
                    # so we do not copy title, description etc from the detailed result
                    item.description = details.description
                    item.seller = details.seller
                    item.name = item_config.name
                    self.logger.debug(
                        f"""{hilight("[Retrieve]", "succ")} New item "{item.title}" from https://www.facebook.com{item.post_url} is sold by "{item.seller}" and with description "{item.description[:100]}..." """
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
        details = None
        for page_model in supported_facebook_item_layouts:
            try:
                details = page_model(self.page, self.logger).parse(post_url)
                break
            except Exception:
                # try next page layout
                continue
        if details is None:
            raise ValueError(f"Failed to get item details from {post_url}")
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
                f"""{hilight("[Skip]", "fail")} Exclude {hilight(item.title)} due to {hilight("excluded keywords", "fail")}: {', '.join(exclude_keywords)}"""
            )
            return False

        # if the return description does not contain any of the search keywords
        include_keywords = item_config.include_keywords
        if include_keywords and not is_substring(include_keywords, item.title):
            self.logger.info(
                f"""{hilight("[Skip]", "fail")} Exclude {hilight(item.title)} {hilight("without required keywords", "fail")} in title."""
            )
            return False

        # get locations from either marketplace config or item config
        if item_config.seller_locations is not None:
            allowed_locations = item_config.seller_locations
        else:
            allowed_locations = self.config.seller_locations or []
        if allowed_locations and not is_substring(allowed_locations, item.location):
            self.logger.info(
                f"""{hilight("[Skip]", "fail")} Exclude {hilight("out of area", "fail")} item {hilight(item.title)} from location {hilight(item.location)}"""
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
                f"""{hilight("[Skip]", "fail")} Exclude {hilight(item.title)} by {hilight("description", "fail")}.\n{hilight(item.description[:100])}..."""
            )
            return False

        # get exclude_sellers from both item_config or config
        if item_config.exclude_sellers is not None:
            exclude_sellers = item_config.exclude_sellers
        else:
            exclude_sellers = self.config.exclude_sellers or []
        if item.seller and exclude_sellers and is_substring(exclude_sellers, item.seller):
            self.logger.info(
                f"""{hilight("[Skip]", "fail")} Exclude {hilight(item.title)} sold by {hilight("banned seller", "failed")} {hilight(item.seller)}"""
            )
            return False

        return True


class WebPage:

    def __init__(self: "WebPage", page: Page, logger: Logger) -> None:
        self.page = page
        self.logger = logger


class FacebookSearchResultPage(WebPage):

    def get_listings(self: "FacebookSearchResultPage") -> List[SearchedItem]:
        listings: List[SearchedItem] = []
        heading = self.page.locator('[aria-label="Collection of Marketplace items"]')

        # find the grid box
        try:
            grid_items = heading.locator(
                ":scope > :first-child > :first-child > :nth-child(3) > :first-child > :nth-child(2) > div"
            ).all()
        except Exception as e:
            self.logger.debug(f'{hilight("[Retrieve]", "fail")} {e}. Page saved to test.html')
            with open("test.html", "w", encoding="utf-8") as f:
                f.write(self.page.content())
            return listings
        # find each listing
        for listing in grid_items:
            if not listing.text_content():
                continue
            atag = listing.locator(
                ":scope > :first-child > :first-child > :first-child > :first-child > :first-child > :first-child > :first-child > :first-child"
            )
            post_url = atag.get_attribute("href") or ""
            details = atag.locator(":scope > :first-child > div").nth(1)
            raw_price = details.locator(":scope > div").nth(0).text_content() or ""
            title = details.locator(":scope > div").nth(1).text_content() or ""
            location = details.locator(":scope > div").nth(2).text_content() or ""
            image = listing.locator("img").get_attribute("src") or ""
            price = extract_price(raw_price)

            listings.append(
                SearchedItem(
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
            )
        # Append the parsed data to the list.
        return listings


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

    def parse(self: "FacebookItemPage", post_url: str) -> SearchedItem:
        if not self.verify_layout():
            raise ValueError("Layout mismatch")

        # title
        item_id = post_url.split("?")[0].rstrip("/").split("/")[-1]

        title = self.get_title()
        price = self.get_price()
        description = self.get_description()

        if not title or not price or not description:
            raise ValueError(f"Failed to parse {post_url}")

        self.logger.info(f'{hilight("[Retrieve]", "succ")} Parsing {hilight(title)}')
        res = SearchedItem(
            marketplace="facebook",
            name="",
            id=item_id,
            title=title,
            image=self.get_image_url(),
            price=extract_price(price),
            post_url=post_url,
            location=self.get_location(),
            description=description,
            seller=self.get_seller(),
        )
        self.logger.debug(f'{hilight("[Retrieve]", "succ")} {pretty_repr(res)}')
        return cast(SearchedItem, res)


class FacebookRegularItemPage(FacebookItemPage):
    def verify_layout(self: "FacebookRegularItemPage") -> bool:
        return any(
            "Condition" in (x.text_content() or "") for x in self.page.query_selector_all("li")
        )

    def get_title(self: "FacebookRegularItemPage") -> str:
        try:
            h1_element = self.page.query_selector_all("h1")[-1]
            return h1_element.text_content() or "**unspecified**"
        except Exception as e:
            self.logger.debug(f'{hilight("[Retrieve]", "fail")} {e}')
            return ""

    def get_price(self: "FacebookRegularItemPage") -> str:
        try:
            price_element = self.page.locator("h1 + *")
            return price_element.text_content() or "**unspecified**"
        except Exception as e:
            self.logger.debug(f'{hilight("[Retrieve]", "fail")} {e}')
            return ""

    def get_image_url(self: "FacebookRegularItemPage") -> str:
        try:
            image_url = self.page.locator("img").first.get_attribute("src") or ""
            return image_url
        except Exception as e:
            self.logger.debug(f'{hilight("[Retrieve]", "fail")} {e}')
            return ""

    def get_seller(self: "FacebookRegularItemPage") -> str:
        try:
            seller_link = self.page.locator('a[href^="/marketplace/profile"]').last
            return seller_link.text_content() or "**unspecified**"
        except Exception as e:
            self.logger.debug(f'{hilight("[Retrieve]", "fail")} {e}')
            return ""

    def get_description(self: "FacebookRegularItemPage") -> str:
        try:
            # Find the span with text "condition", then parent, then next...
            description_element = self.page.locator(
                'span:text("condition") >> xpath=ancestor::ul[1] >> xpath=following-sibling::*[1]'
            )
            return description_element.text_content() or "**unspecified**"
        except Exception as e:
            self.logger.debug(f'{hilight("[Retrieve]", "fail")} {e}')
            return ""

    def get_location(self: "FacebookRegularItemPage") -> str:
        try:
            # look for "Location is approximate", then find its neightbor
            approximate_element = self.page.locator('span:text("Location is approximate")')
            parent: ElementHandle | None = approximate_element.element_handle()
            # look for parent of approximate_element until it has two children and the first child is the heading
            while parent:
                children = parent.query_selector_all(":scope > *")
                if len(children) == 2 and "Location is approximate" in (
                    children[1].text_content() or ""
                ):
                    return children[0].text_content() or "**unspecified**"
                parent = parent.query_selector("xpath=..")
            raise ValueError("No location found.")
        except Exception as e:
            self.logger.debug(f'{hilight("[Retrieve]", "fail")} {e}')
            return ""


class FacebookRentalItemPage(FacebookRegularItemPage):
    def verify_layout(self: "FacebookRentalItemPage") -> bool:
        # there is a header h2 with text Description
        return any(
            "Description" in (x.text_content() or "") for x in self.page.query_selector_all("h2")
        )

    def get_description(self: "FacebookRentalItemPage") -> str:
        # some pages do not have a condition box and appears to have a "Description" header
        # See https://github.com/BoPeng/ai-marketplace-monitor/issues/29 for details.
        try:
            description_header = self.page.query_selector('h2:has(span:text("Description"))')
            # find the parent until it has two children and the first child is the heading
            parent = description_header
            while parent:
                children = parent.query_selector_all(":scope > *")
                if len(children) > 1 and children[0].text_content() == "Description":
                    return children[1].text_content() or "**unspecified**"
                parent = parent.query_selector("xpath=..")
            raise ValueError("No description found.")
        except Exception as e:
            self.logger.debug(f'{hilight("[Retrieve]", "fail")} {e}')
            return ""


class FacebookAutoItemPage(FacebookRegularItemPage):
    def verify_layout(self: "FacebookAutoItemPage") -> bool:
        # there is a header h2 with text "About this vehicle"
        return any(
            "About this vehicle" in (x.text_content() or "")
            for x in self.page.query_selector_all("h2")
        )

    def get_description(self: "FacebookAutoItemPage") -> str:
        #
        # find a h2 with "Seller's description"
        # then find the parent until it has two children and the first child is the heading
        description = []
        try:
            # first get about this vehicle
            element = self.page.locator('h2:has(span:text("About this vehicle"))')
            parent: ElementHandle | None = element.element_handle()
            while parent:
                children = parent.query_selector_all(":scope > *")
                if len(children) > 1 and "About this vehicle" in (
                    children[0].text_content() or "**unspecified**"
                ):
                    break
                parent = parent.query_selector("xpath=..")
            #
            description.extend([child.text_content() or "" for child in children])

            #
            description_header = self.page.query_selector(
                'h2:has(span:text("Seller\'s description"))'
            )
            parent = description_header
            while parent:
                children = parent.query_selector_all(":scope > *")
                if len(children) > 1 and (
                    "Seller's description" in (children[0].text_content() or "")
                ):
                    break
                parent = parent.query_selector("xpath=..")
            # now, we need to drill down from the 2nd child
            parent_element: ElementHandle | None = children[1]
            while parent_element:
                children = parent_element.query_selector_all(":scope > *")
                if len(children) > 1:
                    description.extend(
                        ["Seller's description", children[0].text_content() or "**unspecified**"]
                    )
                    break
                parent_element = parent_element.query_selector("xpath=/*[1]")
            return "\n".join(description)
        except Exception as e:
            self.logger.debug(f'{hilight("[Retrieve]", "fail")} {e}')
            return ""

    def get_price(self: "FacebookAutoItemPage") -> str:
        description = self.get_description()
        # using regular expression to find text that looks like price in the description
        price_pattern = r"\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?(?:,\d{2})?"
        match = re.search(price_pattern, description)
        if match:
            return match.group(0)
        else:
            return "**unspecified**"


supported_facebook_item_layouts = [
    FacebookRegularItemPage,
    FacebookRentalItemPage,
    FacebookAutoItemPage,
]
