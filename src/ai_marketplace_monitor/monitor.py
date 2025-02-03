import os
import sys
import time
from logging import Logger
from typing import ClassVar, List

import humanize
import inflect
import schedule  # type: ignore
from playwright.sync_api import Browser, Playwright, sync_playwright
from rich.pretty import pretty_repr

from .ai import AIBackend, AIResponse
from .config import Config, supported_ai_backends, supported_marketplaces
from .item import SearchedItem
from .marketplace import Marketplace, TItemConfig, TMarketplaceConfig
from .user import User
from .utils import CacheType, cache, calculate_file_hash, hilight, sleep_with_watchdog


class MarketplaceMonitor:
    active_marketplaces: ClassVar = {}

    def __init__(
        self: "MarketplaceMonitor",
        config_files: List[str] | None,
        headless: bool | None,
        disable_javascript: bool | None,
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
        self.config: Config | None = None
        self.config_hash: str | None = None
        self.headless = headless
        self.disable_javascript = disable_javascript
        self.ai_agents: List[AIBackend] = []
        self.playwright: Playwright | None = None
        self.logger = logger
        if clear_cache:
            cache.clear()

    def load_config_file(self: "MarketplaceMonitor") -> Config:
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
                self.config = Config(self.config_files, self.logger)
                self.config_hash = new_file_hash
                # self.logger.debug(self.config)
                assert self.config is not None
                return self.config
            except Exception as e:
                if last_invalid_hash != new_file_hash:
                    last_invalid_hash = new_file_hash
                    self.logger.error(
                        f"""{hilight("[Config]", "fail")} Error parsing:\n\n{hilight(str(e), "fail")}\n\nPlease fix the configuration and I will try again as soon as you are done."""
                    )
                sleep_with_watchdog(60, self.config_files)
                continue

    def load_ai_agents(self: "MarketplaceMonitor") -> None:
        """Load the AI agent."""
        assert self.config is not None
        for ai_config in (self.config.ai or {}).values():
            if (
                ai_config.provider is not None
                and ai_config.provider.lower() in supported_ai_backends
            ):
                ai_class = supported_ai_backends[ai_config.provider.lower()]
            elif ai_config.name.lower() in supported_ai_backends:
                ai_class = supported_ai_backends[ai_config.name.lower()]
            else:
                self.logger.error(
                    f"""{hilight("[Config]", "fail")} Cannot determine an AI service provider from service name or provider."""
                )
                continue

            try:
                self.ai_agents.append(ai_class(config=ai_config, logger=self.logger))
                self.ai_agents[-1].connect()
                self.logger.info(
                    f"""{hilight("[AI]", "succ")} Connected to {hilight(ai_config.name)}"""
                )
            except Exception as e:
                self.logger.error(
                    f"""{hilight("[AI]", "fail")} Failed to connect to {hilight(ai_config.name, "fail")}: {e}"""
                )
                continue

    def search_item(
        self: "MarketplaceMonitor",
        marketplace_config: TMarketplaceConfig,
        marketplace: Marketplace,
        item_config: TItemConfig,
    ) -> None:
        """Search for an item on the marketplace."""
        self.logger.info(
            f"""{hilight("[Search]", "info")} Searching {marketplace_config.name} for {hilight(item_config.name)}"""
        )
        new_listings = []
        listing_ratings = []
        # users to notify is determined from item, then marketplace, then all users
        assert self.config is not None
        users_to_notify = (
            item_config.notify or marketplace_config.notify or list(self.config.user.keys())
        )
        for listing in marketplace.search(item_config):
            # increase the searched_count
            item_config.searched_count += 1
            # if everyone has been notified
            if listing.user_notified_key in cache and all(
                user in cache.get(listing.user_notified_key, ()) for user in users_to_notify
            ):
                self.logger.info(
                    f"""{hilight("[Skip]", "info")} Already sent notification for item {hilight(listing.title)}, skipping."""
                )
                continue
            # for x in self.find_new_items(found_items)
            res = self.evaluate_by_ai(listing, item_config=item_config)
            if item_config.rating:
                acceptable_rating = item_config.rating[
                    0 if item_config.searched_count == 0 else -1
                ]
            elif marketplace_config.rating:
                acceptable_rating = marketplace_config.rating[
                    0 if item_config.searched_count == 0 else -1
                ]
            else:
                acceptable_rating = 3

            if res.score < acceptable_rating:
                self.logger.info(
                    f"""{hilight("[Skip]", "fail")} Rating {hilight(f"{res.conclusion} ({res.score})")} for {listing.title} is below threshold {acceptable_rating}."""
                )
                continue
            new_listings.append(listing)
            listing_ratings.append(res)

        p = inflect.engine()
        self.logger.info(
            f"""{hilight("[Search]", "succ" if len(new_listings) > 0 else "fail")} {hilight(str(len(new_listings)))} new {p.plural_noun("listing", len(new_listings))} for {item_config.name} {p.plural_verb("is", len(new_listings))} found."""
        )
        if new_listings:
            self.notify_users(users_to_notify, new_listings, listing_ratings)
        time.sleep(5)

    def schedule_jobs(self: "MarketplaceMonitor", browser: Browser) -> None:
        """Schedule jobs to run periodically."""
        # we reload the config file each time when a scan action is completed
        # this allows users to add/remove products dynamically.
        self.load_config_file()
        self.load_ai_agents()

        assert self.config is not None
        for marketplace_config in self.config.marketplace.values():
            marketplace_class = supported_marketplaces[marketplace_config.name]
            if marketplace_config.name in self.active_marketplaces:
                marketplace = self.active_marketplaces[marketplace_config.name]
            else:
                marketplace = marketplace_class(marketplace_config.name, browser, self.logger)
                self.active_marketplaces[marketplace_config.name] = marketplace

            # Configure might have been changed
            marketplace.configure(marketplace_config)
            if self.disable_javascript is not None:
                marketplace.set_browser(disable_javascript=self.disable_javascript)

            for item_config in self.config.item.values():
                if not (item_config.enabled or True):
                    continue

                if (
                    item_config.marketplace is None
                    or item_config.marketplace == marketplace_config.name
                ):
                    # wait for some time before next search
                    # interval (in minutes) can be defined both for the marketplace
                    # if there is any configuration file change, stop sleeping and search again
                    scheduled = None
                    start_at_list = item_config.start_at or marketplace_config.start_at
                    if start_at_list is not None and start_at_list:
                        for start_at in start_at_list:
                            if start_at.startswith("*:*:"):
                                # '*:*:12' to ':12'
                                self.logger.info(
                                    f"""{hilight("[Search]", "info")} Scheduling to search for {item_config.name} every minute at {start_at[3:]}s"""
                                )
                                scheduled = schedule.every().minute.at(start_at[3:])
                            elif start_at.startswith("*:"):
                                # '*:12:12' or  '*:12'
                                self.logger.info(
                                    f"""{hilight("[Search]", "info")} Scheduling to search for {item_config.name} every hour at {start_at[1:]}m"""
                                )
                                scheduled = schedule.every().hour.at(
                                    start_at[1:] if start_at.count(":") == 1 else start_at[2:]
                                )
                            else:
                                # '12:12:12' or '12:12'
                                self.logger.info(
                                    f"""{hilight("[Search]", "ss")} Cheduling to search for {item_config.name} every day at {start_at}"""
                                )
                                scheduled = schedule.every().day.at(start_at)
                    else:
                        search_interval = max(
                            item_config.search_interval
                            or marketplace_config.search_interval
                            or 30 * 60,
                            1,
                        )
                        max_search_interval = max(
                            item_config.max_search_interval
                            or marketplace_config.max_search_interval
                            or 60 * 60,
                            search_interval,
                        )
                        self.logger.info(
                            f"""{hilight("[Schedule]", "info")} Scheduling to search for {item_config.name} every {humanize.naturaldelta(search_interval)} {'' if search_interval == max_search_interval else f'to {humanize.naturaldelta(max_search_interval)}'}"""
                        )
                        scheduled = schedule.every(search_interval).to(max_search_interval).seconds
                    if scheduled is None:
                        raise ValueError(
                            f"Cannot determine a schedule for {item_config.name} from configuration file."
                        )
                    scheduled.do(
                        self.search_item,
                        marketplace_config,
                        marketplace,
                        item_config,
                    ).tag(item_config.name)

    def start_monitor(self: "MarketplaceMonitor") -> None:
        """Main function to monitor the marketplace."""
        # start a browser with playwright, cannot use with statement since the jobs will be
        # executed outside of the scope by schedule job runner
        self.playwright = sync_playwright().start()
        # Open a new browser page.
        assert self.playwright is not None
        browser: Browser = self.playwright.chromium.launch(headless=self.headless)
        #
        while True:
            self.schedule_jobs(browser)
            if not schedule.get_jobs():
                # this actually should not happen because at least one item is required for the configuration file
                self.logger.error(
                    "No search job is defined. Please add search items to your config file."
                )
                sleep_with_watchdog(60, self.config_files)
                continue
            # run all jobs at the first time, then on their own schedule
            # we could have used schedule.run_all() but we would like to check if
            # configuration file has been changed, if so, clear all jobs and restart
            for job in schedule.get_jobs():
                job.run()
                # if configuration file has been changed, clear all scheduled jobs and restart
                new_file_hash = calculate_file_hash(self.config_files)
                assert self.config_hash is not None
                if new_file_hash != self.config_hash:
                    self.logger.info(
                        f"""{hilight("[Config]", "info")} Config file changed, restarting monitor."""
                    )
                    schedule.clear()
                    break
            if not schedule.get_jobs():
                continue
            # subsequent runs will be scheduled runs
            while True:
                next_job = None
                for job in schedule.jobs:
                    if job.next_run is None:
                        continue
                    if next_job is None or next_job.next_run > job.next_run:
                        next_job = job
                if next_job is None:
                    # no more job
                    self.logger.warning(
                        f"""{hilight("[Search]", "fail")} No more active search job."""
                    )
                    sys.exit(0)
                # assert next_job is not None
                assert next_job.next_run is not None
                idle_seconds = schedule.idle_seconds() or 0
                if idle_seconds > 60:
                    # the sleep time might not be enough, causing this message
                    # to be sent repeatedly. Having a idle_seconds > 60 helps
                    # to reduce the frequency of this message.
                    self.logger.info(
                        f"""{hilight("[Search]", "info")} Next job to search {hilight(str(next(iter(next_job.tags))))} scheduled to run in {humanize.naturaldelta(idle_seconds)} at {next_job.next_run.strftime("%Y-%m-%d %H:%M:%S")}"""
                    )

                sleep_with_watchdog(
                    max(5, int(idle_seconds)),
                    self.config_files,
                )
                # if configuration file has been changed, clear all scheduled jobs and restart
                new_file_hash = calculate_file_hash(self.config_files)
                assert self.config_hash is not None
                if new_file_hash != self.config_hash:
                    self.logger.info(
                        f"""{hilight("[Config]", "info")} Config file changed, restarting monitor."""
                    )
                    schedule.clear()
                    break
                schedule.run_pending()

    def stop_monitor(self: "MarketplaceMonitor") -> None:
        """Stop the monitor."""
        for marketplace in self.active_marketplaces.values():
            marketplace.stop()
        if self.playwright is not None:
            self.playwright.stop()
        cache.close()

    def check_items(
        self: "MarketplaceMonitor", items: List[str] | None = None, for_item: str | None = None
    ) -> None:
        """Main function to monitor the marketplace."""
        # we reload the config file each time when a scan action is completed
        # this allows users to add/remove products dynamically.
        self.load_config_file()

        if for_item is not None:
            assert self.config is not None
            if for_item not in self.config.item:
                raise ValueError(
                    f"Item {for_item} not found in config, available items are {', '.join(self.config.item.keys())}."
                )

        self.load_ai_agents()

        post_urls = []
        for post_url in items or []:
            if post_url.isnumeric():
                post_url = f"https://www.facebook.com/marketplace/item/{post_url}/"

            if not post_url.startswith("https://www.facebook.com/marketplace/item"):
                raise ValueError(f"URL {post_url} is not a valid Facebook Marketplace URL.")
            post_urls.append(post_url)

        if not post_urls:
            raise ValueError("No URLs to check.")

        # we may or may not need a browser
        with sync_playwright() as p:
            # Open a new browser page.
            browser = None
            for post_url in post_urls or []:
                # check if item in config
                assert self.config is not None

                # which marketplace to check it?
                for marketplace_config in self.config.marketplace.values():
                    marketplace_class = supported_marketplaces[marketplace_config.name]
                    if marketplace_config.name in self.active_marketplaces:
                        marketplace = self.active_marketplaces[marketplace_config.name]
                    else:
                        marketplace = marketplace_class(marketplace_config.name, None, self.logger)
                        self.active_marketplaces[marketplace_config.name] = marketplace

                    # Configure might have been changed
                    marketplace.configure(marketplace_config)

                    # do we need a browser?
                    if (CacheType.ITEM_DETAILS.value, post_url.split("?")[0]) not in cache:
                        if browser is None:
                            self.logger.info(
                                f"""{hilight("[Search]", "info")} Starting a browser because the item was not checked before."""
                            )
                            browser = p.chromium.launch(headless=self.headless)
                            marketplace.set_browser(browser)

                    # ignore enabled
                    # do not search, get the item details directly
                    listing: SearchedItem = marketplace.get_item_details(post_url)

                    self.logger.info(
                        f"""{hilight("[Retrieve]", "succ")} Details of the item is found: {pretty_repr(listing)}"""
                    )

                    for item_config in self.config.item.values():
                        if for_item is not None and item_config.name != for_item:
                            continue
                        self.logger.info(
                            f"""{hilight("[Search]", "succ")} Checking {post_url} for item {item_config.name} with configuration {pretty_repr(item_config)}"""
                        )
                        marketplace.filter_item(listing, item_config)
                        self.evaluate_by_ai(listing, item_config=item_config)
                        if listing.user_notified_key in cache:
                            self.logger.info(
                                f"""{hilight("[Skip]", "succ")} Already sent notification for item {item_config.name}."""
                            )

    def evaluate_by_ai(
        self: "MarketplaceMonitor", item: SearchedItem, item_config: TItemConfig
    ) -> AIResponse:
        for agent in self.ai_agents:
            try:
                return agent.evaluate(item, item_config)
            except Exception as e:
                self.logger.error(
                    f"""{hilight("[AI]", "fail")} Failed to get an answer from {agent.config.name}: {e}"""
                )
                continue
        return AIResponse(5, AIResponse.NOT_EVALUATED)

    def notify_users(
        self: "MarketplaceMonitor",
        users: List[str],
        listings: List[SearchedItem],
        ratings: List[AIResponse],
    ) -> None:
        # get notification msg for this item
        p = inflect.engine()
        for user in users:
            msgs = []
            unnotified_listings = []
            for listing, rating in zip(listings, ratings):
                if listing.user_notified_key in cache and user in cache.get(
                    listing.user_notified_key, ()
                ):
                    continue
                self.logger.info(
                    f"""{hilight("[Search]", "succ")} New item found: {listing.title} with URL https://www.facebook.com{listing.post_url.split("?")[0]} for user {user}"""
                )
                if rating.comment == AIResponse.NOT_EVALUATED:
                    msgs.append(
                        (
                            f"{listing.title}\n"
                            f"{listing.price}, {listing.location}\n"
                            f"https://www.facebook.com{listing.post_url.split('?')[0]}"
                        )
                    )
                else:
                    msgs.append(
                        (
                            f"[{rating.conclusion} ({rating.score})] {listing.title}\n"
                            f"{listing.price}, {listing.location}\n"
                            f"https://www.facebook.com{listing.post_url.split('?')[0]}\n"
                            f"AI: {rating.comment}"
                        )
                    )

                unnotified_listings.append(listing)

            if not unnotified_listings:
                continue

            title = f"Found {len(msgs)} new {p.plural_noun(listing.name, len(msgs))} from {listing.marketplace}: "
            message = "\n\n".join(msgs)
            self.logger.info(
                f"""{hilight("[Notify]", "succ")} Sending {user} a message with title {hilight(title)} and message {hilight(message)}"""
            )
            assert self.config is not None
            assert self.config.user is not None
            try:
                User(user, self.config.user[user], logger=self.logger).notify(title, message)
                for listing in unnotified_listings:
                    cache.set(
                        listing.user_notified_key,
                        (
                            user,
                            *cache.get(listing.user_notified_key, ()),
                        ),
                        tag=CacheType.USER_NOTIFIED.value,
                    )
            except Exception as e:
                self.logger.error(
                    f"""{hilight("[Notify]", "fail")} Failed to notify {user}: {e}"""
                )
                continue
