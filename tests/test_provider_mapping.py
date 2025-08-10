"""Tests for provider mapping system in ai.py."""

import os
from unittest.mock import patch

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_deepseek import ChatDeepSeek
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from ai_marketplace_monitor.ai import (
    AIConfig,
    _create_deepseek_model,
    _create_ollama_model,
    _create_openai_model,
    _create_openrouter_model,
    provider_map,
)


class TestProviderMapping:
    """Test provider mapping functions."""

    def test_provider_map_contains_all_providers(self) -> None:
        """Test that provider_map contains all expected provider keys."""
        expected_providers = {"openai", "deepseek", "ollama", "openrouter"}
        assert set(provider_map.keys()) == expected_providers

    def test_provider_map_functions_are_callable(self) -> None:
        """Test that all provider_map values are callable functions."""
        for provider, func in provider_map.items():
            assert callable(func), f"Provider {provider} mapping is not callable"


class TestOpenAIProviderMapping:
    """Test OpenAI provider mapping function."""

    def test_create_openai_model_with_full_config(self) -> None:
        """Test creating OpenAI model with all config parameters."""
        config = AIConfig(
            name="test-openai",
            api_key="test-key",
            provider="openai",
            model="gpt-4",
            base_url="https://custom.openai.com",
            timeout=60,
            max_retries=5,
        )

        model = _create_openai_model(config)

        assert isinstance(model, ChatOpenAI)
        assert model.openai_api_key.get_secret_value() == "test-key"  # type: ignore
        assert model.model_name == "gpt-4"
        assert model.openai_api_base == "https://custom.openai.com"
        assert model.request_timeout == 60
        assert model.max_retries == 5

    def test_create_openai_model_with_defaults(self) -> None:
        """Test creating OpenAI model with minimal config and defaults."""
        config = AIConfig(name="test-openai", api_key="test-key", provider="openai")

        model = _create_openai_model(config)

        assert isinstance(model, ChatOpenAI)
        assert model.openai_api_key.get_secret_value() == "test-key"  # type: ignore
        assert model.model_name == "gpt-4o"  # Default model

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-env-key"})
    def test_create_openai_model_with_env_fallback(self) -> None:
        """Test OpenAI model creation falls back to environment variable."""
        config = AIConfig(name="test-openai", provider="openai")  # No api_key

        model = _create_openai_model(config)

        assert isinstance(model, ChatOpenAI)
        assert model.openai_api_key.get_secret_value() == "test-env-key"  # type: ignore

    def test_provider_map_openai_integration(self) -> None:
        """Test that provider_map['openai'] works correctly."""
        config = AIConfig(name="test", api_key="test-key", provider="openai")

        model = provider_map["openai"](config)

        assert isinstance(model, ChatOpenAI)


class TestOpenRouterProviderMapping:
    """Test OpenRouter provider mapping function."""

    def test_create_openrouter_model_with_full_config(self) -> None:
        """Test creating OpenRouter model with all config parameters."""
        config = AIConfig(
            name="test-openrouter",
            api_key="test-key",
            provider="openrouter",
            model="openai/gpt-4",
            base_url="https://custom.openrouter.ai/api/v1",
            timeout=60,
            max_retries=5,
        )

        model = _create_openrouter_model(config)

        assert isinstance(model, ChatOpenAI)
        assert model.openai_api_key.get_secret_value() == "test-key"  # type: ignore
        assert model.model_name == "openai/gpt-4"
        assert model.openai_api_base == "https://custom.openrouter.ai/api/v1"
        assert model.request_timeout == 60
        assert model.max_retries == 5

    def test_create_openrouter_model_with_defaults(self) -> None:
        """Test creating OpenRouter model with minimal config and defaults."""
        config = AIConfig(name="test-openrouter", api_key="test-key", provider="openrouter")

        model = _create_openrouter_model(config)

        assert isinstance(model, ChatOpenAI)
        assert model.openai_api_key.get_secret_value() == "test-key"  # type: ignore
        assert model.model_name == "anthropic/claude-3-sonnet"  # Default model
        assert model.openai_api_base == "https://openrouter.ai/api/v1"  # Default base URL

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-env-key"})
    def test_create_openrouter_model_with_env_fallback(self) -> None:
        """Test OpenRouter model creation falls back to environment variable."""
        config = AIConfig(name="test-openrouter", provider="openrouter")  # No api_key

        model = _create_openrouter_model(config)

        assert isinstance(model, ChatOpenAI)
        assert model.openai_api_key.get_secret_value() == "test-env-key"  # type: ignore

    def test_provider_map_openrouter_integration(self) -> None:
        """Test that provider_map['openrouter'] works correctly."""
        config = AIConfig(name="test", api_key="test-key", provider="openrouter")

        model = provider_map["openrouter"](config)

        assert isinstance(model, ChatOpenAI)


class TestDeepSeekProviderMapping:
    """Test DeepSeek provider mapping function."""

    def test_create_deepseek_model_with_full_config(self) -> None:
        """Test creating DeepSeek model with all config parameters."""
        config = AIConfig(
            name="test-deepseek",
            api_key="test-key",
            provider="deepseek",
            model="deepseek-chat",
            timeout=60,
            max_retries=5,
        )

        model = _create_deepseek_model(config)

        assert isinstance(model, ChatDeepSeek)
        assert model.api_key.get_secret_value() == "test-key"  # type: ignore
        assert model.model_name == "deepseek-chat"
        assert model.request_timeout == 60
        assert model.max_retries == 5

    def test_create_deepseek_model_with_defaults(self) -> None:
        """Test creating DeepSeek model with minimal config and defaults."""
        config = AIConfig(name="test-deepseek", api_key="test-key", provider="deepseek")

        model = _create_deepseek_model(config)

        assert isinstance(model, ChatDeepSeek)
        assert model.api_key.get_secret_value() == "test-key"  # type: ignore
        assert model.model_name == "deepseek-chat"  # Default model

    @patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"})
    def test_create_deepseek_model_with_env_fallback(self) -> None:
        """Test DeepSeek model creation falls back to environment variable."""
        config = AIConfig(name="test-deepseek", provider="deepseek")  # No api_key

        model = _create_deepseek_model(config)

        assert isinstance(model, ChatDeepSeek)
        assert model.api_key.get_secret_value() == "env-key"  # type: ignore

    def test_provider_map_deepseek_integration(self) -> None:
        """Test that provider_map['deepseek'] works correctly."""
        config = AIConfig(name="test", api_key="test-key", provider="deepseek")

        model = provider_map["deepseek"](config)

        assert isinstance(model, ChatDeepSeek)


class TestOllamaProviderMapping:
    """Test Ollama provider mapping function."""

    def test_create_ollama_model_with_full_config(self) -> None:
        """Test creating Ollama model with all config parameters."""
        config = AIConfig(
            name="test-ollama",
            provider="ollama",
            model="deepseek-r1:14b",
            base_url="http://localhost:11434",
            timeout=60,
        )

        model = _create_ollama_model(config)

        assert isinstance(model, ChatOllama)
        assert model.model == "deepseek-r1:14b"
        assert model.base_url == "http://localhost:11434"
        assert model.client_kwargs == {"timeout": 60}
        assert model.num_ctx == 4096  # Default context length

    def test_create_ollama_model_with_defaults(self) -> None:
        """Test creating Ollama model with minimal config and defaults."""
        config = AIConfig(name="test-ollama", provider="ollama")

        model = _create_ollama_model(config)

        assert isinstance(model, ChatOllama)
        assert model.model == "deepseek-r1:14b"  # Default model
        assert model.base_url == "http://localhost:11434"  # Default base URL
        assert model.num_ctx == 4096  # Default context length

    def test_provider_map_ollama_integration(self) -> None:
        """Test that provider_map['ollama'] works correctly."""
        config = AIConfig(name="test", provider="ollama")

        model = provider_map["ollama"](config)

        assert isinstance(model, ChatOllama)


class TestProviderMapIntegration:
    """Test complete provider_map integration."""

    def test_all_providers_return_basechatmodel(self) -> None:
        """Test that all provider mapping functions return BaseChatModel instances."""
        test_configs = {
            "openai": AIConfig(name="test", api_key="test-key", provider="OpenAI"),
            "deepseek": AIConfig(name="test", api_key="test-key", provider="DeepSeek"),
            "ollama": AIConfig(name="test", provider="Ollama"),
            "openrouter": AIConfig(name="test", api_key="test-key", provider="OpenRouter"),
        }

        for provider, config in test_configs.items():
            model = provider_map[provider](config)
            assert isinstance(
                model, BaseChatModel
            ), f"Provider {provider} did not return BaseChatModel"

    def test_provider_map_dynamic_access(self) -> None:
        """Test dynamic access to provider mapping functions."""
        config = AIConfig(name="test", api_key="test-key", provider="openai")

        # Test that we can dynamically access providers
        provider_name = "openai"
        assert provider_name in provider_map

        model = provider_map[provider_name](config)
        assert isinstance(model, ChatOpenAI)

    def test_unsupported_provider_raises_keyerror(self) -> None:
        """Test that accessing unsupported provider raises KeyError."""
        with pytest.raises(KeyError):
            provider_map["unsupported_provider"]
