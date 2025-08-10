"""Tests for ProviderInterface abstract base class compliance."""

from typing import Any, Dict
from unittest.mock import Mock

import pytest
from langchain_core.language_models import BaseChatModel

from ai_marketplace_monitor.ai import AIConfig, AIResponse
from ai_marketplace_monitor.provider_interface import ProviderInterface


class CompleteProviderMock(ProviderInterface):
    """Mock subclass implementing all abstract methods for testing."""

    def get_model(self: "CompleteProviderMock", config: AIConfig) -> BaseChatModel:
        """Mock implementation returning a mock LangChain model."""
        mock_model = Mock(spec=BaseChatModel)
        return mock_model

    def map_config(self: "CompleteProviderMock", config: AIConfig) -> Dict[str, Any]:
        """Mock implementation returning mapped config parameters."""
        return {
            "api_key": config.api_key,
            "model": config.model,
            "base_url": config.base_url,
            "timeout": config.timeout,
        }

    def handle_errors(self: "CompleteProviderMock", error: Exception) -> Exception:
        """Mock implementation returning the error as-is."""
        return error

    def adapt_response(self: "CompleteProviderMock", langchain_response: Any) -> AIResponse:
        """Mock implementation returning a test AIResponse."""
        return AIResponse(score=4, comment="Mock response", name="test")


class IncompleteProviderMock(ProviderInterface):
    """Mock subclass missing abstract methods to test enforcement."""

    def get_model(self: "IncompleteProviderMock", config: AIConfig) -> BaseChatModel:
        """Only implements get_model, missing other required methods."""
        mock_model = Mock(spec=BaseChatModel)
        return mock_model

    # Intentionally missing: map_config, handle_errors, adapt_response


class PartialProviderMock(ProviderInterface):
    """Mock subclass missing multiple abstract methods."""

    def get_model(self: "PartialProviderMock", config: AIConfig) -> BaseChatModel:
        """Implements get_model."""
        mock_model = Mock(spec=BaseChatModel)
        return mock_model

    def map_config(self: "PartialProviderMock", config: AIConfig) -> Dict[str, Any]:
        """Implements map_config."""
        return {"api_key": config.api_key}

    # Intentionally missing: handle_errors, adapt_response


def test_complete_provider_instantiation() -> None:
    """Test that complete provider implementation instantiates successfully."""
    provider = CompleteProviderMock()
    assert isinstance(provider, ProviderInterface)
    assert isinstance(provider, CompleteProviderMock)


def test_incomplete_provider_raises_typeerror() -> None:
    """Test that incomplete provider implementation raises TypeError on instantiation."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        IncompleteProviderMock()  # type: ignore


def test_partial_provider_raises_typeerror() -> None:
    """Test that partially implemented provider raises TypeError on instantiation."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        PartialProviderMock()  # type: ignore


def test_complete_provider_method_calls() -> None:
    """Test that all abstract methods can be called on complete implementation."""
    provider = CompleteProviderMock()
    config = AIConfig(name="test-config", api_key="test", provider="OpenAI", model="test-model")

    # Test get_model
    model = provider.get_model(config)
    assert model is not None

    # Test map_config
    mapped = provider.map_config(config)
    assert isinstance(mapped, dict)
    assert mapped["api_key"] == "test"

    # Test handle_errors
    test_error = ValueError("test error")
    handled_error = provider.handle_errors(test_error)
    assert handled_error is test_error

    # Test adapt_response
    mock_response = {"content": "test response"}
    ai_response = provider.adapt_response(mock_response)
    assert isinstance(ai_response, AIResponse)
    assert ai_response.score == 4
    assert ai_response.comment == "Mock response"


def test_provider_interface_is_abstract() -> None:
    """Test that ProviderInterface itself cannot be instantiated."""
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        ProviderInterface()  # type: ignore
