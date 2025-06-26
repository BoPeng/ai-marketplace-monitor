# CI/CD Test Configuration

This document describes the CI/CD test configuration for the AI Marketplace Monitor project, with specific focus on Telegram integration testing.

## Overview

The test suite is designed to run in both local development and CI/CD environments, with automatic configuration detection and appropriate test execution strategies.

## Environment Detection

The test suite automatically detects CI/CD environments by checking for common environment variables:

- `CI`
- `CONTINUOUS_INTEGRATION`
- `GITHUB_ACTIONS`
- `TRAVIS`
- `CIRCLECI`
- `JENKINS_URL`
- `BUILDKITE`
- `GITLAB_CI`

## Test Categories

### Unit Tests
- **Purpose**: Test individual components in isolation
- **Requirements**: No external dependencies
- **Execution**: Always run, regardless of environment
- **Markers**: `@pytest.mark.unit`

### Integration Tests
- **Purpose**: Test end-to-end functionality with real services
- **Requirements**: Valid Telegram bot credentials
- **Execution**: Run only when credentials are available
- **Markers**: `@pytest.mark.integration`

### Performance Tests
- **Purpose**: Test system performance under load
- **Requirements**: Extended timeout settings
- **Execution**: Run with special timing considerations in CI
- **Markers**: `@pytest.mark.slow`

## Environment Variables

### Required for Integration Tests

```bash
# Telegram bot token for testing (should be a dedicated test bot)
TELEGRAM_TEST_BOT_TOKEN=1234567890:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk

# Chat ID for test messages (should be a dedicated test chat)
TELEGRAM_TEST_CHAT_ID=-1001234567890
```

### Optional Configuration

```bash
# Explicitly mark environment as CI (auto-detected)
CI=true

# Test timeout in seconds (default: 300 for CI)
PYTEST_TIMEOUT=300

# Coverage fail threshold (default: 80% for CI)
COVERAGE_FAIL_UNDER=80
```

## GitHub Actions Setup

### Repository Secrets

1. Navigate to your repository on GitHub
2. Go to Settings > Secrets and variables > Actions
3. Add the following repository secrets:
   - `TELEGRAM_TEST_BOT_TOKEN`: Your test bot token
   - `TELEGRAM_TEST_CHAT_ID`: Your test chat ID

### Workflow Configuration

The GitHub Actions workflow is configured to:

1. **Environment Setup**: Install Python, dependencies, and Playwright browsers
2. **Test Execution**: Run tests with split execution for event loop compatibility
3. **Coverage Collection**: Collect and upload coverage data
4. **Artifact Management**: Store test results and coverage reports

### Test Execution Strategy

The test suite uses a split execution strategy to handle event loop conflicts:

1. **Non-Telegram Tests**: Run first, including Playwright browser tests
2. **Telegram Tests**: Run separately with pytest-asyncio event loop management
3. **Coverage Combination**: Merge coverage data from both runs

## Local Development Setup

### Prerequisites

```bash
# Install dependencies
poetry install

# Install Playwright browsers (for browser tests)
playwright install --with-deps

# Install pre-commit hooks
poetry run pre-commit install
```

### Running Tests

```bash
# Run all tests (uses split execution)
invoke tests

# Run only unit tests (fast)
poetry run pytest tests/ -m "not integration"

# Run only integration tests (requires credentials)
poetry run pytest tests/ -m integration

# Run with coverage
poetry run pytest tests/ --cov=ai_marketplace_monitor --cov-report=html
```

### Environment Configuration

For local development with integration tests:

```bash
# Set test credentials (use dedicated test bot)
export TELEGRAM_TEST_BOT_TOKEN="your_test_bot_token"
export TELEGRAM_TEST_CHAT_ID="your_test_chat_id"

# Run tests
invoke tests
```

## Test Bot Setup

### Creating a Test Bot

1. **Create Bot**: Message @BotFather on Telegram
2. **Get Token**: Use `/newbot` command and save the token
3. **Create Test Chat**: Create a dedicated group/channel for testing
4. **Get Chat ID**: Add the bot to the chat and get the chat ID
5. **Set Permissions**: Ensure the bot can send messages

### Security Best Practices

- **Separate Bots**: Use different bots for development, testing, and production
- **Dedicated Chats**: Use separate chats for testing to avoid noise
- **Token Rotation**: Regularly rotate test bot tokens
- **Monitoring**: Monitor test bot usage for anomalies
- **Secrets Management**: Never commit tokens to version control

## Test Configuration Files

### `pytest.ini`
- Base configuration for all environments
- Event loop management settings
- Basic test discovery and output configuration

### `.github/pytest-ci.ini`
- CI-specific configuration overrides
- Enhanced logging and output settings
- CI-optimized timeout and failure limits

### `tests/conftest.py`
- Test fixtures and configuration
- Environment detection logic
- Credential management for testing

## Troubleshooting

### Common Issues

1. **Event Loop Conflicts**
   - **Symptom**: "RuntimeError: This event loop is already running"
   - **Solution**: Tests are automatically split to avoid this conflict

2. **Integration Test Failures**
   - **Symptom**: Tests skip or fail due to missing credentials
   - **Solution**: Set `TELEGRAM_TEST_BOT_TOKEN` and `TELEGRAM_TEST_CHAT_ID`

3. **Timeout Issues**
   - **Symptom**: Tests timeout in CI environment
   - **Solution**: Increase `PYTEST_TIMEOUT` environment variable

4. **Coverage Issues**
   - **Symptom**: Coverage reports missing or incomplete
   - **Solution**: Ensure both test runs complete successfully

### Debug Commands

```bash
# Check environment detection
python -c "from tests.conftest import is_ci_environment; print(f'CI: {is_ci_environment()}')"

# Check test credentials
python -c "from tests.conftest import get_test_bot_token; print(f'Token: {bool(get_test_bot_token())}')"

# Run tests with debug output
poetry run pytest tests/ -v --tb=long --capture=no

# Check coverage
poetry run coverage report --show-missing
```

## Monitoring and Maintenance

### CI/CD Pipeline Health

- Monitor test execution times
- Track test failure rates
- Review coverage trends
- Update dependencies regularly

### Test Bot Maintenance

- Monitor bot message limits
- Review test chat activity
- Rotate credentials periodically
- Update bot permissions as needed

### Configuration Updates

- Review pytest configuration regularly
- Update CI timeouts based on performance
- Adjust coverage thresholds as codebase grows
- Update test markers and categories as needed

## Contributing

When adding new tests:

1. **Mark Appropriately**: Use correct pytest markers
2. **Handle Credentials**: Check for credential availability in integration tests
3. **Follow Patterns**: Use existing fixtures and patterns
4. **Update Documentation**: Update this README for new test categories or requirements

## Support

For issues with CI/CD test configuration:

1. Check the troubleshooting section above
2. Review GitHub Actions logs for specific error messages
3. Verify repository secrets are correctly configured
4. Test locally with the same environment variables
