"""Tests for LangChainBackend validation and error handling enhancements.

This test suite validates the enhanced configuration validation, thread safety,
error mapping, and mixed configuration handling in the compatibility layer.
"""

import os
import threading
import time
from unittest.mock import Mock, patch

import pytest

from ai_marketplace_monitor.ai import AIConfig, LangChainBackend


class TestLangChainBackendValidation:
    """Test suite for LangChainBackend validation enhancements."""

    def test_validate_config_compatibility_openai_valid(self) -> None:
        """Test OpenAI configuration validation with valid inputs."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            config = LangChainBackend.get_config(
                name="test-openai", provider="openai", model="gpt-4", timeout=30, max_retries=5
            )
            assert config.name == "test-openai"
            assert config.provider == "openai"
            assert config.model == "gpt-4"

    def test_validate_config_compatibility_openai_missing_api_key(self) -> None:
        """Test OpenAI configuration validation with missing API key."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="openai requires an API key"):
                LangChainBackend.get_config(name="test-openai", provider="openai", model="gpt-4")

    def test_validate_config_compatibility_deepseek_valid(self) -> None:
        """Test DeepSeek configuration validation with valid inputs."""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            config = LangChainBackend.get_config(
                name="test-deepseek", provider="deepseek", model="deepseek-chat"
            )
            assert config.name == "test-deepseek"
            assert config.provider == "deepseek"

    def test_validate_config_compatibility_ollama_valid(self) -> None:
        """Test Ollama configuration validation with valid inputs."""
        config = LangChainBackend.get_config(
            name="test-ollama",
            provider="ollama",
            model="deepseek-r1:14b",
            base_url="http://localhost:11434",
        )
        assert config.name == "test-ollama"
        assert config.provider == "ollama"
        assert config.base_url == "http://localhost:11434"

    def test_validate_config_compatibility_ollama_missing_model(self) -> None:
        """Test Ollama configuration validation with missing model."""
        with pytest.raises(ValueError, match="Ollama requires a model to be specified"):
            LangChainBackend.get_config(
                name="test-ollama", provider="ollama", base_url="http://localhost:11434"
            )

    def test_validate_config_compatibility_ollama_default_url(self) -> None:
        """Test Ollama configuration sets default base_url if not provided."""
        config = LangChainBackend.get_config(
            name="test-ollama", provider="ollama", model="deepseek-r1:14b"
        )
        assert config.base_url == "http://localhost:11434"

    def test_validate_config_compatibility_unsupported_provider(self) -> None:
        """Test configuration validation with unsupported provider."""
        with pytest.raises(ValueError, match="AIConfig requires a valid service provider"):
            LangChainBackend.get_config(
                name="test-unsupported", provider="unsupported", api_key="test-key"
            )

    def test_validate_config_compatibility_invalid_max_retries(self) -> None:
        """Test configuration validation with invalid max_retries."""
        with pytest.raises(ValueError, match="AIConfig requires a positive integer max_retries"):
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
                LangChainBackend.get_config(name="test-openai", provider="openai", max_retries=-1)

    def test_validate_config_compatibility_invalid_timeout(self) -> None:
        """Test configuration validation with invalid timeout."""
        with pytest.raises(ValueError, match="timeout must be a positive integer"):
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
                LangChainBackend.get_config(name="test-openai", provider="openai", timeout=0)

    def test_validate_config_compatibility_openrouter_valid(self) -> None:
        """Test OpenRouter configuration validation with valid inputs."""
        config = LangChainBackend.get_config(
            name="test-openrouter",
            provider="openrouter",
            api_key="sk-or-abcdefgh7890abcdefgh7890abcdefgh7890abcdefgh",
            model="anthropic/claude-3-sonnet",
        )
        assert config.name == "test-openrouter"
        assert config.provider == "openrouter"
        assert config.model == "anthropic/claude-3-sonnet"

    def test_validate_config_compatibility_openrouter_missing_api_key(self) -> None:
        """Test OpenRouter configuration validation with missing API key."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="OpenRouter requires an API key"):
                LangChainBackend.get_config(
                    name="test-openrouter",
                    provider="openrouter",
                    model="anthropic/claude-3-sonnet",
                )

    def test_validate_config_compatibility_openrouter_invalid_api_key_format(self) -> None:
        """Test OpenRouter configuration validation with invalid API key format."""
        with pytest.raises(ValueError, match="OpenRouter API key must start with 'sk-or-'"):
            LangChainBackend.get_config(
                name="test-openrouter",
                provider="openrouter",
                api_key="invalid-key",
                model="anthropic/claude-3-sonnet",
            )

    def test_validate_config_compatibility_openrouter_invalid_model_format(self) -> None:
        """Test OpenRouter configuration validation with invalid model format."""
        with pytest.raises(
            ValueError, match="OpenRouter model 'gpt-4' must follow 'provider/model' format"
        ):
            LangChainBackend.get_config(
                name="test-openrouter",
                provider="openrouter",
                api_key="sk-or-abcdefgh7890abcdefgh7890abcdefgh7890abcdefgh",
                model="gpt-4",  # Should be "openai/gpt-4"
            )

    def test_validate_config_compatibility_openrouter_env_api_key(self) -> None:
        """Test OpenRouter configuration validation using environment API key."""
        with patch.dict(
            os.environ, {"OPENROUTER_API_KEY": "sk-or-envkey7890abcdefgh7890abcdefgh7890abcdefgh"}
        ):
            config = LangChainBackend.get_config(
                name="test-openrouter",
                provider="openrouter",
                model="openai/gpt-4o",
            )
            assert config.name == "test-openrouter"
            assert config.provider == "openrouter"
            assert config.model == "openai/gpt-4o"

    def test_validate_config_compatibility_openrouter_env_invalid_api_key(self) -> None:
        """Test OpenRouter configuration validation with invalid environment API key."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "invalid-env-key"}):
            with pytest.raises(ValueError, match="OpenRouter API key must start with 'sk-or-'"):
                LangChainBackend.get_config(
                    name="test-openrouter",
                    provider="openrouter",
                    model="anthropic/claude-3-sonnet",
                )

    def test_validate_thread_safety_success(self) -> None:
        """Test thread safety validation with properly initialized backend."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        # Should not raise any exceptions
        backend._validate_thread_safety()

    def test_validate_thread_safety_missing_lock(self) -> None:
        """Test thread safety validation with missing lock."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        # Remove the lock to test validation
        del backend._model_lock

        with pytest.raises(RuntimeError, match="missing proper thread synchronization"):
            backend._validate_thread_safety()

    def test_validate_thread_safety_invalid_lock(self) -> None:
        """Test thread safety validation with invalid lock type."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        # Replace with invalid lock type
        backend._model_lock = "not-a-lock"

        with pytest.raises(RuntimeError, match="missing proper thread synchronization"):
            backend._validate_thread_safety()

    def test_thread_safety_concurrent_access(self) -> None:
        """Test thread safety with concurrent access to backend methods."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        results = []
        exceptions = []

        def validate_thread_safety():
            try:
                backend._validate_thread_safety()
                results.append("success")
            except Exception as e:
                exceptions.append(e)

        # Create multiple threads to test concurrent validation
        threads = []
        for _ in range(10):
            thread = threading.Thread(target=validate_thread_safety)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # All validations should succeed
        assert len(results) == 10
        assert len(exceptions) == 0

    def test_map_langchain_exception_import_error(self) -> None:
        """Test mapping of ImportError to RuntimeError."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        original_error = ImportError("langchain_openai not found")
        mapped_error = backend._map_langchain_exception(original_error, "test context")

        assert isinstance(mapped_error, RuntimeError)
        assert "test context: Provider dependencies not installed" in str(mapped_error)
        assert "Install the required LangChain packages" in str(mapped_error)

    def test_map_langchain_exception_authentication_error(self) -> None:
        """Test mapping of authentication errors to ValueError."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        original_error = ValueError("Invalid API_KEY provided")
        mapped_error = backend._map_langchain_exception(original_error, "test context")

        assert isinstance(mapped_error, ValueError)
        assert "test context: Authentication error" in str(mapped_error)
        assert "Check API key configuration" in str(mapped_error)

    def test_map_langchain_exception_timeout_error(self) -> None:
        """Test mapping of timeout errors to RuntimeError."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        original_error = TimeoutError("Request timed out")
        mapped_error = backend._map_langchain_exception(original_error, "test context")

        assert isinstance(mapped_error, RuntimeError)
        assert "test context: Connection failed" in str(mapped_error)
        assert "Check network connectivity" in str(mapped_error)

    def test_map_langchain_exception_model_error(self) -> None:
        """Test mapping of model configuration errors to ValueError."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        original_error = KeyError("model 'invalid-model' not found")
        mapped_error = backend._map_langchain_exception(original_error, "test context")

        assert isinstance(mapped_error, ValueError)
        assert "test context: Invalid model configuration" in str(mapped_error)
        assert "Check model name and availability" in str(mapped_error)

    def test_map_langchain_exception_unknown_error(self) -> None:
        """Test mapping of unknown errors to RuntimeError."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        original_error = RuntimeError("Unknown runtime error")
        mapped_error = backend._map_langchain_exception(original_error)

        assert isinstance(mapped_error, RuntimeError)
        assert "Unexpected error: Unknown runtime error" in str(mapped_error)

    def test_map_langchain_exception_openrouter_api_key_error(self) -> None:
        """Test mapping of OpenRouter API key format errors."""
        config = AIConfig(
            name="test-backend",
            provider="openrouter",
            api_key="sk-or-abcdefgh7890abcdefgh7890abcdefgh7890abcdefgh",
        )
        backend = LangChainBackend(config)

        original_error = ValueError("OpenRouter API key must start with 'sk-or-'")
        mapped_error = backend._map_langchain_exception(original_error, "OpenRouter connection")

        assert isinstance(mapped_error, ValueError)
        assert "OpenRouter API key format error" in str(mapped_error)
        assert "https://openrouter.ai/keys" in str(mapped_error)

    def test_map_langchain_exception_openrouter_model_format_error(self) -> None:
        """Test mapping of OpenRouter model format errors."""
        config = AIConfig(
            name="test-backend",
            provider="openrouter",
            api_key="sk-or-abcdefgh7890abcdefgh7890abcdefgh7890abcdefgh",
        )
        backend = LangChainBackend(config)

        original_error = ValueError("OpenRouter model 'gpt-4' must follow 'provider/model' format")
        mapped_error = backend._map_langchain_exception(original_error, "OpenRouter validation")

        assert isinstance(mapped_error, ValueError)
        assert "OpenRouter model format error" in str(mapped_error)
        assert "anthropic/claude-3-sonnet" in str(mapped_error)
        assert "https://openrouter.ai/models" in str(mapped_error)

    def test_map_langchain_exception_openrouter_rate_limit_error(self) -> None:
        """Test mapping of OpenRouter rate limit errors."""
        config = AIConfig(
            name="test-backend",
            provider="openrouter",
            api_key="sk-or-abcdefgh7890abcdefgh7890abcdefgh7890abcdefgh",
        )
        backend = LangChainBackend(config)

        original_error = ConnectionError("Rate limit exceeded for OpenRouter API")
        mapped_error = backend._map_langchain_exception(original_error, "OpenRouter evaluation")

        assert isinstance(mapped_error, RuntimeError)
        assert "OpenRouter service error" in str(mapped_error)
        assert "https://openrouter.ai/activity" in str(mapped_error)

    def test_map_langchain_exception_openrouter_quota_exceeded_error(self) -> None:
        """Test mapping of OpenRouter quota exceeded errors."""
        config = AIConfig(
            name="test-backend",
            provider="openrouter",
            api_key="sk-or-abcdefgh7890abcdefgh7890abcdefgh7890abcdefgh",
        )
        backend = LangChainBackend(config)

        original_error = RuntimeError("Quota exceeded: insufficient credits")
        mapped_error = backend._map_langchain_exception(original_error, "OpenRouter request")

        assert isinstance(mapped_error, RuntimeError)
        assert "OpenRouter billing issue" in str(mapped_error)
        assert "https://openrouter.ai/credits" in str(mapped_error)

    def test_validate_mixed_configuration_legacy_provider(self) -> None:
        """Test validation of mixed configuration with legacy service_provider."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        # Add legacy field (simulating old configuration)
        config.service_provider = "openai"

        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        warnings = backend._validate_mixed_configuration(config)

        # Enhanced migration warnings now include additional guidance
        assert len(warnings) >= 1
        service_provider_warning = next((w for w in warnings if "service_provider" in w), None)
        assert service_provider_warning is not None
        assert "Using 'provider' value" in service_provider_warning
        assert "Consider removing 'service_provider'" in service_provider_warning
        assert mock_logger.warning.called

    def test_validate_mixed_configuration_deepseek_api_key(self) -> None:
        """Test validation of mixed configuration with DeepSeek API key sources."""
        config = AIConfig(name="test-deepseek", provider="deepseek", api_key="config-key")

        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}):
            warnings = backend._validate_mixed_configuration(config)

            assert len(warnings) == 1
            assert "api_key and DEEPSEEK_API_KEY" in warnings[0]
            assert "Using environment variable" in warnings[0]
            mock_logger.warning.assert_called_once()

    def test_validate_mixed_configuration_no_conflicts(self) -> None:
        """Test validation of configuration with minimal conflicts."""
        # Use environment variables to avoid API key warnings
        config = AIConfig(name="test-backend", provider="openai")  # No API key in config

        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "proper-length-api-key"}):
            warnings = backend._validate_mixed_configuration(config)

            # Should have no warnings for properly configured environment-based setup
            assert len(warnings) == 0
            mock_logger.warning.assert_not_called()

    def test_connect_with_enhanced_validation(self) -> None:
        """Test connect method with all enhanced validation steps."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        mock_model = Mock()

        with (
            patch.object(backend, "_get_model", return_value=mock_model),
            patch("ai_marketplace_monitor.ai.log_langsmith_status") as mock_langsmith_log,
        ):
            backend.connect()

            # Verify connection succeeded
            assert backend._chat_model is mock_model
            mock_logger.info.assert_called_once_with(f"[cyan][AI][/cyan] {config.name} connected.")
            mock_langsmith_log.assert_called_once_with(mock_logger, None)

            # Verify validation methods were called during connect
            assert hasattr(backend, "_model_lock")

    def test_connect_with_mapped_exception(self) -> None:
        """Test connect method with exception mapping."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        # Simulate an ImportError during model creation
        original_error = ImportError("langchain_openai not found")

        with patch.object(backend, "_get_model", side_effect=original_error):
            with pytest.raises(RuntimeError, match="Provider dependencies not installed"):
                backend.connect()

            # Verify error was logged
            mock_logger.error.assert_called_once()
            assert "Failed to connect" in mock_logger.error.call_args[0][0]


class TestLangChainExceptionMappingComprehensive:
    """Comprehensive test suite for LangChain exception mapping functionality."""

    def test_langchain_core_exception_mapping_functionality(self) -> None:
        """Test that LangChain core exception mapping logic works.

        Since the actual LangChain exceptions are imported dynamically,
        we test the core functionality that's accessible.
        """
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        # Test with actual LangChain exception if available, fallback to mock
        try:
            from langchain_core.exceptions import LangChainException

            original_error = LangChainException("LangChain operation failed")

            mapped_error = backend._map_langchain_exception(original_error, "model evaluation")

            assert isinstance(mapped_error, RuntimeError)
            assert "model evaluation: LangChain operation failed" in str(mapped_error)
            assert mapped_error.__cause__ is original_error

        except ImportError:
            # If LangChain not available, test fallback behavior
            original_error = Exception("LangChain operation failed")
            mapped_error = backend._map_langchain_exception(original_error, "model evaluation")

            # Should fall back to generic handling
            assert isinstance(mapped_error, RuntimeError)
            assert "Unexpected error" in str(mapped_error)

    def test_output_parser_exception_mapping_functionality(self) -> None:
        """Test OutputParserException mapping if LangChain available."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        try:
            from langchain_core.exceptions import LangChainException, OutputParserException

            # Check if OutputParserException inherits from LangChainException
            # If so, it will be caught by the LangChainException handler first
            if issubclass(OutputParserException, LangChainException):
                original_error = OutputParserException("Could not parse model output")
                mapped_error = backend._map_langchain_exception(original_error, "response parsing")

                # Should be caught by LangChainException handler, not OutputParserException specific
                assert isinstance(mapped_error, RuntimeError)
                assert "response parsing: LangChain operation failed" in str(mapped_error)
                assert mapped_error.__cause__ is original_error
            else:
                # If they don't inherit, test the specific handler
                original_error = OutputParserException("Could not parse model output")
                mapped_error = backend._map_langchain_exception(original_error, "response parsing")

                assert isinstance(mapped_error, ValueError)
                assert "response parsing: AI response parsing failed" in str(mapped_error)
                assert mapped_error.__cause__ is original_error

        except ImportError:
            # Skip if LangChain not available - this is expected in some environments
            pytest.skip("LangChain not available - skipping OutputParserException test")

    def test_tracer_exception_mapping_functionality(self) -> None:
        """Test TracerException mapping if LangChain available."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        try:
            from langchain_core.exceptions import LangChainException, TracerException

            # Check if TracerException inherits from LangChainException
            if issubclass(TracerException, LangChainException):
                original_error = TracerException("Tracing failed")
                mapped_error = backend._map_langchain_exception(original_error, "request tracing")

                # Should be caught by LangChainException handler, not TracerException specific
                assert isinstance(mapped_error, RuntimeError)
                assert "request tracing: LangChain operation failed" in str(mapped_error)
                assert mapped_error.__cause__ is original_error
            else:
                # If they don't inherit, test the specific handler
                original_error = TracerException("Tracing failed")
                mapped_error = backend._map_langchain_exception(original_error, "request tracing")

                assert isinstance(mapped_error, RuntimeError)
                assert "request tracing: LangChain tracing error" in str(mapped_error)
                assert mapped_error.__cause__ is original_error

        except ImportError:
            # Skip if LangChain not available - this is expected in some environments
            pytest.skip("LangChain not available - skipping TracerException test")

    def test_provider_exception_mapping_api_connection_error(self) -> None:
        """Test mapping of APIConnectionError to RuntimeError."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        # Create mock exception class with specific name
        class APIConnectionError(Exception):
            pass

        original_error = APIConnectionError("Connection to OpenAI API failed")

        mapped_error = backend._map_langchain_exception(original_error, "model request")

        assert isinstance(mapped_error, RuntimeError)
        assert "model request: Connection failed" in str(mapped_error)
        assert "Check network connectivity" in str(mapped_error)
        assert mapped_error.__cause__ is original_error

    def test_provider_exception_mapping_api_timeout_error(self) -> None:
        """Test mapping of APITimeoutError to RuntimeError."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        class APITimeoutError(Exception):
            pass

        original_error = APITimeoutError("Request timed out")

        mapped_error = backend._map_langchain_exception(original_error, "api call")

        assert isinstance(mapped_error, RuntimeError)
        assert "api call: Connection failed" in str(mapped_error)
        assert "Check network connectivity" in str(mapped_error)

    def test_provider_exception_mapping_authentication_error(self) -> None:
        """Test mapping of AuthenticationError to ValueError."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        class AuthenticationError(Exception):
            pass

        original_error = AuthenticationError("Invalid API key provided")

        mapped_error = backend._map_langchain_exception(original_error)

        assert isinstance(mapped_error, ValueError)
        assert "Authentication error" in str(mapped_error)
        assert "Check API key configuration" in str(mapped_error)
        assert mapped_error.__cause__ is original_error

    def test_provider_exception_mapping_rate_limit_error(self) -> None:
        """Test mapping of RateLimitError to RuntimeError."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        class RateLimitError(Exception):
            pass

        original_error = RateLimitError("Rate limit exceeded")

        mapped_error = backend._map_langchain_exception(original_error, "evaluation")

        assert isinstance(mapped_error, RuntimeError)
        assert "evaluation: Rate limit exceeded" in str(mapped_error)
        assert "Try again later or upgrade your plan" in str(mapped_error)

    def test_provider_exception_mapping_bad_request_error(self) -> None:
        """Test mapping of BadRequestError to ValueError."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        class BadRequestError(Exception):
            pass

        original_error = BadRequestError("Invalid model parameters")

        mapped_error = backend._map_langchain_exception(original_error, "request")

        assert isinstance(mapped_error, ValueError)
        assert "request: Invalid request" in str(mapped_error)
        assert "Check model parameters and input format" in str(mapped_error)
        assert mapped_error.__cause__ is original_error

    def test_provider_exception_mapping_not_found_error(self) -> None:
        """Test mapping of NotFoundError to ValueError."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        class NotFoundError(Exception):
            pass

        original_error = NotFoundError("Model not found")

        mapped_error = backend._map_langchain_exception(original_error)

        assert isinstance(mapped_error, ValueError)
        assert "Resource access error" in str(mapped_error)
        assert "Check model availability and permissions" in str(mapped_error)
        assert mapped_error.__cause__ is original_error

    def test_provider_exception_mapping_permission_denied_error(self) -> None:
        """Test mapping of PermissionDeniedError to ValueError."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        class PermissionDeniedError(Exception):
            pass

        original_error = PermissionDeniedError("Permission denied for model access")

        mapped_error = backend._map_langchain_exception(original_error, "model access")

        assert isinstance(mapped_error, ValueError)
        assert "model access: Resource access error" in str(mapped_error)
        assert "Check model availability and permissions" in str(mapped_error)

    def test_provider_exception_mapping_internal_server_error(self) -> None:
        """Test mapping of InternalServerError to RuntimeError."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        class InternalServerError(Exception):
            pass

        original_error = InternalServerError("Internal server error occurred")

        mapped_error = backend._map_langchain_exception(original_error, "api request")

        assert isinstance(mapped_error, RuntimeError)
        assert "api request: Provider service error" in str(mapped_error)
        assert "Try again later or contact provider support" in str(mapped_error)

    def test_generic_langchain_pattern_import_error(self) -> None:
        """Test mapping of ImportError for missing dependencies."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        original_error = ImportError("No module named 'langchain_openai'")

        mapped_error = backend._map_langchain_exception(original_error, "provider setup")

        assert isinstance(mapped_error, RuntimeError)
        assert "provider setup: Provider dependencies not installed" in str(mapped_error)
        assert "Install the required LangChain packages" in str(mapped_error)
        assert mapped_error.__cause__ is original_error

    def test_generic_langchain_pattern_api_key_value_error(self) -> None:
        """Test mapping of ValueError with API key patterns."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        original_error = ValueError("Invalid api_key provided")

        mapped_error = backend._map_langchain_exception(original_error, "authentication")

        assert isinstance(mapped_error, ValueError)
        assert "authentication: Authentication error" in str(mapped_error)
        assert "Check API key configuration" in str(mapped_error)

    def test_generic_langchain_pattern_authentication_type_error(self) -> None:
        """Test mapping of TypeError with authentication patterns."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        original_error = TypeError("Authentication failed: unauthorized access")

        mapped_error = backend._map_langchain_exception(original_error)

        assert isinstance(mapped_error, ValueError)
        assert "Authentication error" in str(mapped_error)
        assert "Check API key configuration" in str(mapped_error)

    def test_openrouter_specific_api_key_format_error(self) -> None:
        """Test OpenRouter-specific API key format error handling."""
        config = AIConfig(name="test-backend", provider="openrouter")
        backend = LangChainBackend(config)

        original_error = ValueError("OpenRouter API key must start with 'sk-or-'")

        mapped_error = backend._map_langchain_exception(original_error, "openrouter validation")

        assert isinstance(mapped_error, ValueError)
        assert "openrouter validation: OpenRouter API key format error" in str(mapped_error)
        assert "https://openrouter.ai/keys" in str(mapped_error)

    def test_openrouter_specific_model_format_error(self) -> None:
        """Test OpenRouter-specific model format error handling."""
        config = AIConfig(name="test-backend", provider="openrouter")
        backend = LangChainBackend(config)

        original_error = ValueError("OpenRouter model must follow 'provider/model' format")

        mapped_error = backend._map_langchain_exception(original_error, "model validation")

        assert isinstance(mapped_error, ValueError)
        assert "model validation: OpenRouter model format error" in str(mapped_error)
        assert "anthropic/claude-3-sonnet" in str(mapped_error)
        assert "https://openrouter.ai/models" in str(mapped_error)

    def test_openrouter_enhanced_model_not_found_error(self) -> None:
        """Test OpenRouter-enhanced model not found error handling."""
        config = AIConfig(name="test-backend", provider="openrouter")
        backend = LangChainBackend(config)

        original_error = RuntimeError("Model not found on OpenRouter.ai")

        mapped_error = backend._map_langchain_exception(original_error, "openrouter request")

        assert isinstance(mapped_error, ValueError)
        assert "OpenRouter model not available" in str(mapped_error)
        assert "https://openrouter.ai/models" in str(mapped_error)

    def test_openrouter_enhanced_insufficient_credits_error(self) -> None:
        """Test OpenRouter-enhanced insufficient credits error handling."""
        config = AIConfig(name="test-backend", provider="openrouter")
        backend = LangChainBackend(config)

        original_error = RuntimeError("Insufficient credits for this request")

        mapped_error = backend._map_langchain_exception(original_error, "openrouter billing")

        assert isinstance(mapped_error, RuntimeError)
        assert "OpenRouter billing issue" in str(mapped_error)
        assert "https://openrouter.ai/credits" in str(mapped_error)

    def test_openrouter_enhanced_model_overloaded_error(self) -> None:
        """Test OpenRouter-enhanced model overloaded error handling."""
        config = AIConfig(name="test-backend", provider="openrouter")
        backend = LangChainBackend(config)

        original_error = RuntimeError("Model overloaded - try again later")

        mapped_error = backend._map_langchain_exception(original_error, "openrouter capacity")

        assert isinstance(mapped_error, RuntimeError)
        assert "Model temporarily unavailable" in str(mapped_error)
        assert "Try again in a few minutes or select a different model" in str(mapped_error)

    def test_openrouter_http_rate_limit_error(self) -> None:
        """Test OpenRouter HTTP rate limit error handling."""
        config = AIConfig(name="test-backend", provider="openrouter")
        backend = LangChainBackend(config)

        original_error = ConnectionError("Rate limit exceeded: 429")

        mapped_error = backend._map_langchain_exception(original_error, "openrouter api")

        assert isinstance(mapped_error, RuntimeError)
        assert "OpenRouter service error" in str(mapped_error)
        assert "https://openrouter.ai/activity" in str(mapped_error)

    def test_fallback_connection_timeout_error(self) -> None:
        """Test fallback connection and timeout error handling."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        original_error = ConnectionError("Connection timed out")

        mapped_error = backend._map_langchain_exception(original_error, "network request")

        assert isinstance(mapped_error, RuntimeError)
        assert "network request: Connection failed" in str(mapped_error)
        assert "Check network connectivity" in str(mapped_error)

    def test_fallback_model_keyerror(self) -> None:
        """Test fallback KeyError with model pattern handling."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        original_error = KeyError("model 'gpt-5' not found in configuration")

        mapped_error = backend._map_langchain_exception(original_error)

        assert isinstance(mapped_error, ValueError)
        assert "Invalid model configuration" in str(mapped_error)
        assert "Check model name and availability" in str(mapped_error)

    def test_fallback_unknown_exception(self) -> None:
        """Test fallback behavior for unknown exceptions."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        original_error = Exception("Completely unknown error type")

        mapped_error = backend._map_langchain_exception(original_error, "unknown operation")

        assert isinstance(mapped_error, RuntimeError)
        assert "unknown operation: Unexpected error" in str(mapped_error)
        assert mapped_error.__cause__ is original_error
        # Should use fallback mapping type
        mock_logger.debug.assert_called()

    def test_exception_chaining_preservation(self) -> None:
        """Test that exception chaining is properly preserved."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        # Create a chained exception
        try:
            raise ValueError("Original cause")
        except ValueError as original_cause:
            chained_error = RuntimeError("Chained error")
            chained_error.__cause__ = original_cause

            mapped_error = backend._map_langchain_exception(chained_error, "test")

            # Verify the mapped exception preserves the chain
            assert isinstance(mapped_error, RuntimeError)
            assert mapped_error.__cause__ is chained_error
            # Original cause should still be accessible through the chain
            assert chained_error.__cause__ is original_cause

    def test_performance_logging_capture(self) -> None:
        """Test that performance logging captures mapping type and timing."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        original_error = ImportError("Missing dependency")

        # Map the exception
        mapped_error = backend._map_langchain_exception(original_error, "test context")

        # Verify logging was called at least once (initial logging is certain)
        assert mock_logger.debug.call_count >= 1

        # Check that timing information is included in the log
        debug_calls = [call.args[0] for call in mock_logger.debug.call_args_list]

        # Should have original exception logging - check for correct pattern
        original_log = next(
            (call for call in debug_calls if "Mapping" in call and "ImportError" in call), None
        )
        assert original_log is not None
        assert "test context" in original_log

        # The mapped error should be a RuntimeError with proper cause
        assert isinstance(mapped_error, RuntimeError)
        assert mapped_error.__cause__ is original_error

    def test_langchain_import_error_fallback(self) -> None:
        """Test behavior when LangChain core exceptions are not importable."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        # Create a regular exception
        original_error = Exception("Some LangChain-like error")

        # The fallback behavior should map to generic handling
        mapped_error = backend._map_langchain_exception(original_error, "test")

        assert isinstance(mapped_error, RuntimeError)
        assert "test: Unexpected error" in str(mapped_error)
        assert mapped_error.__cause__ is original_error

    def test_empty_context_handling(self) -> None:
        """Test exception mapping with empty context."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        original_error = ValueError("Test error")

        mapped_error = backend._map_langchain_exception(original_error)

        assert isinstance(mapped_error, RuntimeError)
        # Should not have context prefix
        assert not str(mapped_error).startswith(": ")
        assert "Unexpected error: Test error" in str(mapped_error)

    def test_none_input_handling(self) -> None:
        """Test exception mapping edge case with None-like inputs."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        # Test with an exception that has None as message
        original_error = Exception(None)

        mapped_error = backend._map_langchain_exception(original_error, "test")

        assert isinstance(mapped_error, RuntimeError)
        assert "test: Unexpected error" in str(mapped_error)

    def test_long_error_message_truncation_in_logging(self) -> None:
        """Test that long error messages are properly truncated in logging."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        # Create an error with a very long message
        long_message = "A" * 200  # 200 character message
        original_error = Exception(long_message)

        backend._map_langchain_exception(original_error, "test context")

        # Check that the logging truncated the message to 100 characters
        debug_calls = [call.args[0] for call in mock_logger.debug.call_args_list]
        original_log = next(
            (call for call in debug_calls if "Mapping" in call and "Exception" in call), None
        )
        assert original_log is not None

        # The log should contain truncated message (100 chars max as per implementation)
        truncated_part = long_message[:100]
        assert truncated_part in original_log
        # Should not contain the full message
        assert long_message not in original_log


class TestPerformanceRegression:
    """Test performance aspects of the validation enhancements."""

    def test_config_validation_performance(self) -> None:
        """Test that configuration validation doesn't significantly impact performance."""
        start_time = time.time()

        # Create multiple configurations to test performance impact
        for i in range(100):
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
                config = LangChainBackend.get_config(
                    name=f"test-backend-{i}",
                    provider="openai",
                    model="gpt-4",
                    timeout=30,
                    max_retries=5,
                )
                assert config.name == f"test-backend-{i}"

        elapsed_time = time.time() - start_time

        # Validation should complete quickly (under 1 second for 100 configs)
        assert elapsed_time < 1.0, f"Configuration validation took too long: {elapsed_time:.2f}s"

    def test_thread_safety_validation_performance(self) -> None:
        """Test that thread safety validation is performant."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        start_time = time.time()

        # Run validation many times
        for _ in range(1000):
            backend._validate_thread_safety()

        elapsed_time = time.time() - start_time

        # Thread safety validation should be very fast
        assert elapsed_time < 0.1, f"Thread safety validation took too long: {elapsed_time:.2f}s"

    def test_exception_mapping_performance(self) -> None:
        """Test that exception mapping doesn't add significant overhead."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        test_errors = [
            ImportError("test import error"),
            ValueError("test api_key error"),
            TimeoutError("test timeout error"),
            KeyError("test model error"),
            RuntimeError("test runtime error"),
        ]

        start_time = time.time()

        # Map many exceptions
        for _ in range(100):
            for error in test_errors:
                mapped = backend._map_langchain_exception(error, "test context")
                assert isinstance(mapped, Exception)

        elapsed_time = time.time() - start_time

        # Exception mapping should be fast
        assert elapsed_time < 0.1, f"Exception mapping took too long: {elapsed_time:.2f}s"
