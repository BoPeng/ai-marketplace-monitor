"""Backward Compatibility Test Suite

This comprehensive test suite validates that the Configuration Compatibility Layer
works transparently with existing TOML configurations. All tests verify that
the new LangChain backend system maintains full backward compatibility with
legacy configurations, error patterns, and user workflows.

Key validation areas:
1. Legacy TOML configuration loading without changes
2. Provider mapping from old to new backend system
3. Error message consistency with previous implementations
4. DeepSeek API key migration behavior
5. Mixed configuration handling
6. Performance regression prevention
7. Thread safety under concurrent access
"""

import os
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Dict
from unittest.mock import Mock, patch

import pytest

if TYPE_CHECKING:
    from ai_marketplace_monitor.facebook import FacebookItemConfig, FacebookMarketplaceConfig
    from ai_marketplace_monitor.listing import Listing

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ai_marketplace_monitor.ai import AIConfig, LangChainBackend
from ai_marketplace_monitor.config import supported_ai_backends


class TestLegacyConfigurationCompatibility:
    """Test backward compatibility with legacy TOML configurations."""

    @pytest.fixture
    def sample_toml_configs(self) -> Dict[str, str]:
        """Sample TOML configurations representing legacy user configs."""
        return {
            "openai_legacy": """
[ai.chatgpt]
provider = "openai"
api_key = "sk-test123"
model = "gpt-4"
timeout = 30
max_retries = 3
""",
            "deepseek_legacy": """
[ai.deepseek-chat]
provider = "deepseek"
api_key = "dk-test456"
model = "deepseek-chat"
base_url = "https://api.deepseek.com"
""",
            "ollama_legacy": """
[ai.llama]
provider = "ollama"
model = "deepseek-r1:14b"
base_url = "http://localhost:11434"
timeout = 60
""",
            "openrouter_new": """
[ai.router]
provider = "openrouter"
api_key = "sk-or-test789"
model = "anthropic/claude-3.5-sonnet"
base_url = "https://openrouter.ai/api/v1"
""",
            "openrouter_legacy_format": """
[ai.openrouter-legacy]
provider = "openrouter"
api_key = "sk-or-legacy123"
model = "openai/gpt-4"
timeout = 45
max_retries = 2
""",
            "mixed_config": """
[ai.openai-new]
provider = "openai"
api_key = "sk-mixed123"
model = "gpt-4"

[ai.deepseek-old]
provider = "deepseek"
api_key = "dk-mixed456"
model = "deepseek-chat"
service_provider = "deepseek"
""",
        }

    def test_legacy_openai_config_compatibility(
        self, sample_toml_configs: Dict[str, str], tmp_path: Path
    ) -> None:
        """Test that legacy OpenAI configurations work unchanged."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(sample_toml_configs["openai_legacy"])

        # Simulate reading TOML and extracting AI config
        with open(config_file, "rb") as toml_file:
            data = tomllib.load(toml_file)
            ai_data = data["ai"]["chatgpt"]

        # Verify legacy config maps to LangChainBackend
        provider = ai_data["provider"].lower()
        assert provider in supported_ai_backends
        assert supported_ai_backends[provider] == LangChainBackend

        # Verify configuration creates valid AIConfig
        config = LangChainBackend.get_config(
            name="chatgpt",
            provider=ai_data["provider"],
            api_key=ai_data["api_key"],
            model=ai_data["model"],
            timeout=ai_data.get("timeout", 30),
            max_retries=ai_data.get("max_retries", 3),
        )

        assert isinstance(config, AIConfig)
        assert config.name == "chatgpt"
        assert config.provider == "openai"
        assert config.api_key == "sk-test123"
        assert config.model == "gpt-4"
        assert config.timeout == 30
        assert config.max_retries == 3

    def test_legacy_deepseek_config_compatibility(
        self, sample_toml_configs: Dict[str, str], tmp_path: Path
    ) -> None:
        """Test that legacy DeepSeek configurations work unchanged."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(sample_toml_configs["deepseek_legacy"])

        with open(config_file, "rb") as toml_file:
            data = tomllib.load(toml_file)
            ai_data = data["ai"]["deepseek-chat"]

        # Verify legacy config maps to LangChainBackend
        provider = ai_data["provider"].lower()
        assert provider in supported_ai_backends
        assert supported_ai_backends[provider] == LangChainBackend

        # Test with both config API key and environment variable
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}):
            config = LangChainBackend.get_config(
                name="deepseek-chat",
                provider=ai_data["provider"],
                api_key=ai_data.get("api_key"),
                model=ai_data["model"],
                base_url=ai_data.get("base_url"),
            )

            assert isinstance(config, AIConfig)
            assert config.name == "deepseek-chat"
            assert config.provider == "deepseek"
            assert config.model == "deepseek-chat"

    def test_legacy_ollama_config_compatibility(
        self, sample_toml_configs: Dict[str, str], tmp_path: Path
    ) -> None:
        """Test that legacy Ollama configurations work unchanged."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(sample_toml_configs["ollama_legacy"])

        with open(config_file, "rb") as toml_file:
            data = tomllib.load(toml_file)
            ai_data = data["ai"]["llama"]

        # Verify legacy config maps to LangChainBackend
        provider = ai_data["provider"].lower()
        assert provider in supported_ai_backends
        assert supported_ai_backends[provider] == LangChainBackend

        # Verify configuration creates valid AIConfig
        config = LangChainBackend.get_config(
            name="llama",
            provider=ai_data["provider"],
            model=ai_data["model"],
            base_url=ai_data.get("base_url"),
            timeout=ai_data.get("timeout", 30),
        )

        assert isinstance(config, AIConfig)
        assert config.name == "llama"
        assert config.provider == "ollama"
        assert config.model == "deepseek-r1:14b"
        assert config.base_url == "http://localhost:11434"
        assert config.timeout == 60

    def test_new_openrouter_config_compatibility(
        self, sample_toml_configs: Dict[str, str], tmp_path: Path
    ) -> None:
        """Test that new OpenRouter configurations work with compatibility layer."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(sample_toml_configs["openrouter_new"])

        with open(config_file, "rb") as toml_file:
            data = tomllib.load(toml_file)
            ai_data = data["ai"]["router"]

        # Verify new provider maps to LangChainBackend
        provider = ai_data["provider"].lower()
        assert provider in supported_ai_backends
        assert supported_ai_backends[provider] == LangChainBackend

        # Verify configuration creates valid AIConfig
        config = LangChainBackend.get_config(
            name="router",
            provider=ai_data["provider"],
            api_key=ai_data["api_key"],
            model=ai_data["model"],
            base_url=ai_data.get("base_url"),
        )

        assert isinstance(config, AIConfig)
        assert config.name == "router"
        assert config.provider == "openrouter"
        assert config.api_key == "sk-or-test789"
        assert config.model == "anthropic/claude-3.5-sonnet"
        assert config.base_url == "https://openrouter.ai/api/v1"

    def test_mixed_configuration_handling(
        self, sample_toml_configs: Dict[str, str], tmp_path: Path
    ) -> None:
        """Test handling of mixed old/new configuration scenarios."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(sample_toml_configs["mixed_config"])

        with open(config_file, "rb") as toml_file:
            data = tomllib.load(toml_file)

            # Test modern OpenAI config
            openai_data = data["ai"]["openai-new"]
            config1 = LangChainBackend.get_config(
                name="openai-new",
                provider=openai_data["provider"],
                api_key=openai_data["api_key"],
                model=openai_data["model"],
            )
            assert config1.provider == "openai"

            # Test legacy DeepSeek config with deprecated field
            deepseek_data = data["ai"]["deepseek-old"]
            mock_logger = Mock()

            # Create backend to test mixed validation
            temp_config = AIConfig(
                name="deepseek-old",
                provider=deepseek_data["provider"],
                api_key=deepseek_data["api_key"],
                model=deepseek_data["model"],
            )
            # Simulate legacy field
            temp_config.service_provider = deepseek_data.get("service_provider")

            backend = LangChainBackend(temp_config, logger=mock_logger)
            warnings = backend._validate_mixed_configuration(temp_config)

            # Should detect legacy field usage
            assert len(warnings) > 0
            assert any("service_provider" in warning for warning in warnings)

    def test_legacy_openrouter_format_compatibility(
        self, sample_toml_configs: Dict[str, str], tmp_path: Path
    ) -> None:
        """Test that OpenRouter configurations with legacy format work unchanged."""
        config_file = tmp_path / "config.toml"
        config_file.write_text(sample_toml_configs["openrouter_legacy_format"])

        with open(config_file, "rb") as toml_file:
            data = tomllib.load(toml_file)
            ai_data = data["ai"]["openrouter-legacy"]

        # Verify OpenRouter config maps to LangChainBackend
        provider = ai_data["provider"].lower()
        assert provider in supported_ai_backends
        assert supported_ai_backends[provider] == LangChainBackend

        # Verify configuration creates valid AIConfig with validation
        config = LangChainBackend.get_config(
            name="openrouter-legacy",
            provider=ai_data["provider"],
            api_key=ai_data["api_key"],
            model=ai_data["model"],
            timeout=ai_data.get("timeout", 30),
            max_retries=ai_data.get("max_retries", 3),
        )

        assert isinstance(config, AIConfig)
        assert config.name == "openrouter-legacy"
        assert config.provider == "openrouter"
        assert config.api_key == "sk-or-legacy123"
        assert config.model == "openai/gpt-4"
        assert config.timeout == 45
        assert config.max_retries == 2

    def test_openrouter_environment_key_compatibility(self) -> None:
        """Test OpenRouter configuration with environment API key works."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-env-test123"}):
            config = LangChainBackend.get_config(
                name="test-openrouter-env",
                provider="openrouter",
                model="anthropic/claude-3-haiku",
            )

            assert isinstance(config, AIConfig)
            assert config.name == "test-openrouter-env"
            assert config.provider == "openrouter"
            assert config.model == "anthropic/claude-3-haiku"

    def test_openrouter_concurrent_configuration_compatibility(self) -> None:
        """Test OpenRouter configuration works under concurrent access."""
        results = []
        exceptions = []

        def create_openrouter_config(thread_id: int):
            try:
                config = LangChainBackend.get_config(
                    name=f"openrouter-thread-{thread_id}",
                    provider="openrouter",
                    api_key=f"sk-or-test-{thread_id:03d}",
                    model="anthropic/claude-3-sonnet",
                )
                results.append(config)
            except Exception as e:
                exceptions.append(e)

        # Create multiple threads
        threads = []
        for i in range(5):
            thread = threading.Thread(target=create_openrouter_config, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        # Verify all configurations created successfully
        assert len(results) == 5
        assert len(exceptions) == 0

        # Verify each config is unique and correct
        for i, config in enumerate(results):
            assert isinstance(config, AIConfig)
            assert config.provider == "openrouter"
            assert config.model == "anthropic/claude-3-sonnet"
            assert config.name == f"openrouter-thread-{i}"


class TestErrorMessageConsistency:
    """Test that error messages remain consistent with previous implementations."""

    def test_unsupported_provider_error(self) -> None:
        """Test error message for unsupported providers matches legacy pattern."""
        with pytest.raises(ValueError) as exc_info:
            LangChainBackend.get_config(
                name="test", provider="unsupported-provider", api_key="test-key"
            )

        error_message = str(exc_info.value)
        assert "valid service provider" in error_message.lower()

    def test_missing_api_key_error_openai(self) -> None:
        """Test OpenAI missing API key error matches legacy pattern."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError) as exc_info:
                LangChainBackend.get_config(name="test-openai", provider="openai", model="gpt-4")

            error_message = str(exc_info.value)
            assert "openai requires an api key" in error_message.lower()

    def test_missing_model_error_ollama(self) -> None:
        """Test Ollama missing model error matches legacy pattern."""
        with pytest.raises(ValueError) as exc_info:
            LangChainBackend.get_config(
                name="test-ollama", provider="ollama", base_url="http://localhost:11434"
            )

        error_message = str(exc_info.value)
        assert "ollama requires a model" in error_message.lower()

    def test_invalid_parameter_errors(self) -> None:
        """Test parameter validation errors match legacy patterns."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            # Test invalid max_retries
            with pytest.raises(ValueError) as exc_info:
                LangChainBackend.get_config(
                    name="test-openai", provider="openai", model="gpt-4", max_retries=-1
                )
            assert "positive integer max_retries" in str(exc_info.value)

            # Test invalid timeout
            with pytest.raises(ValueError) as exc_info:
                LangChainBackend.get_config(
                    name="test-openai", provider="openai", model="gpt-4", timeout=0
                )
            assert "timeout must be a positive integer" in str(exc_info.value)


class TestDeepSeekAPIKeyMigration:
    """Test DeepSeek API key migration from config to environment variable."""

    def test_config_api_key_only(self) -> None:
        """Test DeepSeek config with only config file API key."""
        with patch.dict(os.environ, {}, clear=True):
            config = LangChainBackend.get_config(
                name="test-deepseek",
                provider="deepseek",
                api_key="config-key",
                model="deepseek-chat",
            )

            assert config.api_key == "config-key"

    def test_environment_api_key_only(self) -> None:
        """Test DeepSeek config with only environment API key."""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}):
            config = LangChainBackend.get_config(
                name="test-deepseek", provider="deepseek", model="deepseek-chat"
            )

            # Environment key should be available during backend instantiation
            assert config.provider == "deepseek"

    def test_both_api_keys_environment_preferred(self) -> None:
        """Test DeepSeek with both config and environment keys - environment preferred."""
        mock_logger = Mock()

        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}):
            config = LangChainBackend.get_config(
                name="test-deepseek",
                provider="deepseek",
                api_key="config-key",
                model="deepseek-chat",
            )

            backend = LangChainBackend(config, logger=mock_logger)
            warnings = backend._validate_mixed_configuration(config)

            # Should warn about dual key sources
            assert any("api_key and DEEPSEEK_API_KEY" in warning for warning in warnings)

    def test_missing_deepseek_api_key_error(self) -> None:
        """Test error when DeepSeek API key is missing from both sources."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError) as exc_info:
                LangChainBackend.get_config(
                    name="test-deepseek", provider="deepseek", model="deepseek-chat"
                )

            error_message = str(exc_info.value)
            assert "deepseek requires an api key" in error_message.lower()


class TestBackendBehaviorIdentity:
    """Test that LangChain backend models behave identically to legacy implementations."""

    @pytest.fixture
    def mock_listing(self) -> "Listing":
        """Mock listing for testing."""
        from ai_marketplace_monitor.listing import Listing

        return Listing(
            marketplace="facebook",
            name="test-search",
            id="test-id",
            title="Test Item",
            image="https://example.com/image.jpg",
            price="$100",
            post_url="https://example.com/listing",
            location="Test City",
            seller="Test Seller",
            condition="New",
            description="Test description",
        )

    @pytest.fixture
    def mock_item_config(self) -> "FacebookItemConfig":
        """Mock item config for testing."""
        from ai_marketplace_monitor.facebook import FacebookItemConfig

        return FacebookItemConfig(
            name="Test Search",
            search_phrases=["test item", "search term"],
            description="Looking for test items",
            min_price=50,
            max_price=200,
        )

    @pytest.fixture
    def mock_marketplace_config(self) -> "FacebookMarketplaceConfig":
        """Mock marketplace config for testing."""
        from ai_marketplace_monitor.facebook import FacebookMarketplaceConfig

        return FacebookMarketplaceConfig(name="facebook")

    def test_prompt_generation_consistency(
        self,
        mock_listing: "Listing",
        mock_item_config: "FacebookItemConfig",
        mock_marketplace_config: "FacebookMarketplaceConfig",
    ) -> None:
        """Test that prompt generation remains consistent across backend types."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        prompt = backend.get_prompt(mock_listing, mock_item_config, mock_marketplace_config)

        # Verify prompt contains expected elements
        assert mock_item_config.name in prompt
        assert mock_listing.title in prompt
        assert mock_listing.condition in prompt
        assert mock_listing.price in prompt
        assert str(mock_item_config.min_price) in prompt
        assert str(mock_item_config.max_price) in prompt

    def test_config_validation_behavior(self) -> None:
        """Test that configuration validation behavior matches legacy patterns."""
        # Test valid configuration
        config = AIConfig(name="test", provider="openai", api_key="key")
        backend = LangChainBackend(config)
        assert backend.config == config

        # Test configuration with all providers
        providers = ["openai", "deepseek", "ollama", "openrouter"]
        for provider in providers:
            if provider == "openai":
                with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
                    cfg = LangChainBackend.get_config(name="test", provider=provider, model="test")
            elif provider == "deepseek":
                with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}):
                    cfg = LangChainBackend.get_config(name="test", provider=provider, model="test")
            elif provider == "ollama":
                cfg = LangChainBackend.get_config(name="test", provider=provider, model="test")
            elif provider == "openrouter":
                cfg = LangChainBackend.get_config(
                    name="test",
                    provider=provider,
                    api_key="sk-or-test-key",
                    model="anthropic/claude-3-sonnet",
                )

            assert cfg.provider.lower() == provider.lower()
            assert isinstance(cfg, AIConfig)


class TestPerformanceRegression:
    """Test performance regression prevention for compatibility layer."""

    def test_configuration_loading_performance(self) -> None:
        """Test that configuration loading performance hasn't regressed."""
        configs_data = []

        # Generate test configurations
        for i in range(50):
            configs_data.append(
                {
                    "name": f"test-config-{i}",
                    "provider": "openai",
                    "api_key": f"test-key-{i}",
                    "model": "gpt-4",
                }
            )

        start_time = time.time()

        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            for config_data in configs_data:
                config = LangChainBackend.get_config(**config_data)
                assert isinstance(config, AIConfig)

        elapsed_time = time.time() - start_time

        # Configuration loading should be fast (under 0.5 seconds for 50 configs)
        assert elapsed_time < 0.5, f"Configuration loading took too long: {elapsed_time:.2f}s"

    def test_backend_instantiation_performance(self) -> None:
        """Test that backend instantiation performance hasn't regressed."""
        configs = []

        # Create test configurations
        for i in range(20):
            configs.append(
                AIConfig(name=f"test-backend-{i}", provider="openai", api_key=f"test-key-{i}")
            )

        start_time = time.time()

        backends = []
        for config in configs:
            backend = LangChainBackend(config)
            backends.append(backend)
            assert backend.config == config

        elapsed_time = time.time() - start_time

        # Backend instantiation should be fast (under 0.2 seconds for 20 backends)
        assert elapsed_time < 0.2, f"Backend instantiation took too long: {elapsed_time:.2f}s"

    def test_provider_mapping_performance(self) -> None:
        """Test that provider mapping doesn't add significant overhead."""
        test_providers = ["openai", "deepseek", "ollama", "openrouter"]

        start_time = time.time()

        # Test provider mapping lookup performance
        for _ in range(100):
            for provider in test_providers:
                # Simulate provider lookup
                assert provider.lower() in supported_ai_backends
                backend_class = supported_ai_backends[provider.lower()]
                assert backend_class == LangChainBackend

        elapsed_time = time.time() - start_time

        # Provider mapping should be very fast
        assert elapsed_time < 0.05, f"Provider mapping took too long: {elapsed_time:.2f}s"


class TestConcurrentAccess:
    """Test thread safety and concurrent access patterns."""

    def test_concurrent_configuration_creation(self) -> None:
        """Test thread safety during concurrent configuration creation."""
        results = []
        exceptions = []

        def create_config(thread_id: int):
            try:
                with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
                    config = LangChainBackend.get_config(
                        name=f"thread-config-{thread_id}", provider="openai", model="gpt-4"
                    )
                    results.append(config)
            except Exception as e:
                exceptions.append(e)

        # Create multiple threads
        threads = []
        for i in range(10):
            thread = threading.Thread(target=create_config, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        # Verify all configurations created successfully
        assert len(results) == 10
        assert len(exceptions) == 0

        # Verify each config is unique and correct
        for _i, config in enumerate(results):
            assert isinstance(config, AIConfig)
            assert config.provider == "openai"
            assert config.model == "gpt-4"

    def test_concurrent_backend_instantiation(self) -> None:
        """Test thread safety during concurrent backend instantiation."""
        results = []
        exceptions = []

        def create_backend(thread_id: int):
            try:
                config = AIConfig(
                    name=f"thread-backend-{thread_id}", provider="openai", api_key="test-key"
                )
                backend = LangChainBackend(config)
                results.append(backend)
            except Exception as e:
                exceptions.append(e)

        # Create multiple threads
        threads = []
        for i in range(10):
            thread = threading.Thread(target=create_backend, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        # Verify all backends created successfully
        assert len(results) == 10
        assert len(exceptions) == 0

        # Verify each backend is properly initialized
        for backend in results:
            assert isinstance(backend, LangChainBackend)
            assert hasattr(backend, "_model_lock")
            assert backend._chat_model is None


class TestEdgeCaseHandling:
    """Test edge cases and unusual configuration scenarios."""

    def test_case_insensitive_provider_matching(self) -> None:
        """Test that provider matching remains case-insensitive."""
        test_cases = [
            ("OpenAI", "OpenAI"),
            ("openai", "openai"),
            ("DEEPSEEK", "DEEPSEEK"),
            ("deepseek", "deepseek"),
            ("Ollama", "Ollama"),
            ("ollama", "ollama"),
            ("openrouter", "openrouter"),
            ("OPENROUTER", "OPENROUTER"),
        ]

        for input_provider, expected_provider in test_cases:
            if input_provider.lower() == "openai":
                with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
                    config = LangChainBackend.get_config(
                        name="test", provider=input_provider, model="test"
                    )
            elif input_provider.lower() == "deepseek":
                with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}):
                    config = LangChainBackend.get_config(
                        name="test", provider=input_provider, model="test"
                    )
            elif input_provider.lower() == "ollama":
                config = LangChainBackend.get_config(
                    name="test", provider=input_provider, model="test"
                )
            elif input_provider.lower() == "openrouter":
                config = LangChainBackend.get_config(
                    name="test",
                    provider=input_provider,
                    api_key="sk-or-test-key",
                    model="anthropic/claude-3-sonnet",
                )

            # Provider is preserved as-is from input
            assert config.provider == expected_provider

    def test_empty_and_whitespace_values(self) -> None:
        """Test handling of empty and whitespace values."""
        # Test empty provider
        with pytest.raises(ValueError):
            LangChainBackend.get_config(name="test", provider="", api_key="test")

        # Test whitespace-only provider
        with pytest.raises(ValueError):
            LangChainBackend.get_config(name="test", provider="   ", api_key="test")

        # Test valid empty name (allowed by current implementation)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
            config = LangChainBackend.get_config(name="", provider="openai", model="test")
            assert config.name == ""

    def test_none_values_handling(self) -> None:
        """Test handling of None values in configuration."""
        # Test None provider (validation requires provider)
        with pytest.raises(ValueError, match="AIConfig must have a provider specified"):
            LangChainBackend.get_config(name="test", provider=None, api_key="test")

        # Test None name (allowed by current implementation)
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
            config = LangChainBackend.get_config(name=None, provider="openai", model="test")
            assert config.name is None

    def test_unicode_and_special_characters(self) -> None:
        """Test handling of unicode and special characters in configuration."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
            # Test unicode in name
            config = LangChainBackend.get_config(
                name="测试-backend", provider="openai", model="gpt-4"
            )
            assert config.name == "测试-backend"

            # Test special characters in model name
            config = LangChainBackend.get_config(
                name="test", provider="openai", model="gpt-4-0125-preview"
            )
            assert config.model == "gpt-4-0125-preview"


if __name__ == "__main__":
    # Run specific test classes for debugging
    pytest.main([__file__, "-v"])
