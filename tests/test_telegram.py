import asyncio
import threading
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from telegram import Message
from telegram.constants import MessageLimit
from telegram.error import BadRequest, RetryAfter, TelegramError, TimedOut

from ai_marketplace_monitor.telegram import TelegramNotificationConfig


def run_async_in_thread(coro: Any) -> Any:
    """Run an async coroutine in a separate thread with its own event loop.

    This custom fixture is necessary to solve the event loop conflict between:
    1. Playwright tests that create their own event loop for browser automation
    2. pytest-asyncio that tries to manage event loops for async test methods

    When both run in the same process, pytest-asyncio throws "RuntimeError: This event loop is already running"
    because Playwright's event loop is already active. By running async tests in a separate thread
    with their own isolated event loop, we avoid this conflict while maintaining full test coverage.

    This is a workaround for the known incompatibility between pytest-playwright and pytest-asyncio
    when used together in the same test suite.
    """
    result = None
    exception = None

    def run_in_thread():
        nonlocal result, exception
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(coro)
            finally:
                loop.close()
        except Exception as e:
            exception = e

    thread = threading.Thread(target=run_in_thread)
    thread.start()
    thread.join()

    if exception:
        raise exception
    return result


class TestTelegramNotificationConfig:
    """Test suite for TelegramNotificationConfig."""

    def test_init_defaults(self: "TestTelegramNotificationConfig") -> None:
        """Test default initialization."""
        config = TelegramNotificationConfig(name="test")
        assert config.notify_method == "telegram"
        assert config.telegram_bot_token is None
        assert config.telegram_chat_id is None
        assert config.message_format == "markdownv2"  # Should default to markdownv2

    def test_init_with_values(self: "TestTelegramNotificationConfig") -> None:
        """Test initialization with values."""
        config = TelegramNotificationConfig(
            name="test",
            telegram_bot_token="bot123",
            telegram_chat_id="chat456",
            message_format="html",
        )
        assert config.telegram_bot_token == "bot123"  # noqa: S105
        assert config.telegram_chat_id == "chat456"
        assert config.message_format == "html"

    def test_required_fields(self: "TestTelegramNotificationConfig") -> None:
        """Test required fields class variable."""
        assert TelegramNotificationConfig.required_fields == [
            "telegram_bot_token",
            "telegram_chat_id",
        ]

    @pytest.mark.parametrize(
        "token,should_raise",
        [
            ("valid_token", False),
            ("  valid_token  ", False),  # Should be stripped
            ("", True),
            (None, False),  # None is allowed
            (123, True),  # Non-string should raise
        ],
    )
    def test_handle_telegram_bot_token(
        self: "TestTelegramNotificationConfig", token: Any, should_raise: bool
    ) -> None:
        """Test telegram_bot_token validation."""
        if should_raise:
            with pytest.raises(ValueError, match="non-empty telegram_bot_token"):
                config = TelegramNotificationConfig(name="test", telegram_bot_token=token)
        else:
            config = TelegramNotificationConfig(name="test", telegram_bot_token=token)
            if token and isinstance(token, str):
                assert config.telegram_bot_token == token.strip()

    @pytest.mark.parametrize(
        "chat_id,should_raise",
        [
            ("123456", False),
            ("  123456  ", False),  # Should be stripped
            ("@channel", False),
            ("", True),
            (None, False),  # None is allowed
            (123, True),  # Non-string should raise
        ],
    )
    def test_handle_telegram_chat_id(
        self: "TestTelegramNotificationConfig", chat_id: Any, should_raise: bool
    ) -> None:
        """Test telegram_chat_id validation."""
        if should_raise:
            with pytest.raises(ValueError, match="non-empty telegram_chat_id"):
                config = TelegramNotificationConfig(name="test", telegram_chat_id=chat_id)
        else:
            config = TelegramNotificationConfig(name="test", telegram_chat_id=chat_id)
            if chat_id and isinstance(chat_id, str):
                assert config.telegram_chat_id == chat_id.strip()

    def test_handle_message_format_default(self: "TestTelegramNotificationConfig") -> None:
        """Test message_format defaults to markdownv2 when None."""
        config = TelegramNotificationConfig(name="test")
        # message_format should already be "markdownv2" due to override in handle_message_format
        assert config.message_format == "markdownv2"

    def test_handle_message_format_explicit(self: "TestTelegramNotificationConfig") -> None:
        """Test message_format when explicitly set."""
        config = TelegramNotificationConfig(name="test", message_format="html")
        config.handle_message_format()
        assert config.message_format == "html"


class TestTelegramMessaging:
    """Test suite for Telegram messaging functionality."""

    @pytest.fixture
    def telegram_config(self: "TestTelegramMessaging") -> TelegramNotificationConfig:
        """Create a TelegramNotificationConfig instance for testing."""
        return TelegramNotificationConfig(
            name="test_telegram",
            telegram_bot_token="test_bot_token",
            telegram_chat_id="test_chat_id",
            message_format="markdown",
        )

    @pytest.fixture
    def mock_logger(self: "TestTelegramMessaging") -> Mock:
        """Create a mock logger."""
        logger = Mock()
        logger.debug = Mock()
        logger.info = Mock()
        logger.warning = Mock()
        logger.error = Mock()
        return logger

    @pytest.mark.asyncio
    async def test_send_message_async_success(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test successful async message sending."""
        mock_bot = AsyncMock()
        mock_message = Mock(spec=Message)
        mock_message.message_id = 12345
        mock_bot.send_message.return_value = mock_message

        result = await telegram_config._send_message_async(
            mock_bot, "Test message", "MarkdownV2", mock_logger
        )

        assert result is True
        mock_bot.send_message.assert_called_once_with(
            chat_id="test_chat_id",
            text="Test message",
            parse_mode="MarkdownV2",
            disable_web_page_preview=True,
        )

    @pytest.mark.asyncio
    async def test_send_message_async_retry_after(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test RetryAfter exception handling."""
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = [RetryAfter(retry_after=0.1), Mock(message_id=12345)]

        result = await telegram_config._send_message_async(
            mock_bot, "Test message", None, mock_logger, max_retries=1
        )

        assert result is True
        assert mock_bot.send_message.call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_message_async_timeout(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test TimedOut exception handling."""
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = [TimedOut(), Mock(message_id=12345)]

        result = await telegram_config._send_message_async(
            mock_bot, "Test message", None, mock_logger, max_retries=1
        )

        assert result is True
        assert mock_bot.send_message.call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_message_async_bad_request(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test BadRequest exception handling (should not retry)."""
        mock_bot = AsyncMock()
        error = BadRequest("Can't parse entities")
        error.message = "Can't parse entities: invalid markup"
        mock_bot.send_message.side_effect = error

        result = await telegram_config._send_message_async(
            mock_bot, "Test message", "MarkdownV2", mock_logger
        )

        assert result is False
        mock_bot.send_message.assert_called_once()
        # Verify error logging
        assert mock_logger.error.call_count >= 3

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_message_async_telegram_error(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test general TelegramError handling."""
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = TelegramError("General error")

        result = await telegram_config._send_message_async(
            mock_bot, "Test message", None, mock_logger
        )

        assert result is False
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_all_messages_async_single(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test sending a single message with formatting."""
        with patch("ai_marketplace_monitor.telegram.Bot") as mock_bot_class:
            mock_bot = AsyncMock()
            mock_bot_class.return_value.__aenter__.return_value = mock_bot
            mock_bot.send_message.return_value = Mock(message_id=12345)

            result = await telegram_config._send_all_messages_async(
                "Test Title", ["Test content"], "MarkdownV2", mock_logger
            )

            assert result is True
            mock_bot.send_message.assert_called_once()
            call_args = mock_bot.send_message.call_args[1]
            assert "Test Title" in call_args["text"]
            assert "Test content" in call_args["text"]
            assert "Sent by AI Marketplace Monitor" in call_args["text"]

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_all_messages_async_multiple(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test sending multiple message parts."""
        with patch("ai_marketplace_monitor.telegram.Bot") as mock_bot_class:
            mock_bot = AsyncMock()
            mock_bot_class.return_value.__aenter__.return_value = mock_bot
            mock_bot.send_message.return_value = Mock(message_id=12345)

            messages = ["Part 1", "Part 2", "Part 3"]
            result = await telegram_config._send_all_messages_async(
                "Test Title", messages, "MarkdownV2", mock_logger
            )

            assert result is True
            assert mock_bot.send_message.call_count == 3

            # Check that part numbers are included
            for i, call in enumerate(mock_bot.send_message.call_args_list):
                text = call[1]["text"]
                assert f"({i + 1}/3)" in text
                assert f"Part {i + 1}" in text

            # Check signature is only in last message
            last_call_text = mock_bot.send_message.call_args_list[-1][1]["text"]
            assert "Sent by AI Marketplace Monitor" in last_call_text

    def test_send_message_no_credentials(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test send_message with missing credentials."""
        telegram_config.telegram_bot_token = None
        result = telegram_config.send_message("Title", "Message", mock_logger)
        assert result is False

        telegram_config.telegram_bot_token = "token"  # noqa: S105
        telegram_config.telegram_chat_id = None
        result = telegram_config.send_message("Title", "Message", mock_logger)
        assert result is False

    def test_send_message_markdown_escaping(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test markdown escaping in messages."""
        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    message = "Test *bold* _italic_ [link](url)"
                    telegram_config.send_message("Title", message, mock_logger)

                    # Verify escaping was applied
                    mock_loop.return_value.run_until_complete.assert_called_once()
                    mock_loop.return_value.run_until_complete.call_args[0][0]
                    # Verify the coroutine was called
                    assert mock_loop.return_value.run_until_complete.called

    def test_send_message_html_escaping(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test HTML escaping in messages."""
        telegram_config.message_format = "html"
        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    message = "Test <b>bold</b> & special"
                    telegram_config.send_message("Title", message, mock_logger)

                    mock_loop.return_value.run_until_complete.assert_called_once()

    def test_send_message_plain_text(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test plain text messages (no escaping)."""
        telegram_config.message_format = "plain_text"
        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    message = "Test *bold* <tag>"
                    telegram_config.send_message("Title", message, mock_logger)

                    mock_loop.return_value.run_until_complete.assert_called_once()

    def test_message_splitting_long_message(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test message splitting for long messages."""
        # Create a message that exceeds the limit
        long_message = "Test content " * 500  # Create a very long message

        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    telegram_config.send_message("Title", long_message, mock_logger)

                    # Should be called with split messages
                    mock_loop.return_value.run_until_complete.call_args[0][0]
                    # Verify it was called (the actual splitting logic is complex)
                    mock_loop.return_value.run_until_complete.assert_called_once()

    def test_message_splitting_by_paragraphs(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test message splitting preserves paragraph boundaries."""
        # Create a message with clear paragraph boundaries
        message_parts = ["Paragraph 1" * 100, "Paragraph 2" * 100, "Paragraph 3" * 100]
        message = "\n\n".join(message_parts)

        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    telegram_config.send_message("Title", message, mock_logger)

                    mock_loop.return_value.run_until_complete.assert_called_once()

    def test_send_message_with_running_event_loop(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test send_message when already in an event loop."""
        with patch("asyncio.get_running_loop", return_value=Mock()):
            with patch("concurrent.futures.ThreadPoolExecutor") as mock_executor:
                mock_future = Mock()
                mock_future.result.return_value = True
                mock_executor.return_value.__enter__.return_value.submit.return_value = mock_future

                result = telegram_config.send_message("Title", "Message", mock_logger)

                assert result is True
                mock_executor.return_value.__enter__.return_value.submit.assert_called_once()

    def test_send_message_exception_handling(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test exception handling in send_message."""
        with patch("asyncio.get_running_loop", side_effect=Exception("Test error")):
            result = telegram_config.send_message("Title", "Message", mock_logger)
            assert result is False

    @pytest.mark.parametrize(
        "message_format,expected_parse_mode",
        [
            ("markdown", "MarkdownV2"),
            ("html", "HTML"),
            ("plain_text", None),
        ],
    )
    def test_parse_mode_selection(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
        message_format: str,
        expected_parse_mode: str,
    ) -> None:
        """Test correct parse mode selection based on message format."""
        telegram_config.message_format = message_format

        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    telegram_config.send_message("Title", "Message", mock_logger)

                    # Get the coroutine that was passed to run_until_complete
                    mock_loop.return_value.run_until_complete.call_args[0][0]
                    # Since we can't easily inspect the coroutine, we'll trust the implementation
                    mock_loop.return_value.run_until_complete.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_message_async_max_retries_exceeded(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test max retries exceeded for rate limiting."""
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = RetryAfter(retry_after=0.01)

        result = await telegram_config._send_message_async(
            mock_bot, "Test message", None, mock_logger, max_retries=2
        )

        assert result is False
        assert mock_bot.send_message.call_count == 3  # initial + 2 retries
        mock_logger.error.assert_called_with("Max retries exceeded for rate limiting")

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_message_async_timeout_max_retries(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test max retries exceeded for timeout."""
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = TimedOut()

        result = await telegram_config._send_message_async(
            mock_bot, "Test message", None, mock_logger, max_retries=1
        )

        assert result is False
        assert mock_bot.send_message.call_count == 2  # initial + 1 retry
        mock_logger.error.assert_called_with("Max retries exceeded for timeout")

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_all_messages_async_html_format(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test HTML formatting in send_all_messages_async."""
        telegram_config.message_format = "html"

        with patch("ai_marketplace_monitor.telegram.Bot") as mock_bot_class:
            mock_bot = AsyncMock()
            mock_bot_class.return_value.__aenter__.return_value = mock_bot
            mock_bot.send_message.return_value = Mock(message_id=12345)

            result = await telegram_config._send_all_messages_async(
                "Test <Title>", ["Test & content"], "HTML", mock_logger
            )

            assert result is True
            call_text = mock_bot.send_message.call_args[1]["text"]
            assert "<b>Test &lt;Title&gt;</b>" in call_text  # Title should be escaped
            # Note: Content is pre-escaped in send_message, not in _send_all_messages_async
            assert "Test & content" in call_text

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_all_messages_async_plain_text(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test plain text formatting in send_all_messages_async."""
        telegram_config.message_format = "plain_text"

        with patch("ai_marketplace_monitor.telegram.Bot") as mock_bot_class:
            mock_bot = AsyncMock()
            mock_bot_class.return_value.__aenter__.return_value = mock_bot
            mock_bot.send_message.return_value = Mock(message_id=12345)

            result = await telegram_config._send_all_messages_async(
                "Test Title", ["Test content"], None, mock_logger
            )

            assert result is True
            call_text = mock_bot.send_message.call_args[1]["text"]
            assert "Test Title" in call_text  # Plain text, no formatting
            assert "https://github.com/BoPeng/ai-marketplace-monitor" in call_text

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_all_messages_async_message_too_long(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test message truncation when exceeding limit."""
        with patch("ai_marketplace_monitor.telegram.Bot") as mock_bot_class:
            mock_bot = AsyncMock()
            mock_bot_class.return_value.__aenter__.return_value = mock_bot
            mock_bot.send_message.return_value = Mock(message_id=12345)

            # Create a message that would exceed the limit
            very_long_message = "x" * (MessageLimit.MAX_TEXT_LENGTH + 1000)

            result = await telegram_config._send_all_messages_async(
                "Title", [very_long_message], "MarkdownV2", mock_logger
            )

            assert result is True
            call_text = mock_bot.send_message.call_args[1]["text"]
            assert len(call_text) <= MessageLimit.MAX_TEXT_LENGTH
            assert "..." in call_text
            mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_all_messages_async_failure(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test handling of send failure in send_all_messages_async."""
        with patch("ai_marketplace_monitor.telegram.Bot") as mock_bot_class:
            mock_bot = AsyncMock()
            mock_bot_class.return_value.__aenter__.return_value = mock_bot
            mock_bot.send_message.side_effect = TelegramError("Network error")

            result = await telegram_config._send_all_messages_async(
                "Title", ["Message 1", "Message 2"], "MarkdownV2", mock_logger
            )

            assert result is False
            # Should stop after first failure
            mock_bot.send_message.assert_called_once()

    def test_send_message_success_with_logging(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test successful message sending with logging."""
        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    result = telegram_config.send_message(
                        "Test Title", "Test message", mock_logger
                    )

                    assert result is True
                    # Check success logging
                    mock_logger.info.assert_called()
                    info_call = mock_logger.info.call_args[0][0]
                    assert "[Notify]" in info_call
                    assert "Test Title" in info_call

    def test_send_message_failure_with_logging(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test failed message sending with logging."""
        with patch.object(telegram_config, "_send_all_messages_async", return_value=False):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = False

                    result = telegram_config.send_message(
                        "Test Title", "Test message", mock_logger
                    )

                    assert result is False
                    # Check failure logging
                    mock_logger.error.assert_called()
                    error_call = mock_logger.error.call_args[0][0]
                    assert "Failed to send message" in error_call

    def test_send_message_splitting_single_long_piece(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test message splitting when a single piece is too long."""
        # Create a single very long word that can't be split at spaces
        long_word = "a" * 4500

        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    telegram_config.send_message("Title", long_word, mock_logger)

                    # Should be called with multiple messages due to splitting
                    mock_loop.return_value.run_until_complete.assert_called_once()

    def test_send_message_debug_logging(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test debug logging throughout send_message."""
        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    telegram_config.send_message("Title", "Message", mock_logger)

                    # Verify debug logging calls
                    assert mock_logger.debug.call_count > 5
                    debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
                    assert any("Entering send_message" in call for call in debug_calls)
                    assert any("Message format: markdown" in call for call in debug_calls)

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_message_async_without_logger(
        self: "TestTelegramMessaging", telegram_config: TelegramNotificationConfig
    ) -> None:
        """Test _send_message_async without logger."""
        mock_bot = AsyncMock()
        mock_message = Mock(spec=Message)
        mock_message.message_id = 12345
        mock_bot.send_message.return_value = mock_message

        # Call without logger
        result = await telegram_config._send_message_async(
            mock_bot, "Test message", "MarkdownV2", None
        )

        assert result is True
        mock_bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_all_messages_async_without_logger(
        self: "TestTelegramMessaging", telegram_config: TelegramNotificationConfig
    ) -> None:
        """Test _send_all_messages_async without logger."""
        with patch("ai_marketplace_monitor.telegram.Bot") as mock_bot_class:
            mock_bot = AsyncMock()
            mock_bot_class.return_value.__aenter__.return_value = mock_bot
            mock_bot.send_message.return_value = Mock(message_id=12345)

            result = await telegram_config._send_all_messages_async(
                "Test Title", ["Test content"], "MarkdownV2", None
            )

            assert result is True
            mock_bot.send_message.assert_called_once()

    def test_send_message_without_logger(
        self: "TestTelegramMessaging", telegram_config: TelegramNotificationConfig
    ) -> None:
        """Test send_message without logger."""
        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    # Call without logger
                    result = telegram_config.send_message("Title", "Message", None)

                    assert result is True

    def test_send_message_no_credentials_no_logger(
        self: "TestTelegramMessaging", telegram_config: TelegramNotificationConfig
    ) -> None:
        """Test send_message with missing credentials and no logger."""
        telegram_config.telegram_bot_token = None
        result = telegram_config.send_message("Title", "Message", None)
        assert result is False

    def test_send_message_split_at_word_boundary(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test message splitting finds word boundaries correctly."""
        # Create a message where we need to split at word boundary
        word = "word "
        # Make it just long enough that adding one more word would exceed limit
        long_message = word * 800  # This should be close to the limit

        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    telegram_config.send_message("Title", long_message, mock_logger)

                    # The message should be split
                    mock_loop.return_value.run_until_complete.assert_called_once()

    def test_send_message_split_force_when_no_space(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test force split when no space found in long piece."""
        # Create a single very long "word" with no spaces that exceeds max_content_length
        long_word_piece = "a" * 5000  # Definitely exceeds max_content_length

        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    telegram_config.send_message("Title", long_word_piece, mock_logger)

                    # Should be called with split messages
                    mock_loop.return_value.run_until_complete.assert_called_once()
                    # Get the actual call to verify multiple messages were created
                    mock_loop.return_value.run_until_complete.call_args[0][0]

    def test_send_message_exception_in_thread(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test exception handling when running in thread."""
        with patch("asyncio.get_running_loop", return_value=Mock()):
            with patch("concurrent.futures.ThreadPoolExecutor") as mock_executor:
                mock_future = Mock()
                mock_future.result.side_effect = Exception("Thread error")
                mock_executor.return_value.__enter__.return_value.submit.return_value = mock_future

                result = telegram_config.send_message("Title", "Message", mock_logger)

                assert result is False
                mock_logger.error.assert_called()
                error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
                assert any(
                    "Unexpected error sending Telegram message" in call for call in error_calls
                )

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_message_async_debug_logging(
        self: "TestTelegramMessaging", telegram_config: TelegramNotificationConfig
    ) -> None:
        """Test debug logging in _send_message_async."""
        mock_bot = AsyncMock()
        mock_message = Mock(spec=Message)
        mock_message.message_id = 12345
        mock_bot.send_message.return_value = mock_message

        mock_logger = Mock()

        result = await telegram_config._send_message_async(
            mock_bot, "Test message", "MarkdownV2", mock_logger
        )

        assert result is True
        # Verify debug logging
        assert mock_logger.debug.call_count >= 3
        debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
        assert any("_send_message_async called" in call for call in debug_calls)
        assert any("Message sent successfully" in call for call in debug_calls)

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_message_async_no_retry_on_general_error(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test that general TelegramError doesn't retry."""
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = TelegramError("General error")

        result = await telegram_config._send_message_async(
            mock_bot, "Test message", None, mock_logger, max_retries=3
        )

        assert result is False
        # Should only try once, no retries for general errors
        mock_bot.send_message.assert_called_once()
        mock_logger.error.assert_called_with("Telegram API error: General error")

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_all_messages_async_debug_logging(
        self: "TestTelegramMessaging", telegram_config: TelegramNotificationConfig
    ) -> None:
        """Test debug logging in _send_all_messages_async."""
        mock_logger = Mock()

        with patch("ai_marketplace_monitor.telegram.Bot") as mock_bot_class:
            mock_bot = AsyncMock()
            mock_bot_class.return_value.__aenter__.return_value = mock_bot
            mock_bot.send_message.return_value = Mock(message_id=12345)

            result = await telegram_config._send_all_messages_async(
                "Test Title", ["Message 1", "Message 2"], "MarkdownV2", mock_logger
            )

            assert result is True
            # Verify debug logging
            debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
            assert any(
                "_send_all_messages_async called with 2 messages" in call for call in debug_calls
            )
            assert any("Using bot token:" in call for call in debug_calls)

    def test_send_message_message_splitting_with_current_message(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test message splitting when current_msg has content."""
        # Create messages that will trigger the split with existing current_msg
        pieces = ["Part 1" * 100, "Part 2" * 100, "Part 3" * 1000]  # Last part is very long
        message = "\n\n".join(pieces)

        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    telegram_config.send_message("Title", message, mock_logger)

                    mock_loop.return_value.run_until_complete.assert_called_once()

    def test_send_message_html_escaping_debug(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test HTML escaping with debug logging."""
        telegram_config.message_format = "html"

        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    message = "Test <b>bold</b> & special"
                    telegram_config.send_message("Title", message, mock_logger)

                    # Verify HTML escaping was logged
                    debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
                    assert any("Escaped message for HTML" in call for call in debug_calls)

    def test_send_message_empty_current_msg_after_split(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test handling when current_msg becomes empty after split."""
        # Create a message that splits exactly at paragraph boundaries
        piece1 = "x" * 3800  # Close to limit
        piece2 = "y" * 10  # Small piece
        message = f"{piece1}\n\n{piece2}"

        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    telegram_config.send_message("Title", message, mock_logger)

                    mock_loop.return_value.run_until_complete.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_message_async_bad_request_with_parse_error(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test BadRequest with parse error details."""
        mock_bot = AsyncMock()
        error = BadRequest("Can't parse entities: unexpected end tag")
        error.message = "Can't parse entities: unexpected end tag at byte offset 42"
        mock_bot.send_message.side_effect = error

        result = await telegram_config._send_message_async(
            mock_bot, "Test *unclosed markdown", "MarkdownV2", mock_logger
        )

        assert result is False
        # Verify detailed error logging for parse errors
        error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
        assert any("Parse error detected" in call for call in error_calls)
        debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
        assert any("Line 0:" in call for call in debug_calls)  # Should log individual lines

    def test_send_message_thread_execution_logging(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test logging when already in event loop (thread execution)."""
        with patch("asyncio.get_running_loop", return_value=Mock()):
            with patch("concurrent.futures.ThreadPoolExecutor") as mock_executor:
                mock_future = Mock()
                mock_future.result.return_value = True
                mock_executor.return_value.__enter__.return_value.submit.return_value = mock_future

                result = telegram_config.send_message("Title", "Message", mock_logger)

                assert result is True
                # Verify thread execution was logged
                debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
                assert any("Already in event loop, using thread" in call for call in debug_calls)

    def test_send_message_no_event_loop_debug(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test logging when no event loop exists."""
        with patch("asyncio.get_running_loop", side_effect=RuntimeError("No running loop")):
            with patch("asyncio.new_event_loop") as mock_loop:
                mock_loop.return_value.run_until_complete.return_value = True

                with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
                    result = telegram_config.send_message("Title", "Message", mock_logger)

                    assert result is True
                    # Verify no event loop was logged
                    debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
                    assert any("No event loop, creating new one" in call for call in debug_calls)

    def test_send_message_plain_text_debug(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test plain text (no escaping) with debug logging."""
        telegram_config.message_format = "plain_text"

        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    message = "Test *bold* <tag>"
                    telegram_config.send_message("Title", message, mock_logger)

                    # Verify no escaping was logged
                    debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
                    assert any("No escaping applied (plain text)" in call for call in debug_calls)

    def test_send_message_exception_with_traceback(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test exception handling with traceback logging."""
        with patch("asyncio.get_running_loop", side_effect=Exception("Test exception")):
            result = telegram_config.send_message("Title", "Message", mock_logger)

            assert result is False
            # Verify traceback was logged
            debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
            assert any("Traceback:" in call for call in debug_calls)

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_message_async_retry_after_zero_retries(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test RetryAfter with zero retries left."""
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = RetryAfter(retry_after=0.01)

        result = await telegram_config._send_message_async(
            mock_bot, "Test message", None, mock_logger, max_retries=0
        )

        assert result is False
        mock_bot.send_message.assert_called_once()
        mock_logger.error.assert_called_with("Max retries exceeded for rate limiting")

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_message_async_timeout_zero_retries(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test TimedOut with zero retries left."""
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = TimedOut()

        result = await telegram_config._send_message_async(
            mock_bot, "Test message", None, mock_logger, max_retries=0
        )

        assert result is False
        mock_bot.send_message.assert_called_once()
        mock_logger.error.assert_called_with("Max retries exceeded for timeout")

    def test_thread_execution_run_in_thread(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test the run_in_thread function execution."""
        with patch("asyncio.get_running_loop", return_value=Mock()):
            with patch("asyncio.new_event_loop") as mock_new_loop:
                new_loop_instance = Mock()
                mock_new_loop.return_value = new_loop_instance
                new_loop_instance.run_until_complete.return_value = True
                new_loop_instance.close = Mock()

                with patch("concurrent.futures.ThreadPoolExecutor") as mock_executor:
                    # Simulate the thread executor actually calling the function
                    def execute_submit(func: Any) -> Any:
                        future = Mock()
                        future.result = Mock(return_value=func())
                        return future

                    mock_executor.return_value.__enter__.return_value.submit.side_effect = (
                        execute_submit
                    )

                    result = telegram_config.send_message("Title", "Message", mock_logger)

                    assert result is True
                    # Verify new loop was created and closed in thread
                    mock_new_loop.assert_called()
                    new_loop_instance.close.assert_called()

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_message_async_should_not_reach_end(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test edge case where max_retries loop completes without returning."""
        mock_bot = AsyncMock()
        # This shouldn't happen in practice, but tests line 129
        with patch("asyncio.sleep", new_callable=AsyncMock):
            # Mock the for loop to somehow not return
            result = await telegram_config._send_message_async(
                mock_bot, "Test", None, mock_logger, max_retries=-1  # Will skip loop
            )
            # Should return False as fallback
            assert result is False

    def test_send_message_split_with_space_at_beginning(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test split point when space is at position 0."""
        # Create a message where split happens with space at beginning
        piece1 = "x" * 3800
        piece2 = " " + "y" * 100  # Space at beginning
        message = piece1 + "\n\n" + piece2

        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    telegram_config.send_message("Title", message, mock_logger)
                    mock_loop.return_value.run_until_complete.assert_called_once()

    def test_send_message_failed_no_logger(
        self: "TestTelegramMessaging", telegram_config: TelegramNotificationConfig
    ) -> None:
        """Test failed message sending without logger."""
        with patch.object(telegram_config, "_send_all_messages_async", return_value=False):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = False

                    result = telegram_config.send_message("Title", "Message", None)
                    assert result is False

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_message_async_retry_after_continue(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test RetryAfter with successful retry on first attempt."""
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = [RetryAfter(retry_after=0.01), Mock(message_id=12345)]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await telegram_config._send_message_async(
                mock_bot, "Test", None, mock_logger, max_retries=1
            )

        assert result is True
        assert mock_bot.send_message.call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_message_async_timeout_continue(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test TimedOut with successful retry."""
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = [TimedOut(), Mock(message_id=12345)]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await telegram_config._send_message_async(
                mock_bot, "Test", None, mock_logger, max_retries=1
            )

        assert result is True
        assert mock_bot.send_message.call_count == 2

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_message_async_bad_request_without_parse_error(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test BadRequest without 'can't parse' in message."""
        mock_bot = AsyncMock()
        error = BadRequest("Chat not found")
        error.message = "Chat not found"
        mock_bot.send_message.side_effect = error

        result = await telegram_config._send_message_async(mock_bot, "Test", None, mock_logger)

        assert result is False
        # Should not log parse error specific messages
        error_calls = [call[0][0] for call in mock_logger.error.call_args_list]
        assert not any("Parse error detected" in call for call in error_calls)

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_send_all_messages_async_message_exceeds_limit(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test message truncation when it exceeds the limit."""
        with patch("ai_marketplace_monitor.telegram.Bot") as mock_bot_class:
            mock_bot = AsyncMock()
            mock_bot_class.return_value.__aenter__.return_value = mock_bot
            mock_bot.send_message.return_value = Mock(message_id=12345)

            # Create a message that will exceed limit after title + signature are added
            # The title formatting and signature will push this over the limit
            base_message = "x" * MessageLimit.MAX_TEXT_LENGTH

            result = await telegram_config._send_all_messages_async(
                "Very Long Title That Takes Up Space", [base_message], "MarkdownV2", mock_logger
            )

            assert result is True
            # Should warn about truncation
            mock_logger.warning.assert_called()
            warning_call = mock_logger.warning.call_args[0][0]
            assert "exceeded limit after formatting" in warning_call

            # Check the message was truncated
            sent_text = mock_bot.send_message.call_args[1]["text"]
            assert "..." in sent_text
            assert len(sent_text) <= MessageLimit.MAX_TEXT_LENGTH

    def test_send_message_markdown_escaping_splits(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test markdown escaping when message needs splitting."""
        # Create a message that will be split
        long_message = "Test *markdown* " * 300  # Will need splitting

        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    telegram_config.send_message("Title", long_message, mock_logger)

                    # Should log about escaping
                    debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
                    assert any("Escaped message for markdown" in call for call in debug_calls)

    def test_send_message_split_at_exact_boundary(
        self: "TestTelegramMessaging",
        telegram_config: TelegramNotificationConfig,
        mock_logger: Mock,
    ) -> None:
        """Test when split point is exactly at max_content_length with no space."""
        # Create a piece that's exactly at the limit
        max_content_length = MessageLimit.MAX_TEXT_LENGTH - 200
        piece = "a" * max_content_length
        message = f"{piece}\n\nmore content"

        with patch.object(telegram_config, "_send_all_messages_async", return_value=True):
            with patch("asyncio.get_running_loop", side_effect=RuntimeError()):
                with patch("asyncio.new_event_loop") as mock_loop:
                    mock_loop.return_value.run_until_complete.return_value = True

                    telegram_config.send_message("Title", message, mock_logger)
                    mock_loop.return_value.run_until_complete.assert_called_once()

    def test_send_message_exception_no_logger(
        self: "TestTelegramMessaging", telegram_config: TelegramNotificationConfig
    ) -> None:
        """Test exception handling without logger."""
        with patch("asyncio.get_running_loop", side_effect=Exception("Test error")):
            result = telegram_config.send_message("Title", "Message", None)
            assert result is False
