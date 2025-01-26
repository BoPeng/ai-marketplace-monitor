import json
import os
import random
import time
from logging import Logger
from typing import Any, ClassVar, Dict, List

from playwright.sync_api import Browser, sync_playwright
from rich.pretty import pretty_repr

from .ai import AIBackend, DeepSeekBackend, OpenAIBackend
from .config import Config
from .facebook import FacebookMarketplace
from .items import SearchedItem
from .users import User
from .utils import amm_home, calculate_file_hash, memory, sleep_with_watchdog

supported_marketplaces = {"facebook": FacebookMarketplace}
supported_ai_backends = {"deepseek": DeepSeekBackend, "openai": OpenAIBackend}


class MarketplaceMonitor:
    search_history_cache = os.path.join(amm_home, "searched_items.json")

    active_marketplaces: ClassVar = {}

    def __init__(
        self: "MarketplaceMonitor",
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
        self.ai_backend: AIBackend | None = None
        self.logger = logger
        if clear_cache:
            if os.path.exists(self.search_history_cache):
                os.remove(self.search_history_cache)
            #
            memory.clear()

    def load_config_file(self: "MarketplaceMonitor") -> Dict[str, Any]:
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
                assert self.logger is not None
                self.config = Config(self.config_files, self.logger).config
                self.config_hash = new_file_hash
                # self.logger.debug(self.config)
                assert self.config is not None
                return self.config
            except ValueError as e:
                if last_invalid_hash != new_file_hash:
                    last_invalid_hash = new_file_hash
                    self.logger.error(
                        f"""Error parsing config file:\n\n[red]{e}[/red]\n\nPlease fix the configuration and I will try again as soon as you are done."""
                    )
                sleep_with_watchdog(60, self.config_files)
                continue

    def load_ai_agent(self: "MarketplaceMonitor") -> None:
        """Load the AI agent."""
        assert self.config is not None
        for ai_name, ai_config in self.config.get("ai", {}).items():
            ai_class = supported_ai_backends[ai_name]
            ai_class.validate(ai_config)
            try:
                self.logger.info(f"Connecting to {ai_name}")
                self.ai_backend = ai_class(config=ai_config, logger=self.logger)
                self.ai_backend.connect()
                # if one works, do not try to load another one
                break
            except Exception as e:
                self.logger.error(f"Error connecting to {ai_name}: {e}")
                continue

    def monitor(self: "MarketplaceMonitor") -> None:
        """Main function to monitor the marketplace."""
        # start a browser with playwright
        with sync_playwright() as p:
            # Open a new browser page.
            browser: Browser = p.chromium.launch(headless=self.headless)
            while True:
                # we reload the config file each time when a scan action is completed
                # this allows users to add/remove products dynamically.
                self.load_config_file()
                self.load_ai_agent()

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
                                f"Searching {marketplace_name} for [magenta]{item_name}[/magenta]"
                            )
                            found_items = marketplace.search(item_config)
                            #
                            new_items = [
                                x
                                for x in self.find_new_items(found_items)
                                if self.confirmed_by_ai(
                                    x, item_name=item_name, item_config=item_config
                                )
                            ]
                            self.logger.info(
                                f"""[magenta]{len(new_items)}[/magenta] new listing{"" if len(new_items) == 1 else "s"} for {item_name} {"is" if len(new_items) == 1 else "are"} found."""
                            )
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

    def check_items(
        self: "MarketplaceMonitor", items: List[str] | None = None, for_item: str | None = None
    ) -> None:
        """Main function to monitor the marketplace."""
        # we reload the config file each time when a scan action is completed
        # this allows users to add/remove products dynamically.
        self.load_config_file()

        if for_item is not None:
            assert self.config is not None
            if for_item not in self.config["item"]:
                raise ValueError(
                    f"Item {for_item} not found in config, available items are {', '.join(self.config['item'].keys())}."
                )

        self.load_ai_agent()

        post_urls = []
        for post_url in items or []:
            if "?" in post_url:
                post_url = post_url.split("?")[0]
            if post_url.startswith("https://www.facebook.com"):
                post_url = post_url[len("https://www.facebook.com") :]
            if post_url.isnumeric():
                post_url = f"/marketplace/item/{post_url}/"
            post_urls.append(post_url)

        if not post_urls:
            raise ValueError("No URLs to check.")

        # we may or may not need a browser
        with sync_playwright() as p:
            # Open a new browser page.
            browser = None
            for post_url in post_urls or []:
                if "?" in post_url:
                    post_url = post_url.split("?")[0]
                if post_url.startswith("https://www.facebook.com"):
                    post_url = post_url[len("https://www.facebook.com") :]
                if post_url.isnumeric():
                    post_url = f"/marketplace/item/{post_url}/"

                # check if item in config
                assert self.config is not None

                # which marketplace to check it?
                for marketplace_name, marketplace_config in self.config["marketplace"].items():
                    marketplace_class = supported_marketplaces[marketplace_name]
                    if marketplace_name in self.active_marketplaces:
                        marketplace = self.active_marketplaces[marketplace_name]
                    else:
                        marketplace = marketplace_class(marketplace_name, None, self.logger)
                        self.active_marketplaces[marketplace_name] = marketplace

                    # Configure might have been changed
                    marketplace.configure(marketplace_config)

                    # do we need a browser?
                    if not marketplace.get_item_details.check_call_in_cache(post_url):
                        if browser is None:
                            self.logger.info(
                                "Starting a browser because the item was not checked before."
                            )
                            browser = p.chromium.launch(headless=self.headless)
                            marketplace.set_browser(browser)

                    # ignore enabled
                    # do not search, get the item details directly
                    listing = marketplace.get_item_details(post_url)

                    self.logger.info(f"Details of the item is found: {pretty_repr(listing)}")

                    for item_name, item_config in self.config["item"].items():
                        if for_item is not None and item_name != for_item:
                            continue
                        self.logger.info(
                            f"Checking {post_url} for item {item_name} with configuration {pretty_repr(item_config)}"
                        )
                        marketplace.filter_item(listing, item_config)
                        self.confirmed_by_ai(listing, item_name=item_name, item_config=item_config)

    def load_searched_items(self: "MarketplaceMonitor") -> List[SearchedItem]:
        if os.path.isfile(self.search_history_cache):
            with open(self.search_history_cache, "r") as f:
                return json.load(f)
        return []

    def save_searched_items(self: "MarketplaceMonitor", items: List[SearchedItem]) -> None:
        with open(self.search_history_cache, "w") as f:
            json.dump(items, f)

    def find_new_items(
        self: "MarketplaceMonitor", items: List[SearchedItem]
    ) -> List[SearchedItem]:
        past_items = self.load_searched_items()
        past_item_ids = [x["id"] for x in past_items]
        new_items = [x for x in items if x["id"] not in past_item_ids]
        if new_items:
            self.save_searched_items(past_items + new_items)
        return new_items

    def confirmed_by_ai(
        self: "MarketplaceMonitor", item: SearchedItem, item_name: str, item_config: Dict[str, Any]
    ) -> bool:
        if self.ai_backend is None:
            self.logger.debug("No AI backend configured, skipping AI-based confirmation.")
            return True
        return self.ai_backend.confirm(item, item_name, item_config)

    def notify_users(
        self: "MarketplaceMonitor", users: List[str], items: List[SearchedItem]
    ) -> None:
        users = list(set(users))
        if not users:
            self.logger.warning("Will notify all users since no user is listed for notify.")
            assert self.config is not None
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
                f"Sending {user} a message with title [magenta]{title}[/magenta] and message [magenta]{message}[/magenta]"
            )
            assert self.config is not None
            assert self.config["user"] is not None
            User(user, self.config["user"][user], logger=self.logger).notify(title, message)
