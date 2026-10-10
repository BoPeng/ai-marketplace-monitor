import logging
import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, fields
from enum import Enum
from logging import Logger
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    DefaultDict,
    Deque,
    Iterator,
    List,
    Optional,
    Tuple,
    Type,
)

from .ai import AIResponse  # type: ignore
from .listing import Listing
from .utils import PACKAGE_DIR, BaseConfig, hilight

if TYPE_CHECKING:
    from .digest import Digest


class NotificationStatus(Enum):
    NOT_NOTIFIED = 0
    EXPIRED = 1
    NOTIFIED = 2
    LISTING_CHANGED = 3
    LISTING_DISCOUNTED = 4


# dataclass metadata key and values describing where a notification field belongs
ROLE = "role"
RECIPIENT = "recipient"  # who receives: stays on [user.*]
CHANNEL = "channel"  # how it is sent (credentials, servers): [notification.*]
COMMON = "common"  # delivery settings shared by every channel type


def notification_field(role: str, default: Any = None) -> Any:
    """Declare a notification field together with its role."""
    return field(default=default, metadata={ROLE: role})


def fields_with_role(cls: type, role: str) -> Tuple[str, ...]:
    """Names of the fields of a notification class that have the given role."""
    return tuple(f.name for f in fields(cls) if f.metadata.get(ROLE) == role)


# seconds a test message may take on one channel before it is reported as failed
TEST_TIMEOUT = 60
TEST_LISTING_URL = "https://github.com/BoPeng/ai-marketplace-monitor"
SAMPLE_IMAGE = PACKAGE_DIR / "sample_listing.jpg"


@dataclass
class ChannelResult:
    """Whether a test message went out through one channel (e.g. ``email``), and why not."""

    channel: str
    ok: bool
    error: str | None = None


def sample_listing() -> Tuple[Listing, AIResponse]:
    """A sample listing, clearly marked as a test, that links to the aimm repository.

    Every part of a real notification is filled in, so that a test shows the channel's real
    layout. Its photo is bundled with aimm: an email test attaches it as it attaches the photo
    of a real listing, without downloading anything.
    """
    listing = Listing(
        marketplace="aimm",
        name="test notification",
        id="aimm-test-notification",
        title="aimm test notification",
        image=SAMPLE_IMAGE.as_uri(),
        price="$100",
        post_url=TEST_LISTING_URL,
        location="Houston, TX",
        seller="AI Marketplace Monitor",
        condition="New",
        description=(
            "This is a test message from AI Marketplace Monitor (aimm), not a real listing. "
            "A real notification shows the listing's description here."
        ),
    )
    rating = AIResponse(
        score=5,
        comment=(
            "Test: this is where aimm's AI explains how well a listing matches what you are "
            "looking for."
        ),
        name="test",
    )
    return listing, rating


# the color tags hilight() puts in log messages
_HILIGHT = re.compile(r"\[/?(?:cyan|red|blue|green|gray)\]")


class _TestLog(logging.Handler):
    """Keeps what a channel logs while it sends a test, to report why it failed."""

    def __init__(self: "_TestLog", forward: Logger | None) -> None:
        super().__init__(logging.DEBUG)
        self.forward = forward
        self.messages: List[Tuple[int, str]] = []

    def emit(self: "_TestLog", record: logging.LogRecord) -> None:
        self.messages.append((record.levelno, _HILIGHT.sub("", record.getMessage())))
        if self.forward is not None and self.forward.isEnabledFor(record.levelno):
            self.forward.handle(record)

    def error(self: "_TestLog") -> str:
        """The most telling failure: the exception of the last attempt, else the last error.

        Only the first line, shortened, is returned: it is shown to the user.
        """
        for _, message in reversed(self.messages):
            if " failed: " in message and "Attempt" in message:
                return _one_line(message.split(" failed: ", 1)[1])
        for level, message in reversed(self.messages):
            if level >= logging.WARNING and "Max retries reached" not in message:
                return _one_line(message)
        return "The message was not sent."


# the longest error shown for a channel
MAX_ERROR_LENGTH = 300


def _one_line(message: str) -> str:
    lines = [line.strip() for line in message.strip().splitlines() if line.strip()]
    line = lines[0] if lines else "The message was not sent."
    return line if len(line) <= MAX_ERROR_LENGTH else line[: MAX_ERROR_LENGTH - 3] + "..."


class _ChannelTest:
    """A test message being sent through one channel, in a thread of its own."""

    def __init__(
        self: "_ChannelTest",
        channel: "NotificationConfig",
        listings: List[Listing],
        ratings: List[AIResponse],
        logger: Logger | None,
    ) -> None:
        self.name = channel.notify_method
        self.log = _TestLog(logger)
        # a logger of its own (not registered), so that tests at the same time do not mix
        self.logger = logging.Logger(f"aimm.test.{self.name}", logging.DEBUG)
        self.logger.addHandler(self.log)
        self.sent = False
        self.thread = threading.Thread(
            target=self._send,
            args=(channel, listings, ratings),
            daemon=True,  # a channel that does not answer must not keep aimm running
            name=f"aimm-test-{self.name}",
        )
        self.thread.start()

    def _send(
        self: "_ChannelTest",
        channel: "NotificationConfig",
        listings: List[Listing],
        ratings: List[AIResponse],
    ) -> None:
        try:
            self.sent = channel.notify(  # type: ignore[attr-defined]
                listings,
                ratings,
                [NotificationStatus.NOT_NOTIFIED] * len(listings),
                force=True,
                logger=self.logger,
            )
        except Exception as e:
            # reported like any other failure: from the channel's log, as one line
            self.logger.error(f"Failed to send: {e or e.__class__.__name__}")

    def result(self: "_ChannelTest", wait: float, timeout: float) -> ChannelResult:
        self.thread.join(max(wait, 0))
        if self.thread.is_alive():
            return ChannelResult(self.name, False, f"No answer in {timeout:g} seconds.")
        if self.sent:
            return ChannelResult(self.name, True)
        return ChannelResult(self.name, False, self.log.error())


@dataclass
class NotificationConfig(BaseConfig):
    required_fields: ClassVar[List[str]] = []
    # format of the digest if the channel does not follow message_format
    digest_format: ClassVar[str | None] = None
    notify_method: ClassVar[str] = ""

    max_retries: int = notification_field(COMMON, 5)
    retry_delay: int = notification_field(COMMON, 60)

    # Rate limiting configuration (disabled by default, but public for user config)
    rate_limit_enabled: bool = notification_field(COMMON, False)
    # seconds between sends per instance
    instance_rate_limit: float = notification_field(COMMON, 1.0)
    # messages per second across all instances
    global_rate_limit: int = notification_field(COMMON, 10)

    # Subclasses that handle rate limiting in their own send path (e.g.
    # Telegram's async _wait_for_rate_limit) should set this to True so
    # the base class _execute_with_retry does NOT also apply sync rate
    # limiting — preventing double-wait.
    _handles_own_rate_limiting: bool = False

    # Private tracking attributes
    _last_send_time: float | None = None

    # Class-level global tracking (shared across all notification types)
    _global_send_times: ClassVar[Deque[float]] = deque()
    _global_lock: ClassVar[threading.Lock] = threading.Lock()

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
            flds = {f.name for f in fields(subclass)}
            subclass_obj = subclass(**{k: getattr(config, k) for k in flds})
            if hasattr(subclass_obj, "notify") and subclass.__name__ not in [
                "UserConfig",
                "PushNotificationConfig",
            ]:
                assert hasattr(subclass_obj, "notify")
                succ.append(subclass_obj.notify(*args, **kwargs))
            # subclases
            if hasattr(subclass_obj, "notify_all"):
                succ.append(subclass.notify_all(config, *args, **kwargs))
        return any(succ)

    @classmethod
    def _channel_classes(
        cls: type["NotificationConfig"],
    ) -> Iterator[type["NotificationConfig"]]:
        """The classes that send through one channel (email, pushbullet, ...), as notify_all."""
        seen = set()
        for subclass in cls.__subclasses__():
            if subclass.__name__ not in ("UserConfig", "PushNotificationConfig") and hasattr(
                subclass, "notify"
            ):
                seen.add(subclass)
                yield subclass
            for sub in subclass._channel_classes():
                if sub not in seen:
                    seen.add(sub)
                    yield sub

    @classmethod
    def channels(
        cls: type["NotificationConfig"], config: "NotificationConfig", **overrides: Any
    ) -> List["NotificationConfig"]:
        """The channels set up in ``config`` (a user with its notifications merged in).

        A channel without its required fields is not set up for this user and is left out.
        """
        out = []
        for subclass in cls._channel_classes():
            flds = {f.name for f in fields(subclass) if not f.name.startswith("_")}
            values = {k: getattr(config, k) for k in flds if hasattr(config, k)}
            channel = subclass(**{**values, **overrides})
            if channel._has_required_fields():
                out.append(channel)
        return out

    @classmethod
    def test_all(
        cls: type["NotificationConfig"],
        config: "NotificationConfig",
        listings: List[Listing] | None = None,
        ratings: List[AIResponse] | None = None,
        *,
        channels: List[str] | None = None,
        timeout: float = TEST_TIMEOUT,
        logger: Logger | None = None,
    ) -> List[ChannelResult]:
        """Send a test message through each channel of ``config``; one result per channel.

        Unlike ``User.notify``, nothing is written to the cache. Each channel makes one attempt
        (no retries); the channels send at the same time and have ``timeout`` seconds in all.
        ``listings`` default to ``sample_listing()``; ``channels`` limits the test to these
        channels (``notify_method``, e.g. ``["email"]``).
        """
        if listings is None or ratings is None:
            listing, rating = sample_listing()
            listings, ratings = [listing], [rating]
        tests = [
            _ChannelTest(channel, listings, ratings, logger)
            for channel in cls.channels(config, max_retries=1)
            if channels is None or channel.notify_method in channels
        ]
        deadline = time.monotonic() + timeout
        return [test.result(deadline - time.monotonic(), timeout) for test in tests]

    def _execute_with_retry(
        self: "NotificationConfig",
        title: str,
        message: str,
        logger: Logger | None = None,
        apply_rate_limiting: bool = False,
    ) -> bool:
        """Common retry logic for message sending with optional rate limiting."""
        if not self._has_required_fields():
            return False

        for attempt in range(self.max_retries):
            try:
                # Apply rate limiting if requested
                if apply_rate_limiting and self.rate_limit_enabled:
                    self._wait_for_rate_limit_sync(logger)

                # Call the send_message method
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

    def _send_message_with_rate_limiting_sync(
        self: "NotificationConfig",
        title: str,
        message: str,
        logger: Logger | None = None,
    ) -> bool:
        """Sync version of send_message_with_retry with rate limiting support."""
        return self._execute_with_retry(title, message, logger, apply_rate_limiting=True)

    def send_message_with_retry(
        self: "NotificationConfig",
        title: str,
        message: str,
        logger: Logger | None = None,
    ) -> bool:
        """Enhanced retry method with rate limiting support.

        Subclasses that set ``_handles_own_rate_limiting = True`` (e.g.
        Telegram, which applies async rate limiting inside its own
        ``send_message``) will NOT get sync rate limiting here —
        avoiding a double-wait.
        """
        apply = self.rate_limit_enabled and not self._handles_own_rate_limiting
        return self._execute_with_retry(title, message, logger, apply_rate_limiting=apply)

    def _get_wait_time(self: "NotificationConfig") -> float:
        """Calculate instance-level wait time. Override for custom logic."""
        if not self.rate_limit_enabled or self._last_send_time is None:
            return 0.0

        elapsed = time.time() - self._last_send_time
        return max(0.0, self.instance_rate_limit - elapsed)

    @classmethod
    def _get_global_wait_time(cls: Type["NotificationConfig"]) -> float:
        """Calculate global wait time across all instances.

        Note: this is only called from _wait_for_rate_limit[_sync] which
        already gates on rate_limit_enabled, so non-rate-limited instances
        never reach here and never populate _global_send_times.
        """
        with cls._global_lock:
            # Check if any instance has rate limiting enabled by checking if we have any tracked times
            # This is a more practical approach than checking class attributes
            if not cls._global_send_times:
                return 0.0

            current_time = time.time()

            # Remove timestamps older than 1 second
            while cls._global_send_times and current_time - cls._global_send_times[0] > 1.0:
                cls._global_send_times.popleft()

            # Use a reasonable default global rate limit (30 msg/sec like Telegram)
            # Individual classes can override this behavior
            global_rate_limit = getattr(cls, "global_rate_limit", 30)

            # If we have less than the rate limit, no wait needed
            if len(cls._global_send_times) < global_rate_limit:
                return 0.0

            # If we're at the limit, wait until the oldest message is more than 1 second old
            oldest_send_time = cls._global_send_times[0]
            wait_time = 1.0 - (current_time - oldest_send_time)
            return max(0.0, wait_time)

    @classmethod
    def _record_global_send_time(cls: Type["NotificationConfig"]) -> None:
        """Record the current time as a global send time."""
        with cls._global_lock:
            cls._global_send_times.append(time.time())

    def _wait_for_rate_limit_sync(
        self: "NotificationConfig", logger: Logger | None = None
    ) -> None:
        """Wait for rate limits and record send time (synchronous version)."""
        if not self.rate_limit_enabled:
            return

        # Check both per-instance and global rate limits
        instance_wait = self._get_wait_time()
        global_wait = self._get_global_wait_time()

        # Use the longer of the two wait times
        wait_time = max(instance_wait, global_wait)

        if wait_time > 0:
            if logger:
                if global_wait > instance_wait:
                    logger.debug(
                        f"Rate limiting: waiting {wait_time:.1f} seconds (global limit: {self.global_rate_limit}s)"
                    )
                else:
                    logger.debug(
                        f"Rate limiting: waiting {wait_time:.1f} seconds (instance limit: {self.instance_rate_limit}s)"
                    )

            time.sleep(wait_time)

        # Record both per-instance and global send times
        self._last_send_time = time.time()
        self._record_global_send_time()

    async def _wait_for_rate_limit(
        self: "NotificationConfig", logger: Logger | None = None
    ) -> None:
        """Wait for rate limits and record send time (async version for Telegram)."""
        if not self.rate_limit_enabled:
            return

        import asyncio

        # Check both per-instance and global rate limits
        instance_wait = self._get_wait_time()
        global_wait = self._get_global_wait_time()

        # Use the longer of the two wait times
        wait_time = max(instance_wait, global_wait)

        if wait_time > 0:
            if logger:
                if global_wait > instance_wait:
                    logger.debug(
                        f"Global rate limiting: waiting {wait_time:.1f} seconds (limit: {self.global_rate_limit} msg/sec)"
                    )
                else:
                    logger.debug(
                        f"Rate limiting: waiting {wait_time:.1f} seconds (limit: {self.instance_rate_limit}s)"
                    )

            await asyncio.sleep(wait_time)

        # Record both per-instance and global send times
        self._last_send_time = time.time()
        self._record_global_send_time()

    def send_message(
        self: "NotificationConfig",
        title: str,
        message: str,
        logger: Logger | None = None,
    ) -> bool:
        raise NotImplementedError("send_message needs to be defined.")

    def send_digest(
        self: "NotificationConfig", digest: "Digest", logger: Logger | None = None
    ) -> bool:
        """Send the short (phone) daily digest, in the channel's format."""
        from .digest import render_phone_digest

        if not self._has_required_fields():
            return False
        fmt = self.digest_format or getattr(self, "message_format", None) or "plain_text"
        message = render_phone_digest(digest, fmt)
        return self.send_message_with_retry(digest.title, message, logger=logger)


@dataclass
class PushNotificationConfig(NotificationConfig):
    notify_method = "push_notification"
    message_format: str | None = notification_field(COMMON)
    with_description: int | None = notification_field(COMMON)

    def handle_message_format(self: "PushNotificationConfig") -> None:
        if self.message_format is None:
            self.message_format = "plain_text"

        if self.message_format not in ["plain_text", "markdown", "html"]:
            raise ValueError("message_format must be 'plain_text', 'markdown', or 'html'.")

    def handle_with_description(self: "PushNotificationConfig") -> None:
        if self.with_description is None:
            return

        if self.with_description is True:
            self.with_description = 1
        elif self.with_description is False:
            self.with_description = 0

        if not isinstance(self.with_description, int) or self.with_description < 0:
            raise ValueError("with_description must be a boolean or a positive integer number.")

    def notify(
        self: "PushNotificationConfig",
        listings: List[Listing],
        ratings: List[AIResponse],
        notification_status: List[NotificationStatus],
        force: bool = False,
        logger: Logger | None = None,
    ) -> bool:
        if not self._has_required_fields():
            if logger:
                logger.debug(
                    f"Missing required fields  {', '.join(self.required_fields)}. No {self.notify_method} notification sent."
                )
            return False
        #
        # we send listings with different status with different messages
        msgs: DefaultDict[NotificationStatus, List[Tuple[Listing, str]]] = defaultdict(list)
        import inflect

        p = inflect.engine()
        for listing, rating, ns in zip(listings, ratings, notification_status):
            if ns == NotificationStatus.NOTIFIED and not force:
                continue
            if self.with_description is None:
                desc = listing.description
            elif self.with_description == 0:
                desc = ""
            elif self.with_description == 1 or len(listing.description) < self.with_description:
                desc = listing.description
            else:
                desc = listing.description[: self.with_description] + "..."

            if self.message_format == "plain_text":
                desc_newline = "\n" if desc else ""
                msg = (
                    (
                        f"{listing.title}\n{listing.price}, {listing.location}\n"
                        f"{listing.post_url.split('?')[0]}{desc_newline}{desc}"
                    )
                    if rating.comment == AIResponse.NOT_EVALUATED
                    else (
                        f"[{rating.conclusion} ({rating.score})] {listing.title}\n"
                        f"{listing.price}, {listing.location}\n"
                        f"{listing.post_url.split('?')[0]}\n{desc}{desc_newline}"
                        f"\nAI: {rating.comment}"
                    )
                )
            elif self.message_format == "markdown":
                desc_newline = "\n" if desc else ""
                msg = (
                    (
                        f"[**{listing.title}**]({listing.post_url.split('?')[0]})\n"
                        f"{listing.price}, {listing.location}"
                        f"{desc_newline}{desc}"
                    )
                    if rating.comment == AIResponse.NOT_EVALUATED
                    else (
                        f"[{rating.conclusion} ({rating.score})] "
                        f"[**{listing.title}**]({listing.post_url.split('?')[0]})\n"
                        f"{listing.price}, {listing.location}\n"
                        f"{desc}{desc_newline}"
                        f"\n**AI**: {rating.comment}"
                    )
                )
            elif self.message_format == "html":
                desc_newline = "<br>" if desc else ""
                msg = (
                    (
                        f"""<a href="{listing.post_url.split("?")[0]}"><b>{listing.title}</b></a>"""
                        f"<br>{listing.price}, {listing.location}{desc_newline}{desc}"
                    )
                    if rating.comment == AIResponse.NOT_EVALUATED
                    else (
                        f"<b>[{rating.conclusion} ({rating.score})]</b>"
                        f"""<a href="{listing.post_url.split("?")[0]}"><b>{listing.title}</b></a>"""
                        f"<br>{listing.price}, {listing.location}<br>"
                        f"{desc}{desc_newline}"
                        f"<br><b>AI</b>: <i>{rating.comment}</i>"
                    )
                )
            warnings = (listing.seller_info or {}).get("warnings") or []
            if warnings:
                text = "; ".join(warnings)
                msg += {
                    "plain_text": f"\nSeller warning: {text}",
                    "markdown": f"\n**Seller warning**: {text}",
                    "html": f"<br><b>Seller warning</b>: {text}",
                }.get(self.message_format or "plain_text", f"\nSeller warning: {text}")
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
