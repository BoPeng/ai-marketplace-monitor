# Developer Setup and Usage Guide

This guide provides detailed instructions for developers working on AI Marketplace Monitor, including environment setup, development workflow, testing procedures, and integration with the LangChain backend.

## Quick Start

```bash
# Clone and setup
git clone https://github.com/BoPeng/ai-marketplace-monitor.git
cd ai-marketplace-monitor

# Environment setup
uv sync
uv run invoke install-hooks

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Run tests
uv run invoke tests

# Start development
uv run ai-marketplace-monitor --config your-config.toml
```

## Development Environment Setup

### Prerequisites

- Python 3.11 or later
- [uv](https://docs.astral.sh/uv/) package manager
- Git
- Modern web browser (for Playwright testing)

### Initial Setup

1. **Clone Repository**
   ```bash
   git clone https://github.com/BoPeng/ai-marketplace-monitor.git
   cd ai-marketplace-monitor
   ```

2. **Install Dependencies**
   ```bash
   # Install all dependencies including dev tools
   uv sync

   # Install browser for Playwright tests
   uv run playwright install
   ```

3. **Setup Pre-commit Hooks**
   ```bash
   uv run invoke install-hooks
   ```

4. **Environment Configuration**
   ```bash
   # Copy environment template
   cp .env.example .env

   # Edit .env with your development API keys
   export OPENAI_API_KEY="your-openai-key"
   export DEEPSEEK_API_KEY="your-deepseek-key"
   export OPENROUTER_API_KEY="your-openrouter-key"

   # Optional: Enable development features
   export AI_MARKETPLACE_MONITOR_SHOW_CONFIG_TIPS="true"
   export LANGCHAIN_TRACING_V2="true"  # If using LangSmith
   ```

### Development Configuration

See [Configuration Reference](configuration-reference.md#development-setup) for complete development setup examples.

## Development Workflow

### Code Quality Tools

```bash
# Linting and formatting
uv run invoke lint       # Run ruff linter
uv run invoke format     # Format with black and isort
uv run invoke mypy       # Type checking

# Run all quality checks
uv run invoke pre-commit  # Same as pre-commit hooks
```

### Testing

```bash
# Run all tests with coverage
uv run invoke tests

# Run specific test files
uv run pytest tests/test_ai.py -v

# Run with verbose output and stop on first failure
uv run pytest tests/ -xvs

# Test specific functionality
uv run pytest tests/test_langchain_backend.py::TestLangChainBackend::test_openai_integration

# Run integration tests (requires API keys)
uv run pytest tests/integration/ -m integration
```

### Running the Application

```bash
# Development run with config file
uv run ai-marketplace-monitor --config dev-config.toml

# Check individual listings
uv run ai-marketplace-monitor --check https://facebook.com/marketplace/item/123 --config dev-config.toml

# Headless mode (no browser window)
uv run ai-marketplace-monitor --config dev-config.toml --headless

# Debug mode with verbose logging
uv run ai-marketplace-monitor --config dev-config.toml --verbose
```

## LangChain Backend Development

### Architecture Overview

The AI Marketplace Monitor uses a unified LangChain backend (`LangChainBackend` class) to interface with all AI providers:

```python
# Core components
src/ai_marketplace_monitor/
├── ai.py                    # Main AI backend classes and provider mapping
├── langsmith_utils.py       # LangSmith integration utilities
├── marketplace.py           # Marketplace abstraction
├── listing.py              # Listing data structures
└── monitor.py              # Main monitoring logic
```

### Key Classes and Methods

#### LangChainBackend Class

```python
from ai_marketplace_monitor.ai import LangChainBackend, AIConfig

# Create backend instance
config = AIConfig(
    provider="openai",
    api_key="your-key",
    model="gpt-4",
    timeout=60,
    max_retries=3
)

backend = LangChainBackend(config)
backend.connect()

# Evaluate listing
response = backend.evaluate(listing, item_config, marketplace_config)
print(f"Score: {response.score}, Comment: {response.comment}")
print(f"Tokens used: {response.total_tokens}")
```

#### Provider Factory Functions

See [API Reference](api-reference.md#provider-factory-functions) for detailed provider factory documentation and examples.

### Testing AI Integrations

#### Unit Tests

```python
# tests/test_langchain_backend.py
import pytest
from ai_marketplace_monitor.ai import LangChainBackend, AIConfig

@pytest.fixture
def openai_config():
    return AIConfig(
        provider="openai",
        api_key="test-key",
        model="gpt-3.5-turbo"
    )

def test_backend_creation(openai_config):
    backend = LangChainBackend(openai_config)
    assert backend.config.provider == "openai"

def test_provider_validation():
    with pytest.raises(ValueError):
        AIConfig(provider="unsupported")
```

#### Integration Tests

Create integration tests that require actual API keys:

```python
# tests/integration/test_ai_providers.py
import os
import pytest
from ai_marketplace_monitor.ai import LangChainBackend, AIConfig

@pytest.mark.integration
@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="API key required")
def test_openai_real_evaluation():
    config = AIConfig(
        provider="openai",
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-3.5-turbo"
    )
    backend = LangChainBackend(config)
    # Test with real API call...
```

Run integration tests:
```bash
uv run pytest tests/integration/ -m integration
```

### Debugging and Troubleshooting

#### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Or via configuration
export PYTHONPATH=src
export AI_MARKETPLACE_MONITOR_LOG_LEVEL=DEBUG
```

#### LangSmith Integration

For debugging AI interactions, you can configure LangSmith tracing via TOML or environment variables:

**TOML Configuration (Recommended):**
```toml
[langsmith]
enabled = true
api_key = "${LANGCHAIN_API_KEY}"
project_name = "ai-marketplace-monitor-dev"
session_name = "dev-${USER}"
metadata = { environment = "development" }
```

**Environment Variables:**
```bash
export LANGCHAIN_TRACING_V2="true"
export LANGCHAIN_API_KEY="your-langsmith-key"
export LANGCHAIN_PROJECT="ai-marketplace-monitor-dev"
```

**Configuration Loading:**
The application loads LangSmith configuration through the unified configuration system:
```python
from ai_marketplace_monitor.langsmith_utils import setup_langsmith_tracing
from ai_marketplace_monitor.config import load_config

config = load_config("your-config.toml")
setup_langsmith_tracing(config)  # Configures tracing from TOML
```

#### Common Debug Scenarios

1. **Provider Connection Issues**
   ```python
   try:
       backend.connect()
   except Exception as e:
       print(f"Connection failed: {e}")
       # Check API key, network, model availability
   ```

2. **Response Parsing Issues**
   ```python
   # Enable response debugging
   backend.logger.setLevel(logging.DEBUG)
   response = backend.evaluate(listing, item_config, marketplace_config)
   ```

3. **Token Usage Monitoring**
   ```python
   response = backend.evaluate(...)
   print(f"Cost estimate: ${response.get_cost_estimate(0.03, 0.06)}")
   ```

## Code Examples and Best Practices

### Adding a New AI Provider

See [API Reference](api-reference.md#provider-factory-functions) for complete instructions on adding new AI providers, including factory functions, validation, and testing examples.

### Exception Handling Best Practices

```python
try:
    response = backend.evaluate(listing, item_config, marketplace_config)
except ValueError as e:
    # Configuration or validation error - user can fix
    logger.error(f"Configuration error: {e}")
    # Suggest fix to user
except RuntimeError as e:
    # Service or connection error - retry or failover
    logger.warning(f"Service error: {e}")
    # Implement retry logic
except Exception as e:
    # Unexpected error - log and escalate
    logger.exception(f"Unexpected error: {e}")
    raise
```

### Performance Optimization

```python
# Thread-safe concurrent evaluation
import concurrent.futures

def evaluate_listings_concurrently(listings, backend, item_config, marketplace_config):
    """Evaluate multiple listings concurrently."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(backend.evaluate, listing, item_config, marketplace_config): listing
            for listing in listings
        }

        results = {}
        for future in concurrent.futures.as_completed(futures):
            listing = futures[future]
            try:
                response = future.result()
                results[listing.id] = response
            except Exception as e:
                logger.error(f"Failed to evaluate listing {listing.id}: {e}")

        return results
```

## Testing Integration with Different Providers

### Mock Testing

```python
# tests/test_providers.py
from unittest.mock import Mock, patch
import pytest

@patch('ai_marketplace_monitor.ai.ChatOpenAI')
def test_openai_provider_mock(mock_chat_openai):
    # Setup mock
    mock_instance = Mock()
    mock_instance.invoke.return_value = Mock(content="Rating 4: Good match")
    mock_chat_openai.return_value = mock_instance

    # Test
    config = AIConfig(provider="openai", api_key="test-key")
    backend = LangChainBackend(config)
    backend.connect()

    # Verify mock was called correctly
    mock_chat_openai.assert_called_once()
```

### Provider-Specific Test Configurations

See [Configuration Reference](configuration-reference.md#configuration-examples-by-use-case) for test configuration examples.

### Continuous Integration Testing

```yaml
# .github/workflows/test.yml (example)
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup uv
        uses: astral-sh/setup-uv@v3
      - name: Install dependencies
        run: uv sync
      - name: Run tests
        run: uv run invoke tests
      - name: Run integration tests
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_TEST_KEY }}
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_TEST_KEY }}
        run: uv run pytest tests/integration/ -m integration
```

## Documentation Standards

### Docstring Format

```python
def evaluate(
    self,
    listing: Listing,
    item_config: TItemConfig,
    marketplace_config: TMarketplaceConfig,
) -> AIResponse:
    """Evaluate a listing using the LangChain model.

    Args:
        listing: The marketplace listing to evaluate
        item_config: Configuration for the item being searched
        marketplace_config: Marketplace-specific configuration

    Returns:
        AIResponse with score, comment, and token usage information

    Raises:
        ValueError: If configuration is invalid or model unavailable
        RuntimeError: If service connection fails or response is malformed

    Example:
        >>> config = AIConfig(provider="openai", api_key="sk-...")
        >>> backend = LangChainBackend(config)
        >>> response = backend.evaluate(listing, item_config, marketplace_config)
        >>> print(f"Score: {response.score}/5")
    """
```

### Type Hints

```python
from typing import Optional, Dict, Any, List, Union
from ai_marketplace_monitor.ai import AIConfig, AIResponse
from ai_marketplace_monitor.listing import Listing

def process_listings(
    listings: List[Listing],
    config: AIConfig,
    timeout: Optional[int] = None
) -> Dict[str, Union[AIResponse, Exception]]:
    """Process multiple listings with error handling."""
    pass
```

## Building and Deployment

### Building Documentation

```bash
# Build docs locally
uv run invoke docs

# Serve with auto-reload
uv run invoke docs --serve --open-browser

# Build for deployment
uv run sphinx-build docs docs/_build/html
```

### Package Building

```bash
# Build package
uv build

# Install in development mode
uv pip install -e .

# Install from wheel
uv pip install dist/ai_marketplace_monitor-*.whl
```

### Release Process

```bash
# Update version in pyproject.toml
# Update CHANGELOG.md
# Commit changes
git commit -am "Release v1.2.3"
git tag v1.2.3

# Build and test
uv build
uv run invoke tests

# Push release
git push origin main --tags
```

## Troubleshooting Development Issues

For common issues and detailed troubleshooting steps, see the [Troubleshooting Guide](troubleshooting.md).

## See Also

- [Configuration Reference](configuration-reference.md) - Complete configuration options
- [API Reference](api-reference.md) - Technical API documentation
- [LangSmith Integration](langsmith-integration.md) - AI monitoring setup
- [Troubleshooting Guide](troubleshooting.md) - Common issues and solutions
