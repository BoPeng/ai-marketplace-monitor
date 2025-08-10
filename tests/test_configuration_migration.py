"""Test configuration migration and deprecation strategy."""

import os
from unittest.mock import Mock, patch

from src.ai_marketplace_monitor.ai import AIConfig, LangChainBackend


class TestConfigurationMigration:
    """Test configuration migration warnings and upgrade guidance."""

    def test_mixed_configuration_warnings_legacy_service_provider(self) -> None:
        """Test warnings for mixed legacy and new configuration patterns."""
        logger = Mock()
        config = AIConfig(name="test", provider="openai", api_key="test-key")
        # Simulate legacy field
        config.service_provider = "legacy_openai"

        backend = LangChainBackend(config, logger=logger)
        warnings = backend._validate_mixed_configuration(config)

        assert len(warnings) >= 1
        assert any("service_provider" in warning for warning in warnings)
        assert any("Consider removing 'service_provider'" in warning for warning in warnings)

        # Verify logger was called
        assert logger.warning.called
        warning_msg = logger.warning.call_args[0][0]
        assert "Configuration migration:" in warning_msg

    def test_deepseek_api_key_migration_warnings(self) -> None:
        """Test DeepSeek API key migration scenarios."""
        logger = Mock()
        config = AIConfig(name="test-deepseek", provider="deepseek", api_key="test-key")
        backend = LangChainBackend(config, logger=logger)

        # Test scenario 1: API key in config only (should suggest environment variable)
        with patch.dict(os.environ, {}, clear=True):
            warnings = backend._validate_mixed_configuration(config)
            assert any(
                "consider moving to DEEPSEEK_API_KEY environment variable" in w for w in warnings
            )

        # Test scenario 2: Both config and environment variable (should warn about duplication)
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}):
            warnings = backend._validate_mixed_configuration(config)
            assert any(
                "Both config api_key and DEEPSEEK_API_KEY environment variable" in w
                for w in warnings
            )
            assert any("Consider removing 'api_key' from config" in w for w in warnings)

    def test_openai_api_key_migration_warnings(self) -> None:
        """Test OpenAI API key migration scenarios."""
        logger = Mock()
        config = AIConfig(name="test-openai", provider="openai", api_key="test-key")
        backend = LangChainBackend(config, logger=logger)

        # Test scenario 1: API key in config only
        with patch.dict(os.environ, {}, clear=True):
            warnings = backend._validate_mixed_configuration(config)
            assert any(
                "consider moving to OPENAI_API_KEY environment variable" in w for w in warnings
            )

        # Test scenario 2: Both config and environment variable
        with patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"}):
            warnings = backend._validate_mixed_configuration(config)
            assert any(
                "Both config api_key and OPENAI_API_KEY environment variable" in w
                for w in warnings
            )

    def test_openrouter_api_key_migration_warnings(self) -> None:
        """Test OpenRouter API key migration scenarios."""
        logger = Mock()
        config = AIConfig(name="test-openrouter", provider="openrouter", api_key="test-key")
        backend = LangChainBackend(config, logger=logger)

        # Test scenario 1: API key in config only
        with patch.dict(os.environ, {}, clear=True):
            warnings = backend._validate_mixed_configuration(config)
            assert any(
                "consider moving to OPENROUTER_API_KEY environment variable" in w for w in warnings
            )

        # Test scenario 2: Both config and environment variable
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "env-key"}):
            warnings = backend._validate_mixed_configuration(config)
            assert any(
                "Both config api_key and OPENROUTER_API_KEY environment variable" in w
                for w in warnings
            )

    def test_ollama_configuration_warnings(self) -> None:
        """Test Ollama-specific configuration warnings."""
        logger = Mock()

        # Test custom base URL warning
        config = AIConfig(
            name="test-ollama",
            provider="ollama",
            base_url="http://custom-server:11434",
            model="llama2",
        )
        backend = LangChainBackend(config, logger=logger)
        warnings = backend._validate_mixed_configuration(config)
        assert any("Custom Ollama base URL detected" in w for w in warnings)
        assert any("Ensure this URL is correct" in w for w in warnings)

        # Test missing model warning
        config_no_model = AIConfig(name="test-ollama", provider="ollama")
        backend_no_model = LangChainBackend(config_no_model, logger=logger)
        warnings = backend_no_model._validate_mixed_configuration(config_no_model)
        assert any("No model specified for Ollama" in w for w in warnings)
        assert any("Consider specifying a model like" in w for w in warnings)

    def test_api_key_length_validation(self) -> None:
        """Test validation for suspiciously short API keys."""
        logger = Mock()
        config = AIConfig(name="test", provider="openai", api_key="short")
        backend = LangChainBackend(config, logger=logger)

        warnings = backend._validate_mixed_configuration(config)
        assert any("API key appears unusually short" in w for w in warnings)
        assert any("Please verify it's correct" in w for w in warnings)

    def test_configuration_suggestions_api_key_migration(self) -> None:
        """Test configuration improvement suggestions for API key migration."""
        logger = Mock()

        # Test OpenAI suggestions
        config = AIConfig(name="test-openai", provider="openai", api_key="test-key")
        backend = LangChainBackend(config, logger=logger)
        suggestions = backend._suggest_configuration_improvements(config)

        assert "OPENAI_API_KEY" in suggestions
        assert "export OPENAI_API_KEY" in suggestions
        assert "remove 'api_key' from your config" in suggestions
        assert "Configuration Suggestions for test-openai" in suggestions

        # Test DeepSeek suggestions
        config_deepseek = AIConfig(name="test-deepseek", provider="deepseek", api_key="test-key")
        backend_deepseek = LangChainBackend(config_deepseek, logger=logger)
        suggestions = backend_deepseek._suggest_configuration_improvements(config_deepseek)

        assert "DEEPSEEK_API_KEY" in suggestions
        assert "export DEEPSEEK_API_KEY" in suggestions

    def test_configuration_suggestions_model_recommendations(self) -> None:
        """Test model recommendation suggestions."""
        logger = Mock()

        # Test OpenAI model recommendations
        config = AIConfig(name="test-openai", provider="openai", api_key="test-key")
        backend = LangChainBackend(config, logger=logger)
        suggestions = backend._suggest_configuration_improvements(config)

        assert "gpt-3.5-turbo" in suggestions
        assert "Fast and cost-effective" in suggestions
        assert "gpt-4" in suggestions

        # Test Ollama model recommendations
        config_ollama = AIConfig(name="test-ollama", provider="ollama")
        backend_ollama = LangChainBackend(config_ollama, logger=logger)
        suggestions = backend_ollama._suggest_configuration_improvements(config_ollama)

        assert "Ollama requires a model specification" in suggestions
        assert "llama2" in suggestions
        assert "codellama" in suggestions

        # Test DeepSeek model recommendations
        config_deepseek = AIConfig(name="test-deepseek", provider="deepseek", api_key="test-key")
        backend_deepseek = LangChainBackend(config_deepseek, logger=logger)
        suggestions = backend_deepseek._suggest_configuration_improvements(config_deepseek)

        assert "deepseek-coder" in suggestions
        assert "deepseek-chat" in suggestions

    def test_configuration_suggestions_timeout_and_retries(self) -> None:
        """Test timeout and retry configuration suggestions."""
        logger = Mock()

        # Test low timeout suggestion
        config = AIConfig(name="test", provider="openai", api_key="test-key", timeout=15)
        backend = LangChainBackend(config, logger=logger)
        suggestions = backend._suggest_configuration_improvements(config)

        assert "Consider increasing timeout" in suggestions
        assert "timeout = 60" in suggestions

        # Test retry suggestion
        config_no_retry = AIConfig(
            name="test", provider="openai", api_key="test-key", max_retries=0
        )
        backend_no_retry = LangChainBackend(config_no_retry, logger=logger)
        suggestions = backend_no_retry._suggest_configuration_improvements(config_no_retry)

        assert "Consider enabling retries" in suggestions
        assert "max_retries = 3" in suggestions

    def test_configuration_suggestions_when_none_needed(self) -> None:
        """Test that no suggestions are returned for optimal configurations."""
        logger = Mock()

        # Well-configured setup using environment variables
        config = AIConfig(
            name="optimal-config",
            provider="openai",
            model="gpt-3.5-turbo",
            timeout=60,
            max_retries=3,
        )

        with patch.dict(os.environ, {"OPENAI_API_KEY": "proper-key"}):
            backend = LangChainBackend(config, logger=logger)
            suggestions = backend._suggest_configuration_improvements(config)

            # Should have minimal or no suggestions for a well-configured backend
            assert suggestions == "" or "Configuration Suggestions" not in suggestions

    def test_suggestions_shown_with_environment_variable(self) -> None:
        """Test that suggestions are shown when environment variable is set."""
        logger = Mock()
        config = AIConfig(name="test", provider="openai", api_key="test-key")
        backend = LangChainBackend(config, logger=logger)

        with patch.dict(os.environ, {"AI_MARKETPLACE_MONITOR_SHOW_CONFIG_TIPS": "true"}):
            with patch.object(backend, "_get_model") as mock_get_model:
                mock_get_model.return_value = Mock()
                backend.connect()

                # Verify suggestions were logged
                assert logger.info.called
                # Check if any of the info calls contain configuration suggestions
                info_calls = [call[0][0] for call in logger.info.call_args_list]
                assert any("Configuration Suggestions" in call for call in info_calls)

    def test_suggestions_not_shown_by_default(self) -> None:
        """Test that suggestions are not shown by default."""
        logger = Mock()
        config = AIConfig(name="test", provider="openai", api_key="test-key")
        backend = LangChainBackend(config, logger=logger)

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(backend, "_get_model") as mock_get_model:
                mock_get_model.return_value = Mock()
                backend.connect()

                # Verify suggestions were not logged (only connection message)
                info_calls = [
                    call[0][0] for call in logger.info.call_args_list if logger.info.called
                ]
                assert not any("Configuration Suggestions" in str(call) for call in info_calls)

    def test_comprehensive_migration_scenario(self) -> None:
        """Test a comprehensive migration scenario with multiple issues."""
        logger = Mock()
        config = AIConfig(
            name="legacy-config",
            provider="deepseek",
            api_key="short",  # Short API key
            timeout=10,  # Low timeout
            max_retries=0,  # No retries
        )

        # Add legacy field
        config.service_provider = "old_deepseek"

        backend = LangChainBackend(config, logger=logger)

        # Test warnings
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}):
            warnings = backend._validate_mixed_configuration(config)

            # Should have multiple warnings
            assert len(warnings) >= 3
            assert any("service_provider" in w for w in warnings)
            assert any("Both config api_key and DEEPSEEK_API_KEY" in w for w in warnings)
            assert any("API key appears unusually short" in w for w in warnings)

        # Test suggestions
        suggestions = backend._suggest_configuration_improvements(config)
        assert "Configuration Suggestions" in suggestions
        assert "DEEPSEEK_API_KEY" in suggestions
        assert "timeout = 60" in suggestions
        assert "max_retries = 3" in suggestions
