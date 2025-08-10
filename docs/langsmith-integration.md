# LangSmith Integration Guide

LangSmith provides comprehensive observability for AI applications built with LangChain. AI Marketplace Monitor includes optional LangSmith integration for monitoring, debugging, and optimizing AI evaluation performance.

## Overview

LangSmith integration enables:

- **Trace Monitoring**: Track every AI evaluation with detailed request/response data
- **Performance Analytics**: Monitor token usage, response times, and error rates
- **Debugging Tools**: Inspect failed evaluations and optimize prompts
- **Cost Analysis**: Track spending across different AI providers
- **A/B Testing**: Compare different models, prompts, and configurations

## Setup Instructions

### 1. Create LangSmith Account

1. Visit [smith.langchain.com](https://smith.langchain.com)
2. Sign up for an account
3. Create a new project for AI Marketplace Monitor

### 2. Get API Credentials

1. Navigate to Settings → API Keys
2. Create a new API key
3. Copy the API key (starts with `ls_`)

### 3. Configuration Options

LangSmith can be configured using either TOML configuration files or environment variables.

#### TOML Configuration (Recommended)

Add a `[langsmith]` section to your configuration file:

```toml
[langsmith]
enabled = true
api_key = "${LANGCHAIN_API_KEY}"
project_name = "ai-marketplace-monitor"
```

#### Environment Variable Configuration

Set the following environment variables:

```bash
# Required: Enable tracing
export LANGCHAIN_TRACING_V2="true"

# Required: API authentication
export LANGCHAIN_API_KEY="ls_your_api_key_here"

# Optional: Project name for organization
export LANGCHAIN_PROJECT="ai-marketplace-monitor"

# Optional: Custom endpoint (rarely needed)
export LANGCHAIN_ENDPOINT="https://api.smith.langchain.com"
```

### 4. Verify Integration

Run AI Marketplace Monitor and check the logs:

```bash
uv run ai-marketplace-monitor --config your-config.toml

# You should see in the logs:
# INFO: LangSmith tracing is enabled (project: ai-marketplace-monitor)
```

## Configuration Examples

### Basic TOML Configuration

```toml
[langsmith]
enabled = true
api_key = "${LANGCHAIN_API_KEY}"
project_name = "ai-marketplace-monitor"
```

### Production TOML Configuration

```toml
[langsmith]
enabled = true
api_key = "${LANGCHAIN_API_KEY}"
project_name = "marketplace-monitor-prod"
endpoint = "https://api.smith.langchain.com"
session_name = "prod-deployment-v1.2.3"
metadata = { environment = "production", version = "1.2.3" }
```

### Development TOML Configuration

```toml
[langsmith]
enabled = true
api_key = "${LANGCHAIN_API_KEY}"
project_name = "marketplace-monitor-dev"
session_name = "dev-session"
metadata = { environment = "development", user = "${USER}" }
```

### Environment Variable Configuration

Environment variables are also supported:

```bash
# Minimal setup
export LANGCHAIN_TRACING_V2="true"
export LANGCHAIN_API_KEY="ls_..."

# Production with project organization
export LANGCHAIN_PROJECT="marketplace-monitor-prod"
export LANGCHAIN_SESSION="prod-deployment-v1.2.3"
```

### Configuration Precedence

TOML configuration takes precedence over environment variables. You can mix both approaches:

```toml
[langsmith]
enabled = true
api_key = "${LANGCHAIN_API_KEY}"  # From environment
project_name = "toml-project"     # Direct TOML value
```

## Monitoring and Analytics

### Viewing Traces

1. **Access Dashboard**: Visit [smith.langchain.com](https://smith.langchain.com)
2. **Select Project**: Choose your AI Marketplace Monitor project
3. **View Traces**: See real-time AI evaluation traces

### Key Metrics to Monitor

#### Performance Metrics
- **Response Time**: Average time per AI evaluation
- **Token Usage**: Input/output tokens per request
- **Success Rate**: Percentage of successful evaluations
- **Error Rate**: Failed evaluations by error type

#### Cost Analytics
- **Daily Spending**: Token costs by provider
- **Cost Per Evaluation**: Average cost per listing analysis
- **Monthly Trends**: Usage patterns over time
- **Provider Comparison**: Cost effectiveness by AI provider

#### Quality Metrics
- **Rating Distribution**: Distribution of 1-5 ratings given by AI
- **Comment Length**: Average length of AI comments
- **Evaluation Consistency**: Variance in ratings for similar items

### Creating Dashboards

1. **Navigate to Analytics**: In your LangSmith project
2. **Create Custom Views**: Filter by specific criteria:
   - Time ranges (last 24h, week, month)
   - AI providers (OpenAI, DeepSeek, etc.)
   - Item categories or search terms
   - Rating scores (high-value vs low-value items)

3. **Set Up Alerts**: Configure notifications for:
   - High error rates
   - Unusual cost spikes
   - Performance degradation

## Debugging with LangSmith

### Investigating Failed Evaluations

When AI evaluations fail or produce unexpected results:

1. **Find the Trace**: Search by timestamp or listing URL
2. **Examine Input**: Review the prompt sent to AI
3. **Check Response**: See the raw AI response
4. **Identify Issues**: Look for:
   - Malformed prompts
   - Token limit exceeded
   - API errors
   - Parsing failures

See [Troubleshooting Guide](troubleshooting.md) for debug workflows and common resolution steps.

### Debug Use Cases

Use LangSmith traces to investigate:
- **Inconsistent ratings**: Compare prompts between evaluations
- **High token usage**: Analyze cost patterns and optimize prompts
- **Timeouts**: Check request duration and adjust settings

## Prompt Optimization

### Analyzing Prompt Performance

Use LangSmith to optimize your AI prompts:

1. **Baseline Metrics**: Record current performance
2. **A/B Testing**: Try different prompt variations
3. **Compare Results**: Use LangSmith analytics to compare:
   - Response quality
   - Token usage
   - Processing time
   - Error rates

### Example Optimization Process

```python
# Original prompt analysis
original_traces = langsmith.filter_traces(
    project="marketplace-monitor",
    filter={"prompt_version": "v1.0"}
)

# New prompt testing
new_traces = langsmith.filter_traces(
    project="marketplace-monitor",
    filter={"prompt_version": "v1.1"}
)

# Compare metrics
compare_performance(original_traces, new_traces)
```

### Best Practices for Prompt Engineering

1. **Structured Prompts**: Use consistent formatting
2. **Clear Instructions**: Be explicit about rating criteria
3. **Examples**: Include few-shot examples for consistency
4. **Length Optimization**: Balance detail with token costs
5. **Version Control**: Tag prompts with versions in LangSmith

## Integration with Development Workflow

### Local Development

```bash
# Development with LangSmith
export LANGCHAIN_TRACING_V2="true"
export LANGCHAIN_API_KEY="ls_..."
export LANGCHAIN_PROJECT="marketplace-dev-${USER}"

# Run tests with tracing
uv run pytest tests/integration/ -m ai_integration
```

### Continuous Integration

```yaml
# .github/workflows/test.yml
name: AI Integration Tests
on: [push, pull_request]

jobs:
  test-ai:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup environment
        run: |
          echo "LANGCHAIN_TRACING_V2=true" >> $GITHUB_ENV
          echo "LANGCHAIN_PROJECT=ci-tests-${{ github.run_id }}" >> $GITHUB_ENV
      - name: Run AI tests
        env:
          LANGCHAIN_API_KEY: ${{ secrets.LANGCHAIN_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          uv run pytest tests/integration/test_ai_providers.py
```

### Production Deployment

```bash
# Production environment
export LANGCHAIN_TRACING_V2="true"
export LANGCHAIN_API_KEY="ls_prod_key"
export LANGCHAIN_PROJECT="marketplace-monitor-prod"
export LANGCHAIN_SESSION="prod-$(date +%Y%m%d)"

# Monitor in production
tail -f /var/log/marketplace-monitor.log | grep "LangSmith"
```

## Security and Privacy

### API Key Management

- **Environment Variables**: Never hardcode API keys
- **Key Rotation**: Regularly rotate LangSmith API keys
- **Access Control**: Use separate keys for dev/staging/prod
- **Monitoring**: Monitor API key usage in LangSmith dashboard

### Data Privacy

**LangSmith Data Collection**:
- Prompts sent to AI models
- AI responses and ratings
- Token usage and timing data
- Error messages and stack traces

**Privacy Considerations**:
- **Listing Data**: Facebook Marketplace listings may contain personal information
- **Search Criteria**: User search preferences are included in prompts
- **PII Filtering**: Consider filtering sensitive data before tracing

### Compliance Settings

```bash
# Disable tracing for sensitive data
export LANGCHAIN_TRACING_V2="false"

# Or use conditional tracing
if [[ "$ENVIRONMENT" == "prod" && "$SENSITIVE_MODE" == "true" ]]; then
    export LANGCHAIN_TRACING_V2="false"
else
    export LANGCHAIN_TRACING_V2="true"
fi
```

## Cost Management

### Understanding Costs

LangSmith costs include:
- **Trace Storage**: Based on number of traces and data size
- **Analytics Processing**: Complex queries and dashboards
- **API Calls**: Retrieving traces and metrics programmatically

### Cost Optimization

1. **Selective Tracing**:
   ```bash
   # Only trace in development
   if [[ "$ENVIRONMENT" == "dev" ]]; then
       export LANGCHAIN_TRACING_V2="true"
   fi
   ```

2. **Data Retention**:
   - Configure automatic cleanup of old traces
   - Archive important traces before deletion
   - Use sampling for high-volume production

3. **Efficient Queries**:
   - Use specific time ranges
   - Filter traces appropriately
   - Avoid unnecessary dashboard refreshes

## Troubleshooting

For LangSmith connection issues, authentication errors, and other common problems, see the [Troubleshooting Guide](troubleshooting.md).

## Advanced Features

### Custom Metadata

Add custom metadata to traces:

```python
import os
os.environ["LANGCHAIN_TAGS"] = "marketplace,production,v1.2.3"
os.environ["LANGCHAIN_METADATA"] = '{"version": "1.2.3", "env": "prod"}'
```

### Programmatic Access

Use LangSmith SDK for custom analytics:

```python
from langsmith import Client

client = Client(api_key="ls_...")

# Get recent traces
traces = client.list_runs(
    project_name="marketplace-monitor",
    limit=100,
    start_time=datetime.now() - timedelta(hours=24)
)

# Analyze token usage
total_tokens = sum(trace.total_tokens for trace in traces if trace.total_tokens)
print(f"24h token usage: {total_tokens:,}")
```

### Integration with Monitoring Systems

Forward LangSmith metrics to other monitoring systems:

```python
# Example: Forward to Prometheus
from prometheus_client import Counter, Histogram
import time

ai_evaluations_total = Counter('ai_evaluations_total', 'Total AI evaluations')
ai_evaluation_duration = Histogram('ai_evaluation_duration_seconds', 'AI evaluation time')

def monitored_evaluate(backend, listing, item_config, marketplace_config):
    start_time = time.time()
    try:
        result = backend.evaluate(listing, item_config, marketplace_config)
        ai_evaluations_total.inc()
        return result
    finally:
        duration = time.time() - start_time
        ai_evaluation_duration.observe(duration)
```

## Best Practices Summary

1. **Setup**:
   - Use environment variables for configuration
   - Separate projects for dev/staging/prod
   - Test integration before production deployment

2. **Monitoring**:
   - Set up alerts for error rates and costs
   - Monitor token usage trends
   - Track evaluation quality metrics

3. **Debugging**:
   - Use LangSmith traces for troubleshooting
   - Compare prompts for consistency issues
   - Optimize based on performance data

4. **Security**:
   - Protect API keys
   - Consider data privacy implications
   - Use selective tracing for sensitive data

5. **Cost Management**:
   - Monitor trace volume and costs
   - Use sampling for high-volume scenarios
   - Clean up old traces regularly

## See Also

- [Configuration Reference](configuration-reference.md) - Environment variable setup
- [Troubleshooting Guide](troubleshooting.md) - LangSmith connection issues
- [Developer Guide](developer-guide.md) - Integration with development workflow
- [LangSmith Documentation](https://docs.smith.langchain.com/) - Official LangSmith docs
