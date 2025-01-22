import json
import os
import random
import time
from logging import Logger
from typing import Any, ClassVar, Dict, List

from playwright.sync_api import Browser, sync_playwright

from .config import Config
from .facebook import FacebookMarketplace
from .items import SearchedItem
from .users import User
from .utils import amm_home, calculate_file_hash, memory, sleep_with_watchdog

supported_marketplaces = {"facebook": FacebookMarketplace}


class MarketplaceMonitor:
    search_history_cache = os.path.join(amm_home, "searched_items.json")

    active_marketplaces: ClassVar = {}

    def __init__(
        self,
        config_files: List[str] | None,
        headless: bool | None,
        clear_cache: bool | None,
        logger: Logger,
    ) -> None:
        for file_path in config_files or []:
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"Config file {file_path} not found.")
        default_config = os.path.join(
            os.path.expanduser("~"), ".ai-marketplace-monitor", "config.toml"
        )
        self.config_files = ([default_config] if os.path.isfile(default_config) else []) + (
            [os.path.abspath(os.path.expanduser(x)) for x in config_files or []]
        )
        #
        self.config: Dict[str, Any] | None = None
        self.config_hash: str | None = None
        self.headless = headless
        self.logger = logger
        if clear_cache:
            if os.path.exists(self.search_history_cache):
                os.remove(self.search_history_cache)
            #
            memory.clear()

    def load_config_file(self) -> Dict[str, Any]:
        """Load the configuration file."""
        last_invalid_hash = None
        while True:
            new_file_hash = calculate_file_hash(self.config_files)
            config_changed = self.config_hash is None or new_file_hash != self.config_hash
            if not config_changed:
                assert self.config is not None
                return self.config
            try:
                # if the config file is ok, break
                self.config = Config(self.config_files, self.logger).config
                self.config_hash = new_file_hash
                self.logger.debug(self.config)
                assert self.config is not None
                return self.config
            except ValueError as e:
                if last_invalid_hash != new_file_hash:
                    last_invalid_hash = new_file_hash
                    self.logger.error(
                        f"""Error parsing config file:\n\n[red]{e}[/red]\n\nPlease fix the file and we will start monitoring as soon as you are done."""
                    )
                sleep_with_watchdog(60, self.config_files)
                continue

    def monitor(self) -> None:
        """Main function to monitor the marketplace."""
        # start a browser with playwright
        with sync_playwright() as p:
            # Open a new browser page.
            browser: Browser = p.chromium.launch(headless=self.headless)
            while True:
                # we reload the config file each time when a scan action is completed
                # this allows users to add/remove products dynamically.
                self.load_config_file()

                assert self.config is not None
                for marketplace_name, marketplace_config in self.config["marketplace"].items():
                    marketplace_class = supported_marketplaces[marketplace_name]
                    if marketplace_name in self.active_marketplaces:
                        marketplace = self.active_marketplaces[marketplace_name]
                    else:
                        marketplace = marketplace_class(marketplace_name, browser, self.logger)
                        self.active_marketplaces[marketplace_name] = marketplace

                    # Configure might have been changed
                    marketplace.configure(marketplace_config)

                    for item_name, item_config in self.config["item"].items():
                        if (
                            "marketplace" not in item_config
                            or item_config["marketplace"] == marketplace_name
                        ):
                            if not item_config.get("enabled", True):
                                continue

                            self.logger.info(
                                f"Searching {marketplace_name} for [blue]{item_name}[/blue]"
                            )
                            found_items = marketplace.search(item_config)
                            #
                            new_items = self.find_new_items(found_items)
                            self.logger.info(f"[blue]{len(new_items)}[/blue] new items are found.")
                            # there can be item-specific notification
                            if new_items:
                                self.notify_users(
                                    marketplace_config.get("notify", [])
                                    + item_config.get("notify", []),
                                    new_items,
                                )
                            time.sleep(5)

                    # wait for some time before next search
                    # interval (in minutes) can be defined both for the
                    # marketplace and the product
                    search_interval = max(marketplace_config.get("search_interval", 30), 1)
                    max_search_interval = max(
                        marketplace_config.get("max_search_interval", 1),
                        search_interval,
                    )
                    sleep_with_watchdog(
                        random.randint(search_interval * 60, max_search_interval * 60),
                        self.config_files,
                    )

    def load_searched_items(self) -> List[SearchedItem]:
        if os.path.isfile(self.search_history_cache):
            with open(self.search_history_cache, "r") as f:
                return json.load(f)
        return []

    def save_searched_items(self, items: List[SearchedItem]) -> None:
        with open(self.search_history_cache, "w") as f:
            json.dump(items, f)

    def find_new_items(self, items: List[SearchedItem]) -> List[SearchedItem]:
        past_items = self.load_searched_items()
        past_item_ids = [x["id"] for x in past_items]
        new_items = [x for x in items if x["id"] not in past_item_ids]
        if new_items:
            self.save_searched_items(past_items + new_items)
        return new_items

    def notify_users(self, users: List[str], items: List[SearchedItem]) -> None:
        users = list(set(users))
        if not users:
            self.logger.warning("Will notify all users since no user is listed for notify.")
            users = list(self.config["user"].keys())

        # get notification msg for this item
        msgs = []
        for item in items:
            self.logger.info(
                f"""New item found: {item["title"]} with URL https://www.facebook.com{item["post_url"]}"""
            )
            msgs.append(
                f"""{item['title']}\n{item['price']}, {item['location']}\nhttps://www.facebook.com{item['post_url']}"""
            )
        # found the user from the user configuration
        for user in users:
            title = f"Found {len(items)} new item from {item['marketplace']}: "
            message = "\n\n".join(msgs)
            self.logger.info(
                f"Sending {user} a message with title [blue]{title}[/blue] and message [blue]{message}[/blue]"
            )
            assert self.config is not None
            assert self.config["user"] is not None
            User(user, self.config["user"][user], logger=self.logger).notify(title, message)
