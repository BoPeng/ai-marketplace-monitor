"""Test configuration for CI/CD environments.

This module provides test fixtures and configuration specifically designed
for continuous integration and deployment environments, with particular
attention to Telegram integration testing requirements.
"""

import os
import uuid
from typing import Dict, Optional
from unittest.mock import Mock

import pytest
from telegram import Bot

from ai_marketplace_monitor.telegram import TelegramNotificationConfig


# CI/CD Environment Detection
def is_ci_environment() -> bool:
    """Detect if tests are running in a CI/CD environment."""
    ci_indicators = [
        "CI",
        "CONTINUOUS_INTEGRATION",
        "GITHUB_ACTIONS",
        "TRAVIS",
        "CIRCLECI",
        "JENKINS_URL",
        "BUILDKITE",
        "GITLAB_CI",
    ]
    return any(os.getenv(indicator) for indicator in ci_indicators)


def get_test_bot_token() -> Optional[str]:
    """Get test bot token from environment variables.

    Returns:
        Test bot token if available, None otherwise.

    Note:
        For CI/CD environments, this should be set as a repository secret.
        For local development, developers can set TELEGRAM_TEST_BOT_TOKEN.
    """
    return os.getenv("TELEGRAM_TEST_BOT_TOKEN")


def get_test_chat_id() -> Optional[str]:
    """Get test chat ID from environment variables.

    Returns:
        Test chat ID if available, None otherwise.

    Note:
        For CI/CD environments, this should be set as a repository secret.
        For local development, developers can set TELEGRAM_TEST_CHAT_ID.
    """
    return os.getenv("TELEGRAM_TEST_CHAT_ID")


# Test Configuration Fixtures
@pytest.fixture
def ci_environment() -> bool:
    """Fixture to detect CI/CD environment."""
    return is_ci_environment()


@pytest.fixture
def test_credentials() -> Dict[str, Optional[str]]:
    """Fixture providing test credentials.

    Returns:
        Dictionary with test bot token and chat ID.
        Values may be None if not configured.
    """
    return {
        "bot_token": get_test_bot_token(),
        "chat_id": get_test_chat_id(),
    }


@pytest.fixture
def integration_test_config(
    test_credentials: Dict[str, Optional[str]]
) -> TelegramNotificationConfig:
    """Fixture providing a real Telegram config for integration tests.

    This fixture provides real credentials when available (CI/CD with secrets)
    or mock credentials for local testing without real bot access.
    """
    bot_token = test_credentials["bot_token"] or "test_bot_token_123456789"
    chat_id = test_credentials["chat_id"] or "test_chat_id_123456789"

    return TelegramNotificationConfig(
        name="integration_test",
        telegram_bot_token=bot_token,
        telegram_chat_id=chat_id,
        message_format="markdownv2",
        max_retries=1,
        base_delay=0.01,  # Fast retries for testing
        max_delay=0.1,
        jitter=False,  # Deterministic timing for tests
        fail_fast=False,  # Continue testing even if some messages fail
    )


@pytest.fixture
def mock_telegram_config() -> TelegramNotificationConfig:
    """Fixture providing a mocked Telegram config for unit tests."""
    return TelegramNotificationConfig(
        name="mock_test",
        telegram_bot_token="mock_bot_token_123456789",
        telegram_chat_id="mock_chat_id_123456789",
        message_format="markdownv2",
        max_retries=2,
        base_delay=0.01,
        max_delay=0.1,
        jitter=False,
        fail_fast=False,
    )


@pytest.fixture
def mock_bot() -> Mock:
    """Fixture providing a mocked Telegram Bot for testing."""
    bot = Mock(spec=Bot)
    bot.send_message.return_value = Mock(message_id=12345)
    return bot


@pytest.fixture
def correlation_id() -> str:
    """Fixture providing a unique correlation ID for test tracing."""
    return str(uuid.uuid4())[:8]


# Test Environment Configuration
def pytest_configure(config: pytest.Config) -> None:
    """Configure pytest for CI/CD environments."""
    # Set timeout for slow CI environments
    if is_ci_environment():
        # Configure longer timeouts for CI
        os.environ.setdefault("PYTEST_TIMEOUT", "300")  # 5 minutes

        # Configure test output for CI visibility
        config.option.verbose = max(config.option.verbose, 1)

        # Enable strict mode in CI
        if not hasattr(config.option, "strict_markers"):
            config.option.strict_markers = True


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Modify test collection for CI/CD environments."""
    if is_ci_environment():
        # Add CI marker to all tests for identification
        ci_marker = pytest.mark.ci
        for item in items:
            item.add_marker(ci_marker)

        # Skip integration tests if no credentials are available
        test_bot_token = get_test_bot_token()
        test_chat_id = get_test_chat_id()

        if not (test_bot_token and test_chat_id):
            integration_skip = pytest.mark.skip(
                reason="Telegram integration tests require TELEGRAM_TEST_BOT_TOKEN and TELEGRAM_TEST_CHAT_ID environment variables"
            )

            for item in items:
                # Skip tests that require real Telegram credentials
                if hasattr(item, "cls") and item.cls and "Integration" in item.cls.__name__:
                    item.add_marker(integration_skip)


# Test Markers for CI/CD
pytest_plugins = []


# Environment Variable Documentation for CI/CD
"""
CI/CD Environment Variables:

Required for Integration Tests:
- TELEGRAM_TEST_BOT_TOKEN: Bot token for integration testing
- TELEGRAM_TEST_CHAT_ID: Chat ID for integration testing

Optional CI/CD Configuration:
- CI: Set to any value to indicate CI environment
- PYTEST_TIMEOUT: Test timeout in seconds (default: 300 for CI)

GitHub Actions Secrets Setup:
1. Go to repository Settings > Secrets and variables > Actions
2. Add repository secrets:
   - TELEGRAM_TEST_BOT_TOKEN: Your test bot token
   - TELEGRAM_TEST_CHAT_ID: Your test chat ID

Local Development:
- Export TELEGRAM_TEST_BOT_TOKEN and TELEGRAM_TEST_CHAT_ID to run integration tests
- Integration tests will be skipped if credentials are not available
- Unit tests always run regardless of credential availability

Security Notes:
- Never commit real bot tokens to version control
- Use separate test bots for CI/CD environments
- Rotate test credentials regularly
- Monitor test bot usage to detect anomalies
"""
