"""Tests for langsmith_utils.py with TOML configuration integration.

This test suite covers the langsmith_utils functions with both environment variable
backward compatibility and new TOML configuration support.

Following TDD principles:
- RED: Write failing tests that describe desired behavior
- GREEN: Write minimal code to make tests pass
- REFACTOR: Improve code while keeping tests green

Test coverage focuses on valuable behaviors including:
- TOML config precedence over environment variables
- Environment variable fallback when TOML config is None
- Mixed scenarios with partial TOML and env configurations
- configure_langsmith_environment() function behavior
- Edge cases and error conditions
- Integration with logging functionality
"""

import os
from logging import Logger
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

from ai_marketplace_monitor.langsmith_utils import (
    configure_langsmith_environment,
    get_langsmith_config,
    is_langsmith_enabled,
    log_langsmith_status,
)

if TYPE_CHECKING:
    from typing_extensions import Self


class TestIsLangSmithEnabled:
    """Test cases for is_langsmith_enabled function - environment variable precedence."""

    def setup_method(self: "Self") -> None:
        """Clean up environment variables before each test."""
        env_vars_to_clear = [
            "LANGCHAIN_TRACING_V2",
            "LANGCHAIN_API_KEY",
            "LANGCHAIN_PROJECT",
            "LANGSMITH_TRACING",
            "LANGSMITH_API_KEY",
            "LANGSMITH_PROJECT",
        ]
        for var in env_vars_to_clear:
            if var in os.environ:
                del os.environ[var]

    def test_should_return_true_when_langchain_variables_are_properly_set(self: "Self") -> None:
        """Should return True when LANGCHAIN_TRACING_V2=true and LANGCHAIN_API_KEY is set."""
        with patch.dict(
            os.environ, {"LANGCHAIN_TRACING_V2": "true", "LANGCHAIN_API_KEY": "lc-test-key-123"}
        ):
            assert is_langsmith_enabled() is True

    def test_should_return_true_with_different_tracing_values(self: "Self") -> None:
        """Should return True for various boolean representations of tracing enabled."""
        test_cases = ["true", "TRUE", "True", "1", "yes", "YES", "Yes"]

        for tracing_value in test_cases:
            with patch.dict(
                os.environ,
                {"LANGCHAIN_TRACING_V2": tracing_value, "LANGCHAIN_API_KEY": "test-key"},
            ):
                assert is_langsmith_enabled() is True, f"Failed for tracing value: {tracing_value}"

    def test_should_return_false_when_tracing_disabled_langchain(self: "Self") -> None:
        """Should return False when LANGCHAIN_TRACING_V2 is set to false values."""
        false_values = ["false", "FALSE", "False", "0", "no", "NO", "No", ""]

        for tracing_value in false_values:
            with patch.dict(
                os.environ,
                {"LANGCHAIN_TRACING_V2": tracing_value, "LANGCHAIN_API_KEY": "test-key"},
            ):
                assert is_langsmith_enabled() is False, f"Failed for false value: {tracing_value}"

    def test_should_return_false_when_api_key_missing_langchain(self: "Self") -> None:
        """Should return False when LANGCHAIN_TRACING_V2 is true but API key is missing."""
        with patch.dict(os.environ, {"LANGCHAIN_TRACING_V2": "true"}):
            assert is_langsmith_enabled() is False

    def test_should_return_false_when_api_key_empty_langchain(self: "Self") -> None:
        """Should return False when LANGCHAIN_API_KEY is empty string or whitespace."""
        empty_values = ["", "   ", "\t", "\n"]

        for api_key_value in empty_values:
            with patch.dict(
                os.environ, {"LANGCHAIN_TRACING_V2": "true", "LANGCHAIN_API_KEY": api_key_value}
            ):
                assert (
                    is_langsmith_enabled() is False
                ), f"Failed for empty API key: '{api_key_value}'"

    def test_should_fallback_to_legacy_langsmith_variables(self: "Self") -> None:
        """Should use LANGSMITH_* variables when LANGCHAIN_* variables are not set."""
        with patch.dict(
            os.environ, {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "ls-test-key-123"}
        ):
            assert is_langsmith_enabled() is True

    def test_should_fallback_with_different_legacy_tracing_values(self: "Self") -> None:
        """Should return True for various boolean representations in legacy LANGSMITH_TRACING."""
        test_cases = ["true", "TRUE", "True", "1", "yes", "YES", "Yes"]

        for tracing_value in test_cases:
            with patch.dict(
                os.environ, {"LANGSMITH_TRACING": tracing_value, "LANGSMITH_API_KEY": "test-key"}
            ):
                assert (
                    is_langsmith_enabled() is True
                ), f"Failed for legacy tracing value: {tracing_value}"

    def test_should_prioritize_langchain_over_langsmith_variables(self: "Self") -> None:
        """Should use LANGCHAIN_* variables when both LANGCHAIN_* and LANGSMITH_* are set."""
        # Test true precedence: LANGCHAIN_TRACING_V2 is truthy, so LANGSMITH_TRACING is ignored
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "lc-key",
                "LANGSMITH_TRACING": "false",  # This should be ignored
                "LANGSMITH_API_KEY": "",  # This should be ignored
            },
        ):
            assert is_langsmith_enabled() is True

        # Test API key precedence: LANGCHAIN_API_KEY is set, so LANGSMITH_API_KEY is ignored
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "lc-key",  # This should be used
                "LANGSMITH_TRACING": "true",
                "LANGSMITH_API_KEY": "",  # This should be ignored
            },
        ):
            assert is_langsmith_enabled() is True

    def test_should_use_partial_fallback_for_mixed_scenarios(self: "Self") -> None:
        """Should use LANGCHAIN_* for some vars and LANGSMITH_* for others when mixed."""
        # LANGCHAIN_TRACING_V2 is set but no API key, fallback to LANGSMITH_API_KEY
        with patch.dict(
            os.environ, {"LANGCHAIN_TRACING_V2": "true", "LANGSMITH_API_KEY": "ls-fallback-key"}
        ):
            assert is_langsmith_enabled() is True

        # LANGSMITH_TRACING is set but no legacy API key, fallback to LANGCHAIN_API_KEY
        with patch.dict(
            os.environ, {"LANGSMITH_TRACING": "true", "LANGCHAIN_API_KEY": "lc-fallback-key"}
        ):
            assert is_langsmith_enabled() is True

    def test_should_handle_no_environment_variables_set(self: "Self") -> None:
        """Should return False when no relevant environment variables are set."""
        # Ensure clean environment
        assert is_langsmith_enabled() is False

    def test_should_handle_undefined_environment_variables(self: "Self") -> None:
        """Should handle cases where environment variables are completely unset."""
        # Test with completely clean environment by explicitly checking getenv behavior
        with patch.dict(os.environ, {}, clear=True):
            assert is_langsmith_enabled() is False

    def test_should_return_false_for_invalid_boolean_values(self: "Self") -> None:
        """Should return False for invalid boolean values in tracing variables."""
        invalid_values = ["maybe", "sometimes", "2", "-1", "on", "off", "enabled"]

        for invalid_value in invalid_values:
            with patch.dict(
                os.environ,
                {"LANGCHAIN_TRACING_V2": invalid_value, "LANGCHAIN_API_KEY": "test-key"},
            ):
                assert (
                    is_langsmith_enabled() is False
                ), f"Should be False for invalid value: {invalid_value}"

    def test_should_require_both_tracing_and_api_key_for_legacy(self: "Self") -> None:
        """Should require both LANGSMITH_TRACING and LANGSMITH_API_KEY for legacy support."""
        # Only tracing set
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "true"}):
            assert is_langsmith_enabled() is False

        # Only API key set
        with patch.dict(os.environ, {"LANGSMITH_API_KEY": "test-key"}):
            assert is_langsmith_enabled() is False


class TestGetLangSmithConfig:
    """Test cases for get_langsmith_config function - configuration retrieval."""

    def setup_method(self: "Self") -> None:
        """Clean up environment variables before each test."""
        env_vars_to_clear = [
            "LANGCHAIN_TRACING_V2",
            "LANGCHAIN_API_KEY",
            "LANGCHAIN_PROJECT",
            "LANGSMITH_TRACING",
            "LANGSMITH_API_KEY",
            "LANGSMITH_PROJECT",
        ]
        for var in env_vars_to_clear:
            if var in os.environ:
                del os.environ[var]

    def test_should_return_langchain_config_when_variables_set(self: "Self") -> None:
        """Should return config with LANGCHAIN_* values when they are set."""
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "lc-test-key",
                "LANGCHAIN_PROJECT": "lc-test-project",
            },
        ):
            config = get_langsmith_config()

            assert config["tracing_enabled"] == "true"
            assert config["api_key_configured"] == "configured"
            assert config["project"] == "lc-test-project"

    def test_should_fallback_to_langsmith_config_when_langchain_not_set(self: "Self") -> None:
        """Should return config with LANGSMITH_* values when LANGCHAIN_* are not set."""
        with patch.dict(
            os.environ,
            {
                "LANGSMITH_TRACING": "true",
                "LANGSMITH_API_KEY": "ls-test-key",
                "LANGSMITH_PROJECT": "ls-test-project",
            },
        ):
            config = get_langsmith_config()

            assert config["tracing_enabled"] == "true"
            assert config["api_key_configured"] == "configured"
            assert config["project"] == "ls-test-project"

    def test_should_prioritize_langchain_over_langsmith_config(self: "Self") -> None:
        """Should use LANGCHAIN_* values when both LANGCHAIN_* and LANGSMITH_* are set."""
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "lc-priority-key",
                "LANGCHAIN_PROJECT": "lc-priority-project",
                "LANGSMITH_TRACING": "false",
                "LANGSMITH_API_KEY": "ls-ignored-key",
                "LANGSMITH_PROJECT": "ls-ignored-project",
            },
        ):
            config = get_langsmith_config()

            assert config["tracing_enabled"] == "true"  # LANGCHAIN value
            assert config["api_key_configured"] == "configured"  # LANGCHAIN key present
            assert config["project"] == "lc-priority-project"  # LANGCHAIN value

    def test_should_handle_mixed_environment_partial_fallback(self: "Self") -> None:
        """Should handle mixed environments using LANGCHAIN_* for some and LANGSMITH_* for others."""
        # LANGCHAIN_TRACING_V2 set, but no LANGCHAIN_API_KEY or LANGCHAIN_PROJECT
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGSMITH_API_KEY": "ls-fallback-key",
                "LANGSMITH_PROJECT": "ls-fallback-project",
            },
        ):
            config = get_langsmith_config()

            assert config["tracing_enabled"] == "true"  # From LANGCHAIN_*
            assert config["api_key_configured"] == "configured"  # From LANGSMITH_*
            assert config["project"] == "ls-fallback-project"  # From LANGSMITH_*

    def test_should_return_defaults_when_no_variables_set(self: "Self") -> None:
        """Should return default values when no environment variables are set."""
        config = get_langsmith_config()

        assert config["tracing_enabled"] == "false"  # Default fallback
        assert config["api_key_configured"] == "not configured"
        assert config["project"] is None

    def test_should_handle_empty_string_values(self: "Self") -> None:
        """Should handle empty string values correctly."""
        with patch.dict(
            os.environ,
            {"LANGCHAIN_TRACING_V2": "", "LANGCHAIN_API_KEY": "", "LANGCHAIN_PROJECT": ""},
        ):
            config = get_langsmith_config()

            assert config["tracing_enabled"] == "false"  # Empty string falls back to default
            assert (
                config["api_key_configured"] == "not configured"
            )  # Empty string is not configured
            assert config["project"] is None  # Empty string is falsy, so fallback to None

    def test_should_handle_empty_string_vs_none_for_project(self: "Self") -> None:
        """Should handle the difference between empty string and None for project field."""
        # When LANGCHAIN_PROJECT is set to non-empty string, it should be used
        with patch.dict(
            os.environ, {"LANGCHAIN_PROJECT": "lc-project", "LANGSMITH_PROJECT": "ls-project"}
        ):
            config = get_langsmith_config()
            assert config["project"] == "lc-project"

        # When LANGCHAIN_PROJECT is empty string, should fallback to LANGSMITH_PROJECT
        with patch.dict(os.environ, {"LANGCHAIN_PROJECT": "", "LANGSMITH_PROJECT": "ls-project"}):
            config = get_langsmith_config()
            assert config["project"] == "ls-project"

        # When both are empty strings, should return empty string (first value in 'or' chain)
        with patch.dict(os.environ, {"LANGCHAIN_PROJECT": "", "LANGSMITH_PROJECT": ""}):
            config = get_langsmith_config()
            assert config["project"] == ""

    def test_should_preserve_original_tracing_values(self: "Self") -> None:
        """Should preserve original tracing values without boolean conversion."""
        test_values = ["false", "0", "no", "invalid", "maybe", "true", "1", "yes"]

        for value in test_values:
            with patch.dict(
                os.environ, {"LANGCHAIN_TRACING_V2": value, "LANGCHAIN_API_KEY": "test-key"}
            ):
                config = get_langsmith_config()
                assert config["tracing_enabled"] == value

    def test_should_handle_whitespace_in_api_keys(self: "Self") -> None:
        """Should handle whitespace in API keys correctly."""
        whitespace_values = ["  ", "\t", "\n", "  key  ", "\tkey\t"]

        for api_key_value in whitespace_values:
            with patch.dict(
                os.environ, {"LANGCHAIN_TRACING_V2": "true", "LANGCHAIN_API_KEY": api_key_value}
            ):
                config = get_langsmith_config()
                # get_langsmith_config() just checks if api_key is truthy, not stripped
                expected = "configured" if api_key_value else "not configured"
                assert config["api_key_configured"] == expected

    def test_should_handle_none_values_from_missing_variables(self: "Self") -> None:
        """Should handle None values from os.getenv when variables don't exist."""
        # Test the behavior when environment variables return None
        config = get_langsmith_config()

        # When no variables are set, should use fallback values
        assert config["tracing_enabled"] == "false"
        assert config["api_key_configured"] == "not configured"
        assert config["project"] is None

    def test_should_handle_special_characters_in_values(self: "Self") -> None:
        """Should handle special characters in environment variable values."""
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "key-with-special!@#$%^&*()chars",
                "LANGCHAIN_PROJECT": "project/with\\special:chars",
            },
        ):
            config = get_langsmith_config()

            assert config["tracing_enabled"] == "true"
            assert config["api_key_configured"] == "configured"
            assert config["project"] == "project/with\\special:chars"

    def test_should_return_consistent_dict_structure(self: "Self") -> None:
        """Should always return dict with same keys regardless of environment."""
        # Test with various environment configurations
        test_environments = [
            {},  # Empty environment
            {"LANGCHAIN_TRACING_V2": "true"},  # Partial LANGCHAIN_*
            {"LANGSMITH_API_KEY": "key"},  # Partial LANGSMITH_*
            {"LANGCHAIN_TRACING_V2": "true", "LANGSMITH_API_KEY": "key"},  # Mixed
        ]

        for env in test_environments:
            with patch.dict(os.environ, env, clear=True):
                config = get_langsmith_config()

                # Should always have these keys
                assert "tracing_enabled" in config
                assert "api_key_configured" in config
                assert "project" in config
                assert len(config) == 3


class TestLogLangSmithStatus:
    """Test cases for log_langsmith_status function - logging integration."""

    def setup_method(self: "Self") -> None:
        """Clean up environment variables before each test."""
        env_vars_to_clear = [
            "LANGCHAIN_TRACING_V2",
            "LANGCHAIN_API_KEY",
            "LANGCHAIN_PROJECT",
            "LANGSMITH_TRACING",
            "LANGSMITH_API_KEY",
            "LANGSMITH_PROJECT",
        ]
        for var in env_vars_to_clear:
            if var in os.environ:
                del os.environ[var]

    def test_should_log_info_when_langsmith_enabled_with_project(self: "Self") -> None:
        """Should log info message when LangSmith is enabled and project is set."""
        mock_logger = Mock(spec=Logger)

        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "test-key",
                "LANGCHAIN_PROJECT": "test-project",
            },
        ):
            log_langsmith_status(mock_logger)

            mock_logger.info.assert_called_once_with(
                "LangSmith tracing is enabled (project: test-project)"
            )
            mock_logger.debug.assert_not_called()

    def test_should_log_info_when_langsmith_enabled_without_project(self: "Self") -> None:
        """Should log info message when LangSmith is enabled but no project set."""
        mock_logger = Mock(spec=Logger)

        with patch.dict(
            os.environ, {"LANGCHAIN_TRACING_V2": "true", "LANGCHAIN_API_KEY": "test-key"}
        ):
            log_langsmith_status(mock_logger)

            mock_logger.info.assert_called_once_with("LangSmith tracing is enabled")
            mock_logger.debug.assert_not_called()

    def test_should_log_debug_when_langsmith_disabled(self: "Self") -> None:
        """Should log debug message when LangSmith is disabled."""
        mock_logger = Mock(spec=Logger)

        with patch.dict(os.environ, {"LANGCHAIN_TRACING_V2": "false"}):
            log_langsmith_status(mock_logger)

            mock_logger.debug.assert_called_once()
            mock_logger.info.assert_not_called()

            # Verify the debug message contains config information
            debug_call_args = mock_logger.debug.call_args[0][0]
            assert "LangSmith tracing is disabled" in debug_call_args
            assert "tracing_enabled" in debug_call_args
            assert "api_key_configured" in debug_call_args

    def test_should_not_log_when_logger_is_none(self: "Self") -> None:
        """Should handle None logger gracefully without raising exceptions."""
        with patch.dict(
            os.environ, {"LANGCHAIN_TRACING_V2": "true", "LANGCHAIN_API_KEY": "test-key"}
        ):
            # Should not raise any exceptions
            log_langsmith_status(None)

    def test_should_not_log_when_logger_is_not_provided(self: "Self") -> None:
        """Should handle missing logger parameter gracefully."""
        with patch.dict(
            os.environ, {"LANGCHAIN_TRACING_V2": "true", "LANGCHAIN_API_KEY": "test-key"}
        ):
            # Should not raise any exceptions
            log_langsmith_status()

    def test_should_log_with_legacy_variables_when_enabled(self: "Self") -> None:
        """Should log correctly when using legacy LANGSMITH_* variables."""
        mock_logger = Mock(spec=Logger)

        with patch.dict(
            os.environ,
            {
                "LANGSMITH_TRACING": "true",
                "LANGSMITH_API_KEY": "legacy-key",
                "LANGSMITH_PROJECT": "legacy-project",
            },
        ):
            log_langsmith_status(mock_logger)

            mock_logger.info.assert_called_once_with(
                "LangSmith tracing is enabled (project: legacy-project)"
            )
            mock_logger.debug.assert_not_called()

    def test_should_handle_empty_project_name_gracefully(self: "Self") -> None:
        """Should handle empty project name without showing empty parentheses."""
        mock_logger = Mock(spec=Logger)

        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "test-key",
                "LANGCHAIN_PROJECT": "",
            },
        ):
            log_langsmith_status(mock_logger)

            mock_logger.info.assert_called_once_with("LangSmith tracing is enabled")
            mock_logger.debug.assert_not_called()

    def test_should_use_mixed_environment_in_logging(self: "Self") -> None:
        """Should correctly log when using mixed LANGCHAIN_*/LANGSMITH_* environment."""
        mock_logger = Mock(spec=Logger)

        # LANGCHAIN tracing enabled, but LANGSMITH project used
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "lc-key",
                "LANGSMITH_PROJECT": "ls-project",
            },
        ):
            log_langsmith_status(mock_logger)

            mock_logger.info.assert_called_once_with(
                "LangSmith tracing is enabled (project: ls-project)"
            )
            mock_logger.debug.assert_not_called()


class TestBackwardCompatibilityIntegration:
    """Integration test cases for backward compatibility between functions."""

    def setup_method(self: "Self") -> None:
        """Clean up environment variables before each test."""
        env_vars_to_clear = [
            "LANGCHAIN_TRACING_V2",
            "LANGCHAIN_API_KEY",
            "LANGCHAIN_PROJECT",
            "LANGSMITH_TRACING",
            "LANGSMITH_API_KEY",
            "LANGSMITH_PROJECT",
        ]
        for var in env_vars_to_clear:
            if var in os.environ:
                del os.environ[var]

    def test_should_maintain_consistency_between_functions_langchain(self: "Self") -> None:
        """Should maintain consistency between is_langsmith_enabled and get_langsmith_config for LANGCHAIN_*."""
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "test-key",
                "LANGCHAIN_PROJECT": "test-project",
            },
        ):
            enabled = is_langsmith_enabled()
            config = get_langsmith_config()

            assert enabled is True
            assert config["tracing_enabled"] == "true"
            assert config["api_key_configured"] == "configured"
            assert config["project"] == "test-project"

    def test_should_maintain_consistency_between_functions_langsmith(self: "Self") -> None:
        """Should maintain consistency between is_langsmith_enabled and get_langsmith_config for LANGSMITH_*."""
        with patch.dict(
            os.environ,
            {
                "LANGSMITH_TRACING": "true",
                "LANGSMITH_API_KEY": "legacy-key",
                "LANGSMITH_PROJECT": "legacy-project",
            },
        ):
            enabled = is_langsmith_enabled()
            config = get_langsmith_config()

            assert enabled is True
            assert config["tracing_enabled"] == "true"
            assert config["api_key_configured"] == "configured"
            assert config["project"] == "legacy-project"

    def test_should_maintain_consistency_when_disabled(self: "Self") -> None:
        """Should maintain consistency when LangSmith is disabled."""
        with patch.dict(os.environ, {"LANGCHAIN_TRACING_V2": "false"}):
            enabled = is_langsmith_enabled()
            config = get_langsmith_config()

            assert enabled is False
            assert config["tracing_enabled"] == "false"
            assert config["api_key_configured"] == "not configured"

    def test_should_handle_precedence_consistently_across_functions(self: "Self") -> None:
        """Should handle LANGCHAIN_* precedence consistently across all functions."""
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "false",  # LANGCHAIN says disabled
                "LANGCHAIN_API_KEY": "lc-key",
                "LANGCHAIN_PROJECT": "lc-project",
                "LANGSMITH_TRACING": "true",  # LANGSMITH says enabled
                "LANGSMITH_API_KEY": "ls-key",
                "LANGSMITH_PROJECT": "ls-project",
            },
        ):
            enabled = is_langsmith_enabled()
            config = get_langsmith_config()

            # is_langsmith_enabled() falls back to LANGSMITH_TRACING when LANGCHAIN_TRACING_V2 is false
            assert enabled is True  # Falls back to LANGSMITH_TRACING=true
            # get_langsmith_config() uses 'or' operator, so LANGCHAIN takes precedence
            assert config["tracing_enabled"] == "false"  # Uses LANGCHAIN_TRACING_V2=false
            assert config["api_key_configured"] == "configured"  # Uses LANGCHAIN_API_KEY
            assert config["project"] == "lc-project"  # Uses LANGCHAIN_PROJECT

    def test_should_handle_mixed_fallback_consistently(self: "Self") -> None:
        """Should handle mixed fallback scenarios consistently across functions."""
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",  # LANGCHAIN tracing enabled
                "LANGSMITH_API_KEY": "ls-key",  # But only LANGSMITH has API key
                "LANGSMITH_PROJECT": "ls-project",  # And only LANGSMITH has project
            },
        ):
            enabled = is_langsmith_enabled()
            config = get_langsmith_config()

            # Both should use mixed fallback correctly
            assert enabled is True  # LANGCHAIN tracing + LANGSMITH API key
            assert config["tracing_enabled"] == "true"  # From LANGCHAIN_TRACING_V2
            assert config["api_key_configured"] == "configured"  # From LANGSMITH_API_KEY
            assert config["project"] == "ls-project"  # From LANGSMITH_PROJECT

    def test_should_integrate_with_logging_for_all_scenarios(self: "Self") -> None:
        """Should integrate logging correctly for all backward compatibility scenarios."""
        mock_logger = Mock(spec=Logger)

        # Test LANGCHAIN_* only scenario
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "lc-key",
                "LANGCHAIN_PROJECT": "lc-project",
            },
        ):
            log_langsmith_status(mock_logger)
            mock_logger.info.assert_called_with(
                "LangSmith tracing is enabled (project: lc-project)"
            )
            mock_logger.reset_mock()

        # Test LANGSMITH_* only scenario
        with patch.dict(
            os.environ,
            {
                "LANGSMITH_TRACING": "true",
                "LANGSMITH_API_KEY": "ls-key",
                "LANGSMITH_PROJECT": "ls-project",
            },
        ):
            log_langsmith_status(mock_logger)
            mock_logger.info.assert_called_with(
                "LangSmith tracing is enabled (project: ls-project)"
            )
            mock_logger.reset_mock()

        # Test mixed scenario
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGSMITH_API_KEY": "ls-key",
                "LANGSMITH_PROJECT": "ls-project",
            },
        ):
            log_langsmith_status(mock_logger)
            mock_logger.info.assert_called_with(
                "LangSmith tracing is enabled (project: ls-project)"
            )


class TestEdgeCasesAndErrorHandling:
    """Test edge cases and error handling scenarios for backward compatibility."""

    def setup_method(self: "Self") -> None:
        """Clean up environment variables before each test."""
        env_vars_to_clear = [
            "LANGCHAIN_TRACING_V2",
            "LANGCHAIN_API_KEY",
            "LANGCHAIN_PROJECT",
            "LANGSMITH_TRACING",
            "LANGSMITH_API_KEY",
            "LANGSMITH_PROJECT",
        ]
        for var in env_vars_to_clear:
            if var in os.environ:
                del os.environ[var]

    def test_should_handle_all_empty_environments(self: "Self") -> None:
        """Should handle completely empty environment gracefully."""
        with patch.dict(os.environ, {}, clear=True):
            assert is_langsmith_enabled() is False

            config = get_langsmith_config()
            assert config["tracing_enabled"] == "false"
            assert config["api_key_configured"] == "not configured"
            assert config["project"] is None

    def test_should_handle_whitespace_only_values(self: "Self") -> None:
        """Should handle whitespace-only environment variable values."""
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "   ",
                "LANGCHAIN_API_KEY": "\t\t",
                "LANGCHAIN_PROJECT": "\n\n",
            },
        ):
            # Whitespace tracing should be treated as False
            assert is_langsmith_enabled() is False

            config = get_langsmith_config()
            assert config["tracing_enabled"] == "   "  # Preserved as-is
            assert (
                config["api_key_configured"] == "configured"
            )  # get_langsmith_config() sees whitespace as truthy
            assert config["project"] == "\n\n"  # Preserved as-is

    def test_should_handle_unicode_and_special_characters(self: "Self") -> None:
        """Should handle Unicode and special characters in environment variables."""
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "key-with-ünicode-and-特殊字符",
                "LANGCHAIN_PROJECT": "project/with\\paths:and=symbols&more",
            },
        ):
            assert is_langsmith_enabled() is True

            config = get_langsmith_config()
            assert config["tracing_enabled"] == "true"
            assert config["api_key_configured"] == "configured"
            assert config["project"] == "project/with\\paths:and=symbols&more"

    def test_should_handle_very_long_values(self: "Self") -> None:
        """Should handle very long environment variable values."""
        long_value = "x" * 10000  # 10KB string

        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": long_value,
                "LANGCHAIN_PROJECT": long_value,
            },
        ):
            assert is_langsmith_enabled() is True

            config = get_langsmith_config()
            assert config["tracing_enabled"] == "true"
            assert config["api_key_configured"] == "configured"
            assert config["project"] == long_value

    def test_should_handle_numeric_string_values(self: "Self") -> None:
        """Should handle numeric string values in environment variables."""
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "1",  # Should be treated as true
                "LANGCHAIN_API_KEY": "12345",
                "LANGCHAIN_PROJECT": "99999",
            },
        ):
            assert is_langsmith_enabled() is True

            config = get_langsmith_config()
            assert config["tracing_enabled"] == "1"
            assert config["api_key_configured"] == "configured"
            assert config["project"] == "99999"

    def test_should_be_case_sensitive_for_boolean_values(self: "Self") -> None:
        """Should handle case sensitivity correctly for boolean tracing values."""
        # Mixed case that's not exactly "true", "1", "yes" should be False
        mixed_case_values = ["TRUE", "True", "tRuE", "YES", "Yes", "yEs"]

        for value in mixed_case_values:
            with patch.dict(
                os.environ, {"LANGCHAIN_TRACING_V2": value, "LANGCHAIN_API_KEY": "test-key"}
            ):
                if value.lower() in ["true", "yes"]:  # Should work due to .lower() call
                    assert is_langsmith_enabled() is True, f"Failed for: {value}"
                else:
                    # This tests the actual implementation
                    result = is_langsmith_enabled()
                    # The implementation uses .lower(), so all these should actually be True
                    assert result is True, f"Expected True for case-insensitive value: {value}"

    def test_should_handle_boolean_edge_cases(self: "Self") -> None:
        """Should handle edge cases in boolean value interpretation."""
        # Test boundary cases for boolean interpretation
        edge_cases = {
            "": False,  # Empty string
            " ": False,  # Space
            "0": False,  # Zero
            "00": False,  # Multiple zeros
            "false": False,  # Explicit false
            "no": False,  # Explicit no
            "True ": False,  # Trailing space - becomes "true " which is not in accepted values
            " true": False,  # Leading space (not in the accepted values)
            "1.0": False,  # Float as string
            "true\n": False,  # With newline
        }

        for test_value, expected in edge_cases.items():
            with patch.dict(
                os.environ, {"LANGCHAIN_TRACING_V2": test_value, "LANGCHAIN_API_KEY": "test-key"}
            ):
                result = is_langsmith_enabled()
                assert (
                    result == expected
                ), f"Failed for value '{test_value}': expected {expected}, got {result}"


# =====================================================================
# TOML Configuration Integration Tests
# =====================================================================


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


class TestIsLangSmithEnabledWithTomlConfig:
    """Test cases for is_langsmith_enabled with TOML configuration precedence."""

    def setup_method(self: "Self") -> None:
        """Clean up environment variables before each test."""
        env_vars_to_clear = [
            "LANGCHAIN_TRACING_V2",
            "LANGCHAIN_API_KEY",
            "LANGCHAIN_PROJECT",
            "LANGCHAIN_ENDPOINT",
            "LANGSMITH_TRACING",
            "LANGSMITH_API_KEY",
            "LANGSMITH_PROJECT",
        ]
        for var in env_vars_to_clear:
            if var in os.environ:
                del os.environ[var]

    def test_should_return_true_when_toml_config_enabled_with_api_key(self: "Self") -> None:
        """Should return True when TOML config is enabled and has API key."""
        toml_config = MockLangSmithConfig(enabled=True, api_key="toml-api-key")
        assert is_langsmith_enabled(toml_config) is True

    def test_should_return_false_when_toml_config_enabled_without_api_key(self: "Self") -> None:
        """Should return False when TOML config is enabled but missing API key."""
        toml_config = MockLangSmithConfig(enabled=True, api_key=None)
        assert is_langsmith_enabled(toml_config) is False

    def test_should_return_false_when_toml_config_disabled_with_api_key(self: "Self") -> None:
        """Should return False when TOML config is disabled even if API key is set."""
        toml_config = MockLangSmithConfig(enabled=False, api_key="toml-api-key")
        assert is_langsmith_enabled(toml_config) is False

    def test_should_return_false_when_toml_config_disabled_without_api_key(self: "Self") -> None:
        """Should return False when TOML config is disabled and no API key."""
        toml_config = MockLangSmithConfig(enabled=False, api_key=None)
        assert is_langsmith_enabled(toml_config) is False

    def test_should_override_environment_variables_when_toml_config_provided(self: "Self") -> None:
        """Should use TOML config and ignore environment variables when config is provided."""
        # Set environment to enabled
        with patch.dict(
            os.environ, {"LANGCHAIN_TRACING_V2": "true", "LANGCHAIN_API_KEY": "env-api-key"}
        ):
            # But TOML config says disabled
            toml_config = MockLangSmithConfig(enabled=False, api_key="toml-api-key")
            assert is_langsmith_enabled(toml_config) is False

        # Set environment to disabled
        with patch.dict(os.environ, {"LANGCHAIN_TRACING_V2": "false"}):
            # But TOML config says enabled
            toml_config = MockLangSmithConfig(enabled=True, api_key="toml-api-key")
            assert is_langsmith_enabled(toml_config) is True

    def test_should_handle_empty_string_api_key_in_toml_config(self: "Self") -> None:
        """Should treat empty string API key in TOML config as missing."""
        toml_config = MockLangSmithConfig(enabled=True, api_key="")
        assert is_langsmith_enabled(toml_config) is False

        toml_config = MockLangSmithConfig(enabled=True, api_key="   ")
        assert is_langsmith_enabled(toml_config) is True  # Non-empty whitespace is truthy

    def test_should_fallback_to_environment_when_toml_config_is_none(self: "Self") -> None:
        """Should use environment variables when TOML config parameter is None."""
        with patch.dict(
            os.environ, {"LANGCHAIN_TRACING_V2": "true", "LANGCHAIN_API_KEY": "env-api-key"}
        ):
            assert is_langsmith_enabled(None) is True

        with patch.dict(os.environ, {"LANGCHAIN_TRACING_V2": "false"}):
            assert is_langsmith_enabled(None) is False


class TestGetLangSmithConfigWithTomlConfig:
    """Test cases for get_langsmith_config with TOML configuration precedence."""

    def setup_method(self: "Self") -> None:
        """Clean up environment variables before each test."""
        env_vars_to_clear = [
            "LANGCHAIN_TRACING_V2",
            "LANGCHAIN_API_KEY",
            "LANGCHAIN_PROJECT",
            "LANGCHAIN_ENDPOINT",
            "LANGSMITH_TRACING",
            "LANGSMITH_API_KEY",
            "LANGSMITH_PROJECT",
        ]
        for var in env_vars_to_clear:
            if var in os.environ:
                del os.environ[var]

    def test_should_return_toml_config_when_provided(self: "Self") -> None:
        """Should return TOML config values when config is provided."""
        toml_config = MockLangSmithConfig(
            enabled=True, api_key="toml-api-key", project_name="toml-project"
        )
        config = get_langsmith_config(toml_config)

        assert config["tracing_enabled"] == "true"
        assert config["api_key_configured"] == "configured"
        assert config["project"] == "toml-project"

    def test_should_return_toml_config_when_disabled(self: "Self") -> None:
        """Should return disabled config when TOML config is disabled."""
        toml_config = MockLangSmithConfig(
            enabled=False, api_key="toml-api-key", project_name="toml-project"
        )
        config = get_langsmith_config(toml_config)

        assert config["tracing_enabled"] == "false"
        assert config["api_key_configured"] == "configured"  # API key still present
        assert config["project"] == "toml-project"

    def test_should_handle_toml_config_with_none_values(self: "Self") -> None:
        """Should handle TOML config with None values correctly."""
        toml_config = MockLangSmithConfig(enabled=True, api_key=None, project_name=None)
        config = get_langsmith_config(toml_config)

        assert config["tracing_enabled"] == "true"
        assert config["api_key_configured"] == "not configured"
        assert config["project"] is None

    def test_should_handle_toml_config_with_empty_strings(self: "Self") -> None:
        """Should handle TOML config with empty string values correctly."""
        toml_config = MockLangSmithConfig(enabled=True, api_key="", project_name="")
        config = get_langsmith_config(toml_config)

        assert config["tracing_enabled"] == "true"
        assert config["api_key_configured"] == "not configured"  # Empty string is falsy
        assert config["project"] == ""  # Empty string preserved

    def test_should_override_environment_with_toml_config(self: "Self") -> None:
        """Should use TOML config values even when environment variables are set."""
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "false",  # Environment says disabled
                "LANGCHAIN_API_KEY": "env-api-key",
                "LANGCHAIN_PROJECT": "env-project",
            },
        ):
            # TOML config overrides environment
            toml_config = MockLangSmithConfig(
                enabled=True, api_key="toml-api-key", project_name="toml-project"
            )
            config = get_langsmith_config(toml_config)

            assert config["tracing_enabled"] == "true"  # TOML value
            assert config["api_key_configured"] == "configured"  # TOML has key
            assert config["project"] == "toml-project"  # TOML value

    def test_should_fallback_to_environment_when_toml_config_is_none(self: "Self") -> None:
        """Should use environment variables when TOML config is None."""
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "env-api-key",
                "LANGCHAIN_PROJECT": "env-project",
            },
        ):
            config = get_langsmith_config(None)

            assert config["tracing_enabled"] == "true"
            assert config["api_key_configured"] == "configured"
            assert config["project"] == "env-project"


class TestConfigureLangsmithEnvironment:
    """Test cases for configure_langsmith_environment function."""

    def setup_method(self: "Self") -> None:
        """Clean up environment variables before each test."""
        env_vars_to_clear = [
            "LANGCHAIN_TRACING_V2",
            "LANGCHAIN_API_KEY",
            "LANGCHAIN_PROJECT",
            "LANGCHAIN_ENDPOINT",
        ]
        for var in env_vars_to_clear:
            if var in os.environ:
                del os.environ[var]

    def test_should_set_environment_variables_when_config_enabled(self: "Self") -> None:
        """Should set environment variables when TOML config is enabled."""
        toml_config = MockLangSmithConfig(
            enabled=True,
            api_key="toml-api-key",
            project_name="toml-project",
            endpoint="https://custom.endpoint.com",
        )

        configure_langsmith_environment(toml_config)

        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
        assert os.environ["LANGCHAIN_API_KEY"] == "toml-api-key"
        assert os.environ["LANGCHAIN_PROJECT"] == "toml-project"
        assert os.environ["LANGCHAIN_ENDPOINT"] == "https://custom.endpoint.com"

    def test_should_set_tracing_false_when_config_disabled(self: "Self") -> None:
        """Should set LANGCHAIN_TRACING_V2=false when TOML config is disabled."""
        toml_config = MockLangSmithConfig(
            enabled=False, api_key="toml-api-key", project_name="toml-project"
        )

        configure_langsmith_environment(toml_config)

        assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
        assert os.environ["LANGCHAIN_API_KEY"] == "toml-api-key"  # API key still set
        assert os.environ["LANGCHAIN_PROJECT"] == "toml-project"

    def test_should_not_override_existing_environment_variables(self: "Self") -> None:
        """Should not override environment variables that are already set."""
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "existing-value",
                "LANGCHAIN_API_KEY": "existing-key",
                "LANGCHAIN_PROJECT": "existing-project",
                "LANGCHAIN_ENDPOINT": "existing-endpoint",
            },
        ):
            toml_config = MockLangSmithConfig(
                enabled=True,
                api_key="toml-api-key",
                project_name="toml-project",
                endpoint="https://toml.endpoint.com",
            )

            configure_langsmith_environment(toml_config)

            # Environment variables should remain unchanged
            assert os.environ["LANGCHAIN_TRACING_V2"] == "existing-value"
            assert os.environ["LANGCHAIN_API_KEY"] == "existing-key"
            assert os.environ["LANGCHAIN_PROJECT"] == "existing-project"
            assert os.environ["LANGCHAIN_ENDPOINT"] == "existing-endpoint"

    def test_should_handle_none_values_in_toml_config(self: "Self") -> None:
        """Should handle None values in TOML config gracefully."""
        toml_config = MockLangSmithConfig(
            enabled=True, api_key=None, project_name=None, endpoint=None
        )

        configure_langsmith_environment(toml_config)

        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"  # Only enabled is set
        # None values should not set environment variables
        assert "LANGCHAIN_API_KEY" not in os.environ
        assert "LANGCHAIN_PROJECT" not in os.environ
        assert "LANGCHAIN_ENDPOINT" not in os.environ

    def test_should_handle_empty_string_values_in_toml_config(self: "Self") -> None:
        """Should handle empty string values in TOML config correctly."""
        toml_config = MockLangSmithConfig(enabled=True, api_key="", project_name="", endpoint="")

        configure_langsmith_environment(toml_config)

        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
        # Empty strings should not set environment variables
        assert "LANGCHAIN_API_KEY" not in os.environ
        assert "LANGCHAIN_PROJECT" not in os.environ
        assert "LANGCHAIN_ENDPOINT" not in os.environ

    def test_should_handle_whitespace_values_in_toml_config(self: "Self") -> None:
        """Should handle whitespace values in TOML config correctly."""
        toml_config = MockLangSmithConfig(
            enabled=True, api_key="   ", project_name="\t", endpoint="\n"
        )

        configure_langsmith_environment(toml_config)

        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
        # Whitespace values should be set (they're truthy)
        assert os.environ["LANGCHAIN_API_KEY"] == "   "
        assert os.environ["LANGCHAIN_PROJECT"] == "\t"
        assert os.environ["LANGCHAIN_ENDPOINT"] == "\n"

    def test_should_set_partial_environment_variables(self: "Self") -> None:
        """Should set only the environment variables that have values in TOML config."""
        toml_config = MockLangSmithConfig(enabled=True, api_key="toml-api-key")
        # project_name and endpoint are None

        configure_langsmith_environment(toml_config)

        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
        assert os.environ["LANGCHAIN_API_KEY"] == "toml-api-key"
        assert "LANGCHAIN_PROJECT" not in os.environ
        assert "LANGCHAIN_ENDPOINT" not in os.environ

    def test_should_handle_special_characters_in_values(self: "Self") -> None:
        """Should handle special characters in TOML config values correctly."""
        toml_config = MockLangSmithConfig(
            enabled=True,
            api_key="key-with-special!@#$%^&*()chars",
            project_name="project/with\\special:chars",
            endpoint="https://endpoint.com?param=value&other=test",
        )

        configure_langsmith_environment(toml_config)

        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
        assert os.environ["LANGCHAIN_API_KEY"] == "key-with-special!@#$%^&*()chars"
        assert os.environ["LANGCHAIN_PROJECT"] == "project/with\\special:chars"
        assert os.environ["LANGCHAIN_ENDPOINT"] == "https://endpoint.com?param=value&other=test"


class TestLogLangSmithStatusWithTomlConfig:
    """Test cases for log_langsmith_status with TOML configuration."""

    def setup_method(self: "Self") -> None:
        """Clean up environment variables before each test."""
        env_vars_to_clear = [
            "LANGCHAIN_TRACING_V2",
            "LANGCHAIN_API_KEY",
            "LANGCHAIN_PROJECT",
            "LANGCHAIN_ENDPOINT",
            "LANGSMITH_TRACING",
            "LANGSMITH_API_KEY",
            "LANGSMITH_PROJECT",
        ]
        for var in env_vars_to_clear:
            if var in os.environ:
                del os.environ[var]

    def test_should_log_info_when_toml_config_enabled_with_project(self: "Self") -> None:
        """Should log info message when TOML config is enabled with project."""
        mock_logger = Mock(spec=Logger)
        toml_config = MockLangSmithConfig(
            enabled=True, api_key="toml-api-key", project_name="toml-project"
        )

        log_langsmith_status(mock_logger, toml_config)

        mock_logger.info.assert_called_once_with(
            "LangSmith tracing is enabled (project: toml-project)"
        )
        mock_logger.debug.assert_not_called()

    def test_should_log_info_when_toml_config_enabled_without_project(self: "Self") -> None:
        """Should log info message when TOML config is enabled without project."""
        mock_logger = Mock(spec=Logger)
        toml_config = MockLangSmithConfig(enabled=True, api_key="toml-api-key", project_name=None)

        log_langsmith_status(mock_logger, toml_config)

        mock_logger.info.assert_called_once_with("LangSmith tracing is enabled")
        mock_logger.debug.assert_not_called()

    def test_should_log_debug_when_toml_config_disabled(self: "Self") -> None:
        """Should log debug message when TOML config is disabled."""
        mock_logger = Mock(spec=Logger)
        toml_config = MockLangSmithConfig(
            enabled=False, api_key="toml-api-key", project_name="toml-project"
        )

        log_langsmith_status(mock_logger, toml_config)

        mock_logger.debug.assert_called_once()
        mock_logger.info.assert_not_called()

        # Verify the debug message contains TOML config information
        debug_call_args = mock_logger.debug.call_args[0][0]
        assert "LangSmith tracing is disabled" in debug_call_args
        assert "tracing_enabled" in debug_call_args
        assert "false" in debug_call_args  # TOML config disabled

    def test_should_use_toml_config_over_environment_in_logging(self: "Self") -> None:
        """Should use TOML config values for logging even when environment is set."""
        mock_logger = Mock(spec=Logger)

        # Environment says one thing
        with patch.dict(
            os.environ,
            {"LANGCHAIN_TRACING_V2": "false", "LANGCHAIN_PROJECT": "env-project"},
        ):
            # TOML config says another
            toml_config = MockLangSmithConfig(
                enabled=True, api_key="toml-api-key", project_name="toml-project"
            )

            log_langsmith_status(mock_logger, toml_config)

            # Should log based on TOML config
            mock_logger.info.assert_called_once_with(
                "LangSmith tracing is enabled (project: toml-project)"
            )
            mock_logger.debug.assert_not_called()

    def test_should_fallback_to_environment_when_toml_config_is_none(self: "Self") -> None:
        """Should use environment variables for logging when TOML config is None."""
        mock_logger = Mock(spec=Logger)

        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "env-api-key",
                "LANGCHAIN_PROJECT": "env-project",
            },
        ):
            log_langsmith_status(mock_logger, None)

            mock_logger.info.assert_called_once_with(
                "LangSmith tracing is enabled (project: env-project)"
            )
            mock_logger.debug.assert_not_called()

    def test_should_handle_empty_project_name_in_toml_config(self: "Self") -> None:
        """Should handle empty project name in TOML config gracefully."""
        mock_logger = Mock(spec=Logger)
        toml_config = MockLangSmithConfig(enabled=True, api_key="toml-api-key", project_name="")

        log_langsmith_status(mock_logger, toml_config)

        mock_logger.info.assert_called_once_with("LangSmith tracing is enabled")
        mock_logger.debug.assert_not_called()


class TestTomlConfigIntegrationScenarios:
    """Integration test cases for realistic TOML configuration scenarios."""

    def setup_method(self: "Self") -> None:
        """Clean up environment variables before each test."""
        env_vars_to_clear = [
            "LANGCHAIN_TRACING_V2",
            "LANGCHAIN_API_KEY",
            "LANGCHAIN_PROJECT",
            "LANGCHAIN_ENDPOINT",
            "LANGSMITH_TRACING",
            "LANGSMITH_API_KEY",
            "LANGSMITH_PROJECT",
        ]
        for var in env_vars_to_clear:
            if var in os.environ:
                del os.environ[var]

    def test_toml_config_overrides_environment_entirely(self: "Self") -> None:
        """Should use TOML config exclusively when provided, ignoring environment."""
        # Set up conflicting environment
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "false",  # Environment disabled
                "LANGCHAIN_API_KEY": "env-key",
                "LANGCHAIN_PROJECT": "env-project",
                "LANGSMITH_TRACING": "true",  # Legacy enabled
                "LANGSMITH_API_KEY": "legacy-key",
            },
        ):
            # TOML config enabled
            toml_config = MockLangSmithConfig(
                enabled=True, api_key="toml-key", project_name="toml-project"
            )

            # All functions should use TOML config
            assert is_langsmith_enabled(toml_config) is True
            config = get_langsmith_config(toml_config)
            assert config["tracing_enabled"] == "true"
            assert config["project"] == "toml-project"

            # Logging should also use TOML config
            mock_logger = Mock(spec=Logger)
            log_langsmith_status(mock_logger, toml_config)
            mock_logger.info.assert_called_once_with(
                "LangSmith tracing is enabled (project: toml-project)"
            )

    def test_environment_fallback_when_no_toml_config(self: "Self") -> None:
        """Should fall back to environment variables when no TOML config provided."""
        with patch.dict(
            os.environ,
            {
                "LANGCHAIN_TRACING_V2": "true",
                "LANGCHAIN_API_KEY": "env-key",
                "LANGCHAIN_PROJECT": "env-project",
            },
        ):
            # No TOML config provided
            assert is_langsmith_enabled(None) is True
            config = get_langsmith_config(None)
            assert config["tracing_enabled"] == "true"
            assert config["project"] == "env-project"

            # Logging should use environment
            mock_logger = Mock(spec=Logger)
            log_langsmith_status(mock_logger, None)
            mock_logger.info.assert_called_once_with(
                "LangSmith tracing is enabled (project: env-project)"
            )

    def test_development_vs_production_configuration_scenario(self: "Self") -> None:
        """Should handle development vs production configuration scenarios."""
        # Production environment (explicit override)
        with patch.dict(
            os.environ, {"LANGCHAIN_TRACING_V2": "false", "LANGCHAIN_API_KEY": "prod-key"}
        ):
            # Development TOML config wants tracing enabled
            dev_toml_config = MockLangSmithConfig(
                enabled=True, api_key="dev-key", project_name="dev-project"
            )

            # TOML should override production environment
            assert is_langsmith_enabled(dev_toml_config) is True
            config = get_langsmith_config(dev_toml_config)
            assert config["tracing_enabled"] == "true"
            assert config["project"] == "dev-project"

    def test_partial_toml_config_scenario(self: "Self") -> None:
        """Should handle partial TOML config with only some fields set."""
        # Minimal TOML config
        minimal_toml_config = MockLangSmithConfig(enabled=True, api_key="minimal-key")
        # project_name and endpoint are None

        assert is_langsmith_enabled(minimal_toml_config) is True
        config = get_langsmith_config(minimal_toml_config)
        assert config["tracing_enabled"] == "true"
        assert config["api_key_configured"] == "configured"
        assert config["project"] is None  # Not set in TOML

        # configure_langsmith_environment should handle partial config
        configure_langsmith_environment(minimal_toml_config)
        assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
        assert os.environ["LANGCHAIN_API_KEY"] == "minimal-key"
        assert "LANGCHAIN_PROJECT" not in os.environ  # Not set

    def test_disabled_toml_config_with_api_key_scenario(self: "Self") -> None:
        """Should handle explicitly disabled TOML config even with valid API key."""
        # Explicitly disabled TOML config
        disabled_toml_config = MockLangSmithConfig(
            enabled=False, api_key="valid-key", project_name="test-project"
        )

        assert is_langsmith_enabled(disabled_toml_config) is False  # Respects disabled
        config = get_langsmith_config(disabled_toml_config)
        assert config["tracing_enabled"] == "false"
        assert config["api_key_configured"] == "configured"  # API key present but disabled

        # Environment setup should still set variables for potential manual override
        configure_langsmith_environment(disabled_toml_config)
        assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
        assert os.environ["LANGCHAIN_API_KEY"] == "valid-key"  # Available if needed
        assert os.environ["LANGCHAIN_PROJECT"] == "test-project"
