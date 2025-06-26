"""Simplified Telegram notification implementation with proper MarkdownV2 escaping."""

import asyncio
import concurrent.futures
import html
from dataclasses import dataclass
from logging import Logger
from typing import ClassVar, List, Optional

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self

from telegram import Bot, helpers
from telegram.constants import MessageLimit
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut
from telegram.request import HTTPXRequest

from .notification import PushNotificationConfig
from .utils import hilight


@dataclass
class TelegramNotificationConfig(PushNotificationConfig):
    """Simplified Telegram configuration with focus on correct formatting."""

    notify_method = "telegram"
    required_fields: ClassVar[List[str]] = ["telegram_bot_token", "telegram_chat_id"]

    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    # Simplified retry configuration
    max_retries: int = 3
    connection_timeout: float = 30.0

    def handle_telegram_bot_token(self: Self) -> None:
        if self.telegram_bot_token is None:
            return
        if not isinstance(self.telegram_bot_token, str) or not self.telegram_bot_token:
            raise ValueError("telegram_bot_token must be a non-empty string")
        self.telegram_bot_token = self.telegram_bot_token.strip()

    def handle_telegram_chat_id(self: Self) -> None:
        if self.telegram_chat_id is None:
            return
        if not isinstance(self.telegram_chat_id, str) or not self.telegram_chat_id:
            raise ValueError("telegram_chat_id must be a non-empty string")
        self.telegram_chat_id = self.telegram_chat_id.strip()

    def handle_message_format(self: Self) -> None:
        """Default to MarkdownV2 for Telegram."""
        if self.message_format is None:
            self.message_format = "markdownv2"
        super().handle_message_format()

    def _escape_text(self: Self, text: str) -> str:
        """Properly escape text for the configured format."""
        if self.message_format == "html":
            return html.escape(text)
        elif self.message_format in ("markdown", "markdownv2"):
            # Use telegram's built-in helper for consistent escaping
            return helpers.escape_markdown(text, version=2)
        else:
            return text

    def _format_bold(self: Self, text: str) -> str:
        """Format text as bold with proper escaping."""
        # First escape the text, then add formatting
        escaped = self._escape_text(text)

        if self.message_format == "html":
            return f"<b>{escaped}</b>"
        elif self.message_format in ("markdown", "markdownv2"):
            return f"*{escaped}*"
        else:
            return text

    def _format_link(self: Self, text: str, url: str, italic: bool = False) -> str:
        """Format a link with proper escaping."""
        escaped_text = self._escape_text(text)

        if self.message_format == "html":
            escaped_url = html.escape(url, quote=True)
            link = f'<a href="{escaped_url}">{escaped_text}</a>'
            return f"<i>{link}</i>" if italic else link
        elif self.message_format in ("markdown", "markdownv2"):
            # In MarkdownV2, URLs in links don't need escaping
            link = f"[{escaped_text}]({url})"
            return f"_{link}_" if italic else link
        else:
            return f"{text}: {url}"

    def _get_parse_mode(self: Self) -> Optional[str]:
        """Get the parse mode for Telegram API."""
        if self.message_format == "html":
            return "HTML"
        elif self.message_format in ("markdown", "markdownv2"):
            return "MarkdownV2"
        else:
            return None

    def _create_bot(self: Self) -> Bot:
        """Create a Bot instance with simple configuration."""
        if not self.telegram_bot_token:
            raise ValueError("telegram_bot_token must be set")

        # Simple HTTPXRequest configuration
        request = HTTPXRequest(
            connection_pool_size=1,
            connect_timeout=self.connection_timeout,
            read_timeout=self.connection_timeout,
        )

        return Bot(token=self.telegram_bot_token, request=request)

    def _split_message(self: Self, message: str, max_length: int) -> List[str]:
        """Split message into parts, preserving paragraph boundaries."""
        if len(message) <= max_length:
            return [message]

        parts = []
        remaining = message

        while remaining:
            if len(remaining) <= max_length:
                parts.append(remaining)
                break

            # Try to split at paragraph boundary
            split_point = remaining[:max_length].rfind("\n\n")
            if split_point == -1:
                # Try line boundary
                split_point = remaining[:max_length].rfind("\n")
            if split_point == -1:
                # Try space
                split_point = remaining[:max_length].rfind(" ")
            if split_point == -1:
                # Force split
                split_point = max_length

            parts.append(remaining[:split_point].rstrip())
            remaining = remaining[split_point:].lstrip()

        return parts

    def _format_message_part(
        self: Self, title: str, content: str, part_num: int, total_parts: int
    ) -> str:
        """Format a message part with proper escaping and numbering."""
        # Format the title
        formatted_title = self._format_bold(title)

        # Add numbering if multiple parts - escape the parentheses!
        if total_parts > 1:
            if self.message_format in ("markdown", "markdownv2"):
                # Escape parentheses for MarkdownV2
                numbering = f" \\({part_num}/{total_parts}\\)"
            elif self.message_format == "html":
                numbering = f" ({part_num}/{total_parts})"
            else:
                numbering = f" ({part_num}/{total_parts})"
            formatted_title += numbering

        # Combine title and content
        full_message = f"{formatted_title}\n\n{content}"

        # Add signature to last part
        if part_num == total_parts:
            signature = self._format_link(
                "Sent by AI Marketplace Monitor",
                "https://github.com/BoPeng/ai-marketplace-monitor",
                italic=True,
            )
            full_message += f"\n\n{signature}"

        return full_message

    async def _send_with_retry(
        self: Self, bot: Bot, text: str, parse_mode: Optional[str], logger: Optional[Logger] = None
    ) -> bool:
        """Send message with simple retry logic."""
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                await bot.send_message(
                    chat_id=self.telegram_chat_id,  # type: ignore[arg-type]
                    text=text,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True,
                )
                return True

            except (RetryAfter, TimedOut, NetworkError) as e:
                # Transient errors - retry with backoff
                last_error = e
                if attempt < self.max_retries - 1:
                    wait_time = 2**attempt  # Exponential backoff
                    if isinstance(e, RetryAfter):
                        wait_time = e.retry_after
                    await asyncio.sleep(wait_time)
                    continue

            except BadRequest as e:
                # Check if it's a formatting error
                error_message = str(e).lower()
                if logger:
                    logger.debug(f"BadRequest caught: {error_message}")

                if "can't parse entities" in error_message:
                    if logger:
                        logger.error(f"MarkdownV2 parsing error: {e}")
                        logger.debug(f"Failed message: {text}")

                    # Try sending as plain text
                    if parse_mode is not None:
                        try:
                            await bot.send_message(
                                chat_id=self.telegram_chat_id,  # type: ignore[arg-type]
                                text=text.replace("\\", ""),  # Remove escape characters
                                parse_mode=None,  # Plain text
                                disable_web_page_preview=True,
                            )
                            if logger:
                                logger.warning("Sent as plain text after formatting error")
                            return True
                        except Exception as e2:
                            last_error = e2
                            if logger:
                                logger.error(f"Fallback to plain text also failed: {e2}")
                else:
                    last_error = e
                break

            except Exception as e:
                last_error = e
                break

        if logger and last_error:
            logger.error(
                f"Failed to send Telegram message after {self.max_retries} attempts: {last_error}"
            )

        return False

    async def _send_all_parts(
        self: Self, title: str, parts: List[str], logger: Optional[Logger] = None
    ) -> bool:
        """Send all message parts."""
        parse_mode = self._get_parse_mode()
        success_count = 0

        async with self._create_bot() as bot:
            for i, part in enumerate(parts):
                # Format the message part with proper numbering
                formatted = self._format_message_part(title, part, i + 1, len(parts))

                # Check length
                if len(formatted) > MessageLimit.MAX_TEXT_LENGTH:
                    if logger:
                        logger.warning(
                            f"Part {i + 1} exceeds limit ({len(formatted)} chars), truncating"
                        )
                    # Leave room for ellipsis and signature
                    max_content = MessageLimit.MAX_TEXT_LENGTH - 200
                    part = part[:max_content] + "..."
                    formatted = self._format_message_part(title, part, i + 1, len(parts))

                # Send with retry
                if await self._send_with_retry(bot, formatted, parse_mode, logger):
                    success_count += 1
                else:
                    if logger:
                        logger.error(f"Failed to send part {i + 1}/{len(parts)}")

        return success_count > 0

    def send_message(
        self: Self, title: str, message: str, logger: Optional[Logger] = None
    ) -> bool:
        """Send a message via Telegram with proper formatting and error handling."""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            if logger:
                logger.error("Missing Telegram configuration")
            return False

        try:
            # Escape the message content
            escaped_message = self._escape_text(message)

            # Calculate max content length (leave room for title, numbering, signature)
            max_content_length = MessageLimit.MAX_TEXT_LENGTH - 300

            # Split message if needed
            parts = self._split_message(escaped_message, max_content_length)

            if logger:
                logger.debug(f"Sending Telegram message in {len(parts)} part(s)")

            # Send asynchronously
            # Handle different async contexts properly
            try:
                # Check if we're in an existing event loop
                asyncio.get_running_loop()
                # We're in an async context (like pytest-asyncio)
                # Can't use asyncio.run(), need to handle differently

                def run_in_thread() -> bool:
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        return new_loop.run_until_complete(
                            self._send_all_parts(title, parts, logger)
                        )
                    finally:
                        new_loop.close()

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(run_in_thread)
                    success = future.result()
            except RuntimeError:
                # No running event loop, safe to use asyncio.run()
                success = asyncio.run(self._send_all_parts(title, parts, logger))

            if success and logger:
                logger.info(f"{hilight('[Notify]', 'succ')} Sent message to {self.name}")

            return success

        except Exception as e:
            if logger:
                logger.error(f"Telegram send error: {e}")
            return False
