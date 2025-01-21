import time
from logging import Logger
from typing import ClassVar, List
from urllib.parse import quote

from bs4 import BeautifulSoup
from playwright.sync_api import Browser

from .items import SearchedItem
from .marketplace import Marketplace


class FacebookMarketplace(Marketplace):
    initial_url = "https://www.facebook.com/login/device-based/regular/login/"

    name = "facebook"

    allowed_config_keys: ClassVar = {
        "username",
        "password",
        "search_interval",
        "max_search_interval",
        "search_city",
        "acceptable_locations",
        "exclude_sellers",
        "notify",
    }

    def __init__(self, name, config, browser: Browser, logger: Logger):
        assert name == self.name
        super().__init__(name, config, browser, logger)
        #
        self.page = None
        self.validate(config)

    @classmethod
    def validate(cls, config) -> None:
        #
        super().validate(config)
        #
        for key in ("username", "password"):
            if key not in config:
                raise ValueError(f"Missing required configuration: {key} for market {cls.name}")
        # locations, if specified, must be a list (or be converted to a list)
        if "locations" in config:
            if isinstance(config["locations"], str):
                config["locations"] = [config["locations"]]
            if not isinstance(config["locations"], list) or not all(
                isinstance(x, str) for x in config["locations"]
            ):
                raise ValueError(
                    f"Marketplace {cls.name} locations must be string or a list of string."
                )
        # if exclude_sellers is specified, it must be a list
        if "exclude_sellers" in config:
            if isinstance(config["exclude_sellers"], str):
                config["exclude_sellers"] = [config["exclude_sellers"]]

            if not isinstance(config["exclude_sellers"], list) or not all(
                isinstance(x, str) for x in config["exclude_sellers"]
            ):
                raise ValueError(
                    f"Marketplace {cls.name} exclude_sellers must be a list of string."
                )

        for interval_field in ("search_interval", "max_search_interval"):
            if interval_field in config:
                if not isinstance(config[interval_field], int):
                    raise ValueError(f"Marketplace {cls.name} search_interval must be an integer.")

    def login(self):
        self.page = self.browser.new_page()
        # Navigate to the URL, no timeout
        self.page.goto(self.initial_url, timeout=0)
        try:
            self.page.wait_for_selector('input[name="email"]').fill(self.config["username"])
            self.page.wait_for_selector('input[name="pass"]').fill(self.config["password"])
            time.sleep(5)
            self.page.wait_for_selector('button[name="login"]').click()
            # in case there is a need to enter additional information
            time.sleep(30)
            self.logger.info("Logging into facebook")
        except:
            pass

    def search(self, item_config) -> List[SearchedItem]:
        if not self.page:
            self.login()

        # get city from either marketplace config or item config
        search_city = self.config.get("search_city", item_config.get("search_city", ""))
        # get max price from either marketplace config or item config
        max_price = self.config.get("max_price", item_config.get("max_price", None))
        # get min price from either marketplace config or item config
        min_price = self.config.get("min_price", item_config.get("min_price", None))

        marketplace_url = f"https://www.facebook.com/marketplace/{search_city}/?"
        if max_price:
            marketplace_url += f"maxPrice={max_price}&"
        if min_price:
            marketplace_url += f"minPrice={min_price}&"

        # search multiple keywords
        found_items = []
        for keyword in item_config.get("keywords", []):
            self.page.goto(marketplace_url + f"query={quote(keyword)}", timeout=0)

            html = self.page.content()

            found_items.extend(
                [x for x in self.get_item_list(html) if self.filter_item(x, item_config)]
            )
            time.sleep(5)

        # check if any of the items have been returned before
        return found_items

    def get_item_list(self, html) -> List[SearchedItem]:
        soup = BeautifulSoup(html, "html.parser")
        parsed = []

        def get_listings_from_structure():
            heading = soup.find(attrs={"aria-label": "Collection of Marketplace items"})
            child1 = next(heading.children)
            child2 = next(child1.children)
            grid_parent = list(child2.children)[2]  # groups of listings
            for group in grid_parent.children:
                grid_child2 = list(group.children)[1]  # the actual grid container
                return list(grid_child2.children)

        def get_listing_from_css():
            return soup.find_all(
                "div",
                class_="x9f619 x78zum5 x1r8uery xdt5ytf x1iyjqo2 xs83m0k x1e558r4 x150jy0e x1iorvi4 xjkvuk6 xnpuxes x291uyu x1uepa24",
            )

        try:
            listings = get_listings_from_structure()
        except Exception as e1:
            try:
                listings = get_listing_from_css()
            except Exception as e2:
                self.logger.info("No listings found from structure and css: {e1}, {e2}")
                self.logger.info("Saving html to test.html")

                with open("test.html", "w") as f:
                    f.write(html)

                return parsed

        for listing in listings:
            try:
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
                price = details[0].contents[-1].text
                title = details[1].contents[-1].text
                location = details[2].contents[-1].text

                # Append the parsed data to the list.
                parsed.append(
                    {
                        "marketplace": self.name,
                        "id": post_url.split("?")[0].rstrip("/").split("/")[-1],
                        "title": title,
                        "image": image,
                        "price": price,
                        "post_url": post_url,
                        "location": location,
                        "description": "",
                    }
                )
            except Exception as e:
                self.logger.debug(e)
                pass

        return parsed

    def filter_item(self, item: SearchedItem, item_config) -> bool:
        # get exclude_keywords from both item_config or config
        exclude_keywords = item_config.get(
            "exclude_keywords", self.config.get("exclude_keywords", [])
        )

        if exclude_keywords and any(
            [x.lower() in item["title"].lower() for x in exclude_keywords or []]
        ):
            self.logger.info(f"Excluding specifically listed item: {item['title']}")
            return False

        # if the return description does not contain any of the search keywords
        search_words = [word for keywords in item_config["keywords"] for word in keywords.split()]
        if not any([x.lower() in item["title"].lower() for x in search_words]):
            self.logger.info(f"Excluding item without search word: {item['title']}")
            return False

        # get locations from either marketplace config or item config
        allowed_locations = item_config.get("locations", self.config.get("locations", []))
        if allowed_locations and not any(
            [x.lower() in item["location"].lower() for x in allowed_locations]
        ):
            self.logger.info(
                f"Excluding item out side of specified locations: {item['title']} from location {item['location']}"
            )
            return False

        return True
