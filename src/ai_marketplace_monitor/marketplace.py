import json
import os
from logging import Logger
from typing import Any, Dict

from playwright.sync_api import Browser


class Marketplace:
    def __init__(
        self: "Marketplace", name: str, browser: Browser, config: Dict[str, Any], logger: Logger
    ) -> None:
        self.name = name
        self.search_history = f"{self.name}_search_items.json"
        self.config = config
        self.browser = browser
        self.logger = logger
        self.browser = None
        self.products = {}

    def login(self) -> None:
        # Implement the login logic here
        raise NotImplementedError("Login method must be implemented by subclasses.")

    def logout(self) -> None:
        # Implement the logout logic here
        raise NotImplementedError("Logout method must be implemented by subclasses.")

    def reset(self) -> None:
        self.search_items = {}

    def add_search_item(self, name, product: Dict[str, Any]) -> None:
        self.search_items[name] = product

    def search_products(self) -> None:
        if not self.products:
            self.logger.warning("No products to search for.")
            return
        for product_name, product in self.products.items():
            self.logger.info(f"Searching for {product_name} on {self.__class__.__name__}")
            # Implement the search logic here
            self.search(product)

    def search(self, product):
        raise NotImplementedError("Search method must be implemented by subclasses.")

    def past_products(self):
        if os.path.isfile(self.search_history):
            with open(self.search_history, "r") as f:
                return json.load(f)
        return []

    def add_to_past_products(self, items):
        past_products = self.past_products()
        past_products.extend(items)
        with open(self.search_history, "w") as f:
            json.dump(past_products, f)

    def find_new_items(self, items):
        past_products = self.past_products()
        new_items = [x for x in items if x["item_id"] not in past_products]
        if new_items:
            # add new_items to past_products
            self.add_to_past_products([x["item_id"] for x in new_items])
        return new_items
