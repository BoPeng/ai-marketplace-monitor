import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging import Logger
from typing import Any, List, Tuple, Type

import humanize
import inflect
from pushbullet import Pushbullet  # type: ignore

from .ai import AIResponse  # type: ignore
from .listing import Listing
from .utils import (
    CacheType,
    CounterItem,
    DataClassWithHandleFunc,
    NotificationStatus,
    cache,
    convert_to_seconds,
    counter,
    hilight,
)


@dataclass
class UserConfig(DataClassWithHandleFunc):
    # this argument is required
    pushbullet_token: str
    remind: int | None = None

    def handle_pushbullet_token(self: "UserConfig") -> None:
        if not isinstance(self.pushbullet_token, str) or not self.pushbullet_token:
            raise ValueError("user requires an non-empty pushbullet_token.")
        self.pushbullet_token = self.pushbullet_token.strip()

    def handle_remind(self: "UserConfig") -> None:
        if self.remind is None:
            return

        if self.remind is False:
            self.remind = None
            return

        if self.remind is True:
            # if set to true but no specific time, set to 1 day
            self.remind = 60 * 60 * 24
            return

        if isinstance(self.remind, str):
            try:
                self.remind = convert_to_seconds(self.remind)
                if self.remind < 60 * 60:
                    raise ValueError(f"Item {hilight(self.name)} remind must be at least 1 hour.")
            except Exception as e:
                raise ValueError(
                    f"Item {hilight(self.name)} remind {self.remind} is not recognized."
                ) from e

        if not isinstance(self.remind, int):
            raise ValueError(
                f"Item {hilight(self.name)} remind must be an time (e.g. 1 day) or false."
            )


class User:

    def __init__(self: "User", config: UserConfig, logger: Logger | None) -> None:
        self.name = config.name
        self.config = config
        self.logger = logger

    @classmethod
    def get_config(cls: Type["User"], **kwargs: Any) -> UserConfig:
        return UserConfig(**kwargs)

    def notified_key(self: "User", listing: Listing) -> Tuple[str, str, str, str]:
        return (CacheType.USER_NOTIFIED.value, listing.marketplace, listing.id, self.name)

    def notification_status(self: "User", listing: Listing) -> NotificationStatus:
        notified = cache.get(self.notified_key(listing))
        # not notified before
        if notified is None:
            return NotificationStatus.NOT_NOTIFIED
        # notified before and remind is None, so one notification will remain valid forever
        if self.config.remind is None:
            return NotificationStatus.NOTIFIED
        # if remind is not None, we need to check the time
        expired = datetime.strptime(notified, "%Y-%m-%d %H:%M:%S") + timedelta(
            seconds=self.config.remind
        )
        # if expired is in the future, user is already notified.
        return (
            NotificationStatus.NOTIFIED if expired > datetime.now() else NotificationStatus.EXPIRED
        )

    def time_since_notification(self: "User", listing: Listing) -> int:
        key = self.notified_key(listing)
        notified = cache.get(key)
        if notified is None:
            return -1
        return (datetime.now() - datetime.strptime(notified, "%Y-%m-%d %H:%M:%S")).seconds

    def notify(self: "User", listings: List[Listing], ratings: List[AIResponse]) -> None:
        msgs = []
        unnotified_listings = []
        p = inflect.engine()
        for listing, rating in zip(listings, ratings):
            ns = self.notification_status(listing)
            if ns == NotificationStatus.NOTIFIED:
                if self.logger:
                    self.logger.info(
                        f"""{hilight("[Notify]", "info")} {self.name} was notified for {listing.title} {humanize.naturaltime(self.time_since_notification(listing))}"""
                    )
                return
            if ns == NotificationStatus.EXPIRED:
                if self.logger:
                    self.logger.info(
                        f"""{hilight("[Notify]", "info")} {self.name} was notified for {listing.title} {humanize.naturaltime(self.time_since_notification(listing))}, which has been expired."""
                    )
            else:
                if self.logger:
                    self.logger.info(
                        f"""{hilight("[Search]", "succ")} New item found: {listing.title} with URL https://www.facebook.com{listing.post_url.split("?")[0]} for user {self.name}"""
                    )

            counter.increment(
                CounterItem.REMINDERS
                if ns == NotificationStatus.EXPIRED
                else CounterItem.NOTIFICATIONS
            )
            if rating.comment == AIResponse.NOT_EVALUATED:
                msg_prefix = "[REMINDER] " if ns == NotificationStatus.EXPIRED else ""
                msgs.append(
                    (
                        f"{msg_prefix}{listing.title}\n{listing.price}, {listing.location}\n"
                        f"https://www.facebook.com{listing.post_url.split('?')[0]}"
                    )
                )
            else:
                msg_prefix = "REMINDER " if ns == NotificationStatus.EXPIRED else ""
                msgs.append(
                    (
                        f"[{msg_prefix}{rating.conclusion} ({rating.score})] {listing.title}\n"
                        f"{listing.price}, {listing.location}\n"
                        f"https://www.facebook.com{listing.post_url.split('?')[0]}\n"
                        f"AI: {rating.comment}"
                    )
                )

            unnotified_listings.append(listing)

        if not unnotified_listings:
            return

        title = f"Found {len(msgs)} new {p.plural_noun(listing.name, len(msgs))} from {listing.marketplace}: "
        message = "\n\n".join(msgs)
        if self.logger:
            self.logger.info(
                f"""{hilight("[Notify]", "succ")} Sending {self.name} a message with title {hilight(title)} and message {hilight(message)}"""
            )
        #
        if self.send_pushbullet_message(title, message):
            for listing in unnotified_listings:
                cache.set(
                    self.notified_key(listing),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    tag=CacheType.USER_NOTIFIED.value,
                )

    def send_pushbullet_message(
        self: "User", title: str, message: str, max_retries: int = 6, delay: int = 10
    ) -> bool:
        pb = Pushbullet(self.config.pushbullet_token)

        for attempt in range(max_retries):
            try:
                pb.push_note(title, message)
                return True
            except Exception as e:
                if self.logger:
                    self.logger.debug(
                        f"""{hilight("[Notify]", "fail")} Attempt {attempt + 1} failed: {e}"""
                    )
                if attempt < max_retries - 1:
                    if self.logger:
                        self.logger.debug(
                            f"""{hilight("[Notify]", "fail")} Retrying in {delay} seconds..."""
                        )
                    time.sleep(delay)
                else:
                    if self.logger:
                        self.logger.error(
                            f"""{hilight("[Notify]", "fail")} Max retries reached. Failed to push note to {self.name}."""
                        )
                    return False
        return False
