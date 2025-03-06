import sys
import time
from logging import Logger
from pathlib import Path
from typing import ClassVar, List

import humanize
import inflect
import rich
import schedule  # type: ignore
from playwright.sync_api import Browser, Playwright, sync_playwright
from rich.pretty import pretty_repr
from rich.prompt import Prompt

from .ai import AIBackend, AIResponse
from .config import Config, supported_ai_backends, supported_marketplaces
from .listing import Listing
from .marketplace import Marketplace, TItemConfig, TMarketplaceConfig
from .notification import NotificationStatus
from .user import User
from .utils import (
    CounterItem,
    KeyboardMonitor,
    SleepStatus,
    amm_home,
    cache,
    calculate_file_hash,
    counter,
    doze,
    hilight,
)


class MarketplaceMonitor:
    active_marketplaces: ClassVar = {}

    def __init__(
        self: "MarketplaceMonitor",
        config_files: List[Path] | None,
        headless: bool | None,
        logger: Logger | None,
    ) -> None:
        for file_path in config_files or []:
            if not file_path.exists():
                raise FileNotFoundError(f"Config file {file_path} not found.")
        default_config = amm_home / "config.toml"
        self.config_files = ([default_config] if default_config.exists() else []) + (
            [x.expanduser().resolve() for x in config_files or []]
        )
        #
        self.config: Config | None = None
        self.config_hash: str | None = None
        self.headless = headless
        self.ai_agents: List[AIBackend] = []
        self.keyboard_monitor: KeyboardMonitor | None = None
        self.playwright: Playwright = sync_playwright().start()
        self.browser: Browser | None = None
        self.logger = logger

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
            except KeyboardInterrupt:
                raise
            except Exception as e:
                if last_invalid_hash != new_file_hash:
                    last_invalid_hash = new_file_hash
                    if self.logger:
                        self.logger.error(
                            f"""{hilight("[Config]", "fail")} Error parsing:\n\n{hilight(str(e), "fail")}\n\nPlease fix the configuration and I will try again as soon as you are done."""
                        )
                doze(60, self.config_files, self.keyboard_monitor)
                continue

    def load_ai_agents(self: "MarketplaceMonitor") -> None:
        """Load the AI agent."""
        assert self.config is not None
        for ai_config in (self.config.ai or {}).values():
            if ai_config.enabled is False:
                continue
            if (
                ai_config.provider is not None
                and ai_config.provider.lower() in supported_ai_backends
            ):
                ai_class = supported_ai_backends[ai_config.provider.lower()]
            elif ai_config.name.lower() in supported_ai_backends:
                ai_class = supported_ai_backends[ai_config.name.lower()]
            else:
                if self.logger:
                    self.logger.error(
                        f"""{hilight("[Config]", "fail")} Cannot determine an AI service provider from service name or provider."""
                    )
                continue

            try:
                self.ai_agents.append(ai_class(config=ai_config, logger=self.logger))
                # self.ai_agents[-1].connect()
                # self.logger.info(
                #     f"""{hilight("[AI]", "succ")} Connected to {hilight(ai_config.name)}"""
                # )
            except KeyboardInterrupt:
                raise
            except Exception as e:
                if self.logger:
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
        new_listings: List[Listing] = []
        listing_ratings = []
        # users to notify is determined from item, then marketplace, then all users
        assert self.config is not None
        users_to_notify = (
            item_config.notify or marketplace_config.notify or list(self.config.user.keys())
        )
        for listing in marketplace.search(item_config):
            # duplicated ID should not happen, but sellers could repost the same listing,
            # potentially under different seller names
            if listing.id in [x.id for x in new_listings] or listing.content in [
                x.content for x in new_listings
            ]:
                if self.logger:
                    self.logger.debug(f"Found duplicated result for {listing}")
                continue
            # if everyone has been notified
            if all(
                User(self.config.user[user], self.logger).notification_status(listing)
                == NotificationStatus.NOTIFIED
                for user in users_to_notify
            ):
                if self.logger:
                    self.logger.info(
                        f"""{hilight("[Skip]", "info")} Already sent notification for item {hilight(listing.title)}, skipping."""
                    )
                continue
            # for x in self.find_new_items(found_items)
            res = self.evaluate_by_ai(
                listing, item_config=item_config, marketplace_config=marketplace_config
            )
            if self.logger:
                self.logger.info(
                    f"""{hilight("[AI]", res.style)} {res.name or "AI"} concludes {hilight(f"{res.conclusion} ({res.score}): {res.comment}", res.style)} for listing {hilight(listing.title)}."""
                )
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
                if self.logger:
                    self.logger.info(
                        f"""{hilight("[Skip]", "fail")} Rating {hilight(f"{res.conclusion} ({res.score})")} for {listing.title} is below threshold {acceptable_rating}."""
                    )
                counter.increment(CounterItem.EXCLUDED_LISTING, item_config.name)
                continue
            new_listings.append(listing)
            listing_ratings.append(res)

        p = inflect.engine()
        if self.logger:
            self.logger.info(
                f"""{hilight("[Search]", "succ" if len(new_listings) > 0 else "fail")} {hilight(str(len(new_listings)))} new {p.plural_noun("listing", len(new_listings))} for {item_config.name} {p.plural_verb("is", len(new_listings))} found."""
            )
        if new_listings:
            counter.increment(
                CounterItem.NEW_VALIDATED_LISTING, item_config.name, len(new_listings)
            )
            for user in users_to_notify:
                User(self.config.user[user], logger=self.logger).notify(
                    new_listings, listing_ratings, item_config
                )
        time.sleep(5)

    def schedule_jobs(self: "MarketplaceMonitor") -> None:
        """Schedule jobs to run periodically."""
        # we reload the config file each time when a scan action is completed
        # this allows users to add/remove products dynamically.
        self.load_config_file()
        self.load_ai_agents()

        assert self.config is not None
        for marketplace_config in self.config.marketplace.values():
            if marketplace_config.enabled is False:
                continue
            marketplace_class = supported_marketplaces[marketplace_config.name]
            if marketplace_config.name in self.active_marketplaces:
                marketplace = self.active_marketplaces[marketplace_config.name]
            else:
                marketplace = marketplace_class(
                    marketplace_config.name, self.browser, self.keyboard_monitor, self.logger
                )
                self.active_marketplaces[marketplace_config.name] = marketplace

            # Configure might have been changed
            marketplace.configure(marketplace_config)
            for item_config in self.config.item.values():
                if item_config.enabled is False:
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
                                if self.logger:
                                    self.logger.info(
                                        f"""{hilight("[Schedule]", "info")} Scheduling to search for {item_config.name} every minute at {start_at[3:]}s"""
                                    )
                                scheduled = schedule.every().minute.at(start_at[3:])
                            elif start_at.startswith("*:"):
                                # '*:12:12' or  '*:12'
                                if self.logger:
                                    self.logger.info(
                                        f"""{hilight("[Schedule]", "info")} Scheduling to search for {item_config.name} every hour at {start_at[1:]}m"""
                                    )
                                scheduled = schedule.every().hour.at(
                                    start_at[1:] if start_at.count(":") == 1 else start_at[2:]
                                )
                            else:
                                # '12:12:12' or '12:12'
                                if self.logger:
                                    self.logger.info(
                                        f"""{hilight("[Schedule]", "ss")} Scheduling to search for {item_config.name} every day at {start_at}"""
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
                        if self.logger:
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

    def handle_pause(self: "MarketplaceMonitor") -> None:
        """Handle interruption signal."""
        if self.keyboard_monitor is None or not self.keyboard_monitor.is_paused():
            return

        rich.print(counter)
        if not self.keyboard_monitor.confirm():
            return

        # now we should go to an interactive session
        while True:
            while True:
                url = (
                    Prompt.ask(
                        f"""\nEnter an {hilight("ID")} or a {hilight("URL")} to check, or {hilight("exit")}."""
                    )
                    .strip("\x1b")
                    .strip()
                )

                if not url.isnumeric() and not url.startswith("https://"):
                    if url.endswith("exit"):
                        url = "exit"
                        break
                    if url:
                        print(f'Invalid input "{url}". Please try again.')
                else:
                    break

            if url == "exit":
                break

            try:
                self.check_items([url], for_item=None)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                if self.logger:
                    self.logger.debug(f"Failed to check item {url}: {e}")

    def start_monitor(self: "MarketplaceMonitor") -> None:
        """Main function to monitor the marketplace."""
        # start a browser with playwright, cannot use with statement since the jobs will be
        # executed outside of the scope by schedule job runner
        self.keyboard_monitor = KeyboardMonitor()
        self.keyboard_monitor.start()

        # Open a new browser page.
        self.load_config_file()
        assert self.config is not None
        self.browser = self.playwright.chromium.launch(
            headless=self.headless, proxy=self.config.monitor.get_proxy_options()
        )
        #
        assert self.browser is not None
        while True:
            self.handle_pause()
            self.schedule_jobs()
            if not schedule.get_jobs():
                # this actually should not happen because at least one item is required for the configuration file
                if self.logger:
                    self.logger.error(
                        "No search job is defined. Please add search items to your config file."
                    )
                self.handle_pause()
                if doze(60, self.config_files, self.keyboard_monitor) == SleepStatus.BY_KEYBOARD:
                    self.keyboard_monitor.set_paused(True)
                continue
            # run all jobs at the first time, then on their own schedule
            # we could have used schedule.run_all() but we would like to check if
            # configuration file has been changed, if so, clear all jobs and restart
            for job in schedule.get_jobs():
                job.run()
                self.handle_pause()
                # if configuration file has been changed, clear all scheduled jobs and restart
                new_file_hash = calculate_file_hash(self.config_files)
                assert self.config_hash is not None
                if new_file_hash != self.config_hash:
                    if self.logger:
                        self.logger.info(
                            f"""{hilight("[Config]", "info")} Config file changed, restarting monitor."""
                        )
                    schedule.clear()
                    break
            if not schedule.get_jobs():
                continue
            # subsequent runs will be scheduled runs
            while True:
                next_job: schedule.Job | None = None
                for job in schedule.jobs:
                    if job.next_run is None:
                        continue
                    if next_job is None or (
                        next_job.next_run and next_job.next_run > job.next_run
                    ):
                        next_job = job

                if next_job is None:
                    # no more job
                    if self.logger:
                        self.logger.warning(
                            f"""{hilight("[Schedule]", "fail")} No more active search job."""
                        )
                    sys.exit(0)
                # assert next_job is not None
                assert next_job.next_run is not None
                idle_seconds = schedule.idle_seconds() or 0
                if idle_seconds > 60:
                    # the sleep time might not be enough, causing this message
                    # to be sent repeatedly. Having a idle_seconds > 60 helps
                    # to reduce the frequency of this message.
                    if self.logger:
                        self.logger.info(
                            f"""{hilight("[Schedule]", "info")} Next job to search {hilight(str(next(iter(next_job.tags))))} scheduled to run in {humanize.naturaldelta(idle_seconds)} at {next_job.next_run.strftime("%Y-%m-%d %H:%M:%S")}"""
                        )

                # sleep at most 1 hr, and print updated "next job" message
                res = doze(
                    min(max(5, int(idle_seconds)), 60 * 60),
                    self.config_files,
                    self.keyboard_monitor,
                )
                if res == SleepStatus.BY_FILE_CHANGE:
                    # if configuration file has been changed, clear all scheduled jobs and restart
                    new_file_hash = calculate_file_hash(self.config_files)
                    assert self.config_hash is not None
                    if new_file_hash != self.config_hash:
                        if self.logger:
                            self.logger.info(
                                f"""{hilight("[Config]", "info")} Config file changed, restarting monitor."""
                            )
                        schedule.clear()
                        break
                elif res == SleepStatus.BY_KEYBOARD:
                    self.keyboard_monitor.set_paused(True)

                self.handle_pause()
                schedule.run_pending()

    def stop_monitor(self: "MarketplaceMonitor") -> None:
        """Stop the monitor."""
        for marketplace in self.active_marketplaces.values():
            marketplace.stop()
        self.playwright.stop()
        if self.keyboard_monitor:
            self.keyboard_monitor.stop()
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

        # Open a new browser page.
        for post_url in post_urls or []:
            # check if item in config
            assert self.config is not None

            # which marketplace to check it?
            for marketplace_config in self.config.marketplace.values():
                if marketplace_config.enabled is False:
                    continue
                marketplace_class = supported_marketplaces[marketplace_config.name]
                if marketplace_config.name in self.active_marketplaces:
                    marketplace = self.active_marketplaces[marketplace_config.name]
                else:
                    marketplace = marketplace_class(
                        marketplace_config.name, None, None, self.logger
                    )
                    self.active_marketplaces[marketplace_config.name] = marketplace

                # Configure might have been changed
                marketplace.configure(marketplace_config)

                # do we need a browser?
                if Listing.from_cache(post_url) is None:
                    if self.browser is None:
                        if self.logger:
                            self.logger.info(
                                f"""{hilight("[Search]", "info")} Starting a browser because the item was not checked before."""
                            )
                        self.browser = self.playwright.chromium.launch(
                            headless=self.headless, proxy=self.config.monitor.get_proxy_options()
                        )
                        marketplace.set_browser(self.browser)

                # ignore enabled
                if for_item is None:
                    # get by asking user
                    name = None
                    item_names = list(self.config.item.keys())
                    if len(item_names) > 1:
                        name = Prompt.ask(
                            f"""Enter name of {hilight("search item")}""", choices=item_names
                        )
                    item_config = self.config.item[name or item_names[0]]
                else:
                    item_config = self.config.item[for_item]

                # do not search, get the item details directly
                listing: Listing = marketplace.get_listing_details(post_url, item_config)

                if self.logger:
                    self.logger.info(
                        f"""{hilight("[Retrieve]", "succ")} Details of the item is found: {pretty_repr(listing)}"""
                    )

                if self.logger:
                    self.logger.info(
                        f"""{hilight("[Search]", "succ")} Checking {post_url} for item {item_config.name} with configuration {pretty_repr(item_config)}"""
                    )
                marketplace.check_listing(listing, item_config)
                rating = self.evaluate_by_ai(
                    listing, item_config=item_config, marketplace_config=marketplace_config
                )
                if self.logger:
                    self.logger.info(
                        f"""{hilight("[AI]", rating.style)} {rating.name or "AI"} concludes {hilight(f"{rating.conclusion} ({rating.score}): {rating.comment}", rating.style)} for listing {hilight(listing.title)}."""
                    )
                # notification status?
                users_to_notify = (
                    item_config.notify
                    or marketplace_config.notify
                    or list(self.config.user.keys())
                )
                # for notification usages
                listing.name = item_config.name
                for user in users_to_notify:
                    ns = User(self.config.user[user], self.logger).notification_status(listing)
                    if self.logger:
                        if ns == NotificationStatus.NOTIFIED:
                            self.logger.info(
                                f"""{hilight("[Notify]", "succ")} Notified {user} about {post_url}."""
                            )
                        elif ns == NotificationStatus.EXPIRED:
                            self.logger.info(
                                f"""{hilight("[Notify]", "info")} Already notified {user} about {post_url}. The notification is ow expired."""
                            )
                        elif ns == NotificationStatus.LISTING_CHANGED:
                            self.logger.info(
                                f"""{hilight("[Notify]", "info")} Already notified {user} about {post_url}, but the listing is now changed."""
                            )
                        else:
                            self.logger.info(
                                f"""{hilight("[Notify]", "info")} Not notified {user} about {post_url} yet."""
                            )

                    # testing notification
                    # User(self.config.user[user], logger=self.logger).notify(
                    #     [listing], [rating], item_config, force=True
                    # )

    def evaluate_by_ai(
        self: "MarketplaceMonitor",
        item: Listing,
        item_config: TItemConfig,
        marketplace_config: TMarketplaceConfig,
    ) -> AIResponse:
        if item_config.ai is not None:
            ai_agents = item_config.ai
        elif marketplace_config.ai is not None:
            ai_agents = marketplace_config.ai
        else:
            ai_agents = None
        #
        for agent in self.ai_agents:
            if ai_agents is not None and agent.config.name not in ai_agents:
                continue
            try:
                return agent.evaluate(item, item_config, marketplace_config)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                if self.logger:
                    self.logger.error(
                        f"""{hilight("[AI]", "fail")} Failed to get an answer from {agent.config.name}: {e}"""
                    )
                continue
        return AIResponse(5, AIResponse.NOT_EVALUATED)
