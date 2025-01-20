import time
from logging import Logger
from typing import Dict, List
from urllib.parse import quote

from bs4 import BeautifulSoup

from .marketplace import Marketplace


class FacebookMarketplace(Marketplace):
    initial_url = "https://www.facebook.com/login/device-based/regular/login/"

    def __init__(self, config, logger: Logger):
        super().__init__("facebook", config, logger)
        for key in ("username", "password"):
            if key not in config:
                raise ValueError(f"Missing required configuration: {key} for market facebook")
        self.page = None

    def login(self):
        page = self.browser.new_page()
        # Navigate to the URL, no timeout
        page.goto(self.initial_url, timeout=0)
        try:
            page.wait_for_selector('input[name="email"]').fill(self.config["username"])
            page.wait_for_selector('input[name="pass"]').fill(self.config["password"])
            time.sleep(5)
            page.wait_for_selector('button[name="login"]').click()
            # in case there is a need to enter additional information
            time.sleep(30)
            self.logger.info("Logging into facebook")
        except:
            pass

    def search(self, product):
        if not self.page:
            self.login()

        # get city from either marketplace config or product config
        search_city = self.config.get("city", product.get("city", ""))
        if not search_city:
            self.logger.error("No city specified for search")
            return
        # get max price from either marketplace config or product config
        max_price = self.config.get("max_price", product.get("max_price", None))
        # get min price from either marketplace config or product config
        min_price = self.config.get("min_price", product.get("min_price", None))

        marketplace_url = f"https://www.facebook.com/marketplace/{search_city}/?"
        if max_price:
            marketplace_url += f"maxPrice={max_price}&"
        if min_price:
            marketplace_url += f"minPrice={min_price}&"

        # search multiple keywords
        found_items = []
        for keyword in product.get("keywords", []):
            marketplace_url += f"query={quote(keyword)}"

            self.page.goto(marketplace_url, timeout=0)

            html = self.page.content()

            found_items.extend(
                [x for x in self.get_product_list(html) if self.filter_item(x, product)]
            )
            time.sleep(5)

        # check if any of the items have been returned before
        new_items = self.find_new_items(found_items)
        # now, notify users
        #
        # get product or marketplace list of users to notify
        notify_users = product.get("notify_users", [])
        if isinstance(notify_users, str):
            notify_users = [notify_users]
        if "notify_users" in self.config:
            global_users = self.config["notify_users"]
            if isinstance(global_users, str):
                global_users = [global_users]
            notify_users.extend(global_users)
        # remove duplicates
        notify_users = list(set(notify_users))
        # get notification msg for this product
        msg = []
        for item in new_items:
            self.logger.info(
                f'New item found: {item["title"]} with URL https://www.facebook.com{item['post_url']}'
            )
            msg.append(
                f"""{item['title']}\n{item['price']}, {item['location']}\nhttps://www.facebook.com{item['post_url']}"""
            )
        for user in notify_users:
            pb = self.notify_user(user, f"{len(new_items)} new item found: ", "\n\n".join(msg))

    def get_product_list(self, html, product) -> List[Dict[str, str]]:
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
                        "image": image,
                        "title": title,
                        "price": price,
                        "post_url": post_url,
                        "location": location,
                        "item_id": post_url.split("?")[0].rstrip("/").split("/")[-1],
                    }
                )
            except Exception as e:
                self.logger.debug(e)
                pass

        return parsed

    def filter_product(self, product, product_config):
        # get exclude_keywords from both product_config or marketplace_config
        exclude_keywords = product_config.get(
            "exclude_keywords", self.config.get("exclude_keywords", [])
        )

        if exclude_keywords and any(
            [x.lower() in product["title"].lower() for x in exclude_keywords or []]
        ):
            self.logger.info(f"Excluding specifically listed item: {product['title']}")
            return False

        # if the return description does not contain any of the search keywords
        search_words = [
            word for keywords in product_config["keywords"] for word in keywords.split()
        ]
        if not any([x.lower() in product["title"].lower() for x in search_words]):
            self.logger.info(f"Excluding item without search word: {product['title']}")
            return False

        # get locations from either marketplace config or product config
        allowed_locations = product_config.get("locations", self.config.get("locations", []))
        if allowed_locations and not any(
            [x.lower() in product["location"].lower() for x in allowed_locations]
        ):
            self.logger.info(
                f"Excluding item out side of specified locations: {title} from location {location}"
            )
            return False

        return True
