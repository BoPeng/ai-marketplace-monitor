import time
from collections import defaultdict
from dataclasses import dataclass, fields
from enum import Enum
from logging import Logger
from typing import Any, ClassVar, DefaultDict, List, Optional, Tuple, Type

import inflect

from .ai import AIResponse  # type: ignore
from .listing import Listing
from .utils import BaseConfig, hilight


class NotificationStatus(Enum):
    NOT_NOTIFIED = 0
    EXPIRED = 1
    NOTIFIED = 2
    LISTING_CHANGED = 3
    LISTING_DISCOUNTED = 4


@dataclass
class NotificationConfig(BaseConfig):
    required_fields: ClassVar[List[str]] = []

    max_retries: int = 5
    retry_delay: int = 60

    def handle_max_retries(self: "NotificationConfig") -> None:
        if not isinstance(self.max_retries, int):
            raise ValueError("max_retries must be an integer.")

    def handle_retry_delay(self: "NotificationConfig") -> None:
        if not isinstance(self.retry_delay, int):
            raise ValueError("retry_delay must be an integer.")

    def _has_required_fields(self: "NotificationConfig") -> bool:
        return all(getattr(self, field, None) is not None for field in self.required_fields)

    @classmethod
    def get_config(
        cls: Type["NotificationConfig"], **kwargs: Any
    ) -> Optional["NotificationConfig"]:
        """Get the specific subclass name from the specified keys, for validation purposes"""
        for subclass in cls.__subclasses__():
            acceptable_keys = {field.name for field in fields(subclass)}
            if all(name in acceptable_keys for name in kwargs.keys()):
                return subclass(**{k: v for k, v in kwargs.items() if k != "type"})
            res = subclass.get_config(**kwargs)
            if res is not None:
                return res
        return None

    @classmethod
    def notify_all(
        cls: type["NotificationConfig"], config: "NotificationConfig", *args, **kwargs: Any
    ) -> bool:
        """Call the notify method of all subclasses"""
        succ = []
        for subclass in cls.__subclasses__():
            if hasattr(subclass, "notify") and subclass.__name__ not in [
                "UserConfig",
                "PushNotificationConfig",
            ]:
                succ.append(subclass.notify(config, *args, **kwargs))
            # subclases
            succ.append(subclass.notify_all(config, *args, **kwargs))
        return any(succ)

    def send_message_with_retry(
        self: "NotificationConfig",
        title: str,
        message: str,
        logger: Logger | None = None,
    ) -> bool:
        if not self._has_required_fields():
            return False

        for attempt in range(self.max_retries):
            try:
                res = self.send_message(title=title, message=message, logger=logger)
                if logger:
                    logger.info(
                        f"""{hilight("[Notify]", "succ")} Sent {self.name} a message with title {hilight(title)}"""
                    )
                return res
            except KeyboardInterrupt:
                raise
            except Exception as e:
                if logger:
                    logger.debug(
                        f"""{hilight("[Notify]", "fail")} Attempt {attempt + 1} failed: {e}"""
                    )
                if attempt < self.max_retries - 1:
                    if logger:
                        logger.debug(
                            f"""{hilight("[Notify]", "fail")} Retrying in {self.retry_delay} seconds..."""
                        )
                    time.sleep(self.retry_delay)
                else:
                    if logger:
                        logger.error(
                            f"""{hilight("[Notify]", "fail")} Max retries reached. Failed to push note to {self.name}."""
                        )
                    return False
        return False

    def send_message(
        self: "NotificationConfig",
        title: str,
        message: str,
        logger: Logger | None = None,
    ) -> bool:
        raise NotImplementedError("send_message needs to be defined.")


@dataclass
class PushNotificationConfig(NotificationConfig):

    def notify(
        self: "PushNotificationConfig",
        listings: List[Listing],
        ratings: List[AIResponse],
        notification_status: List[NotificationStatus],
        force: bool = False,
        logger: Logger | None = None,
    ) -> bool:
        if not self._has_required_fields():
            return False
        #
        # we send listings with different status with different messages
        msgs: DefaultDict[NotificationStatus, List[Tuple[Listing, str]]] = defaultdict(list)
        p = inflect.engine()
        for listing, rating, ns in zip(listings, ratings, notification_status):
            if ns == NotificationStatus.NOTIFIED and not force:
                continue
            msg = (
                (
                    f"{listing.title}\n{listing.price}, {listing.location}\n"
                    f"{listing.post_url.split('?')[0]}"
                )
                if rating.comment == AIResponse.NOT_EVALUATED
                else (
                    f"[{rating.conclusion} ({rating.score})] {listing.title}\n"
                    f"{listing.price}, {listing.location}\n"
                    f"{listing.post_url.split('?')[0]}\n"
                    f"AI: {rating.comment}"
                )
            )
            msgs[ns].append((listing, msg))

        if not msgs:
            if logger:
                logger.debug("No new listings to notify.")
            return False

        for ns, listing_msg in msgs.items():
            if ns == NotificationStatus.NOT_NOTIFIED:
                title = f"Found {len(listing_msg)} new {p.plural_noun(listing.name, len(listing_msg))} from {listing.marketplace}"
            elif ns == NotificationStatus.EXPIRED:
                title = f"Another look at {len(listing_msg)} {p.plural_noun(listing.name, len(listing_msg))} from {listing.marketplace}"
            elif ns == NotificationStatus.LISTING_CHANGED:
                title = f"Found {len(listing_msg)} updated {p.plural_noun(listing.name, len(listing_msg))} from {listing.marketplace}"
            elif ns == NotificationStatus.LISTING_DISCOUNTED:
                title = f"Found {len(listing_msg)} discounted {p.plural_noun(listing.name, len(listing_msg))} from {listing.marketplace}"
            else:
                title = f"Resend {len(listing_msg)} {p.plural_noun(listing.name, len(listing_msg))} from {listing.marketplace}"

            message = "\n\n".join([x[1] for x in listing_msg])
            #
            if not self.send_message_with_retry(title, message, logger=logger):
                return False
        return True
