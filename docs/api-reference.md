# API Reference: LangChain Backend

This document provides a concise reference for the key classes and methods in the LangChain backend architecture.

## Core Classes

### AIConfig

Configuration class for AI providers.

```python
@dataclass
class AIConfig(BaseConfig):
    api_key: str | None = None
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    max_retries: int = 10
    timeout: int | None = None
```

**Parameters:**
- `provider`: AI service provider ("openai", "deepseek", "ollama", "openrouter")
- `api_key`: API key for authentication
- `model`: Model name (provider-specific format)
- `base_url`: Custom API endpoint (optional)
- `max_retries`: Maximum retry attempts (default: 10)
- `timeout`: Request timeout in seconds (optional)

### AIResponse

Standard response format for all AI evaluations.

```python
@dataclass
class AIResponse:
    score: int
    comment: str
    name: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    usage_metadata: Optional[dict] = field(default_factory=dict)
    response_metadata: Optional[dict] = field(default_factory=dict)
```

**Properties:**
- `score`: Rating from 1-5
- `comment`: AI explanation/recommendation
- `name`: Backend identifier
- `*_tokens`: Token usage for cost tracking
- `*_metadata`: Provider-specific metadata

**Methods:**
- `get_cost_estimate(prompt_price_per_k, completion_price_per_k) -> float`: Calculate estimated cost
- `from_cache(listing, item_config, marketplace_config) -> AIResponse | None`: Load from cache
- `to_cache(listing, item_config, marketplace_config) -> None`: Save to cache

### LangChainBackend

Unified backend for all AI providers.

```python
class LangChainBackend(AIBackend[AIConfig]):
    def __init__(self, config: AIConfig, logger: Logger | None = None)
    def connect(self) -> None
    def evaluate(self, listing: Listing, item_config: TItemConfig, marketplace_config: TMarketplaceConfig) -> AIResponse
```

**Key Methods:**

#### `connect() -> None`
Establishes connection and initializes the chat model.

**Raises:**
- `ValueError`: Configuration invalid or model unavailable
- `RuntimeError`: Service connection fails

#### `evaluate(listing, item_config, marketplace_config) -> AIResponse`
Evaluates a marketplace listing using the configured AI model.

**Parameters:**
- `listing`: Marketplace listing to evaluate
- `item_config`: Item search configuration
- `marketplace_config`: Marketplace-specific settings

**Returns:**
- `AIResponse`: Evaluation with score, comment, and metadata

**Raises:**
- `ValueError`: Invalid configuration or empty response
- `RuntimeError`: Service error or connection failure

## Provider Factory Functions

### OpenAI Provider
```python
def _create_openai_model(config: AIConfig) -> BaseChatModel
```
Creates `ChatOpenAI` instance with configuration validation.

### DeepSeek Provider
```python
def _create_deepseek_model(config: AIConfig) -> BaseChatModel
```
Creates `ChatDeepSeek` instance with provider-specific settings.

### OpenRouter Provider
```python
def _create_openrouter_model(config: AIConfig) -> BaseChatModel
```
Creates `ChatOpenAI` instance configured for OpenRouter API.

**Validation:**
- API key must start with `sk-or-`
- Model must follow `provider/model` format
- Includes model availability caching

### Ollama Provider
```python
def _create_ollama_model(config: AIConfig) -> BaseChatModel
```
Creates `ChatOllama` instance for local models.

**Requirements:**
- `base_url` must be specified
- `model` must be pulled locally

## Utility Functions

### Exception Mapping
```python
def _map_langchain_exception(e: Exception, context: str = "") -> Exception
```
Maps LangChain exceptions to standardized error types.

**Strategy:**
- Configuration/Auth errors → `ValueError`
- Service/Infrastructure errors → `RuntimeError`
- Preserves original exception as `__cause__`

### Response Adaptation
```python
def adapt_langchain_response(response, backend_name: str, parsed_score: int, parsed_comment: str) -> AIResponse
```
Converts LangChain response objects to `AIResponse` format with token usage preservation.

### LangSmith Integration
```python
def is_langsmith_enabled() -> bool
def get_langsmith_config() -> dict[str, Optional[str]]
def log_langsmith_status(logger: Optional[Logger] = None) -> None
```

**Environment Variables:**
- `LANGCHAIN_TRACING_V2`: Enable tracing
- `LANGCHAIN_API_KEY`: Authentication
- `LANGCHAIN_PROJECT`: Project name

## Provider Mapping

The `provider_map` dictionary maps provider names to factory functions:

```python
provider_map = {
    "openai": _create_openai_model,
    "deepseek": _create_deepseek_model,
    "ollama": _create_ollama_model,
    "openrouter": _create_openrouter_model,
}
```

## Usage Examples

### Basic Backend Usage
```python
from ai_marketplace_monitor.ai import LangChainBackend, AIConfig

# Configure backend
config = AIConfig(
    provider="openai",
    api_key="sk-...",
    model="gpt-4o",
    timeout=60
)

# Initialize and connect
backend = LangChainBackend(config)
backend.connect()

# Evaluate listing
response = backend.evaluate(listing, item_config, marketplace_config)
print(f"Score: {response.score}, Cost: ${response.get_cost_estimate(0.03, 0.06):.4f}")
```

### Provider-Specific Examples

#### OpenRouter Configuration
```python
config = AIConfig(
    provider="openrouter",
    api_key="sk-or-...",
    model="anthropic/claude-3-sonnet",
    timeout=120
)
```

#### Ollama Configuration
```python
config = AIConfig(
    provider="ollama",
    api_key="ollama",  # Required but unused
    model="deepseek-r1:14b",
    base_url="http://localhost:11434"
)
```

### Error Handling
```python
try:
    backend = LangChainBackend(config)
    backend.connect()
    response = backend.evaluate(listing, item_config, marketplace_config)
except ValueError as e:
    # Configuration error - user can fix
    print(f"Config error: {e}")
except RuntimeError as e:
    # Service error - retry or failover
    print(f"Service error: {e}")
```

### Thread Safety
```python
import concurrent.futures

# LangChainBackend is thread-safe
def evaluate_concurrently(listings):
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(backend.evaluate, listing, item_config, marketplace_config)
            for listing in listings
        ]
        return [future.result() for future in futures]
```

## Configuration Validation

The system performs comprehensive validation:

### Provider Validation
- Supported providers: openai, deepseek, ollama, openrouter
- Provider-specific requirements (API keys, model formats)
- Model availability caching for OpenRouter

### Parameter Validation
- `max_retries`: Non-negative integer
- `timeout`: Positive integer
- API key format validation (provider-specific)

### Error Messages
All validation errors provide clear, actionable error messages with suggestions for resolution.

## Caching System

### Response Caching
- Automatic caching of AI responses to reduce costs
- Cache key: `(item_config.hash, marketplace_config.hash, listing.hash)`
- Cache type: `CacheType.AI_INQUIRY`

### Model Availability Caching (OpenRouter)
- Available models: 5-minute cache
- Unavailable models: 1-minute cache
- Rate-limited providers: 2-minute cache

## Migration from Legacy Backends

The LangChainBackend is fully backward compatible:

```python
# Old backend configuration still works
[ai.openai]
api_key = "sk-..."
model = "gpt-4"

# Automatically maps to LangChainBackend internally
```

All existing configurations continue to work without changes.

## See Also

- [Configuration Reference](configuration-reference.md) - Complete configuration examples
- [Developer Guide](developer-guide.md) - Development workflow and testing
- [Troubleshooting Guide](troubleshooting.md) - Common API and configuration issues
- [LangSmith Integration](langsmith-integration.md) - AI monitoring and debugging
