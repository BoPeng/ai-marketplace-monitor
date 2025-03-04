import time
from collections import defaultdict
from dataclasses import dataclass
from logging import Logger
from typing import DefaultDict, List, Tuple

import inflect
from pushbullet import Pushbullet  # type: ignore

from .ai import AIResponse  # type: ignore
from .listing import Listing
from .notification import NotificationConfig, NotificationStatus
from .utils import hilight, value_from_environ


@dataclass
class PushbulletNotificationConfig(NotificationConfig):
    pushbullet_token: str | None = None
    pushbullet_proxy_type: str | None = None
    pushbullet_proxy_server: str | None = None

    def handle_pushbullet_token(self: "PushbulletNotificationConfig") -> None:
        if self.pushbullet_token is None:
            return

        self.pushbullet_token = value_from_environ(self.pushbullet_token)

        if not isinstance(self.pushbullet_token, str) or not self.pushbullet_token:
            raise ValueError("An non-empty pushbullet_token is needed.")
        self.pushbullet_token = self.pushbullet_token.strip()

    def handle_pushbullet_proxy_type(self: "PushbulletNotificationConfig") -> None:
        if self.pushbullet_proxy_type is None:
            return
        if not isinstance(self.pushbullet_proxy_type, str) or not self.pushbullet_proxy_type:
            raise ValueError("user requires an non-empty pushbullet_proxy_type.")
        self.pushbullet_proxy_type = self.pushbullet_proxy_type.strip()

    def handle_pushbullet_proxy_server(self: "PushbulletNotificationConfig") -> None:
        # pushbullet_proxy_server and pushbullet_proxy_type are both required to be set
        # if either of them is set, then both of them must be set
        if self.pushbullet_proxy_type is None and self.pushbullet_proxy_server is not None:
            raise ValueError(
                "user requires an non-empty pushbullet_proxy_type when pushbullet_proxy_server is set."
            )
        # if pushbullet_proxy_type is set, then pushbullet_proxy_server must be set
        if self.pushbullet_proxy_type is not None and self.pushbullet_proxy_server is None:
            raise ValueError(
                "user requires an non-empty pushbullet_proxy_server when pushbullet_proxy_type is set."
            )
        if self.pushbullet_proxy_server is None:
            return
        if not isinstance(self.pushbullet_proxy_server, str) or not self.pushbullet_proxy_server:
            raise ValueError("user requires an non-empty pushbullet_proxy_server.")
        self.pushbullet_proxy_server = self.pushbullet_proxy_server.strip()

    def notify(
        self: "PushbulletNotificationConfig",
        listings: List[Listing],
        ratings: List[AIResponse],
        notification_status: List[NotificationStatus],
        force: bool = False,
        logger: Logger | None = None,
    ) -> bool:
        if not self.pushbullet_token:
            if logger:
                logger.debug("No pushbullet_token specified.")
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
            if not self.send_pushbullet_message(title, message, logger=logger):
                return False
        return True

    def send_pushbullet_message(
        self: "PushbulletNotificationConfig",
        title: str,
        message: str,
        max_retries: int = 6,
        delay: int = 10,
        logger: Logger | None = None,
    ) -> bool:
        if not self.pushbullet_token:
            if logger:
                logger.debug("No pushbullet_token specified.")
            return False

        try:
            pb = Pushbullet(
                self.pushbullet_token,
                proxy=(
                    {self.pushbullet_proxy_type: self.pushbullet_proxy_server}
                    if self.pushbullet_proxy_server and self.pushbullet_proxy_type
                    else None
                ),
            )
        except Exception as e:
            if logger:
                logger.error(
                    f"""{hilight("[Notify]", "fail")} Failed to create Pushbullet instance: {e}"""
                )
            return False

        for attempt in range(max_retries):
            try:
                pb.push_note(
                    title, message + "\n\nSent by https://github.com/BoPeng/ai-marketplace-monitor"
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
