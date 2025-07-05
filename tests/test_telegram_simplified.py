"""Test cases for the simplified Telegram implementation following TDD principles."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut

from ai_marketplace_monitor.telegram import TelegramNotificationConfig


class TestSimplifiedTelegramFormatting:
    """Test formatting functionality in the simplified implementation."""

    def test_escape_text_markdownv2(self: Self) -> None:
        """Test that text is properly escaped for MarkdownV2."""
        config = TelegramNotificationConfig(
            name="test",
            telegram_bot_token="fake_token",
            telegram_chat_id="fake_chat_id",
            message_format="markdownv2",
        )

        # Test basic escaping
        text = "Hello *world* (test)"
        escaped = config._escape_text(text)
        assert "\\*world\\*" in escaped
        assert "\\(test\\)" in escaped

    def test_escape_text_html(self: Self) -> None:
        """Test that text is properly escaped for HTML."""
        config = TelegramNotificationConfig(
            name="test",
            telegram_bot_token="fake_token",
            telegram_chat_id="fake_chat_id",
            message_format="html",
        )

        text = "Hello <world> & test"
        escaped = config._escape_text(text)
        assert "&lt;world&gt;" in escaped
        assert "&amp; test" in escaped

    def test_escape_text_plain(self: Self) -> None:
        """Test that plain text is not escaped."""
        config = TelegramNotificationConfig(
            name="test",
            telegram_bot_token="fake_token",
            telegram_chat_id="fake_chat_id",
            message_format="plain_text",
        )

        text = "Hello *world* (test)"
        escaped = config._escape_text(text)
        assert escaped == text  # No escaping for plain text

    def test_format_bold(self: Self) -> None:
        """Test bold formatting with proper escaping."""
        config = TelegramNotificationConfig(
            name="test",
            telegram_bot_token="fake_token",
            telegram_chat_id="fake_chat_id",
            message_format="markdownv2",
        )

        text = "Price: $10.50"
        formatted = config._format_bold(text)
        assert formatted == "*Price: $10\\.50*"

    def test_format_link(self: Self) -> None:
        """Test link formatting."""
        config = TelegramNotificationConfig(
            name="test",
            telegram_bot_token="fake_token",
            telegram_chat_id="fake_chat_id",
            message_format="markdownv2",
        )

        text = "Click here!"
        url = "https://example.com"
        formatted = config._format_link(text, url)
        assert formatted == "[Click here\\!](https://example.com)"

        # Test italic link
        formatted_italic = config._format_link(text, url, italic=True)
        assert formatted_italic == "_[Click here\\!](https://example.com)_"

    def test_message_part_formatting_single(self: Self) -> None:
        """Test formatting a single message part (no numbering)."""
        config = TelegramNotificationConfig(
            name="test",
            telegram_bot_token="fake_token",
            telegram_chat_id="fake_chat_id",
            message_format="markdownv2",
        )

        title = "New Items"
        content = "Found some items"
        formatted = config._format_message_part(title, content, 1, 1)

        # Should have bold title
        assert "*New Items*\n\n" in formatted
        # Should have content
        assert "Found some items" in formatted
        # Should have signature
        assert (
            "_[Sent by AI Marketplace Monitor](https://github.com/BoPeng/ai-marketplace-monitor)_"
            in formatted
        )
        # Should NOT have numbering
        assert "\\(1/1\\)" not in formatted

    def test_message_part_formatting_multiple(self: Self) -> None:
        """Test formatting multiple message parts with numbering."""
        config = TelegramNotificationConfig(
            name="test",
            telegram_bot_token="fake_token",
            telegram_chat_id="fake_chat_id",
            message_format="markdownv2",
        )

        title = "New Items"
        content = "Part 1 content"

        # First part
        formatted1 = config._format_message_part(title, content, 1, 2)
        assert "*New Items* \\(1/2\\)\n\n" in formatted1
        assert "Part 1 content" in formatted1
        # First part should NOT have signature
        assert "Sent by AI Marketplace Monitor" not in formatted1

        # Last part
        content2 = "Part 2 content"
        formatted2 = config._format_message_part(title, content2, 2, 2)
        assert "*New Items* \\(2/2\\)\n\n" in formatted2
        assert "Part 2 content" in formatted2
        # Last part SHOULD have signature
        assert (
            "_[Sent by AI Marketplace Monitor](https://github.com/BoPeng/ai-marketplace-monitor)_"
            in formatted2
        )

    def test_split_message(self: Self) -> None:
        """Test message splitting logic."""
        config = TelegramNotificationConfig(
            name="test", telegram_bot_token="fake_token", telegram_chat_id="fake_chat_id"
        )

        # Short message - no split
        short_msg = "Hello world"
        parts = config._split_message(short_msg, 100)
        assert len(parts) == 1
        assert parts[0] == short_msg

        # Long message - split at paragraph
        long_msg = "First paragraph.\n\nSecond paragraph that is very long " * 10
        parts = config._split_message(long_msg, 50)
        assert len(parts) > 1
        assert parts[0] == "First paragraph."

        # No paragraph boundary - split at line
        long_msg = "Line 1\nLine 2 that is very long " * 10
        parts = config._split_message(long_msg, 20)
        assert len(parts) > 1
        assert parts[0] == "Line 1"


class TestSimplifiedTelegramRetry:
    """Test retry logic in the simplified implementation."""

    @pytest.mark.asyncio
    async def test_send_with_retry_success(self: Self) -> None:
        """Test successful send on first attempt."""
        config = TelegramNotificationConfig(
            name="test", telegram_bot_token="fake_token", telegram_chat_id="fake_chat_id"
        )

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(return_value=MagicMock())

        result = await config._send_with_retry(mock_bot, "Test message", "MarkdownV2")

        assert result is True
        assert mock_bot.send_message.call_count == 1

    @pytest.mark.asyncio
    async def test_send_with_retry_transient_error(self: Self) -> None:
        """Test retry on transient errors."""
        config = TelegramNotificationConfig(
            name="test",
            telegram_bot_token="fake_token",
            telegram_chat_id="fake_chat_id",
            max_retries=3,
        )

        mock_bot = AsyncMock()
        # Fail twice, then succeed
        mock_bot.send_message = AsyncMock(
            side_effect=[NetworkError("Network error"), TimedOut(), MagicMock()]
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await config._send_with_retry(mock_bot, "Test message", "MarkdownV2")

        assert result is True
        assert mock_bot.send_message.call_count == 3

    @pytest.mark.asyncio
    async def test_send_with_retry_rate_limit(self: Self) -> None:
        """Test retry with rate limiting."""
        config = TelegramNotificationConfig(
            name="test", telegram_bot_token="fake_token", telegram_chat_id="fake_chat_id"
        )

        mock_bot = AsyncMock()
        # Rate limit, then succeed
        mock_bot.send_message = AsyncMock(side_effect=[RetryAfter(retry_after=1), MagicMock()])

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await config._send_with_retry(mock_bot, "Test message", "MarkdownV2")

        assert result is True
        assert mock_bot.send_message.call_count == 2
        # Should sleep for the server-specified time
        mock_sleep.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_send_with_retry_formatting_error_logs(self: Self) -> None:
        """Test that formatting errors are properly logged."""
        config = TelegramNotificationConfig(
            name="test",
            telegram_bot_token="fake_token",
            telegram_chat_id="fake_chat_id",
            max_retries=1,
        )

        mock_bot = AsyncMock()

        # Always fail with formatting error
        mock_bot.send_message = AsyncMock(
            side_effect=BadRequest("can't parse entities: character '(' is reserved")
        )

        # Create a logger
        mock_logger = MagicMock()

        # Call with text that has MarkdownV2 escapes
        result = await config._send_with_retry(
            mock_bot, "Test \\*bold\\* text", "MarkdownV2", logger=mock_logger
        )

        # Result will be False since fallback is not implemented
        assert result is False

        # Verify error logging occurred
        assert mock_logger.error.called
        assert any(
            "Failed to send Telegram message" in str(call)
            for call in mock_logger.error.call_args_list
        )


class TestSimplifiedTelegramIntegration:
    """Integration tests for the simplified implementation."""

    def test_send_message_missing_config(self: Self) -> None:
        """Test that send_message fails gracefully with missing config."""
        config = TelegramNotificationConfig(name="test")

        # Missing bot token and chat ID
        result = config.send_message("Title", "Message")
        assert result is False

    def test_send_message_success(self: Self) -> None:
        """Test successful message sending."""
        config = TelegramNotificationConfig(
            name="test",
            telegram_bot_token="fake_token",
            telegram_chat_id="fake_chat_id",
            message_format="markdownv2",
        )

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(return_value=MagicMock())

        with patch.object(config, "_create_bot") as mock_create_bot:
            mock_create_bot.return_value.__aenter__.return_value = mock_bot

            result = config.send_message("Test Title", "Test message content")

            assert result is True
            assert mock_bot.send_message.called

            # Check the sent message
            call_args = mock_bot.send_message.call_args[1]
            assert call_args["parse_mode"] == "MarkdownV2"
            assert "*Test Title*" in call_args["text"]
            assert "Test message content" in call_args["text"]

    def test_send_long_message(self: Self) -> None:
        """Test sending a message that needs to be split."""
        config = TelegramNotificationConfig(
            name="test",
            telegram_bot_token="fake_token",
            telegram_chat_id="fake_chat_id",
            message_format="markdownv2",
        )

        # Create a very long message
        long_content = "This is a test message. " * 500

        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(return_value=MagicMock())

        with patch.object(config, "_create_bot") as mock_create_bot:
            mock_create_bot.return_value.__aenter__.return_value = mock_bot

            result = config.send_message("Long Message", long_content)

            assert result is True
            # Should have sent multiple parts
            assert mock_bot.send_message.call_count > 1

            # Check that parts have numbering
            first_call = mock_bot.send_message.call_args_list[0]
            assert "\\(1/" in first_call[1]["text"]
