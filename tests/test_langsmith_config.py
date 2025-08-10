"""Tests for LangSmithConfig class - following TDD principles.

This test suite covers the LangSmithConfig class which provides configuration
for LangSmith tracing integration. Tests focus on valuable behaviors including:
- Configuration instantiation and defaults
- Environment variable substitution (inherited from BaseConfig)
- Validation logic for enabled/api_key relationships
- Integration with the main Config class

Following TDD best practices:
- Test behavior, not implementation details
- Use descriptive test names explaining expected behavior
- Focus on edge cases and error conditions
- Ensure tests provide genuine protection against regressions
"""

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from ai_marketplace_monitor.config import Config, LangSmithConfig

if TYPE_CHECKING:
    from typing_extensions import Self


class TestLangSmithConfig:
    """Test cases for LangSmithConfig class - business logic focus."""

    def test_should_instantiate_with_default_values(self: "Self") -> None:
        """Should create LangSmithConfig with proper default values."""
        config = LangSmithConfig(name="test_langsmith")

        assert config.name == "test_langsmith"
        assert config.enabled is False
        assert config.api_key is None
        assert config.project_name is None
        assert config.endpoint is None

    def test_should_instantiate_with_custom_values(self: "Self") -> None:
        """Should create LangSmithConfig with custom values provided."""
        config = LangSmithConfig(
            name="custom_langsmith",
            enabled=True,
            api_key="ls-test-key",
            project_name="test-project",
            endpoint="https://custom.langsmith.com",
        )

        assert config.name == "custom_langsmith"
        assert config.enabled is True
        assert config.api_key == "ls-test-key"
        assert config.project_name == "test-project"
        assert config.endpoint == "https://custom.langsmith.com"

    def test_should_substitute_environment_variables_in_api_key(self: "Self") -> None:
        """Should substitute environment variables using ${VAR_NAME} syntax in api_key field."""
        with patch.dict(os.environ, {"LANGSMITH_API_KEY": "env-test-key"}):
            config = LangSmithConfig(name="test_langsmith", api_key="${LANGSMITH_API_KEY}")

            assert config.api_key == "env-test-key"

    def test_should_substitute_environment_variables_in_project_name(self: "Self") -> None:
        """Should substitute environment variables in project_name field."""
        with patch.dict(os.environ, {"PROJECT_NAME": "env-project"}):
            config = LangSmithConfig(name="test_langsmith", project_name="${PROJECT_NAME}")

            assert config.project_name == "env-project"

    def test_should_substitute_environment_variables_in_endpoint(self: "Self") -> None:
        """Should substitute environment variables in endpoint field."""
        with patch.dict(os.environ, {"LANGSMITH_ENDPOINT": "https://env.langsmith.com"}):
            config = LangSmithConfig(name="test_langsmith", endpoint="${LANGSMITH_ENDPOINT}")

            assert config.endpoint == "https://env.langsmith.com"

    def test_should_raise_error_when_environment_variable_missing(self: "Self") -> None:
        """Should raise ValueError when referenced environment variable does not exist."""
        # Ensure the env var doesn't exist
        env_key = "NONEXISTENT_LANGSMITH_KEY"
        if env_key in os.environ:
            del os.environ[env_key]

        with pytest.raises(ValueError, match=f"Environment variable {env_key} not set"):
            LangSmithConfig(name="test_langsmith", api_key=f"${{{env_key}}}")

    def test_should_not_substitute_regular_strings(self: "Self") -> None:
        """Should not substitute strings that don't match ${VAR} pattern."""
        config = LangSmithConfig(
            name="test_langsmith",
            api_key="regular-api-key",
            project_name="regular-project",
            endpoint="https://regular.endpoint.com",
        )

        assert config.api_key == "regular-api-key"
        assert config.project_name == "regular-project"
        assert config.endpoint == "https://regular.endpoint.com"

    def test_should_pass_validation_when_enabled_false(self: "Self") -> None:
        """Should not raise error when enabled=False regardless of api_key value."""
        # Should work with no api_key
        config1 = LangSmithConfig(name="test1", enabled=False, api_key=None)
        assert config1.enabled is False
        assert config1.api_key is None

        # Should also work with api_key present
        config2 = LangSmithConfig(name="test2", enabled=False, api_key="some-key")
        assert config2.enabled is False
        assert config2.api_key == "some-key"

    def test_should_pass_validation_when_enabled_true_with_api_key(self: "Self") -> None:
        """Should not raise error when enabled=True and api_key is provided."""
        config = LangSmithConfig(name="test_langsmith", enabled=True, api_key="valid-api-key")

        assert config.enabled is True
        assert config.api_key == "valid-api-key"

    def test_should_raise_error_when_enabled_true_without_api_key(self: "Self") -> None:
        """Should raise ValueError when enabled=True but api_key is None."""
        with pytest.raises(
            ValueError,
            match="LangSmith configuration 'test_langsmith' is enabled but missing api_key",
        ):
            LangSmithConfig(name="test_langsmith", enabled=True, api_key=None)

    def test_should_raise_error_when_enabled_true_with_empty_api_key(self: "Self") -> None:
        """Should raise ValueError when enabled=True but api_key is empty string."""
        with pytest.raises(
            ValueError,
            match="LangSmith configuration 'test_langsmith' is enabled but missing api_key",
        ):
            LangSmithConfig(name="test_langsmith", enabled=True, api_key="")

    def test_should_handle_enabled_none_as_false(self: "Self") -> None:
        """Should convert enabled=None to enabled=False in handle_enabled method."""
        config = LangSmithConfig(name="test_langsmith", enabled=None)
        assert config.enabled is False

    def test_should_handle_enabled_boolean_conversion_with_api_key_validation(
        self: "Self",
    ) -> None:
        """Should properly handle enabled field conversion before api_key validation."""
        # enabled=None should become False, so api_key validation should not trigger
        config = LangSmithConfig(name="test_langsmith", enabled=None, api_key=None)

        assert config.enabled is False
        assert config.api_key is None


class TestConfigLangSmithIntegration:
    """Test cases for LangSmith integration with main Config class."""

    def test_should_create_langsmith_config_from_toml_section(self: "Self") -> None:
        """Should create LangSmithConfig from [langsmith] section in TOML config."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "test_config.toml"
            config_file.write_text(
                """
[monitor]
enabled = true

[langsmith]
enabled = true
api_key = "test-api-key"
project_name = "test-project"
endpoint = "https://test.langsmith.com"

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            config = Config([config_file])

            assert config.langsmith is not None
            assert config.langsmith.enabled is True
            assert config.langsmith.api_key == "test-api-key"
            assert config.langsmith.project_name == "test-project"
            assert config.langsmith.endpoint == "https://test.langsmith.com"

    def test_should_handle_missing_langsmith_section(self: "Self") -> None:
        """Should set langsmith to None when [langsmith] section is missing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "test_config.toml"
            config_file.write_text(
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

            config = Config([config_file])

            assert config.langsmith is None

    def test_should_handle_empty_langsmith_section(self: "Self") -> None:
        """Should set langsmith to None when [langsmith] section is empty."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "test_config.toml"
            config_file.write_text(
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

            config = Config([config_file])

            assert config.langsmith is None

    def test_should_substitute_environment_variables_in_config_loading(self: "Self") -> None:
        """Should substitute environment variables when loading from TOML config."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "test_config.toml"
            config_file.write_text(
                """
[monitor]
enabled = true

[langsmith]
enabled = true
api_key = "${LANGSMITH_TEST_KEY}"
project_name = "${LANGSMITH_TEST_PROJECT}"

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
                    "LANGSMITH_TEST_KEY": "env-loaded-key",
                    "LANGSMITH_TEST_PROJECT": "env-loaded-project",
                },
            ):
                config = Config([config_file])

                assert config.langsmith is not None
                assert config.langsmith.api_key == "env-loaded-key"
                assert config.langsmith.project_name == "env-loaded-project"

    def test_should_raise_error_during_config_loading_when_enabled_without_api_key(
        self: "Self",
    ) -> None:
        """Should raise ValueError during Config loading when LangSmith is enabled but missing api_key."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "test_config.toml"
            config_file.write_text(
                """
[monitor]
enabled = true

[langsmith]
enabled = true

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            with pytest.raises(
                ValueError,
                match="LangSmith configuration 'langsmith' is enabled but missing api_key",
            ):
                Config([config_file])

    def test_should_handle_partial_langsmith_config_when_disabled(self: "Self") -> None:
        """Should successfully load config with partial LangSmith settings when disabled."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "test_config.toml"
            config_file.write_text(
                """
[monitor]
enabled = true

[langsmith]
enabled = false
project_name = "test-project"

[marketplace.facebook]
search_city = ["123456"]

[user.testuser]
email = "test@example.com"

[item.testitem]
search_phrases = ["test"]
            """
            )

            config = Config([config_file])

            assert config.langsmith is not None
            assert config.langsmith.enabled is False
            assert config.langsmith.api_key is None
            assert config.langsmith.project_name == "test-project"


class TestLangSmithConfigEdgeCases:
    """Test edge cases and boundary conditions for LangSmithConfig."""

    def test_should_handle_multiple_environment_variables(self: "Self") -> None:
        """Should handle multiple environment variable substitutions in same config."""
        with patch.dict(
            os.environ,
            {
                "LANGSMITH_KEY": "multi-env-key",
                "LANGSMITH_PROJECT": "multi-env-project",
                "LANGSMITH_ENDPOINT": "https://multi.langsmith.com",
            },
        ):
            config = LangSmithConfig(
                name="multi_env_test",
                enabled=True,
                api_key="${LANGSMITH_KEY}",
                project_name="${LANGSMITH_PROJECT}",
                endpoint="${LANGSMITH_ENDPOINT}",
            )

            assert config.api_key == "multi-env-key"
            assert config.project_name == "multi-env-project"
            assert config.endpoint == "https://multi.langsmith.com"

    def test_should_preserve_none_values_for_optional_fields(self: "Self") -> None:
        """Should preserve None values for optional fields when not provided."""
        config = LangSmithConfig(name="minimal_config", enabled=False)

        assert config.enabled is False
        assert config.api_key is None
        assert config.project_name is None
        assert config.endpoint is None

    def test_should_handle_whitespace_in_field_values(self: "Self") -> None:
        """Should preserve whitespace in configuration field values."""
        config = LangSmithConfig(
            name="whitespace_test",
            enabled=False,
            api_key=" key-with-spaces ",
            project_name=" project with spaces ",
            endpoint=" https://endpoint.com ",
        )

        assert config.api_key == " key-with-spaces "
        assert config.project_name == " project with spaces "
        assert config.endpoint == " https://endpoint.com "

    def test_should_handle_special_characters_in_values(self: "Self") -> None:
        """Should handle special characters in configuration values."""
        config = LangSmithConfig(
            name="special_chars",
            enabled=False,
            api_key="key-with-special!@#$%^&*()chars",
            project_name="project/with\\special:chars",
            endpoint="https://endpoint.com/path?param=value&other=123",
        )

        assert config.api_key == "key-with-special!@#$%^&*()chars"
        assert config.project_name == "project/with\\special:chars"
        assert config.endpoint == "https://endpoint.com/path?param=value&other=123"

    def test_should_validate_after_environment_substitution(self: "Self") -> None:
        """Should validate api_key requirement after environment variable substitution."""
        with patch.dict(os.environ, {"EMPTY_LANGSMITH_KEY": ""}):
            # Should fail because env var expands to empty string
            with pytest.raises(
                ValueError,
                match="LangSmith configuration 'env_validation' is enabled but missing api_key",
            ):
                LangSmithConfig(
                    name="env_validation", enabled=True, api_key="${EMPTY_LANGSMITH_KEY}"
                )

    def test_should_handle_boolean_enabled_values_correctly(self: "Self") -> None:
        """Should properly handle different boolean representations for enabled field."""
        # Test explicit True
        config1 = LangSmithConfig(name="test1", enabled=True, api_key="key")
        assert config1.enabled is True

        # Test explicit False
        config2 = LangSmithConfig(name="test2", enabled=False)
        assert config2.enabled is False

        # Test None (should become False)
        config3 = LangSmithConfig(name="test3", enabled=None)
        assert config3.enabled is False


class TestLangSmithConfigMethodCoverage:
    """Test cases to ensure all LangSmithConfig methods are properly covered."""

    def test_should_call_handle_methods_during_instantiation(self: "Self") -> None:
        """Should verify that handle_* methods are called during __post_init__."""
        # This test ensures that our validation methods are being invoked
        # by testing their side effects (exceptions) which confirms they're called

        # handle_api_key should be called and raise error for enabled=True, api_key=None
        with pytest.raises(ValueError, match="missing api_key"):
            LangSmithConfig(name="test", enabled=True, api_key=None)

        # handle_enabled should be called and convert None to False
        config = LangSmithConfig(name="test", enabled=None)
        assert config.enabled is False  # Confirms handle_enabled was called

        # Both methods should work together correctly
        config2 = LangSmithConfig(name="test", enabled=True, api_key="valid-key")
        assert config2.enabled is True
        assert config2.api_key == "valid-key"
