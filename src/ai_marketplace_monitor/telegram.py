import textwrap
import time
from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from logging import Logger
from typing import TYPE_CHECKING, ClassVar, Deque, List, Type

from .notification import PushNotificationConfig

if TYPE_CHECKING:
    import telegram


@dataclass
class TelegramNotificationConfig(PushNotificationConfig):
    notify_method = "telegram"
    required_fields: ClassVar[List[str]] = ["telegram_token", "telegram_chat_id"]

    telegram_token: str | None = None
    telegram_chat_id: str | None = None

    # Instance-level rate limiting
    _last_send_time: float | None = None

    # Class-level global rate limiting (30 messages/second)
    _global_send_times: ClassVar[Deque[float]] = deque()
    _global_rate_limit: ClassVar[int] = 30  # messages per second

    def handle_telegram_token(self: "TelegramNotificationConfig") -> None:
        if self.telegram_token is None:
            return

        if not isinstance(self.telegram_token, str) or not self.telegram_token:
            raise ValueError("An non-empty telegram_token is needed.")

        self.telegram_token = self.telegram_token.strip()

        # Validate token format: numbers:letters_and_numbers
        if ":" not in self.telegram_token:
            raise ValueError(
                "telegram_token must contain a colon (:) separating bot ID and secret."
            )

        bot_id, secret = self.telegram_token.split(":", 1)
        if not bot_id.isdigit():
            raise ValueError("telegram_token bot ID (before colon) must be numeric.")

        if not secret or not secret.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "telegram_token secret (after colon) must contain only alphanumeric characters, underscores, and hyphens."
            )

    def handle_telegram_chat_id(self: "TelegramNotificationConfig") -> None:
        if self.telegram_chat_id is None:
            return

        if not isinstance(self.telegram_chat_id, str) or not self.telegram_chat_id:
            raise ValueError("An non-empty telegram_chat_id is needed.")

        self.telegram_chat_id = self.telegram_chat_id.strip()

        # Validate chat ID format: numeric (negative for groups) or @username
        if self.telegram_chat_id.startswith("@"):
            # Username format
            username = self.telegram_chat_id[1:]
            if not username or not username.replace("_", "").isalnum():
                raise ValueError(
                    "telegram_chat_id username must contain only alphanumeric characters and underscores."
                )
        else:
            # Numeric format (can be negative for groups)
            try:
                int(self.telegram_chat_id)
            except ValueError as e:
                raise ValueError(
                    "telegram_chat_id must be numeric or start with @ for usernames."
                ) from e

    def send_message(
        self: "TelegramNotificationConfig",
        title: str,
        message: str,
        logger: Logger | None = None,
    ) -> bool:
        """Send message using asyncio.run to call async Telegram operations."""
        import asyncio

        try:
            # Check if an event loop is already running
            try:
                asyncio.get_running_loop()
                # If we get here, an event loop is already running
                # We need to use asyncio.create_task or similar
                if logger:
                    logger.debug("Event loop already running, using alternative async execution")
                # Create a new event loop in a thread to avoid conflicts
                import concurrent.futures

                def run_async():
                    # Create a new event loop for this thread
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        return new_loop.run_until_complete(
                            self._send_message_async(title, message, logger)
                        )
                    finally:
                        new_loop.close()

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(run_async)
                    return future.result(timeout=60)  # 60 second timeout for notification

            except RuntimeError:
                # No event loop running, safe to use asyncio.run
                if logger:
                    logger.debug("No event loop running, using asyncio.run")
                return asyncio.run(self._send_message_async(title, message, logger))

        except Exception as e:
            if logger:
                logger.error(f"Telegram notification failed: {e}")
            raise

    def _split_message_at_boundaries(
        self: "TelegramNotificationConfig", text: str, max_length: int
    ) -> List[str]:
        """Split message at word boundaries while respecting character limit."""
        return textwrap.wrap(
            text, width=max_length, break_long_words=False, break_on_hyphens=False
        )

    def _is_group_chat(self: "TelegramNotificationConfig") -> bool:
        """Determine if the chat_id represents a group chat (negative ID or supergroup)."""
        if self.telegram_chat_id is None:
            return False

        # Group chats have negative IDs, individual chats have positive IDs
        # Usernames (@username) are treated as individual chats for rate limiting
        if self.telegram_chat_id.startswith("@"):
            return False

        try:
            chat_id_int = int(self.telegram_chat_id)
            return chat_id_int < 0
        except ValueError:
            # If we can't parse as int, default to individual chat
            return False

    def _get_wait_time(self: "TelegramNotificationConfig") -> float:
        """Calculate wait time needed before next send."""
        if self._last_send_time is None:
            return 0.0

        elapsed = time.time() - self._last_send_time
        # Use different intervals: 1.1s for individual chats, 3.0s for groups
        min_interval = 3.0 if self._is_group_chat() else 1.1
        return max(0.0, min_interval - elapsed)

    @classmethod
    def _get_global_wait_time(cls: Type["TelegramNotificationConfig"]) -> float:
        """Calculate wait time needed to respect global rate limit (30 msg/sec)."""
        current_time = time.time()

        # Remove timestamps older than 1 second
        while cls._global_send_times and current_time - cls._global_send_times[0] > 1.0:
            cls._global_send_times.popleft()

        # If we have less than the rate limit, no wait needed
        if len(cls._global_send_times) < cls._global_rate_limit:
            return 0.0

        # If we're at the limit, wait until the oldest message is more than 1 second old
        oldest_send_time = cls._global_send_times[0]
        wait_time = 1.0 - (current_time - oldest_send_time)
        return max(0.0, wait_time)

    @classmethod
    def _record_global_send_time(cls: Type["TelegramNotificationConfig"]) -> None:
        """Record the current time as a global send time."""
        cls._global_send_times.append(time.time())

    async def _wait_for_rate_limit(
        self: "TelegramNotificationConfig", logger: Logger | None = None
    ) -> None:
        """Wait if rate limiting is needed, then record send time."""
        import asyncio

        # Check both per-chat and global rate limits
        per_chat_wait = self._get_wait_time()
        global_wait = self._get_global_wait_time()

        # Use the longer of the two wait times
        wait_time = max(per_chat_wait, global_wait)

        if wait_time > 0:
            if logger:
                if global_wait > per_chat_wait:
                    logger.debug(
                        f"Global rate limiting: waiting {wait_time:.1f} seconds (limit: {self._global_rate_limit} msg/sec)"
                    )
                else:
                    chat_type = "group" if self._is_group_chat() else "individual"
                    logger.debug(
                        f"Rate limiting {chat_type} chat {self.telegram_chat_id}: waiting {wait_time:.1f} seconds"
                    )

            await asyncio.sleep(wait_time)

        # Record both per-chat and global send times
        self._last_send_time = time.time()
        self._record_global_send_time()

    async def _send_single_message_with_retry(
        self: "TelegramNotificationConfig",
        bot: "telegram.Bot",
        chat_id: str,
        text: str,
        logger: Logger | None = None,
        max_retries: int = 3,
    ) -> bool:
        """Send a single message with HTTP 429 retry handling."""
        import asyncio

        import telegram

        for attempt in range(max_retries + 1):
            try:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="MarkdownV2")
                return True
            except telegram.error.RetryAfter as e:
                # Handle HTTP 429 with Retry-After header
                retry_after = e.retry_after
                # Convert timedelta to float seconds if needed for asyncio.sleep compatibility
                sleep_duration = (
                    retry_after.total_seconds()
                    if isinstance(retry_after, timedelta)
                    else float(retry_after)
                )

                if logger:
                    logger.warning(
                        f"Telegram rate limit hit (429), waiting {sleep_duration} seconds (attempt {attempt + 1}/{max_retries + 1})"
                    )

                if attempt < max_retries:
                    await asyncio.sleep(sleep_duration)
                    continue
                else:
                    if logger:
                        logger.error(f"Max retries ({max_retries}) reached for 429 errors")
                    return False
            except telegram.error.TelegramError as e:
                # Handle other Telegram errors with exponential backoff
                if attempt < max_retries:
                    backoff_time = 2**attempt  # Exponential backoff: 1s, 2s, 4s
                    if logger:
                        logger.warning(
                            f"Telegram error: {e}, retrying in {backoff_time} seconds (attempt {attempt + 1}/{max_retries + 1})"
                        )
                    await asyncio.sleep(backoff_time)
                    continue
                else:
                    if logger:
                        logger.error(
                            f"Max retries ({max_retries}) reached for Telegram errors: {e}"
                        )
                    return False
            except Exception as e:
                # Handle unexpected errors
                if logger:
                    logger.error(f"Unexpected error sending Telegram message: {e}")
                return False

        return False

    async def _send_message_async(
        self: "TelegramNotificationConfig",
        title: str,
        message: str,
        logger: Logger | None = None,
    ) -> bool:
        """Private async method to send messages using telegram.Bot."""
        try:
            import telegram
            from telegram.helpers import escape_markdown
        except ImportError:
            if logger:
                logger.error("python-telegram-bot library is required for Telegram notifications")
            return False

        # Check for required Telegram configuration
        if self.telegram_token is None:
            if logger:
                logger.error("telegram_token is required but not configured")
            return False

        if self.telegram_chat_id is None:
            if logger:
                logger.error("telegram_chat_id is required but not configured")
            return False

        # Wait for rate limits before sending
        await self._wait_for_rate_limit(logger)

        try:
            bot = telegram.Bot(token=self.telegram_token)

            # Format message with MarkdownV2 escaping
            escaped_title = escape_markdown(title, version=2)
            escaped_message = escape_markdown(message, version=2)
            formatted_message = f"*{escaped_title}*\n\n{escaped_message}"

            # Telegram message length limit is 4096 characters
            max_message_length = 4096

            # Check if message needs splitting
            if len(formatted_message) <= max_message_length:
                return await self._send_single_message_with_retry(
                    bot, self.telegram_chat_id, formatted_message, logger
                )
            # Split the ORIGINAL unescaped message to preserve MarkdownV2 formatting
            # Reserve space for title formatting and continuation indicators
            title_with_formatting = f"*{escaped_title}*\n\n"
            continuation_space = 15  # Space for " \(1/999\)" indicator
            available_for_message = (
                max_message_length - len(title_with_formatting) - continuation_space
            )

            # Split the original message (before escaping) to avoid breaking escape sequences
            message_parts = self._split_message_at_boundaries(message, available_for_message)
            total_parts = len(message_parts)

            # Send first message with title
            escaped_first_part = escape_markdown(message_parts[0], version=2)
            first_message = f"{title_with_formatting}{escaped_first_part}"
            if total_parts > 1:
                first_message += f" \\(1/{total_parts}\\)"

            success = await self._send_single_message_with_retry(
                bot, self.telegram_chat_id, first_message, logger
            )
            if not success:
                return False

            # Send remaining parts without title
            for i, part in enumerate(message_parts[1:], 2):
                # Wait for rate limits before sending each additional part
                await self._wait_for_rate_limit(logger)

                escaped_part = escape_markdown(part, version=2)
                continuation_message = f"{escaped_part} \\({i}/{total_parts}\\)"
                success = await self._send_single_message_with_retry(
                    bot, self.telegram_chat_id, continuation_message, logger
                )
                if not success:
                    return False

            return True

        except Exception as e:
            if logger:
                logger.error(f"Failed to send Telegram message: {e}")
            return False
