"""Test monitor integration with LangChain backend compatibility layer and TOML configuration.

This test suite focuses on testing the monitor's integration with the LangChain backend
system and TOML configuration, particularly for passing main_config to AI backends.

Following TDD principles:
- RED: Write failing tests that describe desired behavior
- GREEN: Write minimal code to make tests pass
- REFACTOR: Improve code while keeping tests green

Test coverage focuses on valuable behaviors including:
- Monitor passing main_config to LangChain backends
- Backend selection logic with TOML configuration
- Integration with LangSmith configuration via monitor
- Backward compatibility when backends don't support main_config
- Error handling during AI agent loading
"""

import os
from logging import Logger
from typing import TYPE_CHECKING, Any
from unittest.mock import Mock, patch

import pytest

from ai_marketplace_monitor.ai import AIConfig, LangChainBackend
from ai_marketplace_monitor.config import supported_ai_backends
from ai_marketplace_monitor.monitor import MarketplaceMonitor

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
    """Mock main Config class for testing without circular imports."""

    def __init__(
        self,
        ai: dict | None = None,
        langsmith: MockLangSmithConfig | None = None,
        marketplace: dict | None = None,
        item: dict | None = None,
    ) -> None:
        self.ai = ai or {}
        self.langsmith = langsmith
        self.marketplace = marketplace or {}
        self.item = item or {}


class MockBackendWithMainConfig:
    """Mock backend that supports main_config parameter for testing."""

    def __init__(self, config: Any, logger: Any, main_config: Any = None) -> None:
        self.config = config
        self.logger = logger
        self.main_config = main_config


class MockBackendWithoutMainConfig:
    """Mock backend that does NOT support main_config parameter for testing."""

    def __init__(self, config: Any, logger: Any) -> None:
        self.config = config
        self.logger = logger


class MockAIConfig:
    """Mock AIConfig for testing without circular imports."""

    def __init__(
        self,
        name: str,
        provider: str | None = None,
        enabled: bool = True,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.name = name
        self.provider = provider
        self.enabled = enabled
        self.api_key = api_key
        self.model = model


class TestMonitorCompatibilityLayer:
    """Test that monitor.py works correctly with the LangChain backend compatibility layer."""

    def test_supported_ai_backends_uses_langchain(self: "Self") -> None:
        """Test that all supported AI backends now use LangChainBackend."""
        for provider, backend_class in supported_ai_backends.items():
            assert (
                backend_class is LangChainBackend
            ), f"Provider {provider} should use LangChainBackend"

    def test_monitor_backend_selection_works(self: "Self") -> None:
        """Test that monitor backend selection logic works with compatibility layer."""
        # Test provider-based selection
        ai_config = AIConfig(name="test-openai", provider="openai", api_key="test-key")
        provider_key = ai_config.provider.lower() if ai_config.provider else None

        if provider_key and provider_key in supported_ai_backends:
            ai_class = supported_ai_backends[provider_key]
            assert ai_class is LangChainBackend

        # Test name-based fallback selection
        ai_config_name = AIConfig(name="deepseek", api_key="test-key")
        name_key = ai_config_name.name.lower()

        if name_key in supported_ai_backends:
            ai_class = supported_ai_backends[name_key]
            assert ai_class is LangChainBackend

    def test_case_insensitive_provider_matching(self: "Self") -> None:
        """Test that case-insensitive provider matching works through compatibility layer."""
        # Test that monitor logic handles case-insensitive matching
        test_providers = ["OpenAI", "DEEPSEEK", "ollama", "OpenRouter"]

        for provider in test_providers:
            provider_lower = provider.lower()
            assert provider_lower in supported_ai_backends
            assert supported_ai_backends[provider_lower] is LangChainBackend


class TestMonitorTomlConfigIntegration:
    """Test cases for monitor integration with TOML configuration and LangChain backends."""

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

    def test_should_pass_main_config_to_langchain_backends(self: "Self") -> None:
        """Should pass main_config to LangChain backends that support it."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            mock_logger = Mock(spec=Logger)
            monitor = MarketplaceMonitor(config_files=None, headless=True, logger=mock_logger)

            # Create mock config with AI and LangSmith configuration
            openai_ai_config = MockAIConfig(name="test-openai", provider="openai", model="gpt-4")
            langsmith_config = MockLangSmithConfig(
                enabled=True,
                api_key="monitor-langsmith-key",
                project_name="monitor-project",
            )
            mock_config = MockConfig(
                ai={"test-openai": openai_ai_config},
                langsmith=langsmith_config,
            )
            monitor.config = mock_config

            # Patch the supported_ai_backends to use our class
            with patch.dict(supported_ai_backends, {"openai": MockBackendWithMainConfig}):
                monitor.load_ai_agents()

                # Should add the backend to ai_agents
                assert len(monitor.ai_agents) == 1
                backend_instance = monitor.ai_agents[0]
                assert isinstance(backend_instance, MockBackendWithMainConfig)

                # Check that main_config was passed to the constructor
                assert backend_instance.config is openai_ai_config
                assert backend_instance.logger is mock_logger
                assert backend_instance.main_config is mock_config

    def test_should_fallback_to_no_main_config_for_unsupported_backends(self: "Self") -> None:
        """Should fall back to no main_config for backends that don't support it."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            mock_logger = Mock(spec=Logger)
            monitor = MarketplaceMonitor(config_files=None, headless=True, logger=mock_logger)

            # Create mock config with AI configuration
            openai_ai_config = MockAIConfig(name="test-openai", provider="openai", model="gpt-4")
            langsmith_config = MockLangSmithConfig(enabled=True, api_key="monitor-langsmith-key")
            mock_config = MockConfig(
                ai={"test-openai": openai_ai_config},
                langsmith=langsmith_config,
            )
            monitor.config = mock_config

            with patch.dict(supported_ai_backends, {"openai": MockBackendWithoutMainConfig}):
                monitor.load_ai_agents()

                # Should initialize one agent without main_config
                assert len(monitor.ai_agents) == 1
                agent = monitor.ai_agents[0]
                assert isinstance(agent, MockBackendWithoutMainConfig)
                assert agent.config is openai_ai_config
                assert agent.logger is mock_logger

    def test_should_handle_provider_based_ai_selection_with_main_config(self: "Self") -> None:
        """Should handle provider-based AI selection and pass main_config correctly."""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-deepseek-key"}):
            mock_logger = Mock(spec=Logger)
            monitor = MarketplaceMonitor(config_files=None, headless=True, logger=mock_logger)

            # Create mock config with provider-based AI configuration
            deepseek_ai_config = MockAIConfig(
                name="my-deepseek-ai", provider="deepseek", model="deepseek-chat"
            )
            langsmith_config = MockLangSmithConfig(
                enabled=True,
                api_key="monitor-langsmith-key",
                project_name="monitor-deepseek-project",
            )
            mock_config = MockConfig(
                ai={"my-deepseek-ai": deepseek_ai_config},
                langsmith=langsmith_config,
            )
            monitor.config = mock_config

            # Patch the supported_ai_backends to use our mock class
            with patch.dict(supported_ai_backends, {"deepseek": MockBackendWithMainConfig}):
                monitor.load_ai_agents()

                # Should create backend instance with main_config
                assert len(monitor.ai_agents) == 1
                backend_instance = monitor.ai_agents[0]
                assert isinstance(backend_instance, MockBackendWithMainConfig)
                assert backend_instance.config is deepseek_ai_config
                assert backend_instance.logger is mock_logger
                assert backend_instance.main_config is mock_config

    def test_should_handle_name_based_ai_selection_with_main_config(self: "Self") -> None:
        """Should handle name-based AI selection and pass main_config correctly."""
        mock_logger = Mock(spec=Logger)
        monitor = MarketplaceMonitor(config_files=None, headless=True, logger=mock_logger)

        # Create mock config with name-based AI configuration (no provider specified)
        ollama_ai_config = MockAIConfig(name="ollama", model="llama2")
        langsmith_config = MockLangSmithConfig(
            enabled=True,
            api_key="monitor-langsmith-key",
            project_name="monitor-ollama-project",
        )
        mock_config = MockConfig(
            ai={"ollama": ollama_ai_config},
            langsmith=langsmith_config,
        )
        monitor.config = mock_config

        # Patch the supported_ai_backends to use our mock class
        with patch.dict(supported_ai_backends, {"ollama": MockBackendWithMainConfig}):
            monitor.load_ai_agents()

            # Should create backend instance with main_config based on name fallback
            assert len(monitor.ai_agents) == 1
            backend_instance = monitor.ai_agents[0]
            assert isinstance(backend_instance, MockBackendWithMainConfig)
            assert backend_instance.config is ollama_ai_config
            assert backend_instance.logger is mock_logger
            assert backend_instance.main_config is mock_config

    def test_should_skip_disabled_ai_configurations(self: "Self") -> None:
        """Should skip disabled AI configurations and not pass main_config to them."""
        mock_logger = Mock(spec=Logger)
        monitor = MarketplaceMonitor(config_files=None, headless=True, logger=mock_logger)

        # Create mock config with disabled AI configuration
        disabled_ai_config = MockAIConfig(
            name="disabled-ai", provider="openai", enabled=False, model="gpt-4"
        )
        enabled_ai_config = MockAIConfig(
            name="enabled-ai", provider="deepseek", enabled=True, model="deepseek-chat"
        )
        langsmith_config = MockLangSmithConfig(enabled=True, api_key="monitor-langsmith-key")
        mock_config = MockConfig(
            ai={"disabled-ai": disabled_ai_config, "enabled-ai": enabled_ai_config},
            langsmith=langsmith_config,
        )
        monitor.config = mock_config

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-deepseek-key"}):
            # Patch the supported_ai_backends to use our mock class
            with patch.dict(supported_ai_backends, {"deepseek": MockBackendWithMainConfig}):
                monitor.load_ai_agents()

                # Should only initialize backend for enabled configuration
                assert len(monitor.ai_agents) == 1
                backend_instance = monitor.ai_agents[0]
                assert isinstance(backend_instance, MockBackendWithMainConfig)
                assert backend_instance.config is enabled_ai_config
                assert backend_instance.logger is mock_logger
                assert backend_instance.main_config is mock_config

    def test_should_handle_multiple_ai_backends_with_same_main_config(self: "Self") -> None:
        """Should handle multiple AI backends and pass the same main_config to all."""
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-openai-key", "DEEPSEEK_API_KEY": "test-deepseek-key"},
        ):
            mock_logger = Mock(spec=Logger)
            monitor = MarketplaceMonitor(config_files=None, headless=True, logger=mock_logger)

            # Create mock config with multiple AI configurations
            openai_ai_config = MockAIConfig(name="openai-ai", provider="openai", model="gpt-4")
            deepseek_ai_config = MockAIConfig(
                name="deepseek-ai", provider="deepseek", model="deepseek-chat"
            )
            langsmith_config = MockLangSmithConfig(
                enabled=True,
                api_key="shared-langsmith-key",
                project_name="shared-project",
            )
            mock_config = MockConfig(
                ai={"openai-ai": openai_ai_config, "deepseek-ai": deepseek_ai_config},
                langsmith=langsmith_config,
            )
            monitor.config = mock_config

            # Patch the supported_ai_backends to use our mock class for both providers
            with patch.dict(
                supported_ai_backends,
                {"openai": MockBackendWithMainConfig, "deepseek": MockBackendWithMainConfig},
            ):
                monitor.load_ai_agents()

                # Should add both backends to ai_agents with same main_config
                assert len(monitor.ai_agents) == 2

                # Check first backend (order may vary)
                backend_configs = {agent.config for agent in monitor.ai_agents}
                assert openai_ai_config in backend_configs
                assert deepseek_ai_config in backend_configs

                # All backends should have the same main_config
                for backend_instance in monitor.ai_agents:
                    assert isinstance(backend_instance, MockBackendWithMainConfig)
                    assert backend_instance.logger is mock_logger
                    assert backend_instance.main_config is mock_config

    def test_should_pass_none_main_config_when_no_langsmith_in_config(self: "Self") -> None:
        """Should pass main_config even when there's no LangSmith configuration."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            mock_logger = Mock(spec=Logger)
            monitor = MarketplaceMonitor(config_files=None, headless=True, logger=mock_logger)

            # Create mock config without LangSmith configuration
            openai_ai_config = MockAIConfig(name="test-openai", provider="openai", model="gpt-4")
            mock_config = MockConfig(
                ai={"test-openai": openai_ai_config},
                langsmith=None,  # No LangSmith config
            )
            monitor.config = mock_config

            # Patch the supported_ai_backends to use our mock class
            with patch.dict(supported_ai_backends, {"openai": MockBackendWithMainConfig}):
                monitor.load_ai_agents()

                # Should still pass main_config (backend will handle None langsmith)
                assert len(monitor.ai_agents) == 1
                backend_instance = monitor.ai_agents[0]
                assert isinstance(backend_instance, MockBackendWithMainConfig)
                assert backend_instance.config is openai_ai_config
                assert backend_instance.logger is mock_logger
                assert backend_instance.main_config is mock_config

    def test_should_handle_unsupported_ai_provider_gracefully(self: "Self") -> None:
        """Should handle unsupported AI provider gracefully and log error."""
        mock_logger = Mock(spec=Logger)
        monitor = MarketplaceMonitor(config_files=None, headless=True, logger=mock_logger)

        # Create mock config with unsupported AI provider
        unsupported_ai_config = MockAIConfig(
            name="unsupported-ai", provider="unsupported-provider", model="some-model"
        )
        langsmith_config = MockLangSmithConfig(enabled=True, api_key="monitor-langsmith-key")
        mock_config = MockConfig(
            ai={"unsupported-ai": unsupported_ai_config},
            langsmith=langsmith_config,
        )
        monitor.config = mock_config

        monitor.load_ai_agents()

        # Should not add any agents
        assert len(monitor.ai_agents) == 0

        # Should log error about unsupported provider
        mock_logger.error.assert_called_once()
        error_message = mock_logger.error.call_args[0][0]
        assert "Cannot determine an AI service provider" in error_message

    def test_should_handle_backend_initialization_exception(self: "Self") -> None:
        """Should handle backend initialization exception gracefully."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            mock_logger = Mock(spec=Logger)
            monitor = MarketplaceMonitor(config_files=None, headless=True, logger=mock_logger)

            # Create mock config with AI configuration
            openai_ai_config = MockAIConfig(name="test-openai", provider="openai", model="gpt-4")
            langsmith_config = MockLangSmithConfig(enabled=True, api_key="monitor-langsmith-key")
            mock_config = MockConfig(
                ai={"test-openai": openai_ai_config},
                langsmith=langsmith_config,
            )
            monitor.config = mock_config

            # Create mock backend class that raises exception
            class FailingBackend:
                def __init__(self, config: Any, logger: Any, main_config: Any = None) -> None:
                    raise Exception("Backend initialization failed")

            # Patch the supported_ai_backends to use our failing mock
            with patch.dict(supported_ai_backends, {"openai": FailingBackend}):
                # Should not raise exception but log error and continue gracefully
                monitor.load_ai_agents()

                # Should not add any agents when initialization fails
                assert len(monitor.ai_agents) == 0

                # Should log error about backend initialization failure
                mock_logger.error.assert_called_once()
                error_message = mock_logger.error.call_args[0][0]
                assert "Failed to connect to" in error_message
                assert "test-openai" in error_message
                assert "Backend initialization failed" in error_message

    def test_should_handle_keyboard_interrupt_during_loading(self: "Self") -> None:
        """Should handle KeyboardInterrupt during AI agent loading."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"}):
            mock_logger = Mock(spec=Logger)
            monitor = MarketplaceMonitor(config_files=None, headless=True, logger=mock_logger)

            # Create mock config with AI configuration
            openai_ai_config = MockAIConfig(name="test-openai", provider="openai", model="gpt-4")
            langsmith_config = MockLangSmithConfig(enabled=True, api_key="monitor-langsmith-key")
            mock_config = MockConfig(
                ai={"test-openai": openai_ai_config},
                langsmith=langsmith_config,
            )
            monitor.config = mock_config

            # Create mock backend class that raises KeyboardInterrupt
            class InterruptedBackend:
                def __init__(self, config: Any, logger: Any, main_config: Any = None) -> None:
                    raise KeyboardInterrupt("User interrupted")

            # Patch the supported_ai_backends to use our interrupting mock
            with patch.dict(supported_ai_backends, {"openai": InterruptedBackend}):
                with pytest.raises(KeyboardInterrupt):
                    monitor.load_ai_agents()


class TestMonitorIntegrationScenarios:
    """Integration test scenarios for realistic monitor usage with TOML configuration."""

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

    def test_complete_monitor_workflow_with_langsmith_integration(self: "Self") -> None:
        """Should handle complete monitor workflow with LangSmith integration via TOML."""
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "workflow-openai-key", "DEEPSEEK_API_KEY": "workflow-deepseek-key"},
        ):
            mock_logger = Mock(spec=Logger)
            monitor = MarketplaceMonitor(config_files=None, headless=True, logger=mock_logger)

            # Create comprehensive mock config
            openai_ai_config = MockAIConfig(name="primary-ai", provider="openai", model="gpt-4")
            deepseek_ai_config = MockAIConfig(
                name="fallback-ai", provider="deepseek", model="deepseek-chat"
            )
            langsmith_config = MockLangSmithConfig(
                enabled=True,
                api_key="workflow-langsmith-key",
                project_name="ai-marketplace-monitor-production",
                endpoint="https://api.smith.langchain.com",
            )
            mock_config = MockConfig(
                ai={"primary-ai": openai_ai_config, "fallback-ai": deepseek_ai_config},
                langsmith=langsmith_config,
            )
            monitor.config = mock_config

            with patch(
                "ai_marketplace_monitor.ai.configure_langsmith_environment"
            ) as mock_configure:
                monitor.load_ai_agents()

                # Should load two AI agents
                assert len(monitor.ai_agents) == 2

                # Both agents should be LangChain backends with LangSmith configured
                for agent in monitor.ai_agents:
                    assert isinstance(agent, LangChainBackend)
                    assert agent._main_config is mock_config

                # configure_langsmith_environment should be called twice (once per backend)
                assert mock_configure.call_count == 2
                for call in mock_configure.call_args_list:
                    assert call.args[0] is langsmith_config

    def test_monitor_schedule_jobs_reloads_ai_agents_with_config(self: "Self") -> None:
        """Should reload AI agents with updated configuration during schedule_jobs."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "schedule-openai-key"}):
            mock_logger = Mock(spec=Logger)
            monitor = MarketplaceMonitor(config_files=None, headless=True, logger=mock_logger)

            # Mock the config loading to avoid file system dependencies
            initial_ai_config = MockAIConfig(name="initial-ai", provider="openai", model="gpt-3.5")
            initial_langsmith_config = MockLangSmithConfig(
                enabled=False,
                api_key="initial-langsmith-key",
            )
            initial_config = MockConfig(
                ai={"initial-ai": initial_ai_config},
                langsmith=initial_langsmith_config,
            )

            updated_ai_config = MockAIConfig(name="updated-ai", provider="openai", model="gpt-4")
            updated_langsmith_config = MockLangSmithConfig(
                enabled=True,
                api_key="updated-langsmith-key",
                project_name="updated-project",
            )
            updated_config = MockConfig(
                ai={"updated-ai": updated_ai_config},
                langsmith=updated_langsmith_config,
            )

            with (patch.object(monitor, "load_config_file") as mock_load_config,):
                # Set initial config
                monitor.config = initial_config

                # Mock load_config_file to update config
                def update_config():
                    monitor.config = updated_config

                mock_load_config.side_effect = update_config

                # Patch the supported_ai_backends to use our mock class
                with patch.dict(supported_ai_backends, {"openai": MockBackendWithMainConfig}):
                    # Call schedule_jobs (which calls load_ai_agents)
                    monitor.schedule_jobs()

                    # Should call load_config_file and then load AI agents with updated config
                    mock_load_config.assert_called_once()

                    # Should create backend with updated config
                    assert len(monitor.ai_agents) == 1
                    backend_instance = monitor.ai_agents[0]
                    assert isinstance(backend_instance, MockBackendWithMainConfig)
                    assert backend_instance.config is updated_ai_config
                    assert backend_instance.logger is mock_logger
                    assert backend_instance.main_config is updated_config

    def test_monitor_check_item_loads_ai_agents_with_config(self: "Self") -> None:
        """Should load AI agents with configuration when checking specific items."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "check-item-openai-key"}):
            mock_logger = Mock(spec=Logger)
            monitor = MarketplaceMonitor(config_files=None, headless=True, logger=mock_logger)

            # Create mock config for check_item scenario
            check_ai_config = MockAIConfig(name="check-ai", provider="openai", model="gpt-4")
            check_langsmith_config = MockLangSmithConfig(
                enabled=True,
                api_key="check-langsmith-key",
                project_name="ai-marketplace-monitor-check",
            )
            mock_config = MockConfig(
                ai={"check-ai": check_ai_config},
                langsmith=check_langsmith_config,
                item={"test-item": {}},  # Add the test-item to config
            )
            monitor.config = mock_config

            # Mock dependencies for check_item method
            with (
                patch.object(monitor, "load_config_file"),
                patch("ai_marketplace_monitor.monitor.supported_marketplaces", {}),
            ):
                # Patch the supported_ai_backends to use our mock class
                with patch.dict(supported_ai_backends, {"openai": MockBackendWithMainConfig}):
                    try:
                        monitor.check_items(
                            items=["https://www.facebook.com/marketplace/item/123456789/"],
                            for_item="test-item",
                        )
                    except Exception:  # noqa: S110
                        # We don't care about the actual error - we just want to test that AI agents loaded
                        # This is expected as we're mocking dependencies
                        pass

                    # Should load AI agents with main_config before any potential error
                    assert len(monitor.ai_agents) == 1
                    backend_instance = monitor.ai_agents[0]
                    assert isinstance(backend_instance, MockBackendWithMainConfig)
                    assert backend_instance.config is check_ai_config
                    assert backend_instance.logger is mock_logger
                    assert backend_instance.main_config is mock_config
