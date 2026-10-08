import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging import Logger
from typing import Any, Dict, List, Tuple, Type

from diskcache import Cache  # type: ignore

from .ai import AIResponse  # type: ignore
from .email_notify import EmailNotificationConfig
from .evaluations import NOTIFIED, EvaluationRecord, record_evaluation
from .listing import Listing
from .marketplace import TItemConfig
from .notification import TEST_TIMEOUT, ChannelResult, NotificationConfig, NotificationStatus
from .ntfy import NtfyNotificationConfig
from .pushbullet import PushbulletNotificationConfig
from .pushover import PushoverNotificationConfig
from .telegram import TelegramNotificationConfig
from .unitysvc_notify import UnitySVCNotificationConfig
from .utils import CacheType, CounterItem, cache, convert_to_seconds, counter, hilight


@dataclass
class UserConfig(
    EmailNotificationConfig,
    PushbulletNotificationConfig,
    PushoverNotificationConfig,
    NtfyNotificationConfig,
    TelegramNotificationConfig,
    UnitySVCNotificationConfig,
):
    """UserConfiguration

    Derive from EmailNotificationConfig, PushbulletNotificationConfig allows
    the user config class to use settings from both classes.

    It is possible to dynamically added these classes as parent class
    of UserConfig, but it is troublesome to make sure that these classes
    are imported.
    """

    notify_with: List[str] | None = None
    remind: int | None = None
    # local time (HH:MM) of the daily digest, like start_at; None for no digest
    digest_at: str | None = None
    # notification sections that receive the digest, like notify_with; None for all of them
    digest_with: List[str] | None = None

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

    def handle_digest_at(self: "UserConfig") -> None:
        if self.digest_at is None or self.digest_at is False:
            self.digest_at = None
            return

        matched = (
            re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", self.digest_at)
            if isinstance(self.digest_at, str)
            else None
        )
        if matched is None or int(matched.group(1)) > 23 or int(matched.group(2)) > 59:
            raise ValueError(
                f"User {hilight(self.name)} digest_at must be a local time such as '08:00'."
            )
        # schedule needs two-digit hours
        self.digest_at = f"{int(matched.group(1)):02d}:{matched.group(2)}"

    def handle_digest_with(self: "UserConfig") -> None:
        if self.digest_with is None:
            return

        if isinstance(self.digest_with, str):
            self.digest_with = [self.digest_with]

        if (
            not isinstance(self.digest_with, list)
            or not self.digest_with
            or not all(isinstance(x, str) for x in self.digest_with)
        ):
            raise ValueError(
                f"User {hilight(self.name)} digest_with must be a list of notification section names."
            )

    def handle_notify_with(self: "UserConfig") -> None:
        if self.notify_with is None:
            return

        if isinstance(self.notify_with, str):
            self.notify_with = [self.notify_with]

        if not isinstance(self.notify_with, list) or not all(
            isinstance(x, str) for x in self.notify_with
        ):
            raise ValueError(
                f"Item {hilight(self.name)} notify_with must be a list of notification section values."
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
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), listing.hash, listing.price),
            tag=CacheType.USER_NOTIFIED.value,
        )

    def _is_discounted(self: "User", old_price: str | None, new_price: str | None) -> bool:
        def to_price(price_str: str | None):
            if not price_str or price_str == "**unspecified**":
                # invalid price is "very expensive", the new one might be cheaper.
                return 999999999
            matched = re.match(r"(\D*)\d+", price_str)
            if matched:
                currency = matched.group(1).strip()
                price_str = price_str.replace(currency, "")
            try:
                return float(price_str.replace(",", "").replace(" ", ""))
            except:
                return 999999999

        return to_price(old_price) > to_price(new_price)

    def notification_status(
        self: "User", listing: Listing, local_cache: Cache | None = None
    ) -> NotificationStatus:
        notified = (cache if local_cache is None else local_cache).get(self.notified_key(listing))
        # not notified before, or saved information is of old type
        if notified is None:
            return NotificationStatus.NOT_NOTIFIED

        if isinstance(notified, str):
            # old style cache
            notification_date, listing_hash, listing_price = notified, None, None
        else:
            assert isinstance(notified, tuple)
            if len(notified) == 2:
                notification_date, listing_hash, listing_price = (*notified, None)
            else:
                notification_date, listing_hash, listing_price = notified

        if listing_price is not None and self._is_discounted(listing_price, listing.price):
            return NotificationStatus.LISTING_DISCOUNTED

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

        if NotificationConfig.notify_all(
            self.config, listings, ratings, statuses, force=force, logger=self.logger
        ):
            counter.increment(CounterItem.NOTIFICATIONS_SENT, item_config.name)
            for listing, rating, ns in zip(listings, ratings, statuses):
                if force or ns != NotificationStatus.NOTIFIED:
                    self.to_cache(listing, local_cache=local_cache)
                    rated = rating.comment != AIResponse.NOT_EVALUATED
                    record_evaluation(
                        EvaluationRecord.from_listing(
                            listing,
                            item=item_config.name,
                            stage=NOTIFIED,
                            rating=rating.score if rated else None,
                            ai_comment=rating.comment if rated else "",
                        ),
                        local_cache=local_cache,
                    )


def send_test_notifications(
    users: Dict[str, UserConfig],
    name: str | None = None,
    logger: Logger | None = None,
    timeout: float = TEST_TIMEOUT,
) -> Dict[str, List[ChannelResult]]:
    """Send a test message through every channel of every enabled user, or of one user.

    Returns the results by user (an empty list: the user has no channel). Nothing is written
    to the cache; see ``NotificationConfig.test_all``. Raises KeyError for an unknown user.
    """
    if name is not None:
        if name not in users:
            raise KeyError(f"There is no user {name}. Users: {', '.join(users) or 'none'}.")
        names = [name]
    else:
        names = [n for n, u in users.items() if u.enabled is not False]
    return {
        n: NotificationConfig.test_all(users[n], timeout=timeout, logger=logger) for n in names
    }
