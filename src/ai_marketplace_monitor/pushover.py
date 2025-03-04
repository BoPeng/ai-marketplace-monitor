import time
from collections import defaultdict
from logging import Logger
from typing import DefaultDict, List, Tuple

import inflect
from pushover import Client  # type: ignore

from .ai import AIResponse  # type: ignore
from .listing import Listing
from .notification import NotificationConfig, NotificationStatus
from .utils import hilight, value_from_environ


class PushoverNotificationConfig(NotificationConfig):
    pushover_user_id: str | None = None
    pushover_api_token: str | None = None

    def handle_pushover_user_id(self: "PushoverNotificationConfig") -> None:
        if self.pushover_user_id is None:
            return

        self.pushover_user_id = value_from_environ(self.pushover_user_id)

        if not isinstance(self.pushover_user_id, str) or not self.pushover_user_id:
            raise ValueError("An non-empty pushover_user_id is needed.")
        self.pushover_user_id = self.pushover_user_id.strip()

    def handle_pushover_api_token(self: "PushoverNotificationConfig") -> None:
        if self.pushover_api_token is None:
            return

        self.pushover_api_token = value_from_environ(self.pushover_api_token)

        if not isinstance(self.pushover_api_token, str) or not self.pushover_api_token:
            raise ValueError("user requires an non-empty pushover_api_token.")
        self.pushover_api_token = self.pushover_api_token.strip()

    def notify(
        self: "PushoverNotificationConfig",
        listings: List[Listing],
        ratings: List[AIResponse],
        notification_status: List[NotificationStatus],
        force: bool = False,
        logger: Logger | None = None,
    ) -> bool:
        if not self.pushover_user_id:
            if logger:
                logger.debug("No pushover_user_id specified.")
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
            else:
                title = f"Resend {len(listing_msg)} {p.plural_noun(listing.name, len(listing_msg))} from {listing.marketplace}"

            message = "\n\n".join([x[1] for x in listing_msg])
            #
            if not self.send_pushover_message(title, message, logger=logger):
                return False
        return True

    def send_pushover_message(
        self: "PushoverNotificationConfig",
        title: str,
        message: str,
        max_retries: int = 6,
        delay: int = 10,
        logger: Logger | None = None,
    ) -> bool:
        if not self.pushover_user_id or not self.pushover_api_token:
            if logger:
                logger.debug("No pushover_user_id or pushover_api_token specified.")
            return False

        try:
            client = Client(self.pushover_user_id, self.pushover_api_token)
        except Exception as e:
            if logger:
                logger.error(
                    f"""{hilight("[Notify]", "fail")} Failed to create Pushover instance: {e}"""
                )
            return False

        for attempt in range(max_retries):
            try:
                client.send_message(
                    message + "\n\nSent by https://github.com/BoPeng/ai-marketplace-monitor",
                    title=title,
                )
                if logger:
                    logger.info(
                        f"""{hilight("[Notify]", "succ")} Sent {self.name} a message with title {hilight(title)}"""
                    )
                return True
            except KeyboardInterrupt:
                raise
            except Exception as e:
                if logger:
                    logger.debug(
                        f"""{hilight("[Notify]", "fail")} Attempt {attempt + 1} failed: {e}"""
                    )
                if attempt < max_retries - 1:
                    if logger:
                        logger.debug(
                            f"""{hilight("[Notify]", "fail")} Retrying in {delay} seconds..."""
                        )
                    time.sleep(delay)
                else:
                    if logger:
                        logger.error(
                            f"""{hilight("[Notify]", "fail")} Max retries reached. Failed to push note to {self.name}."""
                        )
                    return False
        return False
