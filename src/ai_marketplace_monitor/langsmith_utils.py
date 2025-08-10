"""Utilities for optional LangSmith tracing integration."""

import os
from logging import Logger
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .config import LangSmithConfig


def is_langsmith_enabled(config: Optional["LangSmithConfig"] = None) -> bool:
    """Check if LangSmith tracing is properly configured.

    Args:
        config: Optional LangSmithConfig from TOML configuration. Takes precedence over environment variables.

    LangSmith automatically traces LangChain calls when these environment variables are set:
    - LANGCHAIN_TRACING_V2=true (enables tracing)
    - LANGCHAIN_API_KEY=<your_api_key> (authenticates)
    - LANGCHAIN_PROJECT=<project_name> (optional, for organization)

    For backward compatibility, also supports legacy LANGSMITH_* variable names.

    Returns:
        True if LangSmith tracing is enabled and API key is set.
    """
    # If config provided, use it with highest precedence
    if config is not None:
        return config.enabled and bool(config.api_key)

    # Check for primary LANGCHAIN_* variables first
    tracing_enabled = os.getenv("LANGCHAIN_TRACING_V2", "").lower() in ("true", "1", "yes")
    api_key_set = bool(os.getenv("LANGCHAIN_API_KEY", "").strip())

    # Fallback to legacy LANGSMITH_* variables for backward compatibility
    if not tracing_enabled:
        tracing_enabled = os.getenv("LANGSMITH_TRACING", "").lower() in ("true", "1", "yes")
    if not api_key_set:
        api_key_set = bool(os.getenv("LANGSMITH_API_KEY", "").strip())

    return tracing_enabled and api_key_set


def get_langsmith_config(config: Optional["LangSmithConfig"] = None) -> dict[str, Optional[str]]:
    """Get current LangSmith configuration from TOML config or environment variables.

    Args:
        config: Optional LangSmithConfig from TOML configuration. Takes precedence over environment variables.

    Supports both LANGCHAIN_* and legacy LANGSMITH_* variable names.

    Returns:
        Dict with tracing status, API key presence, and project name.
    """
    # If config provided, use it with highest precedence
    if config is not None:
        return {
            "tracing_enabled": "true" if config.enabled else "false",
            "api_key_configured": "configured" if config.api_key else "not configured",
            "project": config.project_name,
        }

    # Primary LANGCHAIN_* variables with fallback to legacy LANGSMITH_* variables
    tracing_enabled = os.getenv("LANGCHAIN_TRACING_V2") or os.getenv("LANGSMITH_TRACING", "false")
    api_key = os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY")
    project = os.getenv("LANGCHAIN_PROJECT") or os.getenv("LANGSMITH_PROJECT")

    return {
        "tracing_enabled": tracing_enabled,
        "api_key_configured": "configured" if api_key else "not configured",
        "project": project,
    }


def configure_langsmith_environment(config: "LangSmithConfig") -> None:
    """Configure environment variables for LangChain integration from LangSmithConfig.

    Sets the LANGCHAIN_* environment variables that LangChain uses for tracing.
    Only sets variables that aren't already set to preserve explicit environment overrides.

    Args:
        config: LangSmithConfig instance with tracing configuration.
    """
    # Only set environment variables if they're not already set
    # This allows explicit environment variable overrides
    if config.enabled and "LANGCHAIN_TRACING_V2" not in os.environ:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
    elif not config.enabled and "LANGCHAIN_TRACING_V2" not in os.environ:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"

    if config.api_key and "LANGCHAIN_API_KEY" not in os.environ:
        os.environ["LANGCHAIN_API_KEY"] = config.api_key

    if config.project_name and "LANGCHAIN_PROJECT" not in os.environ:
        os.environ["LANGCHAIN_PROJECT"] = config.project_name

    if config.endpoint and "LANGCHAIN_ENDPOINT" not in os.environ:
        os.environ["LANGCHAIN_ENDPOINT"] = config.endpoint


def log_langsmith_status(
    logger: Optional[Logger] = None, config: Optional["LangSmithConfig"] = None
) -> None:
    """Log current LangSmith configuration status for debugging.

    Args:
        logger: Logger instance to use for logging.
        config: Optional LangSmithConfig from TOML configuration. Takes precedence over environment variables.
    """
    if not logger:
        return

    status_config = get_langsmith_config(config)
    if is_langsmith_enabled(config):
        project_info = (
            f" (project: {status_config['project']})" if status_config["project"] else ""
        )
        logger.info(f"LangSmith tracing is enabled{project_info}")
    else:
        logger.debug(f"LangSmith tracing is disabled - {status_config}")
