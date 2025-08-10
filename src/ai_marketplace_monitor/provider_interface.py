"""Abstract provider interface for AI backends."""

from abc import ABC, abstractmethod
from typing import Any, Dict

from langchain_core.language_models import BaseChatModel

from .ai import AIConfig, AIResponse


class ProviderInterface(ABC):
    """Abstract base class defining the interface for all AI providers.

    This interface standardizes model retrieval, config mapping, error handling,
    and response adaptation across different AI providers in the LangChain migration.
    """

    @abstractmethod
    def get_model(self: "ProviderInterface", config: AIConfig) -> BaseChatModel:
        """Retrieve and configure a LangChain chat model for the given config.

        Args:
            config: The AIConfig containing provider-specific settings

        Returns:
            A configured LangChain BaseChatModel instance

        Raises:
            ValueError: If required config parameters are missing
            ConnectionError: If model initialization fails
        """
        pass

    @abstractmethod
    def map_config(self: "ProviderInterface", config: AIConfig) -> Dict[str, Any]:
        """Map AIConfig parameters to provider-specific LangChain model parameters.

        Args:
            config: The AIConfig to map

        Returns:
            Dictionary of LangChain model constructor parameters
        """
        pass

    @abstractmethod
    def handle_errors(self: "ProviderInterface", error: Exception) -> Exception:
        """Map provider-specific exceptions to standardized error types.

        Args:
            error: The original exception from the provider

        Returns:
            A standardized exception that maintains existing error patterns
        """
        pass

    @abstractmethod
    def adapt_response(self: "ProviderInterface", langchain_response: Any) -> AIResponse:
        """Convert LangChain response objects to AIResponse format.

        Args:
            langchain_response: The response object from LangChain model

        Returns:
            AIResponse object maintaining cache compatibility
        """
        pass
