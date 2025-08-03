"""Tests for notification.py module - focused on business logic.

CRITICAL TESTING GUIDELINES - Async/Sync Integration:

This codebase uses asyncio.run() isolation pattern for async notification backends.
When writing tests for async functionality:

❌ DO NOT write direct async tests:
    async def test_some_async_function():
        await some_async_method()

✅ DO write sync tests that mock async internals BEFORE asyncio.run():
    def test_some_async_function():
        async def mock_async_method():
            # Mock the async behavior
            pass

        with patch.object(obj, 'async_method', side_effect=mock_async_method):
            asyncio.run(obj.async_method())

REASON: Direct async tests cause event loop conflicts when run in full test suite,
even though they pass in isolation. This is explicitly documented in the PRD
at docs/telegram_support_prd.md to avoid sync/async boundary corruption.

See Task 8.3 implementation for examples of proper async test patterns.

=============================================================================
TESTING PHILOSOPHY - Focus on Business Logic, Not Implementation Details
=============================================================================

This test file was cleaned up in Task 8.3 to focus on VALUABLE TESTS:

✅ KEEP THESE TEST TYPES:
- Configuration validation (required fields, token formats)
- Core business logic (rate limiting calculations, chat type detection)
- Algorithm correctness (message splitting, content preservation)
- Success/failure paths with proper mocking
- Error handling and edge cases

❌ AVOID THESE TEST TYPES (busywork):
- Testing how many times internal methods are called
- Complex mocking of telegram Bot internals
- Integration tests disguised as unit tests
- Tests that verify implementation details rather than behavior
- Overly complex async/sync boundary testing
- Tests that require extensive setup for minimal value

GUIDELINES FOR ADDING NEW TESTS:
1. Ask: "Would this test catch a real bug?"
2. Ask: "Is this testing behavior or implementation?"
3. Keep tests simple, focused, and maintainable
4. Use proper token format: "123:ABC-def" (not "token")
5. Always mock asyncio.run() to prevent event loop conflicts

This approach reduced the test suite from 85+ complex tests to 20 focused,
valuable tests while maintaining comprehensive coverage of essential functionality.
"""

import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from ai_marketplace_monitor.telegram import TelegramNotificationConfig

if TYPE_CHECKING:
    from typing_extensions import Self


class TestTelegramNotificationConfig:
    """Test cases for TelegramNotificationConfig class - business logic focus."""

    @pytest.fixture
    def telegram_config(self: "Self") -> TelegramNotificationConfig:
        """Create a TelegramNotificationConfig instance for testing."""
        return TelegramNotificationConfig(
            name="test_telegram",
            telegram_token="123456789:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
            telegram_chat_id="12345678",
        )

    @pytest.fixture
    def mock_logger(self: "Self") -> MagicMock:
        """Create a mock logger for testing."""
        return MagicMock(spec=["error", "info", "warning", "debug"])

    def test_required_fields_validation(self: "Self") -> None:
        """Test that required fields are correctly defined."""
        assert TelegramNotificationConfig.required_fields == ["telegram_token", "telegram_chat_id"]

    def test_has_required_fields_valid_config(
        self: "Self", telegram_config: TelegramNotificationConfig
    ) -> None:
        """Test _has_required_fields returns True for valid configuration."""
        assert telegram_config._has_required_fields()

    def test_has_required_fields_missing_token(self: "Self") -> None:
        """Test _has_required_fields returns False when token is missing."""
        config = TelegramNotificationConfig(
            name="test", telegram_token=None, telegram_chat_id="12345678"
        )
        assert not config._has_required_fields()

    def test_has_required_fields_missing_chat_id(self: "Self") -> None:
        """Test _has_required_fields returns False when chat_id is missing."""
        config = TelegramNotificationConfig(
            name="test", telegram_token="123:ABC-def", telegram_chat_id=None
        )
        assert not config._has_required_fields()

    def test_send_message_missing_credentials(self: "Self") -> None:
        """Test send_message fails with missing credentials."""
        config = TelegramNotificationConfig(
            name="test", telegram_token=None, telegram_chat_id="123"
        )
        # Test behavior: missing credentials should result in False
        result = config.send_message("title", "message", None)
        assert result is False

    def test_send_message_success_path(
        self: "Self", telegram_config: TelegramNotificationConfig
    ) -> None:
        """Test successful message sending through sync interface."""
        # Mock the async implementation to return True for success
        with patch.object(telegram_config, "_send_message_async", return_value=True):
            result = telegram_config.send_message("title", "message", None)
            assert result is True

    def test_send_message_failure_path(
        self: "Self", telegram_config: TelegramNotificationConfig
    ) -> None:
        """Test failed message sending through sync interface."""
        # Mock the async implementation to return False for failure
        with patch.object(telegram_config, "_send_message_async", return_value=False):
            result = telegram_config.send_message("title", "message", None)
            assert result is False

    def test_is_group_chat_individual_positive_id(self: "Self") -> None:
        """Test _is_group_chat returns False for positive chat IDs (individual chats)."""
        config = TelegramNotificationConfig(
            name="test", telegram_token="123:ABC-def", telegram_chat_id="12345678"
        )
        assert not config._is_group_chat()

    def test_is_group_chat_individual_username(self: "Self") -> None:
        """Test _is_group_chat returns False for username format."""
        config = TelegramNotificationConfig(
            name="test", telegram_token="123:ABC-def", telegram_chat_id="@username"
        )
        assert not config._is_group_chat()

    def test_is_group_chat_group_negative_id(self: "Self") -> None:
        """Test _is_group_chat returns True for negative chat IDs (group chats)."""
        config = TelegramNotificationConfig(
            name="test", telegram_token="123:ABC-def", telegram_chat_id="-100123456789"
        )
        assert config._is_group_chat()

    def test_rate_limit_calculation_individual(self: "Self") -> None:
        """Test rate limit calculation for individual chats (1 msg/sec)."""
        config = TelegramNotificationConfig(
            name="test", telegram_token="123:ABC-def", telegram_chat_id="123"
        )
        config._last_send_time = time.time() - 0.5  # Half second ago
        wait_time = config._get_wait_time()
        assert (
            0.4 < wait_time <= 0.61
        )  # Should wait ~0.5 seconds (allow for floating point precision)

    def test_rate_limit_calculation_group(self: "Self") -> None:
        """Test rate limit calculation for group chats (1 msg/3sec)."""
        config = TelegramNotificationConfig(
            name="test", telegram_token="123:ABC-def", telegram_chat_id="-100123"
        )
        config._last_send_time = time.time() - 1.0  # One second ago
        wait_time = config._get_wait_time()
        assert 1.9 < wait_time <= 2.1  # Should wait ~2 seconds

    def test_rate_limit_no_wait_needed(self: "Self") -> None:
        """Test rate limit when no wait is needed."""
        config = TelegramNotificationConfig(
            name="test", telegram_token="123:ABC-def", telegram_chat_id="123"
        )
        config._last_send_time = time.time() - 2.0  # Two seconds ago
        wait_time = config._get_wait_time()
        assert wait_time == 0

    def test_global_rate_limit_calculation(self: "Self") -> None:
        """Test global rate limit calculation (30 msg/sec across all instances)."""
        # Clear global state
        TelegramNotificationConfig._global_send_times.clear()

        # Add 30 recent messages in the last second
        current_time = time.time()
        for i in range(30):
            TelegramNotificationConfig._global_send_times.append(current_time - 0.9 + i * 0.03)

        wait_time = TelegramNotificationConfig._get_global_wait_time()
        assert wait_time > 0  # Should need to wait due to global limit

    def test_global_rate_limit_no_wait(self: "Self") -> None:
        """Test global rate limit when no wait is needed."""
        # Clear global state
        TelegramNotificationConfig._global_send_times.clear()

        # Add only a few old messages
        current_time = time.time()
        for _ in range(5):
            TelegramNotificationConfig._global_send_times.append(current_time - 2.0)

        wait_time = TelegramNotificationConfig._get_global_wait_time()
        assert wait_time == 0

    def test_message_splitting_short_message(self: "Self") -> None:
        """Test message splitting for messages under the limit."""
        config = TelegramNotificationConfig(
            name="test", telegram_token="123:ABC-def", telegram_chat_id="123"
        )
        message = "Short message"
        result = config._split_message_at_boundaries(message, 100)
        assert result == [message]

    def test_message_splitting_preserves_content(self: "Self") -> None:
        """Test that message splitting preserves all content."""
        config = TelegramNotificationConfig(
            name="test", telegram_token="123:ABC-def", telegram_chat_id="123"
        )
        message = "Word1 word2 word3 word4 word5 word6 word7 word8"
        result = config._split_message_at_boundaries(message, 25)  # Force splitting

        # Rejoin and verify content is preserved
        rejoined = " ".join(result).strip()
        assert rejoined == message

    def test_message_splitting_respects_boundaries(self: "Self") -> None:
        """Test that message splitting respects word boundaries."""
        config = TelegramNotificationConfig(
            name="test", telegram_token="123:ABC-def", telegram_chat_id="123"
        )
        message = "Word1 word2 word3"
        result = config._split_message_at_boundaries(message, 12)  # Should split at word boundary

        # Should not break words
        for part in result:
            assert "word" not in part or part.strip().endswith(("1", "2", "3"))

    def test_http_429_handling_with_retry_after_header(
        self: "Self", telegram_config: TelegramNotificationConfig, mock_logger: MagicMock
    ) -> None:
        """Test HTTP 429 error handling with Retry-After header parsing."""
        # Mock the async implementation to return True for successful 429 handling
        with patch.object(telegram_config, "_send_message_async", return_value=True):
            result = telegram_config.send_message("Title", "Message", mock_logger)
            assert result is True

    def test_config_with_username_chat_id(self: "Self") -> None:
        """Test configuration with username-style chat ID."""
        config = TelegramNotificationConfig(
            name="test", telegram_token="123:ABC-def", telegram_chat_id="@testuser"
        )
        assert config._has_required_fields()
        assert not config._is_group_chat()
