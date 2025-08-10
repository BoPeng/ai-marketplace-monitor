import os
from typing import Any
from unittest.mock import Mock, patch

import pytest

from ai_marketplace_monitor.ai import (
    AIConfig,
    AIResponse,
    LangChainBackend,
    OllamaBackend,
    OllamaConfig,
    adapt_langchain_response,
)
from ai_marketplace_monitor.facebook import FacebookItemConfig, FacebookMarketplaceConfig
from ai_marketplace_monitor.listing import Listing


@pytest.mark.skipif(True, reason="Condition met, skipping this test")
def test_ai(
    ollama_config: OllamaConfig,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    listing: Listing,
) -> None:
    ai = OllamaBackend(ollama_config)
    # ai.config = ollama_config
    res = ai.evaluate(listing, item_config, marketplace_config)
    assert res.score >= 1 and res.score <= 5


def test_prompt(
    ollama: OllamaBackend,
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
) -> None:
    prompt = ollama.get_prompt(listing, item_config, marketplace_config)
    assert item_config.name in prompt
    assert (item_config.description or "something weird") in prompt
    assert str(item_config.min_price) in prompt
    assert str(item_config.max_price) in prompt

    assert listing.title in prompt
    assert listing.condition in prompt
    assert listing.price in prompt
    assert listing.post_url in prompt


def test_extra_prompt(
    ollama: OllamaBackend,
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
) -> None:
    marketplace_config.extra_prompt = "This is an extra prompt"
    prompt = ollama.get_prompt(listing, item_config, marketplace_config)
    assert "extra prompt" in prompt
    #
    item_config.extra_prompt = "This overrides marketplace prompt"
    prompt = ollama.get_prompt(listing, item_config, marketplace_config)
    assert "extra prompt" not in prompt
    assert "overrides marketplace prompt" in prompt
    #
    assert "Great deal: Fully matches" in prompt
    item_config.rating_prompt = "something else"
    prompt = ollama.get_prompt(listing, item_config, marketplace_config)
    assert "Great deal: Fully matches" not in prompt
    assert "something else" in prompt
    #
    assert "Evaluate how well this listing" in prompt
    marketplace_config.prompt = "myprompt"
    prompt = ollama.get_prompt(listing, item_config, marketplace_config)
    assert "Evaluate how well this listing" not in prompt
    assert "myprompt" in prompt


class TestLangChainBackend:
    """Test suite for LangChainBackend class."""

    def test_get_config(self) -> None:
        """Test LangChainBackend.get_config returns AIConfig."""
        config = LangChainBackend.get_config(
            name="test-backend",
            provider="openai",
            api_key="test-key",
            model="gpt-4",
        )
        assert isinstance(config, AIConfig)
        assert config.name == "test-backend"
        assert config.provider == "openai"
        assert config.api_key == "test-key"
        assert config.model == "gpt-4"

    def test_init(self) -> None:
        """Test LangChainBackend initialization."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        assert backend.config == config
        assert backend._chat_model is None
        assert backend.logger is None

    def test_get_model_success(self) -> None:
        """Test _get_model with valid provider."""
        config = AIConfig(
            name="test-backend", provider="openai", api_key="test-key", model="gpt-4"
        )
        backend = LangChainBackend(config)

        with patch("ai_marketplace_monitor.ai.provider_map") as mock_provider_map:
            mock_factory = Mock()
            mock_model = Mock()
            mock_factory.return_value = mock_model
            mock_provider_map.__getitem__.return_value = mock_factory
            mock_provider_map.__contains__.return_value = True
            mock_provider_map.keys.return_value = ["openai", "deepseek"]

            result = backend._get_model(config)

            assert result == mock_model
            mock_factory.assert_called_once_with(config)

    def test_get_model_no_provider(self) -> None:
        """Test _get_model with missing provider."""
        config = AIConfig(name="test-backend", api_key="test-key")
        backend = LangChainBackend(config)

        with pytest.raises(ValueError, match="AIConfig must have a provider specified"):
            backend._get_model(config)

    def test_get_model_unsupported_provider(self) -> None:
        """Test _get_model with unsupported provider."""
        # Skip provider validation by mocking it
        with patch.object(AIConfig, "handle_provider"):
            config = AIConfig(name="test-backend", provider="unsupported", api_key="test-key")
            backend = LangChainBackend(config)

            with patch("ai_marketplace_monitor.ai.provider_map") as mock_provider_map:
                mock_provider_map.__contains__.return_value = False
                mock_provider_map.keys.return_value = ["openai", "deepseek"]

                with pytest.raises(ValueError, match="Unsupported provider 'unsupported'"):
                    backend._get_model(config)

    def test_get_model_factory_error(self) -> None:
        """Test _get_model when factory raises exception."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        with patch("ai_marketplace_monitor.ai.provider_map") as mock_provider_map:
            mock_factory = Mock(side_effect=Exception("Factory error"))
            mock_provider_map.__getitem__.return_value = mock_factory
            mock_provider_map.__contains__.return_value = True

            with pytest.raises(RuntimeError, match="Failed to create model for provider 'openai'"):
                backend._get_model(config)

    def test_connect_success(self) -> None:
        """Test successful connection."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        mock_model = Mock()
        with (
            patch.object(backend, "_get_model", return_value=mock_model),
            patch("ai_marketplace_monitor.ai.log_langsmith_status") as mock_langsmith_log,
        ):
            backend.connect()

            assert backend._chat_model == mock_model
            mock_logger.info.assert_called_once_with(f"[cyan][AI][/cyan] {config.name} connected.")
            mock_langsmith_log.assert_called_once_with(mock_logger, None)

    def test_connect_already_connected(self) -> None:
        """Test connect when already connected."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        mock_model = Mock()
        backend._chat_model = mock_model

        with patch.object(backend, "_get_model") as mock_get_model:
            backend.connect()
            mock_get_model.assert_not_called()

    def test_connect_error(self) -> None:
        """Test connection error handling."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        with patch.object(backend, "_get_model", side_effect=Exception("Connection failed")):
            with pytest.raises(Exception, match="Connection failed"):
                backend.connect()

            mock_logger.error.assert_called_once()

    def test_evaluate_with_cache(
        self,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
        listing: Listing,
    ) -> None:
        """Test evaluate method with cached response."""
        config = AIConfig(provider="openai", api_key="test-key", name="test-backend")
        backend = LangChainBackend(config)

        # Mock cached response
        with patch("ai_marketplace_monitor.ai.AIResponse.from_cache") as mock_cache:
            mock_response = Mock()
            mock_response.style = "succ"
            mock_response.conclusion = "Good match"
            mock_response.score = 4
            mock_response.comment = "Test comment"
            mock_cache.return_value = mock_response

            result = backend.evaluate(listing, item_config, marketplace_config)

            assert result == mock_response

    def test_evaluate_success(
        self,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
        listing: Listing,
    ) -> None:
        """Test successful evaluation without cache."""
        config = AIConfig(
            provider="openai", api_key="test-key", name="test-backend", max_retries=3
        )
        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        # Mock LangChain model response
        mock_model = Mock()
        mock_response = Mock()
        mock_response.content = "This is a good match.\nRating 4: Great condition and price"
        mock_model.invoke.return_value = mock_response

        backend._chat_model = mock_model

        with (
            patch("ai_marketplace_monitor.ai.AIResponse.from_cache", return_value=None),
            patch("ai_marketplace_monitor.ai.counter"),
            patch.object(backend, "get_prompt", return_value="test prompt"),
        ):
            result = backend.evaluate(listing, item_config, marketplace_config)

            assert result.score == 4
            assert "Great condition and price" in result.comment
            assert result.name == "test-backend"

    def test_evaluate_retry_on_error(
        self,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
        listing: Listing,
    ) -> None:
        """Test retry logic on evaluation error."""
        config = AIConfig(
            name="test-backend", provider="openai", api_key="test-key", max_retries=3
        )
        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        # Mock connection to reset _chat_model back to mock_model after connect() is called
        def mock_connect():
            backend._chat_model = mock_model

        mock_model = Mock()
        # First call fails, second succeeds
        mock_response = Mock()
        mock_response.content = "Rating 3: Decent match"
        mock_model.invoke.side_effect = [Exception("Network error"), mock_response]

        with (
            patch("ai_marketplace_monitor.ai.AIResponse.from_cache", return_value=None),
            patch("ai_marketplace_monitor.ai.counter"),
            patch.object(backend, "connect", side_effect=mock_connect),
            patch.object(backend, "get_prompt", return_value="test prompt"),
            patch("time.sleep"),
        ):
            backend._chat_model = mock_model
            result = backend.evaluate(listing, item_config, marketplace_config)

            assert result.score == 3
            assert mock_logger.error.called

    def test_extract_response_content_with_string_content(self) -> None:
        """Test _extract_response_content with string content attribute."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        mock_response = Mock()
        mock_response.content = "Test response content"

        result = backend._extract_response_content(mock_response)
        assert result == "Test response content"

    def test_extract_response_content_with_list_content(self) -> None:
        """Test _extract_response_content with list content attribute."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        mock_response = Mock()
        mock_response.content = ["First message", "Second message"]

        result = backend._extract_response_content(mock_response)
        assert "First message" in result

    def test_extract_response_content_with_text_fallback(self) -> None:
        """Test _extract_response_content falling back to text attribute."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        mock_response = Mock()
        del mock_response.content  # Remove content attribute
        mock_response.text = "Response from text attribute"

        result = backend._extract_response_content(mock_response)
        assert result == "Response from text attribute"

    def test_extract_response_content_with_message_fallback(self) -> None:
        """Test _extract_response_content falling back to message.content."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        mock_response = Mock()
        del mock_response.content
        del mock_response.text
        mock_response.message = Mock()
        mock_response.message.content = "Message content"

        result = backend._extract_response_content(mock_response)
        assert result == "Message content"

    def test_extract_response_content_string_fallback(self) -> None:
        """Test _extract_response_content final string fallback."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        mock_response = "Raw string response"

        result = backend._extract_response_content(mock_response)
        assert result == "Raw string response"
        mock_logger.warning.assert_called_once()

    def test_evaluate_retry_with_connection_failure(
        self,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
        listing: Listing,
    ) -> None:
        """Test retry logic handles connection failures during reconnect attempts."""
        config = AIConfig(
            name="test-backend", provider="openai", api_key="test-key", max_retries=3
        )
        mock_logger = Mock()
        backend = LangChainBackend(config, logger=mock_logger)

        mock_model = Mock()
        # First call fails, connection during retry also fails, then succeeds
        mock_response = Mock()
        mock_response.content = "Rating 4: Good match"
        mock_model.invoke.side_effect = [
            Exception("Network error"),  # First attempt fails
            mock_response,  # Second attempt succeeds
        ]

        # Mock connect to fail on second call (during retry), then succeed
        connect_call_count = 0

        def mock_connect():
            nonlocal connect_call_count
            connect_call_count += 1
            if connect_call_count == 2:
                # Reconnect attempt during retry fails
                raise Exception("Connection failed")
            else:
                # Initial connect and final reconnect succeed
                backend._chat_model = mock_model

        with (
            patch("ai_marketplace_monitor.ai.AIResponse.from_cache", return_value=None),
            patch("ai_marketplace_monitor.ai.counter"),
            patch.object(backend, "connect", side_effect=mock_connect),
            patch.object(backend, "get_prompt", return_value="test prompt"),
            patch("time.sleep"),
        ):
            backend._chat_model = mock_model
            result = backend.evaluate(listing, item_config, marketplace_config)

            assert result.score == 4
            # Should log both the invoke error and the connection error
            assert mock_logger.error.call_count >= 2

    def test_thread_safety_with_concurrent_access(
        self,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
        listing: Listing,
    ) -> None:
        """Test thread safety when multiple threads access the backend concurrently."""
        import concurrent.futures
        from unittest.mock import patch

        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        mock_response = Mock()
        mock_response.content = "Rating 3: Thread-safe response"

        results = []
        errors = []

        def evaluate_listing():
            try:
                with (
                    patch("ai_marketplace_monitor.ai.AIResponse.from_cache", return_value=None),
                    patch("ai_marketplace_monitor.ai.counter"),
                    patch.object(backend, "get_prompt", return_value="test prompt"),
                    patch.object(backend, "_get_model") as mock_get_model,
                ):
                    mock_model = Mock()
                    mock_model.invoke.return_value = mock_response
                    mock_get_model.return_value = mock_model

                    result = backend.evaluate(listing, item_config, marketplace_config)
                    results.append(result)
            except Exception as e:
                errors.append(e)

        # Run multiple threads concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(evaluate_listing) for _ in range(10)]
            concurrent.futures.wait(futures)

        # All evaluations should succeed
        assert len(errors) == 0, f"Unexpected errors: {errors}"
        assert len(results) == 10
        # All results should have the same score
        assert all(result.score == 3 for result in results)

    def test_parse_ai_response_basic(self) -> None:
        """Test _parse_ai_response with basic rating format."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)
        item_config = Mock()
        item_config.name = "test-item"

        answer = "This is a good match.\nRating 4: Great condition and price"

        with patch("ai_marketplace_monitor.ai.counter"):
            result = backend._parse_ai_response(answer, item_config)

        assert result.score == 4
        assert "Great condition and price" in result.comment
        assert result.name == "test-backend"

    def test_parse_ai_response_multiline_comment(self) -> None:
        """Test _parse_ai_response with multiline comment after rating."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)
        item_config = Mock()
        item_config.name = "test-item"

        answer = """This looks good.
Rating 3: Decent match
The price is reasonable
But condition could be better"""

        with patch("ai_marketplace_monitor.ai.counter"):
            result = backend._parse_ai_response(answer, item_config)

        assert result.score == 3
        assert (
            "Decent match The price is reasonable But condition could be better" in result.comment
        )

    def test_parse_ai_response_invalid_format(self) -> None:
        """Test _parse_ai_response with invalid response format."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)
        item_config = Mock()
        item_config.name = "test-item"

        answer = "No rating provided in this response"

        with patch("ai_marketplace_monitor.ai.counter") as mock_counter:
            with pytest.raises(ValueError, match="Empty or invalid response"):
                backend._parse_ai_response(answer, item_config)

            mock_counter.increment.assert_called_once()

    def test_get_model_keyerror_handling(self) -> None:
        """Test enhanced error handling for KeyError from provider factory."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        with patch("ai_marketplace_monitor.ai.provider_map") as mock_provider_map:
            mock_factory = Mock(side_effect=KeyError("api_key"))
            mock_provider_map.__getitem__.return_value = mock_factory
            mock_provider_map.__contains__.return_value = True

            with pytest.raises(ValueError, match="configuration error.*Check API key"):
                backend._get_model(config)

    def test_get_model_typeerror_handling(self) -> None:
        """Test enhanced error handling for TypeError from provider factory."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        with patch("ai_marketplace_monitor.ai.provider_map") as mock_provider_map:
            mock_factory = Mock(side_effect=TypeError("invalid parameter type"))
            mock_provider_map.__getitem__.return_value = mock_factory
            mock_provider_map.__contains__.return_value = True

            with pytest.raises(ValueError, match="configuration error.*Check API key"):
                backend._get_model(config)

    def test_get_model_importerror_handling(self) -> None:
        """Test enhanced error handling for ImportError from provider factory."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        with patch("ai_marketplace_monitor.ai.provider_map") as mock_provider_map:
            mock_factory = Mock(side_effect=ImportError("langchain_openai not found"))
            mock_provider_map.__getitem__.return_value = mock_factory
            mock_provider_map.__contains__.return_value = True

            with pytest.raises(
                RuntimeError, match="dependencies not installed.*Install the required"
            ):
                backend._get_model(config)

    def test_get_model_chained_exception_handling(self) -> None:
        """Test enhanced error handling for RuntimeError exceptions."""
        config = AIConfig(name="test-backend", provider="openai", api_key="test-key")
        backend = LangChainBackend(config)

        # Create a chained exception
        try:
            raise ValueError("original error")
        except ValueError as original:
            chained_error = RuntimeError("chained error")
            chained_error.__cause__ = original

            with patch("ai_marketplace_monitor.ai.provider_map") as mock_provider_map:
                mock_factory = Mock(side_effect=chained_error)
                mock_provider_map.__getitem__.return_value = mock_factory
                mock_provider_map.__contains__.return_value = True

                with pytest.raises(RuntimeError, match="Failed to create model.*chained error"):
                    backend._get_model(config)


class TestResponseAdapter:
    """Test the LangChain response adapter functionality."""

    def test_adapt_langchain_response_basic(self) -> None:
        """Test adapter with basic LangChain response."""
        mock_response = Mock()
        mock_response.content = "Sample response content"
        mock_response.usage_metadata = {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        }
        mock_response.response_metadata = {
            "model": "gpt-4",
            "provider": "openai",
        }

        result = adapt_langchain_response(
            response=mock_response,
            backend_name="test-backend",
            parsed_score=4,
            parsed_comment="Good match",
        )

        assert result.score == 4
        assert result.comment == "Good match"
        assert result.name == "test-backend"
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 50
        assert result.total_tokens == 150
        assert result.usage_metadata["input_tokens"] == 100
        assert result.usage_metadata["output_tokens"] == 50
        assert result.response_metadata["model"] == "gpt-4"
        assert result.has_token_usage is True

    def test_adapt_langchain_response_no_usage_metadata(self) -> None:
        """Test adapter with response lacking usage metadata."""
        mock_response = Mock()
        mock_response.content = "Sample response content"
        mock_response.usage_metadata = None
        mock_response.response_metadata = {"model": "gpt-3.5"}

        result = adapt_langchain_response(
            response=mock_response,
            backend_name="test-backend",
            parsed_score=3,
            parsed_comment="Average match",
        )

        assert result.score == 3
        assert result.comment == "Average match"
        assert result.name == "test-backend"
        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0
        assert result.total_tokens == 0
        assert result.usage_metadata == {}
        assert result.response_metadata["model"] == "gpt-3.5"
        assert result.has_token_usage is False

    def test_adapt_langchain_response_additional_kwargs_usage(self) -> None:
        """Test adapter with usage info in additional_kwargs."""
        mock_response = Mock()
        mock_response.content = "Sample response content"
        mock_response.usage_metadata = None
        mock_response.response_metadata = None
        mock_response.additional_kwargs = {
            "usage": {
                "prompt_tokens": 75,
                "completion_tokens": 25,
                "total_tokens": 100,
            },
            "model": "deepseek-chat",
            "_private_field": "should_be_ignored",
        }

        result = adapt_langchain_response(
            response=mock_response,
            backend_name="deepseek-backend",
            parsed_score=5,
            parsed_comment="Excellent match",
        )

        assert result.score == 5
        assert result.comment == "Excellent match"
        assert result.name == "deepseek-backend"
        assert result.prompt_tokens == 75
        assert result.completion_tokens == 25
        assert result.total_tokens == 100
        assert result.usage_metadata["prompt_tokens"] == 75
        assert result.response_metadata["model"] == "deepseek-chat"
        assert "_private_field" not in result.response_metadata
        assert result.has_token_usage is True

    def test_adapt_langchain_response_no_attributes(self) -> None:
        """Test adapter with minimal response object."""
        mock_response = Mock()
        mock_response.content = "Sample response content"
        # Remove attributes that might not exist on all response types
        del mock_response.usage_metadata
        del mock_response.response_metadata
        del mock_response.additional_kwargs

        result = adapt_langchain_response(
            response=mock_response,
            backend_name="minimal-backend",
            parsed_score=2,
            parsed_comment="Poor match",
        )

        assert result.score == 2
        assert result.comment == "Poor match"
        assert result.name == "minimal-backend"
        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0
        assert result.total_tokens == 0
        assert result.usage_metadata == {}
        assert result.response_metadata == {}
        assert result.has_token_usage is False


class TestAIResponseEnhancements:
    """Test enhanced AIResponse functionality."""

    def test_ai_response_cost_estimation(self) -> None:
        """Test cost estimation functionality."""
        response = AIResponse(
            score=4,
            comment="Good match",
            name="test",
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
        )

        # Test cost calculation
        cost = response.get_cost_estimate(prompt_price_per_k=0.01, completion_price_per_k=0.02)
        expected_cost = (1000 / 1000) * 0.01 + (500 / 1000) * 0.02  # 0.01 + 0.01 = 0.02
        assert cost == expected_cost

        # Test with no token usage
        response_no_tokens = AIResponse(score=3, comment="Test", name="test")
        assert response_no_tokens.get_cost_estimate(0.01, 0.02) == 0.0

    def test_ai_response_backward_compatibility(self) -> None:
        """Test that enhanced AIResponse maintains backward compatibility."""
        # Old-style construction (should work with defaults)
        old_style = AIResponse(score=3, comment="Test", name="backend")
        assert old_style.prompt_tokens == 0
        assert old_style.completion_tokens == 0
        assert old_style.total_tokens == 0
        assert old_style.usage_metadata == {}
        assert old_style.response_metadata == {}
        assert old_style.has_token_usage is False

        # Properties should still work
        assert old_style.conclusion == "Poor match"
        assert old_style.style == "name"
        assert "☆" in old_style.stars  # Should have some empty stars

    def test_ai_response_serialization_compatibility(self) -> None:
        """Test that enhanced AIResponse works with serialization."""
        import json
        from dataclasses import asdict

        enhanced_response = AIResponse(
            score=4,
            comment="Great deal",
            name="test-backend",
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
            usage_metadata={"model": "gpt-4", "provider": "openai"},
            response_metadata={"temperature": 0.7, "max_tokens": 150},
        )

        # Test serialization
        serialized = asdict(enhanced_response)
        assert serialized["prompt_tokens"] == 200
        assert serialized["usage_metadata"]["model"] == "gpt-4"

        # Test JSON compatibility
        json_str = json.dumps(serialized)
        deserialized = json.loads(json_str)

        # Test reconstruction
        reconstructed = AIResponse(**deserialized)
        assert reconstructed.score == 4
        assert reconstructed.prompt_tokens == 200
        assert reconstructed.usage_metadata["model"] == "gpt-4"
        assert reconstructed.has_token_usage is True


class TestOpenRouterProvider:
    """Test suite for OpenRouter provider functionality."""

    def test_create_openrouter_model_valid_config(self) -> None:
        """Test OpenRouter model creation with valid configuration."""
        from ai_marketplace_monitor.ai import _create_openrouter_model

        config = AIConfig(
            name="test-openrouter",
            provider="openrouter",
            api_key="sk-or-abcdefgh7890abcdefgh7890abcdefgh7890abcdefgh",
            model="anthropic/claude-3-sonnet",
            timeout=60,
            max_retries=3,
        )

        with patch("ai_marketplace_monitor.ai.ChatOpenAI") as mock_chat_openai:
            mock_model = Mock()
            mock_chat_openai.return_value = mock_model

            result = _create_openrouter_model(config)

            assert result == mock_model
            mock_chat_openai.assert_called_once()
            call_args = mock_chat_openai.call_args

            # Verify API key is properly wrapped in SecretStr
            assert (
                call_args.kwargs["api_key"].get_secret_value()
                == "sk-or-abcdefgh7890abcdefgh7890abcdefgh7890abcdefgh"
            )
            assert call_args.kwargs["model"] == "anthropic/claude-3-sonnet"
            assert call_args.kwargs["base_url"] == "https://openrouter.ai/api/v1"
            assert call_args.kwargs["timeout"] == 60
            assert call_args.kwargs["max_retries"] == 3

            # Verify headers
            headers = call_args.kwargs["default_headers"]
            assert headers["X-Title"] == "AI Marketplace Monitor"
            assert headers["HTTP-Referer"] == "https://github.com/BoPeng/ai-marketplace-monitor"

    def test_create_openrouter_model_env_api_key(self) -> None:
        """Test OpenRouter model creation using environment API key."""
        from ai_marketplace_monitor.ai import _create_openrouter_model

        config = AIConfig(name="test-openrouter", provider="openrouter", model="openai/gpt-4o")

        with (
            patch.dict(
                os.environ,
                {"OPENROUTER_API_KEY": "sk-or-envkey7890abcdefgh7890abcdefgh7890abcdefgh"},
            ),
            patch("ai_marketplace_monitor.ai.ChatOpenAI") as mock_chat_openai,
        ):
            mock_model = Mock()
            mock_chat_openai.return_value = mock_model

            result = _create_openrouter_model(config)

            assert result == mock_model
            call_args = mock_chat_openai.call_args
            assert (
                call_args.kwargs["api_key"].get_secret_value()
                == "sk-or-envkey7890abcdefgh7890abcdefgh7890abcdefgh"
            )

    def test_create_openrouter_model_missing_api_key(self) -> None:
        """Test OpenRouter model creation with missing API key."""
        from ai_marketplace_monitor.ai import _create_openrouter_model

        config = AIConfig(
            name="test-openrouter", provider="openrouter", model="anthropic/claude-3-sonnet"
        )

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="OpenRouter API key is required"):
                _create_openrouter_model(config)

    def test_create_openrouter_model_invalid_api_key_format(self) -> None:
        """Test OpenRouter model creation with invalid API key format."""
        from ai_marketplace_monitor.ai import _create_openrouter_model

        config = AIConfig(
            name="test-openrouter",
            provider="openrouter",
            api_key="invalid-key-format",
            model="anthropic/claude-3-sonnet",
        )

        with pytest.raises(ValueError, match="OpenRouter API key must start with 'sk-or-'"):
            _create_openrouter_model(config)

    def test_create_openrouter_model_invalid_model_format(self) -> None:
        """Test OpenRouter model creation with invalid model format."""
        from ai_marketplace_monitor.ai import _create_openrouter_model

        config = AIConfig(
            name="test-openrouter",
            provider="openrouter",
            api_key="sk-or-abcdefgh7890abcdefgh7890abcdefgh7890abcdefgh",
            model="gpt-4",  # Should be "openai/gpt-4"
        )

        with pytest.raises(ValueError, match="must follow 'provider/model' format"):
            _create_openrouter_model(config)

    def test_create_openrouter_model_default_model(self) -> None:
        """Test OpenRouter model creation with default model."""
        from ai_marketplace_monitor.ai import _create_openrouter_model

        config = AIConfig(
            name="test-openrouter",
            provider="openrouter",
            api_key="sk-or-abcdefgh7890abcdefgh7890abcdefgh7890abcdefgh",
            # No model specified - should use default
        )

        with patch("ai_marketplace_monitor.ai.ChatOpenAI") as mock_chat_openai:
            mock_model = Mock()
            mock_chat_openai.return_value = mock_model

            result = _create_openrouter_model(config)

            assert result == mock_model
            call_args = mock_chat_openai.call_args
            assert call_args.kwargs["model"] == "anthropic/claude-3-sonnet"

    def test_create_openrouter_model_custom_base_url(self) -> None:
        """Test OpenRouter model creation with custom base URL."""
        from ai_marketplace_monitor.ai import _create_openrouter_model

        config = AIConfig(
            name="test-openrouter",
            provider="openrouter",
            api_key="sk-or-abcdefgh7890abcdefgh7890abcdefgh7890abcdefgh",
            model="anthropic/claude-3-sonnet",
            base_url="https://custom-openrouter-proxy.example.com/v1",
        )

        with patch("ai_marketplace_monitor.ai.ChatOpenAI") as mock_chat_openai:
            mock_model = Mock()
            mock_chat_openai.return_value = mock_model

            result = _create_openrouter_model(config)

            assert result == mock_model
            call_args = mock_chat_openai.call_args
            assert call_args.kwargs["base_url"] == "https://custom-openrouter-proxy.example.com/v1"

    def test_openrouter_provider_mapping(self) -> None:
        """Test that OpenRouter is properly mapped in the provider_map."""
        from ai_marketplace_monitor.ai import _create_openrouter_model, provider_map

        assert "openrouter" in provider_map
        assert provider_map["openrouter"] == _create_openrouter_model

    def test_langchain_backend_with_openrouter(
        self,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
        listing: Listing,
    ) -> None:
        """Test LangChainBackend integration with OpenRouter provider."""
        config = AIConfig(
            name="test-openrouter",
            provider="openrouter",
            api_key="sk-or-abcdefgh7890abcdefgh7890abcdefgh7890abcdefgh",
            model="anthropic/claude-3-sonnet",
            max_retries=1,
        )
        backend = LangChainBackend(config)

        # Mock the OpenRouter model and its response
        mock_model = Mock()
        mock_response = Mock()
        mock_response.content = "This looks good.\nRating 4: Great deal with good condition"
        mock_response.usage_metadata = {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
        }
        mock_response.response_metadata = {"model": "anthropic/claude-3-sonnet"}
        mock_model.invoke.return_value = mock_response

        with (
            patch("ai_marketplace_monitor.ai.AIResponse.from_cache", return_value=None),
            patch("ai_marketplace_monitor.ai.counter"),
            patch.object(backend, "_get_model", return_value=mock_model),
        ):
            result = backend.evaluate(listing, item_config, marketplace_config)

            assert result.score == 4
            assert "Great deal with good condition" in result.comment
            assert result.name == "test-openrouter"
            assert result.prompt_tokens == 100
            assert result.completion_tokens == 50
            assert result.total_tokens == 150


class TestOpenRouterValidationEnhancements:
    """Test enhanced validation for OpenRouter provider."""

    def test_model_format_validation_edge_cases(self) -> None:
        """Test edge cases in model format validation."""
        from ai_marketplace_monitor.ai import _validate_openrouter_model_format

        # Valid cases should not raise
        _validate_openrouter_model_format("anthropic/claude-3-sonnet")
        _validate_openrouter_model_format("openai/gpt-4")
        _validate_openrouter_model_format("meta-llama/llama-3.1-8b-instruct")

        # Invalid cases should raise ValueError
        invalid_models = [
            "",  # Empty string
            "no-slash",  # No slash
            "provider/",  # Empty model
            "/model",  # Empty provider
            "provider//model",  # Double slash
            "provider/model/extra",  # Too many parts
            " provider/model",  # Leading whitespace
            "provider/model ",  # Trailing whitespace
            "provider/ model",  # Whitespace in model name
        ]

        for invalid_model in invalid_models:
            with pytest.raises(ValueError):
                _validate_openrouter_model_format(invalid_model)

    def test_api_key_strength_validation_placeholder_detection(self) -> None:
        """Test API key strength validation detects placeholder keys."""
        from ai_marketplace_monitor.ai import _validate_openrouter_api_key_strength

        # Valid key should pass
        _validate_openrouter_api_key_strength("sk-or-abcdef7890abcdef7890abcdef7890abcdef78901234")

        # Short keys should fail
        with pytest.raises(ValueError, match="too short"):
            _validate_openrouter_api_key_strength("sk-or-short")

        # Placeholder keys should fail (make them long enough to avoid length check)
        placeholder_keys = [
            "sk-or-test-1234567890abcdef1234567890",
            "sk-or-example-key-1234567890abcdef123",
            "sk-or-your-key-here-1234567890abcdef",
            "sk-or-placeholder-12345-1234567890ab",
            "sk-or-demo-key-1234567890abcdef12345",
            "sk-or-sample-key-1234567890abcdef123",
            "sk-or-fake-key-1234567890abcdef12345",
        ]

        for placeholder_key in placeholder_keys:
            with pytest.raises(ValueError, match="actual OpenRouter API key"):
                _validate_openrouter_api_key_strength(placeholder_key)

        # Test that short placeholder key is caught for length first
        with pytest.raises(ValueError, match="too short"):
            _validate_openrouter_api_key_strength("sk-or-test")

        # Test the specific 12345 pattern with sufficient length
        with pytest.raises(ValueError, match="actual OpenRouter API key"):
            _validate_openrouter_api_key_strength("sk-or-12345-1234567890abcdef1234567890")

    def test_api_key_strength_validation_openai_key_detection(self) -> None:
        """Test that OpenAI keys are detected and rejected."""
        from ai_marketplace_monitor.ai import _validate_openrouter_api_key_strength

        # OpenAI-style keys should be rejected
        openai_keys = [
            "sk-1234567890abcdef1234567890abcdef12345678",
            "sk-proj-1234567890abcdef1234567890abcdef12345678",
        ]

        for openai_key in openai_keys:
            with pytest.raises(ValueError, match="OpenAI API key for OpenRouter"):
                _validate_openrouter_api_key_strength(openai_key)


class TestOpenRouterCaching:
    """Test OpenRouter model availability and rate limiting caching with disk-based cache."""

    @pytest.fixture(autouse=True)
    def setup_cache_cleanup(self) -> Any:
        """Efficiently clear cache before and after each test."""
        from ai_marketplace_monitor.utils import cache

        # More efficient cache cleanup - target specific patterns
        self._clear_openrouter_cache(cache)
        yield
        # Cleanup after test as well
        self._clear_openrouter_cache(cache)

    def _clear_openrouter_cache(self, cache: Any) -> None:
        """Efficiently clear OpenRouter-specific cache entries."""
        try:
            # Try more efficient bulk operations if available
            cache_keys_to_delete = []
            key_count = 0
            for key in cache.iterkeys():
                if isinstance(key, str) and key.startswith("openrouter_"):
                    cache_keys_to_delete.append(key)
                    key_count += 1
                # Early termination to avoid full cache scan for large caches
                if key_count > 1000:  # Reasonable limit
                    break

            # Batch delete for better performance
            for key in cache_keys_to_delete:
                cache.delete(key)

        except Exception:
            # Fallback: clear entire cache if targeted cleanup fails
            # This ensures test isolation even if optimization fails
            cache.clear()

    @pytest.fixture
    def unique_model_name(self) -> str:
        """Provide unique model name for testing to ensure isolation."""
        import uuid

        return f"test/model-{uuid.uuid4().hex[:8]}"

    @pytest.fixture
    def unique_provider_name(self) -> str:
        """Provide unique provider name for testing to ensure isolation."""
        import uuid

        return f"test-provider-{uuid.uuid4().hex[:8]}"

    def test_model_availability_caching(self, unique_model_name: str) -> None:
        """Test that model availability is cached properly using disk cache."""
        from ai_marketplace_monitor.ai import (
            _cache_model_availability,
            _is_model_cached_available,
            _is_model_cached_unavailable,
        )

        model = unique_model_name

        # Initially should not be cached
        assert not _is_model_cached_available(
            model
        ), f"Model {model} should not be initially cached as available"
        assert (
            _is_model_cached_unavailable(model) is None
        ), f"Model {model} should not be initially cached as unavailable"

        # Cache as available
        _cache_model_availability(model, available=True)
        assert _is_model_cached_available(
            model
        ), f"Model {model} should be cached as available after caching"
        assert (
            _is_model_cached_unavailable(model) is None
        ), f"Model {model} should not be cached as unavailable when available"

        # Cache as unavailable with error type
        _cache_model_availability(model, available=False, error_type="model_not_found")
        assert not _is_model_cached_available(
            model
        ), f"Model {model} should not be cached as available when unavailable"
        assert (
            _is_model_cached_unavailable(model) == "model_not_found"
        ), f"Model {model} should be cached as unavailable with error 'model_not_found'"

        # Test switching back to available clears unavailable status
        _cache_model_availability(model, available=True)
        assert _is_model_cached_available(
            model
        ), f"Model {model} should be cached as available after switching back"
        assert (
            _is_model_cached_unavailable(model) is None
        ), f"Model {model} should not be cached as unavailable after switching back to available"

    def test_rate_limiting_caching(self, unique_provider_name: str) -> None:
        """Test that provider rate limiting is cached properly using disk cache."""
        from ai_marketplace_monitor.ai import _cache_rate_limit, _is_provider_rate_limited

        provider = unique_provider_name

        # Initially should not be rate limited
        assert not _is_provider_rate_limited(
            provider
        ), f"Provider {provider} should not be initially rate limited"

        # Cache rate limit status
        _cache_rate_limit(provider)
        assert _is_provider_rate_limited(
            provider
        ), f"Provider {provider} should be rate limited after caching"

        # Test with different provider to ensure isolation
        other_provider = f"{unique_provider_name}-other"
        assert not _is_provider_rate_limited(
            other_provider
        ), f"Different provider {other_provider} should not be affected by rate limiting another provider"

    def test_cache_expiration_integration(self) -> None:
        """Test that cache entries expire properly by testing cache behavior over time."""
        from ai_marketplace_monitor.ai import (
            _cache_model_availability,
            _cache_rate_limit,
            _is_model_cached_available,
            _is_model_cached_unavailable,
            _is_provider_rate_limited,
        )
        from ai_marketplace_monitor.utils import cache

        model = "test/expiration-model"
        provider = "test-provider"

        # Cache model as available
        _cache_model_availability(model, available=True)
        assert _is_model_cached_available(model)

        # Cache model as unavailable
        _cache_model_availability(model, available=False, error_type="test_error")
        assert _is_model_cached_unavailable(model) == "test_error"

        # Cache rate limit
        _cache_rate_limit(provider)
        assert _is_provider_rate_limited(provider)

        # Test cache expiration by checking cache keys exist
        unavailable_key = f"openrouter_model_unavailable_{model}"
        rate_limit_key = f"openrouter_rate_limit_{provider}"

        # Keys should exist in cache immediately after setting
        assert unavailable_key in cache
        assert rate_limit_key in cache

        # Manually expire entries and verify they're gone
        cache.delete(unavailable_key)
        cache.delete(rate_limit_key)

        assert not _is_model_cached_unavailable(model)
        assert not _is_provider_rate_limited(provider)

    def test_openrouter_model_creation_with_cached_unavailable(self) -> None:
        """Test that cached unavailable models are rejected early in model creation."""
        from ai_marketplace_monitor.ai import _cache_model_availability, _create_openrouter_model

        config = AIConfig(
            name="test-openrouter",
            provider="openrouter",
            api_key="sk-or-abcdefgh7890abcdefgh7890abcdefgh7890abcdefgh",
            model="invalid/model",
        )

        # Cache model as unavailable with specific error type
        _cache_model_availability("invalid/model", available=False, error_type="model_not_found")

        # Should raise ValueError due to cached unavailable status
        with pytest.raises(ValueError, match="currently unavailable"):
            _create_openrouter_model(config)

    def test_openrouter_model_creation_with_rate_limited_provider(self) -> None:
        """Test that rate limited providers are rejected early in model creation."""
        from ai_marketplace_monitor.ai import _cache_rate_limit, _create_openrouter_model

        config = AIConfig(
            name="test-openrouter",
            provider="openrouter",
            api_key="sk-or-abcdefgh7890abcdefgh7890abcdefgh7890abcdefgh",
            model="anthropic/claude-3-sonnet",
        )

        # Cache provider as rate limited
        _cache_rate_limit("anthropic")

        # Should raise RuntimeError due to cached rate limit status
        with pytest.raises(RuntimeError, match="currently rate limited"):
            _create_openrouter_model(config)

    def test_cache_key_isolation(self, unique_model_name: str, unique_provider_name: str) -> None:
        """Test that cache keys are properly isolated between models and providers."""
        from ai_marketplace_monitor.ai import (
            _cache_model_availability,
            _cache_rate_limit,
            _is_model_cached_available,
            _is_model_cached_unavailable,
            _is_provider_rate_limited,
        )

        # Test different models don't interfere with each other
        model1 = unique_model_name
        model2 = f"{unique_model_name}-different"

        _cache_model_availability(model1, available=True)
        _cache_model_availability(model2, available=False, error_type="quota_exceeded")

        assert _is_model_cached_available(model1), f"Model {model1} should be cached as available"
        assert not _is_model_cached_available(
            model2
        ), f"Model {model2} should not be cached as available"
        assert (
            _is_model_cached_unavailable(model1) is None
        ), f"Model {model1} should not be cached as unavailable"
        assert (
            _is_model_cached_unavailable(model2) == "quota_exceeded"
        ), f"Model {model2} should be cached as unavailable with error 'quota_exceeded'"

        # Test different providers don't interfere with each other
        provider1 = unique_provider_name
        provider2 = f"{unique_provider_name}-different"

        _cache_rate_limit(provider1)

        assert _is_provider_rate_limited(
            provider1
        ), f"Provider {provider1} should be rate limited after caching"
        assert not _is_provider_rate_limited(
            provider2
        ), f"Provider {provider2} should not be affected by rate limiting {provider1}"

    def test_cache_state_transitions(self, unique_model_name: str) -> None:
        """Test that cache properly handles state transitions between available/unavailable."""
        from ai_marketplace_monitor.ai import (
            _cache_model_availability,
            _is_model_cached_available,
            _is_model_cached_unavailable,
        )

        model = unique_model_name

        # Start with unavailable
        _cache_model_availability(model, available=False, error_type="temporary_error")
        assert not _is_model_cached_available(
            model
        ), f"Model {model} should not be cached as available when unavailable"
        assert (
            _is_model_cached_unavailable(model) == "temporary_error"
        ), f"Model {model} should be cached as unavailable with error 'temporary_error'"

        # Transition to available should clear unavailable status
        _cache_model_availability(model, available=True)
        assert _is_model_cached_available(
            model
        ), f"Model {model} should be cached as available after transition"
        assert (
            _is_model_cached_unavailable(model) is None
        ), f"Model {model} should not be cached as unavailable after transition to available"

        # Transition back to unavailable should clear available status
        _cache_model_availability(model, available=False, error_type="permanent_error")
        assert not _is_model_cached_available(
            model
        ), f"Model {model} should not be cached as available after transition back to unavailable"
        assert (
            _is_model_cached_unavailable(model) == "permanent_error"
        ), f"Model {model} should be cached as unavailable with error 'permanent_error'"

    def test_cache_corruption_resilience(
        self, unique_model_name: str, unique_provider_name: str
    ) -> None:
        """Test current behavior when cache contains corrupted or invalid data.

        Note: This test documents the current behavior and can serve as a basis
        for future improvements to add corruption resilience.
        """
        from ai_marketplace_monitor.ai import (
            _is_model_cached_available,
            _is_model_cached_unavailable,
            _is_provider_rate_limited,
        )
        from ai_marketplace_monitor.utils import cache

        model = unique_model_name
        provider = unique_provider_name

        # Test corrupted boolean availability data - currently returns the corrupted value as-is
        available_key = f"openrouter_model_available_{model}"
        cache.set(available_key, "invalid_boolean_value")

        # Current behavior: returns the corrupted value (future improvement: should handle gracefully)
        result = _is_model_cached_available(model)
        assert (
            result == "invalid_boolean_value"
        ), f"Current implementation returns corrupted value as-is for model {model}"

        # Test corrupted unavailable data - currently returns the corrupted value as-is
        unavailable_key = f"openrouter_model_unavailable_{model}"
        cache.set(unavailable_key, {"invalid": "structure"})

        result = _is_model_cached_unavailable(model)
        assert result == {
            "invalid": "structure"
        }, f"Current implementation returns corrupted value as-is for model {model}"

        # Test corrupted rate limit data - currently returns the corrupted value as-is
        rate_limit_key = f"openrouter_rate_limit_{provider}"
        cache.set(rate_limit_key, [1, 2, 3])  # Invalid type

        result = _is_provider_rate_limited(provider)
        assert result == [
            1,
            2,
            3,
        ], f"Current implementation returns corrupted value as-is for provider {provider}"

        # Test handling of None values - this should work correctly as None is the expected default
        cache.set(available_key, None)
        result = _is_model_cached_available(model)
        assert result is None, f"None cache value should be returned as-is for model {model}"

        # Test with explicit default values working correctly
        cache.delete(available_key)  # Remove the key entirely
        result = _is_model_cached_available(model)
        assert result is False, f"Missing cache key should return default False for model {model}"

    def test_concurrent_cache_access(
        self, unique_model_name: str, unique_provider_name: str
    ) -> None:
        """Test thread safety of cache operations with concurrent access."""
        import threading
        import time

        from ai_marketplace_monitor.ai import (
            _cache_model_availability,
            _cache_rate_limit,
            _is_model_cached_available,
            _is_provider_rate_limited,
        )

        model = unique_model_name
        provider = unique_provider_name
        results = []
        errors = []

        def cache_model_worker():
            """Worker function that performs cache operations on models."""
            try:
                for i in range(10):
                    _cache_model_availability(f"{model}-{i}", True)
                    time.sleep(0.001)  # Small delay to increase chance of race conditions
                    result = _is_model_cached_available(f"{model}-{i}")
                    results.append(("model", f"{model}-{i}", result))
            except Exception as e:
                errors.append(("model_worker", e))

        def cache_provider_worker():
            """Worker function that performs cache operations on providers."""
            try:
                for i in range(10):
                    _cache_rate_limit(f"{provider}-{i}")
                    time.sleep(0.001)  # Small delay to increase chance of race conditions
                    result = _is_provider_rate_limited(f"{provider}-{i}")
                    results.append(("provider", f"{provider}-{i}", result))
            except Exception as e:
                errors.append(("provider_worker", e))

        # Create multiple threads performing concurrent cache operations
        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=cache_model_worker))
            threads.append(threading.Thread(target=cache_provider_worker))

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=10.0)  # 10 second timeout to prevent hanging
            assert not thread.is_alive(), "Thread should have completed within timeout"

        # Verify no errors occurred during concurrent access
        assert len(errors) == 0, f"Concurrent cache access errors: {errors}"

        # Verify all operations completed successfully
        expected_results = 3 * 10 * 2  # 3 threads * 10 operations * 2 types (model/provider)
        assert (
            len(results) == expected_results
        ), f"Expected {expected_results} results, got {len(results)}"

        # Verify all cached values are correct
        model_results = [r for r in results if r[0] == "model"]
        provider_results = [r for r in results if r[0] == "provider"]

        assert all(r[2] is True for r in model_results), "All model cache results should be True"
        assert all(
            r[2] is True for r in provider_results
        ), "All provider cache results should be True"

        # Test cache consistency after concurrent operations
        for i in range(10):
            assert _is_model_cached_available(
                f"{model}-{i}"
            ), f"Model {model}-{i} should remain cached after concurrent operations"
            assert _is_provider_rate_limited(
                f"{provider}-{i}"
            ), f"Provider {provider}-{i} should remain cached after concurrent operations"
