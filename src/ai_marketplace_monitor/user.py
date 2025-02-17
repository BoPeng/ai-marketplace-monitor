from dataclasses import dataclass
from datetime import datetime, timedelta
from logging import Logger
from typing import Any, List, Tuple, Type

from diskcache import Cache  # type: ignore

from .ai import AIResponse  # type: ignore
from .listing import Listing
from .marketplace import TItemConfig
from .pushbullet import PushbulletConfig
from .smtp import SMTPConfig
from .utils import (
    CacheType,
    CounterItem,
    NotificationStatus,
    cache,
    convert_to_seconds,
    counter,
    hilight,
)


@dataclass
class UserConfig(SMTPConfig, PushbulletConfig):
    # this argument is required
    email: List[str] | None = None
    smtp: str | None = None
    remind: int | None = None

    def handle_pushbullet_token(self: "UserConfig") -> None:
        if self.pushbullet_token is None:
            return
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
            except KeyboardInterrupt:
                raise
            except Exception as e:
                raise ValueError(
                    f"Item {hilight(self.name)} remind {self.remind} is not recognized."
                ) from e

        if not isinstance(self.remind, int):
            raise ValueError(
                f"Item {hilight(self.name)} remind must be an time (e.g. 1 day) or false."
            )

    def handle_email(self: "UserConfig") -> None:
        if self.email is None:
            return
        if isinstance(self.email, str):
            self.email = [self.email]
        if not isinstance(self.email, list) or not all(
            (isinstance(x, str) and "@" in x and "." in x.split("@")[1]) for x in self.email
        ):
            raise ValueError(
                f"Item {hilight(self.name)} email must be a string or list of string."
            )

    def handle_smtp(self: "UserConfig") -> None:
        if self.smtp is None:
            return
        if not isinstance(self.smtp, str):
            raise ValueError(
                f"Item {hilight(self.name)} smtp must be a valid smtp server configuration name."
            )


class User:

    def __init__(self: "User", config: UserConfig, logger: Logger | None = None) -> None:
        self.name = config.name
        self.config = config
        self.logger = logger

    @classmethod
    def get_config(cls: Type["User"], **kwargs: Any) -> UserConfig:
        return UserConfig(**kwargs)

    def notified_key(self: "User", listing: Listing) -> Tuple[str, str, str, str]:
        return (CacheType.USER_NOTIFIED.value, listing.marketplace, listing.id, self.name)

    def to_cache(self: "User", listing: Listing, local_cache: Cache | None = None) -> None:
        (cache if local_cache is None else local_cache).set(
            self.notified_key(listing),
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), listing.hash),
            tag=CacheType.USER_NOTIFIED.value,
        )

    def notification_status(
        self: "User", listing: Listing, local_cache: Cache | None = None
    ) -> NotificationStatus:
        notified = (cache if local_cache is None else local_cache).get(self.notified_key(listing))
        # not notified before, or saved information is of old type
        if notified is None:
            return NotificationStatus.NOT_NOTIFIED

        if isinstance(notified, str):
            # old style cache
            notification_date, listing_hash = notified, None
        else:
            notification_date, listing_hash = notified

        # if listing_hash is not None, we need to check if the listing is still valid
        if listing_hash is not None and listing_hash != listing.hash:
            return NotificationStatus.LISTING_CHANGED

        # notified before and remind is None, so one notification will remain valid forever
        if self.config.remind is None:
            return NotificationStatus.NOTIFIED

        # if remind is not None, we need to check the time
        expired = datetime.strptime(notification_date, "%Y-%m-%d %H:%M:%S") + timedelta(
            seconds=self.config.remind
        )
        # if expired is in the future, user is already notified.
        return (
            NotificationStatus.NOTIFIED if expired > datetime.now() else NotificationStatus.EXPIRED
        )

    def time_since_notification(
        self: "User", listing: Listing, local_cache: Cache | None = None
    ) -> int:
        key = self.notified_key(listing)
        notified = (cache if local_cache is None else local_cache).get(key)
        if notified is None:
            return -1

        notification_date = notified if isinstance(notified, str) else notified[0]
        return (datetime.now() - datetime.strptime(notification_date, "%Y-%m-%d %H:%M:%S")).seconds

    def notify(
        self: "User",
        listings: List[Listing],
        ratings: List[AIResponse],
        item_config: TItemConfig,
        local_cache: Cache | None = None,
        force: bool = False,
    ) -> None:
        if self.config.enabled is False:
            if self.logger:
                self.logger.info(
                    f"""{hilight("[Notify]", "skip")} User {hilight(self.name)} is disabled."""
                )
            return
        statuses = [self.notification_status(listing, local_cache) for listing in listings]
        if self.config.notify_through_pushbullet(
            listings, ratings, statuses, force=force, logger=self.logger
        ) or self.config.notify_through_email(
            self.config.email, listings, ratings, statuses, force=force, logger=self.logger
        ):
            counter.increment(CounterItem.NOTIFICATIONS_SENT, item_config.name)
            for listing, ns in zip(listings, statuses):
                if force or ns != NotificationStatus.NOTIFIED:
                    self.to_cache(listing, local_cache=local_cache)
