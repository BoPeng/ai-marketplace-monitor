import random
import time
from logging import Logger

import toml
from playwright.sync_api import sync_playwright
from pushbullet import Pushbullet

from .facebook import FacebookMarketplace
from .utils import calculate_file_hash

supported_marketplaces = {"facebook": FacebookMarketplace}


class MarketplaceMonitor:
    def __init__(self, config_file: str, headless: bool, logger: Logger):
        self.config_file = config_file
        self.config_hash = None
        self.headless = headless
        self.logger = logger

    def monitor(self) -> None:
        """Main function to monitor the marketplace."""
        # start a browser with playwright
        with sync_playwright() as p:
            # Open a new browser page.
            browser = p.chromium.launch(headless=self.headless)
            while True:
                # we reload the config file each time when a scan action is completed
                # this allows users to add/remove products dynamically.
                new_file_hash = calculate_file_hash(self.config_file)
                config_changed = self.config_hash is None or new_file_hash != self.config_hash
                if config_changed:
                    self.config_hash = new_file_hash
                #            #
                with open(self.config_file, "r") as f:
                    config = toml.load(f)

                for marketplace_name, marketplace_config in config["marketplace"].items():
                    if marketplace_name in supported_marketplaces:
                        marketplace_class = supported_marketplaces[marketplace_name]
                        marketplace = marketplace_class(marketplace_config, logger)
                        # find products that will be monitored by this market place
                        #
                        if config_changed:
                            marketplace.login()
                            marketplace.reset()
                        #
                        for product, product_config in config["product"].items():
                            if (
                                "marketplace" not in product_config
                                or product_config["marketplace"] == marketplace_name
                            ):
                                marketplace.add_product(product, product_config)

                        marketplace.search_products()
                        # wait for some time before next search
                        # interval (in minutes) can be defined both for the
                        # marketplace and the product
                        interval = max(
                            product_config.get(
                                "interval", marketplace_config.get("interval", 60), 1
                            )
                        )
                        max_interval = max(
                            product_config.get(
                                "max_interval", marketplace_config.get("max_interval", 0), interval
                            )
                        )
                        time.sleep(random.randint(interval * 60, max_interval * 60))
                    else:
                        self.logger.error(f"Unsupported marketplace: {marketplace_name}")

    def notify_user(self, user, title, msg):
        # found the user from the user configuration
        if "users" not in self.config:
            self.logger.warning("No users specified in the config file.")
            return
        if user not in self.config["users"]:
            self.logger.warning(f"User {user} not found in the config file.")
            return
        user_config = self.config["users"][user]
        if "pushbullet_token" not in user_config:
            self.logger.warning(f"No pushbullet token specified for user {user}.")
            return

        pb = Pushbullet(user_config["pushbullet_token"])
        pb.push_note(msg)
