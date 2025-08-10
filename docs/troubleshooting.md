# Troubleshooting Guide

Common issues and solutions for AI Marketplace Monitor, organized by error type and component.

## Quick Diagnostics

**Run these commands first to identify the issue:**

```bash
# Check configuration and connectivity
uv run ai-marketplace-monitor --config your-config.toml --verbose

# Test specific provider
uv run python -c "from ai_marketplace_monitor.ai import LangChainBackend, AIConfig;
config = AIConfig(provider='openai', api_key='your-key');
backend = LangChainBackend(config); backend.connect()"

# Verify environment variables
echo $OPENAI_API_KEY | cut -c1-7  # Should show "sk-proj" or "sk-"
```

## Configuration Issues

### Unsupported Provider

**Error:** `Unsupported provider 'xyz'`

**Cause:** Invalid provider name in configuration

**Solution:** Use supported providers: `openai`, `deepseek`, `ollama`, `openrouter`

```toml
# Fix this:
[ai.invalid]
provider = "xyz"

# To this:
[ai.openai]
provider = "openai"
```

### Missing API Keys

**Error:** `API key is required`

**Solutions:**
1. **Set environment variable:**
   ```bash
   export OPENAI_API_KEY="sk-..."
   ```

2. **Add to configuration:**
   ```toml
   [ai.openai]
   api_key = "sk-..."  # Not recommended for production
   ```

3. **Verify key format:**
   - OpenAI: `sk-proj...` or `sk-...`
   - DeepSeek: `sk-...`
   - OpenRouter: `sk-or-...`

### Invalid Model Names

**Error:** `Model 'xyz' does not exist`

**Provider-Specific Solutions:**

**OpenAI:**
- Use `gpt-4o` instead of `gpt-4`
- Check [platform.openai.com/docs/models](https://platform.openai.com/docs/models)

**OpenRouter:**
- Use `provider/model` format: `anthropic/claude-3-sonnet`
- Check [openrouter.ai/models](https://openrouter.ai/models)

**Ollama:**
- Pull model first: `ollama pull deepseek-r1:14b`
- List available: `ollama list`

## Connection Issues

### Network Connectivity

**Error:** `Connection failed` or `Connection timeout`

**Solutions:**
1. **Test connectivity:**
   ```bash
   curl -I https://api.openai.com/v1/models
   curl -I https://api.deepseek.com/v1/models
   ```

2. **Check firewall/proxy settings**

3. **Increase timeout:**
   ```toml
   [ai.provider]
   timeout = 180  # 3 minutes
   ```

### Service Outages

**Error:** `Provider service error`

**Solutions:**
1. **Check status pages:**
   - OpenAI: [status.openai.com](https://status.openai.com)
   - Check provider official channels

2. **Use backup provider:**
   ```toml
   [ai.backup]
   provider = "deepseek"
   api_key = "${DEEPSEEK_API_KEY}"
   ```

## Authentication Issues

### Invalid API Keys

**Error:** `Authentication error: Incorrect API key provided`

**Solutions:**
1. **Verify key format and check for typos**
2. **Test key directly:**
   ```bash
   curl -H "Authorization: Bearer $OPENAI_API_KEY" \
        https://api.openai.com/v1/models
   ```
3. **Regenerate key** in provider dashboard if compromised

### Rate Limits

**Error:** `Rate limit exceeded`

**Solutions:**
1. **Upgrade API plan** with provider
2. **Add delays between requests** (automatic retry handles this)
3. **Use backup provider** for overflow

### Billing Issues

**Error:** `Insufficient balance` or `Billing issue`

**Solutions:**
1. **Check account balance** in provider dashboard
2. **Add payment method** or funds
3. **Verify billing limits** aren't exceeded

## Provider-Specific Issues

### OpenAI

**Model Access Issues:**
```
ValueError: The model 'gpt-4' does not exist
```
- **Solution:** Use `gpt-4o` or check account access level

**Usage Limits:**
```
RuntimeError: Rate limit exceeded: Too many requests
```
- **Solution:** Upgrade to paid plan or implement longer delays

### DeepSeek

**Geographic Latency:**
```
RuntimeError: Connection timeout
```
- **Solution:** Increase timeout for regions outside China:
  ```toml
  [ai.deepseek]
  timeout = 180
  ```

### OpenRouter

**Model Unavailability:**
```
ValueError: OpenRouter model 'provider/model' is currently unavailable
```
- **Solution:** Try alternative models:
  ```toml
  model = "anthropic/claude-3-haiku"  # Often more available
  ```

**Billing Issues:**
```
RuntimeError: OpenRouter billing issue: Insufficient balance
```
- **Solution:** Add credits at [openrouter.ai/credits](https://openrouter.ai/credits)

### Ollama

**Service Not Running:**
```
RuntimeError: Connection refused
```
- **Solution:** Start Ollama:
  ```bash
  ollama serve
  ```

**Model Not Found:**
```
RuntimeError: Model 'model-name' not found
```
- **Solution:** Pull model:
  ```bash
  ollama pull deepseek-r1:14b
  ```

## Performance Issues

### Slow AI Responses

**Causes and Solutions:**

1. **Model Selection:**
   ```toml
   # Use faster models for development
   [ai.openai]
   model = "gpt-3.5-turbo"  # vs gpt-4o
   ```

2. **Geographic Distance:**
   ```toml
   # Increase timeout for distant providers
   [ai.deepseek]
   timeout = 180
   ```

3. **Network Issues:**
   - Test with different internet connection
   - Check for proxy/VPN interference

### High API Costs

**Cost Monitoring:**
- Check provider dashboards for usage
- Monitor token counts in application logs

**Cost Reduction:**
1. **Use cheaper models:**
   ```toml
   [ai.budget]
   provider = "deepseek"  # ~$0.001 per 1K tokens
   model = "deepseek-chat"
   ```

2. **Optimize search criteria:**
   ```toml
   [item.search]
   rating_threshold = 4  # Only evaluate high-potential items
   ```

3. **Enable caching:**
   ```toml
   [monitor]
   enable_caching = true
   ```

### Memory Issues

**High Memory Usage:**
- **Solution:** Restart application periodically for long-running processes
- **Clear caches:** Delete `~/.ai-marketplace-monitor/cache/` contents

## Facebook Marketplace Issues

### Login Problems

**Error:** `Facebook login failed`

**Solutions:**
1. **Check credentials:**
   ```bash
   echo $FACEBOOK_USERNAME
   echo $FACEBOOK_PASSWORD  # Be careful with this
   ```

2. **Handle 2FA:** Currently not supported - disable for monitoring account

3. **CAPTCHA challenges:** Run in non-headless mode first:
   ```toml
   [marketplace.facebook]
   headless = false
   ```

### Scraping Issues

**Error:** `Failed to find listings`

**Solutions:**
1. **Update search terms** - Facebook may have changed UI
2. **Check city name** spelling in configuration
3. **Run in headed mode** to see what's happening

**Error:** `Browser timeout`
- **Solution:** Increase timeouts in marketplace configuration

## Error Message Reference

| Error Type | Pattern | Quick Fix |
|------------|---------|-----------|
| Configuration | `Unsupported provider` | Use: openai, deepseek, ollama, openrouter |
| Authentication | `Incorrect API key` | Check key format and spelling |
| Network | `Connection failed` | Test connectivity, check firewall |
| Rate Limit | `Rate limit exceeded` | Upgrade plan or add delays |
| Model | `Model does not exist` | Check model name and availability |
| Service | `Provider service error` | Check status page, try backup |

## Debug Commands

### Enable Debug Logging

```bash
export AI_MARKETPLACE_MONITOR_LOG_LEVEL=DEBUG
uv run ai-marketplace-monitor --config your-config.toml --verbose
```

### Test Individual Components

**Test AI Backend:**
```python
from ai_marketplace_monitor.ai import LangChainBackend, AIConfig
config = AIConfig(provider="openai", api_key="sk-...")
backend = LangChainBackend(config)
backend.connect()  # Should succeed without error
```

**Test Marketplace Connection:**
```python
from ai_marketplace_monitor.facebook import FacebookMarketplace
marketplace = FacebookMarketplace(config)
marketplace.connect()  # Opens browser - check manually
```

### Check System Information

```bash
# Python and package versions
uv run python --version
uv run python -c "import ai_marketplace_monitor; print(ai_marketplace_monitor.__version__)"

# Environment check
env | grep -E "(OPENAI|DEEPSEEK|FACEBOOK|LANGCHAIN)"

# Cache status
ls -la ~/.ai-marketplace-monitor/cache/
```

## LangSmith Configuration Issues

### LangSmith Connection Failures

**Error:** `LangSmith authentication failed`

**Solutions:**
1. **Verify API key format:**
   ```bash
   echo $LANGCHAIN_API_KEY | cut -c1-3  # Should show "ls_"
   ```

2. **Check TOML configuration:**
   ```toml
   [langsmith]
   enabled = true
   api_key = "${LANGCHAIN_API_KEY}"  # Use environment variable
   project_name = "your-project"
   ```

3. **Test connectivity:**
   ```bash
   curl -H "x-api-key: $LANGCHAIN_API_KEY" \
        https://api.smith.langchain.com/projects
   ```

### Invalid LangSmith Configuration

**Error:** `Invalid LangSmith configuration`

**Common Issues:**
1. **Missing required fields:**
   ```toml
   [langsmith]
   enabled = true
   # Missing api_key and project_name
   ```

2. **Invalid environment variable substitution:**
   ```toml
   [langsmith]
   api_key = "${MISSING_VAR}"  # Environment variable not set
   ```

3. **Type errors:**
   ```toml
   [langsmith]
   enabled = "true"  # Should be boolean, not string
   ```

**Solutions:**
- Use configuration validation: `uv run ai-marketplace-monitor --config your-config.toml --validate`
- Check environment variables are set: `env | grep LANGCHAIN`

### LangSmith Project Access Issues

**Error:** `Project not found` or `Access denied`

**Solutions:**
1. **Verify project exists** in LangSmith dashboard
2. **Check API key permissions** for the project
3. **Use correct project name:**
   ```toml
   [langsmith]
   project_name = "exact-project-name"  # Case sensitive
   ```

### LangSmith Tracing Not Working

**Symptoms:** AI calls work but no traces appear in LangSmith dashboard

**Debug Steps:**
1. **Verify tracing is enabled:**
   ```bash
   # Check logs for:
   # "LangSmith tracing enabled (project: your-project)"
   uv run ai-marketplace-monitor --config your-config.toml --verbose
   ```

2. **Test minimal configuration:**
   ```toml
   [langsmith]
   enabled = true
   api_key = "${LANGCHAIN_API_KEY}"
   project_name = "test-project"
   ```

3. **Check environment variable precedence:**
   ```bash
   # These can override TOML settings
   export LANGCHAIN_TRACING_V2="false"  # Disables tracing
   unset LANGCHAIN_TRACING_V2
   ```

### Configuration Precedence Issues

**Problem:** TOML configuration not taking effect

**Cause:** Environment variables override TOML settings

**Solution:** Check for conflicting environment variables:
```bash
env | grep LANGCHAIN
# Unset conflicting variables:
unset LANGCHAIN_PROJECT
unset LANGCHAIN_TRACING_V2
```

**Precedence Order (highest to lowest):**
1. Environment variables (when using `${VAR_NAME}` in TOML)
2. Direct TOML values
3. Default values

## Getting Help

**Before Creating an Issue:**

1. **Check logs** with debug enabled
2. **Test with simple configuration** to isolate the problem
3. **Verify network connectivity** to your chosen provider
4. **Review recent changes** to configuration or environment

**When Reporting Issues:**

Include:
- Configuration file (remove API keys)
- Complete error message and stack trace
- Environment details (OS, Python version)
- Steps to reproduce the problem

**Resources:**
- [GitHub Issues](https://github.com/BoPeng/ai-marketplace-monitor/issues)
- [Configuration Reference](configuration-reference.md)
- [Provider Setup Guide](ai-providers.md)

## Emergency Procedures

### Service Restoration

**If monitoring stops working:**

1. **Quick health check:**
   ```bash
   uv run ai-marketplace-monitor --check https://facebook.com/marketplace/item/test
   ```

2. **Switch providers temporarily:**
   ```bash
   # Change provider in config or use environment override
   export OPENAI_API_KEY=""  # Disable OpenAI
   export DEEPSEEK_API_KEY="sk-..."  # Enable DeepSeek
   ```

3. **Reset caches:**
   ```bash
   rm -rf ~/.ai-marketplace-monitor/cache/
   ```

### Data Recovery

**If configuration is corrupted:**
- Restore from backup or recreate using [Configuration Reference](configuration-reference.md)

**If cache issues occur:**
- Delete cache directory - will be recreated: `rm -rf ~/.ai-marketplace-monitor/cache/`

This troubleshooting guide covers the most common issues. For additional help, consult the [Configuration Reference](configuration-reference.md) or create a GitHub issue with detailed information.
