# Migration and Troubleshooting Guide

This guide helps users migrate to the new LangChain backend architecture and troubleshoot common issues.

> **Implementation Note:** This release implements Phase 1 of [GitHub issue #187](https://github.com/BoPeng/ai-marketplace-monitor/issues/187) with LangChain integration. Future releases will add LangGraph capabilities for advanced agent workflows.

## Migration Overview

The AI Marketplace Monitor has migrated from provider-specific backends to a unified LangChain backend. **Your existing configurations will continue to work without changes** - this is a backward-compatible upgrade focused on improving reliability and consistency.

### Key Changes

The system now uses a unified `LangChainBackend` instead of separate provider backends, with improved error handling and token tracking. **Your existing configurations continue to work unchanged.**

## Migration Steps

### For Existing Users

**No action required** - your existing configuration will work automatically. The system transparently maps your configuration to the new architecture.

#### Verification Steps

1. **Test Your Configuration**
   ```bash
   # Your existing command works unchanged
   ai-marketplace-monitor --config your-existing-config.toml

   # Check logs for successful connection
   # You should see: "AI backend_name connected"
   ```

2. **Verify Provider Functionality**
   ```bash
   # Test with a specific listing
   ai-marketplace-monitor --check https://facebook.com/marketplace/item/123456 --config your-config.toml
   ```

3. **Check Token Usage Tracking** (New Feature)
   Look for enhanced token usage information in logs and monitor costs more effectively.

### For New Users

Follow the standard setup in the [README](../README.md), which now uses the new unified architecture by default.

### Optional: Enable New Features

#### 1. Enhanced Configuration Tips
```bash
export AI_MARKETPLACE_MONITOR_SHOW_CONFIG_TIPS="true"
```

#### 2. LangSmith Monitoring (Optional)

**TOML Configuration (Recommended):**
```toml
[langsmith]
enabled = true
api_key = "${LANGCHAIN_API_KEY}"
project_name = "marketplace-monitor"
```

**Environment Variables:**
```bash
export LANGCHAIN_TRACING_V2="true"
export LANGCHAIN_API_KEY="ls_your_key"
export LANGCHAIN_PROJECT="marketplace-monitor"
```

See the [LangSmith Integration Guide](langsmith-integration.md) for details.

## Migration Scenarios

All existing configurations work without changes. The system automatically maps your settings to the new unified architecture with enhanced reliability and consistency.

## Common Issues

For detailed troubleshooting of configuration, connection, performance, and provider-specific issues, see the [Troubleshooting Guide](troubleshooting.md).

## If Issues Occur

The migration is backward compatible, so no rollback is needed. If you experience problems:

1. **Switch providers temporarily** using backup configuration
2. **Adjust timeouts and retries** in your config
3. **Check the [Troubleshooting Guide](troubleshooting.md)** for specific solutions

## Frequently Asked Questions

### Q: Do I need to update my configuration?

**A:** No, all existing configurations work unchanged. The system automatically maps your settings to the new architecture.

### Q: Will my AI evaluation results change?

**A:** No, the scoring and evaluation logic remain identical. You'll get the same results with improved reliability.

### Q: Can I use multiple providers simultaneously?

**A:** Yes, the same multi-provider configuration syntax works as before, now with better consistency across providers.

### Q: How do I enable the new features?

**A:** New features are automatically enabled. For LangSmith monitoring, see the [LangSmith Integration Guide](langsmith-integration.md).

### Q: What if I encounter issues?

**A:** Check the [Troubleshooting Guide](troubleshooting.md) or create a GitHub issue with logs and configuration details.

### Q: Is the migration reversible?

**A:** The migration is backward compatible. Your configurations work unchanged, so there's no "rollback" needed - everything continues to work.

### Q: Will my cached AI responses still work?

**A:** Yes, cached responses remain valid and will be used to save costs and improve performance.

### Q: How do I know if I'm using the new architecture?

**A:** Check your logs for "LangChain backend" references, or look for enhanced token usage information in the output.

## Getting Help

For issues not covered here:

1. **Check the [Troubleshooting Guide](troubleshooting.md)** for detailed solutions
2. **Review the [Configuration Reference](configuration-reference.md)** for setup examples
3. **Create a GitHub issue** with configuration (no API keys) and error logs

## Enhanced Features

The new architecture provides:
- Enhanced error handling and logging
- Detailed token usage tracking for cost monitoring
- Optional [LangSmith integration](langsmith-integration.md) for tracing
- Thread-safe concurrent evaluations

Your existing setup works seamlessly with these new reliability and monitoring features.
