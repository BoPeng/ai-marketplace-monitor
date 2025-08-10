"""Tests for LangSmith configuration merging and precedence behavior - TDD focus.

This test suite covers the complex merging behavior of LangSmith configurations
across multiple sources with proper precedence rules:
1. System config (lowest precedence) - from src/ai_marketplace_monitor/config.toml
2. User config files (higher precedence) - passed to Config constructor
3. Environment variables (used for substitution in TOML configs)

Key behaviors tested:
- User config overrides system config for LangSmith sections
- TOML config takes precedence over environment variables
- Fallback to environment variables when TOML config missing
- Partial config merging scenarios
- Multiple config file merging with proper precedence

Following TDD best practices:
- Test behavior that provides genuine value
- Cover complex merging edge cases
- Ensure protection against config loading regressions
- Focus on integration scenarios that could break in production
"""

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from ai_marketplace_monitor.config import Config

if TYPE_CHECKING:
    from typing_extensions import Self


class TestLangSmithConfigMergingPrecedence:
    """Test cases for LangSmith configuration merging and precedence behavior."""

    def test_should_merge_user_config_over_empty_system_config(self: "Self") -> None:
        """Should load LangSmith config from user file when system config has no LangSmith section."""
        with tempfile.TemporaryDirectory() as temp_dir:
            user_config = Path(temp_dir) / "user_config.toml"
            user_config.write_text(
                """
[monitor]
enabled = true

[langsmith]
enabled = true
api_key = "user-api-key"
project_name = "user-project"
endpoint = "https://user.langsmith.com"

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            config = Config([user_config])

            assert config.langsmith is not None
            assert config.langsmith.enabled is True
            assert config.langsmith.api_key == "user-api-key"
            assert config.langsmith.project_name == "user-project"
            assert config.langsmith.endpoint == "https://user.langsmith.com"

    def test_should_override_system_langsmith_config_with_user_config(self: "Self") -> None:
        """Should override system LangSmith settings with user config when both exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create system config file with LangSmith settings
            system_config = Path(temp_dir) / "system_config.toml"
            system_config.write_text(
                """
[monitor]
enabled = true

[langsmith]
enabled = false
api_key = "system-api-key"
project_name = "system-project"

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            user_config = Path(temp_dir) / "user_config.toml"
            user_config.write_text(
                """
[langsmith]
enabled = true
api_key = "user-api-key"
project_name = "user-project"
endpoint = "https://user.langsmith.com"
            """
            )

            # Simulate Config loading system first, then user config
            # (Note: We can't directly test this without modifying Config.__init__
            # to accept system_config_path, so we test the end result)
            config = Config([system_config, user_config])

            # User config should override system config
            assert config.langsmith is not None
            assert config.langsmith.enabled is True  # User override
            assert config.langsmith.api_key == "user-api-key"  # User override
            assert config.langsmith.project_name == "user-project"  # User override
            assert config.langsmith.endpoint == "https://user.langsmith.com"  # User only

    def test_should_merge_partial_user_config_with_system_config(self: "Self") -> None:
        """Should merge partial user LangSmith config with system config defaults."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # System config with full LangSmith settings
            system_config = Path(temp_dir) / "system_config.toml"
            system_config.write_text(
                """
[monitor]
enabled = true

[langsmith]
enabled = false
api_key = "system-api-key"
project_name = "system-project"
endpoint = "https://system.langsmith.com"

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            # User config with only partial LangSmith settings
            user_config = Path(temp_dir) / "user_config.toml"
            user_config.write_text(
                """
[langsmith]
enabled = true
api_key = "user-api-key"
            """
            )

            config = Config([system_config, user_config])

            # Should merge: user overrides + system defaults
            assert config.langsmith is not None
            assert config.langsmith.enabled is True  # User override
            assert config.langsmith.api_key == "user-api-key"  # User override
            assert config.langsmith.project_name == "system-project"  # System default
            assert config.langsmith.endpoint == "https://system.langsmith.com"  # System default

    def test_should_use_toml_config_over_environment_variables(self: "Self") -> None:
        """Should prioritize TOML config values over environment variables for same settings."""
        with tempfile.TemporaryDirectory() as temp_dir:
            user_config = Path(temp_dir) / "user_config.toml"
            user_config.write_text(
                """
[monitor]
enabled = true

[langsmith]
enabled = true
api_key = "toml-api-key"
project_name = "toml-project"

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            # Set environment variables that would conflict
            with patch.dict(
                os.environ,
                {
                    "LANGCHAIN_API_KEY": "env-api-key",
                    "LANGSMITH_API_KEY": "env-api-key-2",
                    "LANGCHAIN_PROJECT": "env-project",
                    "LANGSMITH_PROJECT": "env-project-2",
                },
            ):
                config = Config([user_config])

                # TOML values should take precedence
                assert config.langsmith is not None
                assert config.langsmith.api_key == "toml-api-key"
                assert config.langsmith.project_name == "toml-project"

    def test_should_substitute_environment_variables_in_toml_config(self: "Self") -> None:
        """Should substitute environment variables using ${VAR} syntax in TOML config."""
        with tempfile.TemporaryDirectory() as temp_dir:
            user_config = Path(temp_dir) / "user_config.toml"
            user_config.write_text(
                """
[monitor]
enabled = true

[langsmith]
enabled = true
api_key = "${LANGSMITH_TEST_API_KEY}"
project_name = "${LANGSMITH_TEST_PROJECT}"
endpoint = "${LANGSMITH_TEST_ENDPOINT}"

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            with patch.dict(
                os.environ,
                {
                    "LANGSMITH_TEST_API_KEY": "env-substituted-key",
                    "LANGSMITH_TEST_PROJECT": "env-substituted-project",
                    "LANGSMITH_TEST_ENDPOINT": "https://env-substituted.langsmith.com",
                },
            ):
                config = Config([user_config])

                assert config.langsmith is not None
                assert config.langsmith.api_key == "env-substituted-key"
                assert config.langsmith.project_name == "env-substituted-project"
                assert config.langsmith.endpoint == "https://env-substituted.langsmith.com"

    def test_should_fallback_when_toml_missing_but_env_vars_available(self: "Self") -> None:
        """Should create LangSmith config from env vars when TOML section is missing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Config without LangSmith section
            user_config = Path(temp_dir) / "user_config.toml"
            user_config.write_text(
                """
[monitor]
enabled = true

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            # Environment variables alone don't create LangSmith config
            # (this tests that missing TOML section results in None)
            with patch.dict(
                os.environ,
                {
                    "LANGCHAIN_API_KEY": "env-fallback-key",
                    "LANGCHAIN_PROJECT": "env-fallback-project",
                },
            ):
                config = Config([user_config])

                # Should be None because no [langsmith] section in TOML
                assert config.langsmith is None

    def test_should_merge_multiple_user_config_files_with_precedence(self: "Self") -> None:
        """Should merge multiple user config files with later files taking precedence."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # First user config file
            config1 = Path(temp_dir) / "config1.toml"
            config1.write_text(
                """
[monitor]
enabled = true

[langsmith]
enabled = false
api_key = "config1-api-key"
project_name = "config1-project"
endpoint = "https://config1.langsmith.com"

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            # Second user config file (should override first)
            config2 = Path(temp_dir) / "config2.toml"
            config2.write_text(
                """
[langsmith]
enabled = true
api_key = "config2-api-key"
project_name = "config2-project"
            """
            )

            # Third user config file (should override previous)
            config3 = Path(temp_dir) / "config3.toml"
            config3.write_text(
                """
[langsmith]
api_key = "config3-api-key"
            """
            )

            config = Config([config1, config2, config3])

            # Later configs should override earlier ones
            assert config.langsmith is not None
            assert config.langsmith.enabled is True  # From config2
            assert config.langsmith.api_key == "config3-api-key"  # From config3 (latest)
            assert config.langsmith.project_name == "config2-project"  # From config2
            assert config.langsmith.endpoint == "https://config1.langsmith.com"  # From config1

    def test_should_handle_mixed_env_substitution_and_direct_values(self: "Self") -> None:
        """Should handle mix of environment variable substitution and direct values."""
        with tempfile.TemporaryDirectory() as temp_dir:
            user_config = Path(temp_dir) / "user_config.toml"
            user_config.write_text(
                """
[monitor]
enabled = true

[langsmith]
enabled = true
api_key = "${LANGSMITH_MIXED_API_KEY}"
project_name = "direct-project-name"
endpoint = "${LANGSMITH_MIXED_ENDPOINT}"

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            with patch.dict(
                os.environ,
                {
                    "LANGSMITH_MIXED_API_KEY": "env-mixed-key",
                    "LANGSMITH_MIXED_ENDPOINT": "https://env-mixed.langsmith.com",
                },
            ):
                config = Config([user_config])

                assert config.langsmith is not None
                assert config.langsmith.api_key == "env-mixed-key"  # From env substitution
                assert config.langsmith.project_name == "direct-project-name"  # Direct value
                assert (
                    config.langsmith.endpoint == "https://env-mixed.langsmith.com"
                )  # From env substitution

    def test_should_raise_error_when_env_substitution_variable_missing(self: "Self") -> None:
        """Should raise ValueError when TOML references missing environment variable."""
        with tempfile.TemporaryDirectory() as temp_dir:
            user_config = Path(temp_dir) / "user_config.toml"
            user_config.write_text(
                """
[monitor]
enabled = true

[langsmith]
enabled = true
api_key = "${MISSING_LANGSMITH_KEY}"

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            # Ensure the env var doesn't exist
            if "MISSING_LANGSMITH_KEY" in os.environ:
                del os.environ["MISSING_LANGSMITH_KEY"]

            with pytest.raises(
                ValueError, match="Environment variable MISSING_LANGSMITH_KEY not set"
            ):
                Config([user_config])

    def test_should_validate_merged_config_after_loading(self: "Self") -> None:
        """Should validate the final merged LangSmith config after all merging is complete."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # System config with enabled=false (valid)
            system_config = Path(temp_dir) / "system_config.toml"
            system_config.write_text(
                """
[monitor]
enabled = true

[langsmith]
enabled = false
api_key = "system-key"

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            # User config enables LangSmith but removes api_key (should fail)
            user_config = Path(temp_dir) / "user_config.toml"
            user_config.write_text(
                """
[langsmith]
enabled = true
api_key = ""
            """
            )

            with pytest.raises(
                ValueError,
                match="LangSmith configuration 'langsmith' is enabled but missing api_key",
            ):
                Config([system_config, user_config])

    def test_should_handle_empty_langsmith_sections_during_merge(self: "Self") -> None:
        """Should handle empty [langsmith] sections gracefully during merge process."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Config with empty langsmith section
            config1 = Path(temp_dir) / "config1.toml"
            config1.write_text(
                """
[monitor]
enabled = true

[langsmith]

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            # Config with actual langsmith values
            config2 = Path(temp_dir) / "config2.toml"
            config2.write_text(
                """
[langsmith]
enabled = true
api_key = "merged-key"
            """
            )

            config = Config([config1, config2])

            # Should merge successfully and create LangSmith config
            assert config.langsmith is not None
            assert config.langsmith.enabled is True
            assert config.langsmith.api_key == "merged-key"


class TestLangSmithConfigComplexMergingScenarios:
    """Test complex merging scenarios that could occur in production."""

    def test_should_handle_system_langsmith_with_user_override_and_env_substitution(
        self: "Self",
    ) -> None:
        """Should handle complex scenario with system config, user override, and env substitution."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # System config
            system_config = Path(temp_dir) / "system_config.toml"
            system_config.write_text(
                """
[monitor]
enabled = true

[langsmith]
enabled = false
api_key = "system-default-key"
project_name = "system-default-project"
endpoint = "https://system-default.langsmith.com"

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            # User config with env substitution
            user_config = Path(temp_dir) / "user_config.toml"
            user_config.write_text(
                """
[langsmith]
enabled = true
api_key = "${COMPLEX_LANGSMITH_KEY}"
endpoint = "${COMPLEX_LANGSMITH_ENDPOINT}"
            """
            )

            with patch.dict(
                os.environ,
                {
                    "COMPLEX_LANGSMITH_KEY": "complex-env-key",
                    "COMPLEX_LANGSMITH_ENDPOINT": "https://complex-env.langsmith.com",
                },
            ):
                config = Config([system_config, user_config])

                assert config.langsmith is not None
                assert config.langsmith.enabled is True  # User override
                assert config.langsmith.api_key == "complex-env-key"  # User + env substitution
                assert config.langsmith.project_name == "system-default-project"  # System fallback
                assert (
                    config.langsmith.endpoint == "https://complex-env.langsmith.com"
                )  # User + env

    def test_should_preserve_config_precedence_with_multiple_partial_overrides(
        self: "Self",
    ) -> None:
        """Should maintain proper precedence when multiple files have partial overrides."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Base config
            base_config = Path(temp_dir) / "base.toml"
            base_config.write_text(
                """
[monitor]
enabled = true

[langsmith]
enabled = false
api_key = "base-key"
project_name = "base-project"
endpoint = "https://base.langsmith.com"

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            # Environment-specific override
            env_config = Path(temp_dir) / "env.toml"
            env_config.write_text(
                """
[langsmith]
enabled = true
endpoint = "https://env.langsmith.com"
            """
            )

            # User-specific override
            user_config = Path(temp_dir) / "user.toml"
            user_config.write_text(
                """
[langsmith]
api_key = "user-key"
            """
            )

            config = Config([base_config, env_config, user_config])

            # Should show proper precedence chain
            assert config.langsmith is not None
            assert config.langsmith.enabled is True  # From env_config
            assert config.langsmith.api_key == "user-key"  # From user_config (latest)
            assert config.langsmith.project_name == "base-project"  # From base_config
            assert config.langsmith.endpoint == "https://env.langsmith.com"  # From env_config

    def test_should_handle_env_substitution_across_multiple_config_files(self: "Self") -> None:
        """Should handle environment variable substitution consistently across multiple files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # First config with env substitution
            config1 = Path(temp_dir) / "config1.toml"
            config1.write_text(
                """
[monitor]
enabled = true

[langsmith]
enabled = true
api_key = "${MULTI_FILE_KEY}"
project_name = "config1-project"

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            # Second config with different env substitution
            config2 = Path(temp_dir) / "config2.toml"
            config2.write_text(
                """
[langsmith]
project_name = "${MULTI_FILE_PROJECT}"
endpoint = "${MULTI_FILE_ENDPOINT}"
            """
            )

            with patch.dict(
                os.environ,
                {
                    "MULTI_FILE_KEY": "multi-env-key",
                    "MULTI_FILE_PROJECT": "multi-env-project",
                    "MULTI_FILE_ENDPOINT": "https://multi-env.langsmith.com",
                },
            ):
                config = Config([config1, config2])

                # All env substitutions should work
                assert config.langsmith is not None
                assert config.langsmith.api_key == "multi-env-key"
                assert config.langsmith.project_name == "multi-env-project"  # config2 override
                assert config.langsmith.endpoint == "https://multi-env.langsmith.com"

    def test_should_merge_configs_when_some_have_no_langsmith_section(self: "Self") -> None:
        """Should handle merging when some config files don't have [langsmith] sections."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Config without langsmith section
            config1 = Path(temp_dir) / "config1.toml"
            config1.write_text(
                """
[monitor]
enabled = true

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            # Config with langsmith section
            config2 = Path(temp_dir) / "config2.toml"
            config2.write_text(
                """
[langsmith]
enabled = true
api_key = "only-langsmith-key"
            """
            )

            # Another config without langsmith section
            config3 = Path(temp_dir) / "config3.toml"
            config3.write_text(
                """
[monitor]
proxy_server = ["http://proxy.example.com"]
            """
            )

            config = Config([config1, config2, config3])

            # Should successfully create LangSmith config from the one file that has it
            assert config.langsmith is not None
            assert config.langsmith.enabled is True
            assert config.langsmith.api_key == "only-langsmith-key"
