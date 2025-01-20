import random
import time
from logging import Logger
from typing import Any, Dict

from playwright.sync_api import Browser, sync_playwright

from .config import Config
from .facebook import FacebookMarketplace
from .users import Users
from .utils import calculate_file_hash

supported_marketplaces = {"facebook": FacebookMarketplace}


class MarketplaceMonitor:
    def __init__(self, config_file: str, headless: bool, clear_cache: bool, logger: Logger):
        self.config_file = config_file
        self.config = None
        self.config_hash = None
        self.headless = headless
        self.clear_cache = clear_cache
        self.logger = logger
        self.users = None

    def load_config_file(self) -> Dict[str, Any]:
        """Load the configuration file."""
        last_invalid_hash = None
        while True:
            new_file_hash = calculate_file_hash(self.config_file)
            config_changed = self.config_hash is None or new_file_hash != self.config_hash
            if not config_changed:
                return self.config
            try:
                # if the config file is ok, break
                self.config = Config(self.config_file).config
                self.config_hash = new_file_hash
                self.users = Users(self.config)
                self.logger.debug(self.config)
                return config_changed
            except ValueError as e:
                if last_invalid_hash != new_file_hash:
                    last_invalid_hash = new_file_hash
                    self.logger.error(
                        f"""Error parsing config file:\n\n{e}\n\nPlease fix the file and we will start monitoring as soon as you are done."""
                    )

                time.sleep(10)
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
                config_changed = self.load_config_file()

                for marketplace_name, marketplace_config in self.config["marketplace"].items():
                    if marketplace_name in supported_marketplaces:
                        marketplace_class = supported_marketplaces[marketplace_name]
                        marketplace = marketplace_class(
                            marketplace_name, marketplace_config, browser, self.logger
                        )
                        #
                        if config_changed:
                            marketplace.reset()
                            marketplace.login()
                        #
                        for item_name, item_config in self.config["item"].items():
                            if (
                                "marketplace" not in item_config
                                or item_config["marketplace"] == marketplace_name
                            ):
                                marketplace.add_search_item(item_name, item_config)
                            #
                            marketplace.search_products()
                            # wait for some time before next search
                            # interval (in minutes) can be defined both for the
                            # marketplace and the product
                            search_interval = max(marketplace_config.get("search_interval", 30), 1)
                            max_search_interval = max(
                                marketplace_config.get("max_search_interval", 1),
                                search_interval,
                            )
                            time.sleep(
                                random.randint(search_interval * 60, max_search_interval * 60)
                            )
                    else:
                        self.logger.error(f"Unsupported marketplace: {marketplace_name}")

    def notify_users(self, users, title, msg):
        # found the user from the user configuration
        Users(users, self.config).notify(title, msg)
