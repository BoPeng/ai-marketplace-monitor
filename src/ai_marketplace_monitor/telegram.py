import asyncio
import concurrent.futures
import html
from dataclasses import dataclass
from logging import Logger
from typing import ClassVar, List

from telegram import Bot, helpers
from telegram.constants import MessageLimit
from telegram.error import BadRequest, RetryAfter, TelegramError, TimedOut

from .notification import PushNotificationConfig
from .utils import hilight


@dataclass
class TelegramNotificationConfig(PushNotificationConfig):
    notify_method = "telegram"
    required_fields: ClassVar[List[str]] = ["telegram_bot_token", "telegram_chat_id"]

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    def handle_telegram_bot_token(self: "TelegramNotificationConfig") -> None:
        if self.telegram_bot_token is None:
            return
        if not isinstance(self.telegram_bot_token, str) or not self.telegram_bot_token:
            raise ValueError("An non-empty telegram_bot_token is needed.")
        self.telegram_bot_token = self.telegram_bot_token.strip()

    def handle_telegram_chat_id(self: "TelegramNotificationConfig") -> None:
        if self.telegram_chat_id is None:
            return
        if not isinstance(self.telegram_chat_id, str) or not self.telegram_chat_id:
            raise ValueError("An non-empty telegram_chat_id is needed.")
        self.telegram_chat_id = self.telegram_chat_id.strip()

    def handle_message_format(self: "TelegramNotificationConfig") -> None:
        # Store original value to check if it was None before parent processing
        was_none = self.message_format is None
        super().handle_message_format()
        # If it was originally None, override the parent's "plain_text" default with "markdownv2"
        # This ensures Telegram uses MarkdownV2 formatting by default for proper rendering
        # Users can still explicitly set "markdown", "html", or "plain_text" if needed
        if was_none:
            self.message_format = "markdownv2"

    async def _send_message_async(
        self: "TelegramNotificationConfig",
        bot: Bot,
        text: str,
        parse_mode: str | None,
        logger: Logger | None = None,
        max_retries: int = 3,
    ) -> bool:
        """Send a single message using async telegram bot with retry logic."""
        if logger:
            logger.debug(
                f"[TELEGRAM DEBUG] _send_message_async called with text length: {len(text)}"
            )
            logger.debug(f"[TELEGRAM DEBUG] Parse mode: {parse_mode}")
            logger.debug(f"[TELEGRAM DEBUG] Text preview (first 100 chars): {text[:100]!r}")

        for attempt in range(max_retries + 1):
            try:
                if logger:
                    logger.debug(
                        f"[TELEGRAM DEBUG] Sending message attempt {attempt + 1}/{max_retries + 1}"
                    )

                result = await bot.send_message(
                    chat_id=self.telegram_chat_id,  # type: ignore[arg-type]
                    text=text,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True,
                )

                if logger:
                    logger.debug(
                        f"[TELEGRAM DEBUG] Message sent successfully! Message ID: {result.message_id}"
                    )
                    logger.debug(f"[TELEGRAM DEBUG] Response: {result}")
                return True
            except RetryAfter as e:
                if logger:
                    logger.warning(
                        f"Telegram rate limit hit, waiting {e.retry_after} seconds (attempt {attempt + 1}/{max_retries + 1})"
                    )
                if attempt < max_retries:
                    await asyncio.sleep(e.retry_after)
                    continue
                else:
                    if logger:
                        logger.error("Max retries exceeded for rate limiting")
                    return False
            except TimedOut as e:
                if logger:
                    logger.warning(
                        f"Telegram request timed out (attempt {attempt + 1}/{max_retries + 1}): {e}"
                    )
                if attempt < max_retries:
                    # Exponential backoff for timeouts
                    wait_time = 2**attempt
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    if logger:
                        logger.error("Max retries exceeded for timeout")
                    return False
            except BadRequest as e:
                if logger:
                    logger.error(f"[TELEGRAM DEBUG] BadRequest error: {e}")
                    logger.error(f"[TELEGRAM DEBUG] Error message: {e.message}")
                    logger.error(f"[TELEGRAM DEBUG] Full error dict: {e.__dict__}")
                    # Log specific details for common formatting issues
                    if "can't parse" in str(e).lower():
                        logger.error(
                            "[TELEGRAM DEBUG] Parse error detected - likely issue with message formatting"
                        )
                        logger.debug(f"[TELEGRAM DEBUG] Full text that failed: {text!r}")
                        logger.debug(f"[TELEGRAM DEBUG] Parse mode: {parse_mode}")
                        # Log each line to find problematic characters
                        for i, line in enumerate(text.split("\n")[:10]):
                            logger.debug(f"[TELEGRAM DEBUG] Line {i}: {line!r}")
                return False  # Don't retry BadRequest errors
            except TelegramError as e:
                if logger:
                    logger.error(f"Telegram API error: {e}")
                return False  # Don't retry other TelegramError cases

        return False  # Should not reach here

    async def _send_all_messages_async(
        self: "TelegramNotificationConfig",
        title: str,
        messages: list[str],
        parse_mode: str | None,
        logger: Logger | None = None,
    ) -> bool:
        """Send all message parts using async context manager."""
        if logger:
            logger.debug(
                f"[TELEGRAM DEBUG] _send_all_messages_async called with {len(messages)} messages"
            )
            logger.debug(
                f"[TELEGRAM DEBUG] Using bot token: {self.telegram_bot_token[:20]}..."
                if self.telegram_bot_token
                else "No token"
            )

        async with Bot(token=self.telegram_bot_token) as bot:  # type: ignore[arg-type]
            # Helper function to format text based on message_format
            def format_bold(text: str) -> str:
                if self.message_format == "html":
                    return f"<b>{html.escape(text)}</b>"
                elif self.message_format == "markdown":
                    escaped = helpers.escape_markdown(text, version=2)
                    return f"*{escaped}*"
                elif self.message_format == "markdownv2":
                    # For MarkdownV2, escape special characters manually
                    special_chars = [
                        "_",
                        "*",
                        "[",
                        "]",
                        "(",
                        ")",
                        "~",
                        "`",
                        ">",
                        "#",
                        "+",
                        "-",
                        "=",
                        "|",
                        "{",
                        "}",
                        ".",
                        "!",
                    ]
                    escaped = text
                    for char in special_chars:
                        escaped = escaped.replace(char, f"\\{char}")
                    return f"*{escaped}*"
                else:
                    return text

            def format_italic_link(text: str, url: str) -> str:
                if self.message_format == "html":
                    escaped_text = html.escape(text)
                    escaped_url = html.escape(url, quote=True)
                    return f'<i><a href="{escaped_url}">{escaped_text}</a></i>'
                elif self.message_format == "markdown":
                    escaped_text = helpers.escape_markdown(text, version=2)
                    # In MarkdownV2, URLs in links don't need escaping
                    return f"[{escaped_text}]({url})"
                elif self.message_format == "markdownv2":
                    # For MarkdownV2, escape special characters manually
                    special_chars = [
                        "_",
                        "*",
                        "[",
                        "]",
                        "(",
                        ")",
                        "~",
                        "`",
                        ">",
                        "#",
                        "+",
                        "-",
                        "=",
                        "|",
                        "{",
                        "}",
                        ".",
                        "!",
                    ]
                    escaped_text = text
                    for char in special_chars:
                        escaped_text = escaped_text.replace(char, f"\\{char}")
                    return f"_[{escaped_text}]({url})_"
                else:
                    return f"{text}: {url}"

            signature = format_italic_link(
                "Sent by AI Marketplace Monitor",
                "https://github.com/BoPeng/ai-marketplace-monitor",
            )

            for idx, msg in enumerate(messages):
                title_part = format_bold(title)
                if len(messages) > 1:
                    title_part += f" ({idx + 1}/{len(messages)})"

                full_message = f"{title_part}\n\n{msg}"

                # Add signature to the last message
                if idx == len(messages) - 1:
                    full_message += f"\n\n{signature}"

                # Final safety check
                if len(full_message) > MessageLimit.MAX_TEXT_LENGTH:
                    if logger:
                        logger.warning(
                            f"Message part {idx + 1} exceeded limit after formatting. Truncating..."
                        )
                    # Truncate with some buffer for the ellipsis
                    truncate_at = MessageLimit.MAX_TEXT_LENGTH - len(signature) - 50
                    msg = msg[:truncate_at] + "..."
                    full_message = f"{title_part}\n\n{msg}\n\n{signature}"

                success = await self._send_message_async(bot, full_message, parse_mode, logger)
                if not success:
                    return False

            return True

    def send_message(
        self: "TelegramNotificationConfig",
        title: str,
        message: str,
        logger: Logger | None = None,
    ) -> bool:
        # DEBUG: Log entry into send_message
        if logger:
            logger.debug(f"[TELEGRAM DEBUG] Entering send_message with title: {title!r}")
            logger.debug(
                f"[TELEGRAM DEBUG] Bot token: {self.telegram_bot_token[:20]}..."
                if self.telegram_bot_token
                else "[TELEGRAM DEBUG] Bot token is None"
            )
            logger.debug(f"[TELEGRAM DEBUG] Chat ID: {self.telegram_chat_id}")
            logger.debug(f"[TELEGRAM DEBUG] Message format: {self.message_format}")
            logger.debug(f"[TELEGRAM DEBUG] Message length: {len(message)} chars")
            logger.debug(f"[TELEGRAM DEBUG] Message preview: {message[:100]!r}...")

        if not self.telegram_bot_token or not self.telegram_chat_id:
            if logger:
                logger.error(
                    "telegram_bot_token and telegram_chat_id must be set before calling send_message()"
                )
            return False

        # Escape the message content based on format
        if self.message_format == "markdown":
            escaped_message = helpers.escape_markdown(message, version=2)
            if logger:
                logger.debug(
                    f"[TELEGRAM DEBUG] Escaped message for markdown (first 200 chars): {escaped_message[:200]!r}"
                )
        elif self.message_format == "markdownv2":
            # Apply MarkdownV2 escaping to handle special characters
            escaped_message = helpers.escape_markdown(message, version=2)
            if logger:
                logger.debug(
                    f"[TELEGRAM DEBUG] Escaped message for MarkdownV2 (first 200 chars): {escaped_message[:200]!r}"
                )
        elif self.message_format == "html":
            escaped_message = html.escape(message)
            if logger:
                logger.debug(
                    f"[TELEGRAM DEBUG] Escaped message for HTML (first 200 chars): {escaped_message[:200]!r}"
                )
        else:
            escaped_message = message
            if logger:
                logger.debug("[TELEGRAM DEBUG] No escaping applied (plain text)")

        # Conservative estimate for overhead
        max_overhead = 200  # Title + part numbering + signature + safety buffer
        max_content_length = MessageLimit.MAX_TEXT_LENGTH - max_overhead

        # Split message if it's too long
        messages = []
        if len(escaped_message) <= max_content_length:
            messages.append(escaped_message)
        else:
            # Split by '\n\n' which separates listings
            pieces = escaped_message.split("\n\n")
            current_msg = ""

            for piece in pieces:
                test_msg = current_msg + "\n\n" + piece if current_msg else piece
                if len(test_msg) <= max_content_length:
                    current_msg = test_msg
                else:
                    if current_msg:
                        messages.append(current_msg)
                        current_msg = piece
                    else:
                        # Single piece is too long, split it at word boundaries
                        while len(piece) > max_content_length:
                            split_point = piece.rfind(" ", 0, max_content_length)
                            if split_point == -1 or split_point == 0:
                                # No space found or space at beginning, force split
                                split_point = max_content_length
                            messages.append(piece[:split_point])
                            piece = piece[split_point:].lstrip()
                        current_msg = piece

            if current_msg:
                messages.append(current_msg)

        # Set parse mode based on message format
        parse_mode = None
        if self.message_format == "markdown":
            parse_mode = "MarkdownV2"
        elif self.message_format == "markdownv2":
            parse_mode = "MarkdownV2"
        elif self.message_format == "html":
            parse_mode = "HTML"

        if logger:
            logger.debug(f"[TELEGRAM DEBUG] Parse mode set to: {parse_mode}")
            logger.debug(f"[TELEGRAM DEBUG] Number of message parts: {len(messages)}")

        # Handle both sync and async contexts
        try:
            # Check if we're already in a running event loop
            try:
                asyncio.get_running_loop()
                if logger:
                    logger.debug("[TELEGRAM DEBUG] Already in event loop, using thread")

                # We're in a running loop, use a thread to avoid RuntimeError
                def run_in_thread():
                    new_loop = asyncio.new_event_loop()
                    try:
                        return new_loop.run_until_complete(
                            self._send_all_messages_async(title, messages, parse_mode, logger)
                        )
                    finally:
                        new_loop.close()

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(run_in_thread)
                    all_sent = future.result()

            except RuntimeError:
                # No running loop, we can create our own
                if logger:
                    logger.debug("[TELEGRAM DEBUG] No event loop, creating new one")
                loop = asyncio.new_event_loop()
                try:
                    all_sent = loop.run_until_complete(
                        self._send_all_messages_async(title, messages, parse_mode, logger)
                    )
                finally:
                    loop.close()

        except Exception as e:
            if logger:
                logger.error(f"Unexpected error sending Telegram message: {e}")
                logger.error(f"[TELEGRAM DEBUG] Exception type: {type(e).__name__}")
                logger.error(f"[TELEGRAM DEBUG] Exception details: {e!r}")
                import traceback

                logger.debug(f"[TELEGRAM DEBUG] Traceback: {traceback.format_exc()}")
            all_sent = False

        if all_sent and logger:
            logger.info(
                f"""{hilight("[Notify]", "succ")} Sent {self.name} a message with title {hilight(title)}"""
            )
        elif logger:
            logger.error(f"[TELEGRAM DEBUG] Failed to send message. all_sent={all_sent}")

        return all_sent
