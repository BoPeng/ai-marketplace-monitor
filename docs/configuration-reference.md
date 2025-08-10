# Configuration Reference

Complete reference for AI Marketplace Monitor configuration options, provider settings, and environment variables.

## Configuration File Structure

AI Marketplace Monitor uses TOML configuration files with sections for different components:

```toml
# ~/.ai-marketplace-monitor/config.toml
[ai.provider_name]      # AI provider configuration
[marketplace.facebook]  # Marketplace settings
[item.search_name]      # Search item definitions
[user.user_name]        # User and notification settings
[notification.*]        # Notification service settings
[monitor]              # Global monitoring settings
```

## AI Provider Configuration

### OpenAI

```toml
[ai.openai]
provider = "openai"
api_key = "${OPENAI_API_KEY}"
model = "gpt-4o"
timeout = 60
max_retries = 3
```

**Environment Variables:**
- `OPENAI_API_KEY`: API key (starts with `sk-`)

**Models:** `gpt-4o`, `gpt-4o-mini`, `gpt-3.5-turbo`

**Cost:** $0.03-0.06 per 1K tokens (varies by model)

### DeepSeek

```toml
[ai.deepseek]
provider = "deepseek"
api_key = "${DEEPSEEK_API_KEY}"
model = "deepseek-chat"
timeout = 120  # Higher for geographic latency
max_retries = 3
```

**Environment Variables:**
- `DEEPSEEK_API_KEY`: API key (starts with `sk-`)

**Models:** `deepseek-chat`, `deepseek-coder`

**Cost:** ~$0.001 per 1K tokens (very cost-effective)

### OpenRouter

```toml
[ai.openrouter]
provider = "openrouter"
api_key = "${OPENROUTER_API_KEY}"
model = "anthropic/claude-3-sonnet"  # provider/model format required
timeout = 120
max_retries = 3
```

**Environment Variables:**
- `OPENROUTER_API_KEY`: API key (must start with `sk-or-`)

**Model Format:** `provider/model` (e.g., `anthropic/claude-3-haiku`, `openai/gpt-4o`)

**Cost:** Variable by model, check [openrouter.ai/models](https://openrouter.ai/models)

### Ollama (Local Models)

```toml
[ai.ollama]
provider = "ollama"
api_key = "ollama"  # Required but unused
model = "deepseek-r1:14b"
base_url = "http://localhost:11434"
timeout = 180
```

**Prerequisites:**
```bash
# Install and start Ollama
ollama serve
ollama pull deepseek-r1:14b
```

**Models:** Any model pulled locally (`ollama list` to see available)

**Cost:** Free (local processing)

## Marketplace Configuration

### Facebook Marketplace

```toml
[marketplace.facebook]
search_city = "houston"
username = "${FACEBOOK_USERNAME}"
password = "${FACEBOOK_PASSWORD}"
headless = true  # Run without browser window
max_listings = 50
```

**Environment Variables:**
- `FACEBOOK_USERNAME`: Your Facebook login email
- `FACEBOOK_PASSWORD`: Your Facebook password

## Item Search Configuration

```toml
[item.search_name]
search_phrases = "vintage guitar, fender stratocaster"
description = "Looking for vintage electric guitars"
min_price = 200
max_price = 2000
excluded_words = "broken, damaged, parts only"
rating_threshold = 3  # Only notify for ratings >= 3
```

**Parameters:**
- `search_phrases`: Comma-separated search terms
- `description`: Context for AI evaluation
- `min_price`/`max_price`: Price range filters
- `excluded_words`: Skip listings containing these terms
- `rating_threshold`: Minimum AI rating (1-5) for notifications

## User and Notification Configuration

### User Settings

```toml
[user.username]
notification_services = ["pushbullet", "email"]
notification_level = 4  # Only high-rated items (4-5 stars)
rate_limit_minutes = 60  # Max one notification per hour per item
```

### Email Notifications

```toml
[notification.email]
smtp_server = "smtp.gmail.com"
smtp_port = 587
username = "${EMAIL_USERNAME}"
password = "${EMAIL_PASSWORD}"
from_email = "${EMAIL_USERNAME}"
to_email = "alerts@yourdomain.com"
```

### PushBullet Notifications

```toml
[notification.pushbullet]
api_token = "${PUSHBULLET_TOKEN}"
```

### Telegram Notifications

```toml
[notification.telegram]
bot_token = "${TELEGRAM_BOT_TOKEN}"
chat_id = "${TELEGRAM_CHAT_ID}"
```

### Other Notification Services

**PushOver:**
```toml
[notification.pushover]
user_key = "${PUSHOVER_USER_KEY}"
api_token = "${PUSHOVER_API_TOKEN}"
```

**Ntfy:**
```toml
[notification.ntfy]
topic = "marketplace-alerts"
server_url = "https://ntfy.sh"  # or your private server
```

## Environment Variables

### Required by Provider

| Provider   | Variable              | Format                    |
|------------|-----------------------|---------------------------|
| OpenAI     | `OPENAI_API_KEY`     | `sk-proj...` or `sk-...`  |
| DeepSeek   | `DEEPSEEK_API_KEY`   | `sk-...`                  |
| OpenRouter | `OPENROUTER_API_KEY` | `sk-or-...`              |
| Facebook   | `FACEBOOK_USERNAME`  | Email address             |
| Facebook   | `FACEBOOK_PASSWORD`  | Account password          |

### Optional Configuration

```bash
# Development and debugging
export AI_MARKETPLACE_MONITOR_SHOW_CONFIG_TIPS="true"
export AI_MARKETPLACE_MONITOR_LOG_LEVEL="DEBUG"

# LangSmith monitoring (optional) - can also be configured in TOML
export LANGCHAIN_TRACING_V2="true"
export LANGCHAIN_API_KEY="ls_..."
export LANGCHAIN_PROJECT="marketplace-monitor"

# Cache and data directories
export AI_MARKETPLACE_MONITOR_CACHE_DIR="~/.ai-marketplace-monitor/cache"
export AI_MARKETPLACE_MONITOR_CONFIG_DIR="~/.ai-marketplace-monitor"
```

## LangSmith Tracing Configuration

[LangSmith](https://langchain.com/langsmith) provides AI application monitoring and debugging capabilities. Configure tracing integration using the `[langsmith]` section.

### Basic Configuration

```toml
[langsmith]
enabled = true
api_key = "${LANGCHAIN_API_KEY}"
project_name = "${LANGCHAIN_PROJECT}"
```

### Complete Configuration

```toml
[langsmith]
enabled = true
api_key = "${LANGCHAIN_API_KEY}"
project_name = "marketplace-monitor-prod"
endpoint = "https://api.smith.langchain.com"
session_name = "monitoring-session"
metadata = { environment = "production", version = "1.0" }
```

**Parameters:**
- `enabled` (boolean): Enable/disable LangSmith tracing (default: `false`)
- `api_key` (string): LangSmith API key (format: `ls_...`) - **required**
- `project_name` (string): Project name in LangSmith dashboard - **required**
- `endpoint` (string): LangSmith API endpoint (default: `"https://api.smith.langchain.com"`)
- `session_name` (string): Session identifier for grouping traces (optional)
- `metadata` (table): Additional metadata for traces (optional)

**Environment Variables:**
- `LANGCHAIN_API_KEY`: LangSmith API key (starts with `ls_`)
- `LANGCHAIN_PROJECT`: Default project name
- `LANGCHAIN_TRACING_V2`: Enable tracing (use TOML `enabled` for better control)

### Security Best Practices

**✅ Secure Configuration:**
```toml
[langsmith]
enabled = true
api_key = "${LANGCHAIN_API_KEY}"  # Use environment variable
project_name = "${LANGCHAIN_PROJECT}"
```

**❌ Insecure Configuration:**
```toml
[langsmith]
api_key = "ls_1234567890abcdef"  # Never store API keys in plain text
```

### Configuration Precedence

Configuration values are resolved in the following order (highest to lowest priority):

1. **Environment Variables** (if TOML uses `${VAR_NAME}`)
2. **TOML Configuration** (direct values)
3. **Default Values**

**Example with Precedence:**
```toml
[langsmith]
enabled = true
api_key = "${LANGCHAIN_API_KEY}"  # Resolved from environment
project_name = "direct-value"     # Used as-is
endpoint = "${LANGSMITH_ENDPOINT:-https://api.smith.langchain.com}"  # Environment with default
```

## Global Monitor Settings

```toml
[monitor]
check_interval = 900  # Check every 15 minutes
max_concurrent_evaluations = 5
cache_ttl_days = 30
enable_caching = true
```

## Configuration Examples by Use Case

### Development Setup

```toml
[ai.dev]
provider = "openai"
api_key = "${OPENAI_API_KEY}"
model = "gpt-3.5-turbo"  # Faster/cheaper
timeout = 30
max_retries = 2

[monitor]
check_interval = 300  # 5 minutes for testing
```

### Cost-Optimized Setup

```toml
[ai.budget]
provider = "deepseek"  # Most cost-effective
api_key = "${DEEPSEEK_API_KEY}"
model = "deepseek-chat"

[item.search]
rating_threshold = 4  # Only high-value items
```

### High-Volume Production

```toml
[ai.primary]
provider = "openai"
api_key = "${OPENAI_API_KEY}"
model = "gpt-4o-mini"
max_retries = 5

[ai.backup]
provider = "deepseek"
api_key = "${DEEPSEEK_API_KEY}"
model = "deepseek-chat"

[monitor]
max_concurrent_evaluations = 10
```

### Local/Privacy-First Setup

```toml
[ai.local]
provider = "ollama"
api_key = "ollama"
model = "deepseek-r1:14b"
base_url = "http://localhost:11434"
timeout = 180
```

## Configuration Validation

The system validates configurations at startup:

- **Provider Support:** Only `openai`, `deepseek`, `ollama`, `openrouter` are supported
- **API Key Formats:** Provider-specific validation (OpenRouter must start with `sk-or-`)
- **Required Fields:** Provider, model specifications
- **Model Availability:** Real-time checking for OpenRouter models
- **Network Connectivity:** Connection testing during startup

## Configuration File Locations

**Default Search Order:**
1. `--config` command line argument
2. `./config.toml` (current directory)
3. `~/.ai-marketplace-monitor/config.toml`
4. `~/.config/ai-marketplace-monitor/config.toml`

**Environment Variable Substitution:**
- Use `${VARIABLE_NAME}` syntax in TOML files
- Variables resolved at runtime
- Supports default values: `${VAR_NAME:-default_value}`

## Security Best Practices

- **Never commit API keys** to version control
- **Use environment variables** for all sensitive data
- **Rotate API keys** regularly
- **Use separate keys** for development/production
- **Monitor API usage** in provider dashboards
- **Set appropriate rate limits** to prevent unexpected costs

## See Also

- [AI Provider Setup Guide](ai-providers.md) - Detailed provider setup instructions
- [Developer Guide](developer-guide.md) - Development workflow
- [Troubleshooting Guide](troubleshooting.md) - Common configuration issues
- [Migration Guide](migration-guide.md) - Upgrading from older versions
