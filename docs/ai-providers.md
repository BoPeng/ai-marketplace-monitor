# AI Provider Configuration Guide

This guide provides detailed information about configuring AI providers with the LangChain backend.

## Provider Overview

The AI Marketplace Monitor supports multiple AI providers through a unified LangChain interface. All providers use the same configuration structure while supporting provider-specific options.

### Supported Providers

| Provider | Description | Cost | Setup Difficulty |
|----------|-------------|------|------------------|
| OpenAI | GPT-3.5, GPT-4 models | Medium to High | Easy |
| DeepSeek | Cost-effective alternative | Low | Easy |
| OpenRouter | Access to multiple models | Variable | Easy |
| Ollama | Self-hosted models | None (local compute) | Medium |

## Configuration

See the [Configuration Reference](configuration-reference.md) for complete provider setup examples, including:
- Basic configuration structure
- Provider-specific settings and models
- Environment variable requirements
- Setup prerequisites for each provider

## Backend Architecture

All AI providers use a unified LangChain backend internally while preserving your existing configuration syntax. This provides:

- **Consistent Error Handling**: All providers use the same exception mapping and error messages
- **Enhanced Token Usage Tracking**: Detailed cost monitoring with prompt/completion token counts
- **Thread Safety**: Concurrent evaluation support with proper synchronization
- **Standardized Response Metadata**: Unified response format across all providers

**Timeout Recommendations by Provider:**
- OpenAI: 60 seconds (default)
- DeepSeek: 90 seconds (higher latency in some regions)
- OpenRouter: 120 seconds (variable provider latency)
- Ollama: 120 seconds (local processing time)

## Provider Mapping Details

### Configuration Preservation

The LangChain backend preserves all existing configuration syntax. Your current configuration files will continue to work without changes.

**Legacy vs New Configuration:**
```toml
# Both formats work identically
[ai.openai_legacy]
api_key = "sk-..."
model = "gpt-4"

[ai.openai_new]
provider = "openai"
api_key = "sk-..."
model = "gpt-4"
```

### Internal Provider Mapping

The system automatically maps configurations to appropriate LangChain models:

| Configuration | LangChain Model | Notes |
|---------------|-----------------|-------|
| `provider = "openai"` | `ChatOpenAI` | Direct mapping |
| `provider = "deepseek"` | `ChatDeepSeek` | Uses DeepSeek-specific client |
| `provider = "openrouter"` | `ChatOpenAI` | With OpenRouter base URL |
| `provider = "ollama"` | `ChatOllama` | Local model interface |

### Response Processing

All providers return responses in the same `AIResponse` format:

```python
AIResponse(
    score=4,
    comment="Good match with clear details",
    name="openai",
    prompt_tokens=150,
    completion_tokens=45,
    total_tokens=195,
    usage_metadata={...},
    response_metadata={...}
)
```

## Troubleshooting

For provider-specific connection issues, authentication errors, and setup problems, see the [Troubleshooting Guide](troubleshooting.md).

## Best Practices

### Security
- Use environment variables for API keys
- Never commit API keys to version control
- Rotate API keys regularly

### Performance
- Set appropriate timeout values for your use case
- Use faster models for high-volume processing
- Consider cost vs performance trade-offs

### Reliability
- Enable retries for production use
- Monitor token usage and costs
- Set up fallback providers for critical applications

### Cost Management
- Monitor token usage with built-in tracking
- Use cost-effective models where appropriate
- Set reasonable timeout and retry limits

## Migration Guide

### From Legacy Backends
If upgrading from older versions, your configuration will work automatically. The system maps legacy configurations to the new LangChain backend transparently.

### Adding New Providers
To add a new provider, update the `provider_map` in `src/ai_marketplace_monitor/ai.py` and add the appropriate LangChain model factory function.

## See Also

- [Configuration Reference](configuration-reference.md) - Complete setup examples and environment variables
- [Troubleshooting Guide](troubleshooting.md) - Provider-specific issues and solutions
- [API Reference](api-reference.md) - Technical backend architecture details
- [LangSmith Integration Guide](langsmith-integration.md) - AI monitoring setup
