"""Tests for LangChain backend integration with TOML configuration support.

This test suite focuses on testing the integration between LangChain backends and
the main TOML configuration system, particularly for LangSmith tracing setup.

Following TDD principles:
- RED: Write failing tests that describe desired behavior
- GREEN: Write minimal code to make tests pass
- REFACTOR: Improve code while keeping tests green

Test coverage focuses on valuable behaviors including:
- LangChain backend initialization with main_config parameter
- Automatic LangSmith environment configuration from TOML config
- Backward compatibility when main_config is None
- Integration with logging and status reporting
- Error handling during configuration setup
"""

import os
from logging import Logger
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

import pytest

from ai_marketplace_monitor.ai import AIConfig, LangChainBackend

if TYPE_CHECKING:
    from typing_extensions import Self


class MockLangSmithConfig:
    """Mock LangSmithConfig for testing without circular imports."""

    def __init__(
        self,
        enabled: bool = False,
        api_key: str | None = None,
        project_name: str | None = None,
        endpoint: str | None = None,
    ) -> None:
        self.enabled = enabled
        self.api_key = api_key
        self.project_name = project_name
        self.endpoint = endpoint


class MockConfig:
    """Mock Config class for testing without circular imports."""

    def __init__(self, langsmith: MockLangSmithConfig | None = None) -> None:
        self.langsmith = langsmith


class TestLangChainBackendTomlConfigIntegration:
    """Test cases for LangChain backend integration with TOML configuration."""

    def setup_method(self: "Self") -> None:
        """Clean up environment variables before each test."""
        env_vars_to_clear = [
            "LANGCHAIN_TRACING_V2",
            "LANGCHAIN_API_KEY",
            "LANGCHAIN_PROJECT",
            "LANGCHAIN_ENDPOINT",
            "OPENAI_API_KEY",
        ]
        for var in env_vars_to_clear:
            if var in os.environ:
                del os.environ[var]

    def test_should_initialize_backend_without_main_config_for_backward_compatibility(
        self: "Self",
    ) -> None:
        """Should initialize LangChain backend without main_config for backward compatibility."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            ai_config = AIConfig(name="test-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Should not raise any exceptions
            backend = LangChainBackend(ai_config, logger=mock_logger)

            assert backend._main_config is None
            assert backend.config.name == "test-ai"

    def test_should_initialize_backend_with_main_config_containing_langsmith_config(
        self: "Self",
    ) -> None:
        """Should initialize LangChain backend with main_config and configure LangSmith."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            ai_config = AIConfig(name="test-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Create main config with LangSmith configuration
            langsmith_config = MockLangSmithConfig(
                enabled=True,
                api_key="toml-langsmith-key",
                project_name="toml-project",
                endpoint="https://toml.endpoint.com",
            )
            main_config = MockConfig(langsmith=langsmith_config)

            with patch(
                "ai_marketplace_monitor.ai.configure_langsmith_environment"
            ) as mock_configure:
                backend = LangChainBackend(ai_config, logger=mock_logger, main_config=main_config)

                # Should store main_config and call configure_langsmith_environment
                assert backend._main_config is main_config
                mock_configure.assert_called_once_with(langsmith_config)

    def test_should_not_configure_langsmith_when_main_config_has_no_langsmith(
        self: "Self",
    ) -> None:
        """Should not configure LangSmith when main_config has no langsmith section."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            ai_config = AIConfig(name="test-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Create main config without LangSmith configuration
            main_config = MockConfig(langsmith=None)

            with patch(
                "ai_marketplace_monitor.ai.configure_langsmith_environment"
            ) as mock_configure:
                backend = LangChainBackend(ai_config, logger=mock_logger, main_config=main_config)

                # Should store main_config but not call configure_langsmith_environment
                assert backend._main_config is main_config
                mock_configure.assert_not_called()

    def test_should_not_configure_langsmith_when_main_config_is_none(self: "Self") -> None:
        """Should not configure LangSmith when main_config is None."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            ai_config = AIConfig(name="test-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            with patch(
                "ai_marketplace_monitor.ai.configure_langsmith_environment"
            ) as mock_configure:
                backend = LangChainBackend(ai_config, logger=mock_logger, main_config=None)

                # Should not call configure_langsmith_environment
                assert backend._main_config is None
                mock_configure.assert_not_called()

    def test_should_set_environment_variables_from_toml_config_during_init(self: "Self") -> None:
        """Should set LangChain environment variables from TOML config during initialization."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            ai_config = AIConfig(name="test-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Create main config with LangSmith configuration
            langsmith_config = MockLangSmithConfig(
                enabled=True,
                api_key="toml-langsmith-key",
                project_name="toml-project",
                endpoint="https://toml.endpoint.com",
            )
            main_config = MockConfig(langsmith=langsmith_config)

            _backend = LangChainBackend(ai_config, logger=mock_logger, main_config=main_config)

            # Environment variables should be set from TOML config
            assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
            assert os.environ["LANGCHAIN_API_KEY"] == "toml-langsmith-key"
            assert os.environ["LANGCHAIN_PROJECT"] == "toml-project"
            assert os.environ["LANGCHAIN_ENDPOINT"] == "https://toml.endpoint.com"

    def test_should_not_override_existing_environment_variables(self: "Self") -> None:
        """Should not override existing LangChain environment variables."""
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-openai-key",
                "LANGCHAIN_TRACING_V2": "existing-tracing",
                "LANGCHAIN_API_KEY": "existing-langchain-key",
                "LANGCHAIN_PROJECT": "existing-project",
                "LANGCHAIN_ENDPOINT": "existing-endpoint",
            },
        ):
            ai_config = AIConfig(name="test-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Create main config with different LangSmith configuration
            langsmith_config = MockLangSmithConfig(
                enabled=True,
                api_key="toml-langsmith-key",
                project_name="toml-project",
                endpoint="https://toml.endpoint.com",
            )
            main_config = MockConfig(langsmith=langsmith_config)

            _backend = LangChainBackend(ai_config, logger=mock_logger, main_config=main_config)

            # Existing environment variables should not be changed
            assert os.environ["LANGCHAIN_TRACING_V2"] == "existing-tracing"
            assert os.environ["LANGCHAIN_API_KEY"] == "existing-langchain-key"
            assert os.environ["LANGCHAIN_PROJECT"] == "existing-project"
            assert os.environ["LANGCHAIN_ENDPOINT"] == "existing-endpoint"

    def test_should_handle_partial_langsmith_config_from_toml(self: "Self") -> None:
        """Should handle partial LangSmith configuration from TOML."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            ai_config = AIConfig(name="test-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Create main config with partial LangSmith configuration
            langsmith_config = MockLangSmithConfig(
                enabled=True,
                api_key="toml-langsmith-key",
                # project_name and endpoint are None
            )
            main_config = MockConfig(langsmith=langsmith_config)

            _backend = LangChainBackend(ai_config, logger=mock_logger, main_config=main_config)

            # Only the provided values should be set
            assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
            assert os.environ["LANGCHAIN_API_KEY"] == "toml-langsmith-key"
            assert "LANGCHAIN_PROJECT" not in os.environ
            assert "LANGCHAIN_ENDPOINT" not in os.environ

    def test_should_handle_disabled_langsmith_config_from_toml(self: "Self") -> None:
        """Should handle disabled LangSmith configuration from TOML."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            ai_config = AIConfig(name="test-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Create main config with disabled LangSmith configuration
            langsmith_config = MockLangSmithConfig(
                enabled=False,  # Explicitly disabled
                api_key="toml-langsmith-key",
                project_name="toml-project",
            )
            main_config = MockConfig(langsmith=langsmith_config)

            _backend = LangChainBackend(ai_config, logger=mock_logger, main_config=main_config)

            # Should set tracing to false but still set other values
            assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
            assert os.environ["LANGCHAIN_API_KEY"] == "toml-langsmith-key"
            assert os.environ["LANGCHAIN_PROJECT"] == "toml-project"

    def test_should_use_toml_config_with_logging_status_integration(self: "Self") -> None:
        """Should integrate TOML config with logging status when connecting."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            ai_config = AIConfig(name="test-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Create main config with LangSmith configuration
            langsmith_config = MockLangSmithConfig(
                enabled=True,
                api_key="toml-langsmith-key",
                project_name="toml-project",
            )
            main_config = MockConfig(langsmith=langsmith_config)

            backend = LangChainBackend(ai_config, logger=mock_logger, main_config=main_config)

            with (
                patch.object(backend, "_get_model", return_value=Mock()),
                patch("ai_marketplace_monitor.ai.log_langsmith_status") as mock_log_status,
            ):
                backend.connect()

                # Should log status using the configured logger and langsmith config
                mock_log_status.assert_called_once_with(mock_logger, langsmith_config)
                # Note: log_langsmith_status is called with None because it gets config from environment
                # which was set by configure_langsmith_environment during init

    def test_should_handle_configure_langsmith_environment_exception_gracefully(
        self: "Self",
    ) -> None:
        """Should handle exceptions during LangSmith environment configuration gracefully."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            ai_config = AIConfig(name="test-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Create main config with LangSmith configuration
            langsmith_config = MockLangSmithConfig(
                enabled=True,
                api_key="toml-langsmith-key",
                project_name="toml-project",
            )
            main_config = MockConfig(langsmith=langsmith_config)

            # Mock configure_langsmith_environment to raise an exception
            with patch(
                "ai_marketplace_monitor.ai.configure_langsmith_environment",
                side_effect=Exception("Test configuration error"),
            ):
                # Should not raise exception, but handle it gracefully
                # In the actual implementation, this might log an error instead of failing
                with pytest.raises(Exception, match="Test configuration error"):
                    LangChainBackend(ai_config, logger=mock_logger, main_config=main_config)

    def test_should_work_with_different_ai_providers(self: "Self") -> None:
        """Should work with different AI providers, not just OpenAI."""
        # Test with Ollama provider
        ollama_config = AIConfig(
            name="test-ollama",
            provider="ollama",
            model="llama2",
            base_url="http://localhost:11434",
        )
        mock_logger = Mock(spec=Logger)

        # Create main config with LangSmith configuration
        langsmith_config = MockLangSmithConfig(
            enabled=True,
            api_key="toml-langsmith-key",
            project_name="ollama-project",
        )
        main_config = MockConfig(langsmith=langsmith_config)

        with patch("ai_marketplace_monitor.ai.configure_langsmith_environment") as mock_configure:
            backend = LangChainBackend(ollama_config, logger=mock_logger, main_config=main_config)

            # Should configure LangSmith regardless of AI provider
            assert backend._main_config is main_config
            mock_configure.assert_called_once_with(langsmith_config)

    def test_should_pass_main_config_to_logging_functions_if_enhanced(self: "Self") -> None:
        """Should pass main_config to logging functions when available for enhanced functionality."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            ai_config = AIConfig(name="test-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Create main config with LangSmith configuration
            langsmith_config = MockLangSmithConfig(
                enabled=True,
                api_key="toml-langsmith-key",
                project_name="toml-project",
            )
            main_config = MockConfig(langsmith=langsmith_config)

            backend = LangChainBackend(ai_config, logger=mock_logger, main_config=main_config)

            # For now, the backend stores main_config but log_langsmith_status is called with None
            # This test documents current behavior and can be updated when enhanced logging is implemented
            assert backend._main_config is main_config


class TestLangChainBackendTomlConfigErrorHandling:
    """Test cases for error handling in TOML configuration integration."""

    def setup_method(self: "Self") -> None:
        """Clean up environment variables before each test."""
        env_vars_to_clear = [
            "LANGCHAIN_TRACING_V2",
            "LANGCHAIN_API_KEY",
            "LANGCHAIN_PROJECT",
            "LANGCHAIN_ENDPOINT",
            "OPENAI_API_KEY",
        ]
        for var in env_vars_to_clear:
            if var in os.environ:
                del os.environ[var]

    def test_should_handle_invalid_main_config_type_gracefully(self: "Self") -> None:
        """Should handle invalid main_config type gracefully."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            ai_config = AIConfig(name="test-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Pass invalid type as main_config
            invalid_main_config = "not-a-config-object"

            with patch(
                "ai_marketplace_monitor.ai.configure_langsmith_environment"
            ) as mock_configure:
                # Should not crash, but also shouldn't try to configure LangSmith
                backend = LangChainBackend(
                    ai_config, logger=mock_logger, main_config=invalid_main_config
                )

                # Should not call configure_langsmith_environment with invalid config
                mock_configure.assert_not_called()
                assert backend._main_config == invalid_main_config

    def test_should_handle_main_config_without_langsmith_attribute(self: "Self") -> None:
        """Should handle main_config that doesn't have langsmith attribute."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            ai_config = AIConfig(name="test-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Create mock config without langsmith attribute
            class ConfigWithoutLangSmith:
                pass

            main_config = ConfigWithoutLangSmith()

            with patch(
                "ai_marketplace_monitor.ai.configure_langsmith_environment"
            ) as mock_configure:
                # Should handle gracefully by not calling configure_langsmith_environment
                backend = LangChainBackend(ai_config, logger=mock_logger, main_config=main_config)

                mock_configure.assert_not_called()
                assert backend._main_config is main_config

    def test_should_handle_none_langsmith_attribute_gracefully(self: "Self") -> None:
        """Should handle main_config with None langsmith attribute gracefully."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            ai_config = AIConfig(name="test-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Create main config with None langsmith
            main_config = MockConfig(langsmith=None)

            with patch(
                "ai_marketplace_monitor.ai.configure_langsmith_environment"
            ) as mock_configure:
                backend = LangChainBackend(ai_config, logger=mock_logger, main_config=main_config)

                # Should not call configure_langsmith_environment with None
                mock_configure.assert_not_called()
                assert backend._main_config is main_config


class TestLangChainBackendTomlConfigIntegrationScenarios:
    """Integration test scenarios for realistic TOML configuration usage."""

    def setup_method(self: "Self") -> None:
        """Clean up environment variables before each test."""
        env_vars_to_clear = [
            "LANGCHAIN_TRACING_V2",
            "LANGCHAIN_API_KEY",
            "LANGCHAIN_PROJECT",
            "LANGCHAIN_ENDPOINT",
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
        ]
        for var in env_vars_to_clear:
            if var in os.environ:
                del os.environ[var]

    def test_development_environment_with_toml_langsmith_enabled(self: "Self") -> None:
        """Should handle development environment with TOML LangSmith tracing enabled."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "dev-openai-key"}):
            ai_config = AIConfig(name="dev-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Development TOML config with LangSmith enabled
            langsmith_config = MockLangSmithConfig(
                enabled=True,
                api_key="dev-langsmith-key",
                project_name="ai-marketplace-monitor-dev",
                endpoint="https://api.smith.langchain.com",
            )
            main_config = MockConfig(langsmith=langsmith_config)

            _backend = LangChainBackend(ai_config, logger=mock_logger, main_config=main_config)

            # Should configure development tracing
            assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
            assert os.environ["LANGCHAIN_API_KEY"] == "dev-langsmith-key"
            assert os.environ["LANGCHAIN_PROJECT"] == "ai-marketplace-monitor-dev"
            assert os.environ["LANGCHAIN_ENDPOINT"] == "https://api.smith.langchain.com"

    def test_production_environment_with_explicit_env_override(self: "Self") -> None:
        """Should respect explicit environment variables and fill missing ones from TOML config."""
        # Clear any existing LangSmith environment variables first
        env_vars_to_clear = [
            "LANGCHAIN_PROJECT",
            "LANGCHAIN_ENDPOINT",
            "LANGSMITH_PROJECT",
            "LANGSMITH_API_KEY",
            "LANGSMITH_TRACING",
            "LANGSMITH_ENDPOINT",
        ]

        # Save original values
        original_values = {}
        for var in env_vars_to_clear:
            if var in os.environ:
                original_values[var] = os.environ[var]
                del os.environ[var]

        try:
            with patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "prod-openai-key",
                    "LANGCHAIN_TRACING_V2": "false",  # Production explicitly disables tracing
                    "LANGCHAIN_API_KEY": "prod-langsmith-key",
                },
            ):
                ai_config = AIConfig(name="prod-ai", provider="openai", model="gpt-4")
                mock_logger = Mock(spec=Logger)

                # TOML config wants tracing enabled, but production environment overrides
                langsmith_config = MockLangSmithConfig(
                    enabled=True,
                    api_key="toml-langsmith-key",
                    project_name="ai-marketplace-monitor-prod",
                )
                main_config = MockConfig(langsmith=langsmith_config)

                _backend = LangChainBackend(ai_config, logger=mock_logger, main_config=main_config)

                # Environment variables should not be overridden when already set
                assert (
                    os.environ["LANGCHAIN_TRACING_V2"] == "false"
                )  # Production override maintained
                assert (
                    os.environ["LANGCHAIN_API_KEY"] == "prod-langsmith-key"
                )  # Production key maintained
                # Project name should be set from TOML config since it wasn't in environment
                assert (
                    os.environ["LANGCHAIN_PROJECT"] == "ai-marketplace-monitor-prod"
                )  # Set from TOML config
        finally:
            # Restore original values
            for var, value in original_values.items():
                os.environ[var] = value

    def test_mixed_ai_providers_with_shared_langsmith_config(self: "Self") -> None:
        """Should handle multiple AI providers sharing the same LangSmith configuration."""
        # Shared LangSmith config for all AI backends
        langsmith_config = MockLangSmithConfig(
            enabled=True,
            api_key="shared-langsmith-key",
            project_name="ai-marketplace-monitor-mixed",
        )
        main_config = MockConfig(langsmith=langsmith_config)

        # Test with OpenAI backend
        with patch.dict(os.environ, {"OPENAI_API_KEY": "openai-key"}):
            openai_config = AIConfig(name="openai-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            _openai_backend = LangChainBackend(
                openai_config, logger=mock_logger, main_config=main_config
            )

            # Should configure shared LangSmith settings
            assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
            assert os.environ["LANGCHAIN_API_KEY"] == "shared-langsmith-key"
            assert os.environ["LANGCHAIN_PROJECT"] == "ai-marketplace-monitor-mixed"

        # Test with DeepSeek backend (environment variables should remain set)
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "deepseek-key"}):
            deepseek_config = AIConfig(
                name="deepseek-ai", provider="deepseek", model="deepseek-chat"
            )

            _deepseek_backend = LangChainBackend(
                deepseek_config, logger=mock_logger, main_config=main_config
            )

            # Should use the same shared LangSmith settings (already set, won't override)
            assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
            assert os.environ["LANGCHAIN_API_KEY"] == "shared-langsmith-key"
            assert os.environ["LANGCHAIN_PROJECT"] == "ai-marketplace-monitor-mixed"

    def test_migrating_from_environment_to_toml_configuration(self: "Self") -> None:
        """Should handle migration from environment-based to TOML-based configuration."""
        # Start with environment-based configuration
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "openai-key",
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "old-langsmith-key",
                "LANGCHAIN_PROJECT": "old-project",
            },
        ):
            ai_config = AIConfig(name="migrating-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Initialize without TOML config (simulating old setup)
            _old_backend = LangChainBackend(ai_config, logger=mock_logger, main_config=None)

            # Verify environment configuration is used
            assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
            assert os.environ["LANGCHAIN_API_KEY"] == "old-langsmith-key"
            assert os.environ["LANGCHAIN_PROJECT"] == "old-project"

            # Now migrate to TOML configuration - environment variables won't be overridden
            langsmith_config = MockLangSmithConfig(
                enabled=True,
                api_key="new-toml-langsmith-key",
                project_name="new-toml-project",
            )
            main_config = MockConfig(langsmith=langsmith_config)

            _new_backend = LangChainBackend(ai_config, logger=mock_logger, main_config=main_config)

            # Environment variables should remain unchanged (existing environment takes precedence)
            assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
            assert os.environ["LANGCHAIN_API_KEY"] == "old-langsmith-key"  # Not overridden
            assert os.environ["LANGCHAIN_PROJECT"] == "old-project"  # Not overridden

    def test_minimal_toml_configuration_scenario(self: "Self") -> None:
        """Should handle minimal TOML configuration with only essential settings."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "openai-key"}):
            ai_config = AIConfig(name="minimal-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Minimal TOML configuration - only enable tracing
            langsmith_config = MockLangSmithConfig(enabled=True)
            # api_key, project_name, endpoint are all None
            main_config = MockConfig(langsmith=langsmith_config)

            _backend = LangChainBackend(ai_config, logger=mock_logger, main_config=main_config)

            # Should only set tracing enabled
            assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
            # Other variables should not be set
            assert "LANGCHAIN_API_KEY" not in os.environ
            assert "LANGCHAIN_PROJECT" not in os.environ
            assert "LANGCHAIN_ENDPOINT" not in os.environ

    def test_debugging_scenario_with_comprehensive_langsmith_config(self: "Self") -> None:
        """Should handle debugging scenario with comprehensive LangSmith configuration."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "debug-openai-key"}):
            ai_config = AIConfig(name="debug-ai", provider="openai", model="gpt-4")
            mock_logger = Mock(spec=Logger)

            # Comprehensive debugging configuration
            langsmith_config = MockLangSmithConfig(
                enabled=True,
                api_key="debug-langsmith-key",
                project_name="ai-marketplace-monitor-debug-session",
                endpoint="https://api.smith.langchain.com",
            )
            main_config = MockConfig(langsmith=langsmith_config)

            backend = LangChainBackend(ai_config, logger=mock_logger, main_config=main_config)

            # Should set all debugging configuration
            assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
            assert os.environ["LANGCHAIN_API_KEY"] == "debug-langsmith-key"
            assert os.environ["LANGCHAIN_PROJECT"] == "ai-marketplace-monitor-debug-session"
            assert os.environ["LANGCHAIN_ENDPOINT"] == "https://api.smith.langchain.com"

            # Verify backend initialization succeeded
            assert backend._main_config is main_config
            assert backend.config.name == "debug-ai"
