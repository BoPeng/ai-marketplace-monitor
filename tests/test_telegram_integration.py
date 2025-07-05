"""Integration tests for Telegram formatting fixes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from typing import Self
except ImportError:
    from typing_extensions import Self

from ai_marketplace_monitor.telegram import TelegramNotificationConfig


class TestTelegramIntegration:
    """Integration tests for the Telegram formatting fix."""

    @pytest.mark.asyncio
    async def test_multipart_message_with_special_characters(self: Self) -> None:
        """Test that multipart messages with special characters are properly formatted."""
        config = TelegramNotificationConfig(
            name="test",
            telegram_bot_token="fake_token",
            telegram_chat_id="fake_chat_id",
            message_format="markdownv2",
        )

        # Create a long message that will be split
        title = "Found 10 new priuses from facebook"
        message_content = """[Good match (4)] [*2017 Toyota prius*](https://www.facebook.com/marketplace/item/123/)
$11,500, High Point, NC
About this vehicle
Driven 95,550 miles · Automatic transmission
Exterior color: Blue · Interior color: Black
Fuel type: Hybrid · Excellent condition

Seller's description:
Excellent condition. Needs a new owner.
*AI*: This listing mostly meets the criteria with relevant details but lacks specificity.
"""

        # Create a message that's long enough to be split (repeat content)
        long_message = (message_content + "\n\n") * 50  # Make it really long

        # Mock the bot
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=123))

        with patch.object(config, "_create_bot") as mock_create_bot:
            mock_create_bot.return_value.__aenter__.return_value = mock_bot

            # Send the message
            success = config.send_message(title, long_message)

            # Should succeed
            assert success

            # Check that multiple messages were sent
            assert mock_bot.send_message.call_count > 1

            # Check the first message
            first_call = mock_bot.send_message.call_args_list[0]
            first_message = first_call[1]["text"]

            # Should have escaped parentheses in numbering
            assert "\\(1/" in first_message
            assert "*Found 10 new priuses from facebook* \\(1/" in first_message

            # Should have escaped special characters in content
            assert "\\[Good match \\(4\\)\\]" in first_message
            assert "\\*2017 Toyota prius\\*" in first_message

    def test_formatting_error_fallback(self: Self) -> None:
        """Test that formatting errors are handled gracefully."""
        config = TelegramNotificationConfig(
            name="test",
            telegram_bot_token="fake_token",
            telegram_chat_id="fake_chat_id",
            message_format="markdownv2",
        )

        title = "Test Message"
        # Message with properly escaped formatting
        message = "This has matched *bold* and _italic_ formatting"

        # Mock the bot to succeed
        mock_bot = AsyncMock()
        mock_bot.send_message = AsyncMock(return_value=MagicMock(message_id=123))

        with patch.object(config, "_create_bot") as mock_create_bot:
            mock_create_bot.return_value.__aenter__.return_value = mock_bot

            # Send the message
            success = config.send_message(title, message)

            # Should succeed
            assert success

            # Check the message was properly escaped
            call_args = mock_bot.send_message.call_args_list[0]
            sent_text = call_args[1]["text"]

            # Should have escaped formatting characters
            assert "\\*bold\\*" in sent_text
            assert "\\_italic\\_" in sent_text

    def test_edge_case_formatting(self: Self) -> None:
        """Test edge cases in formatting."""
        config = TelegramNotificationConfig(
            name="test",
            telegram_bot_token="fake_token",
            telegram_chat_id="fake_chat_id",
            message_format="markdownv2",
        )

        # Test various edge cases
        test_cases = [
            # (title, message, expected_in_output)
            ("Price: $10.50", "Content", "$10\\.50"),
            ("100% match!", "Content", "100% match\\!"),
            ("A/C & Heat", "Content", "A/C & Heat"),  # & is not escaped
            ("Email: test@example.com", "Content", "test@example\\.com"),
            ("Phone: (555) 123-4567", "Content", "\\(555\\) 123\\-4567"),
        ]

        for title, _message, expected in test_cases:
            # Format using _format_message_part and extract title
            full_message = config._format_message_part(title, "", 1, 1)
            formatted = full_message.split("\n")[0]
            assert (
                expected in formatted
            ), f"Expected '{expected}' in '{formatted}' for title '{title}'"

        print("All edge case formatting tests passed!")
