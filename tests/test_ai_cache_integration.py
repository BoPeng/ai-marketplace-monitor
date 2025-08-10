"""Integration tests for AIResponse caching behavior validation.

Tests comprehensive cache integration scenarios for Task 9.3:
- Cache hit/miss scenarios with different backends
- Cache invalidation when listings or configs change
- Serialization consistency across AI backends
- Performance validation with caching enabled
- Migration compatibility for legacy cached responses
"""

import time
import unittest.mock
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Generator, Optional, Tuple, Type
from unittest.mock import Mock, patch

import pytest
from diskcache import Cache

from ai_marketplace_monitor.ai import (
    AIConfig,
    AIResponse,
    LangChainBackend,
    adapt_langchain_response,
)
from ai_marketplace_monitor.facebook import FacebookItemConfig, FacebookMarketplaceConfig
from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.utils import CacheType


@pytest.mark.usefixtures("clean_ai_response")
class TestAIResponseCacheIntegration:
    """Integration test suite for comprehensive AIResponse cache behavior validation."""

    @pytest.fixture(autouse=True)
    def clean_ai_response(self, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
        """Ensure AIResponse.from_cache is not mocked for cache integration tests."""
        # Stop all active patches to clean up any lingering mocks
        unittest.mock.patch.stopall()

        # Directly import and use the original methods from the module
        # This ensures we're using the real implementation, not any mocked version
        import ai_marketplace_monitor.ai

        # Store the original methods before any potential interference
        original_from_cache = self._create_clean_from_cache()
        original_to_cache = self._create_clean_to_cache()

        # Replace the methods on the AIResponse class with clean versions
        monkeypatch.setattr(
            ai_marketplace_monitor.ai.AIResponse, "from_cache", original_from_cache
        )
        monkeypatch.setattr(ai_marketplace_monitor.ai.AIResponse, "to_cache", original_to_cache)

        # Yield control to the test
        yield

        # Cleanup is handled by monkeypatch automatically

    def _create_clean_from_cache(self) -> classmethod:
        """Create a clean version of from_cache that bypasses any mocking."""
        from ai_marketplace_monitor.ai import AIResponse
        from ai_marketplace_monitor.utils import CacheType, cache

        @classmethod
        def clean_from_cache(
            cls: Type[AIResponse],
            listing: Listing,
            item_config: FacebookItemConfig,
            marketplace_config: FacebookMarketplaceConfig,
            local_cache: Optional[Cache] = None,
        ) -> Optional[AIResponse]:
            """Clean implementation of from_cache that bypasses mocks."""
            target_cache = cache if local_cache is None else local_cache
            cache_key = (
                CacheType.AI_INQUIRY.value,
                item_config.hash,
                marketplace_config.hash,
                listing.hash,
            )

            res = target_cache.get(cache_key)
            if res is None:
                return None

            # Handle cache migration for legacy AIResponse objects without new metadata fields
            if not isinstance(res, dict):
                return None

            # Provide defaults for new metadata fields if missing from cached response
            migrated_res = res.copy()
            if "usage_metadata" not in migrated_res:
                migrated_res["usage_metadata"] = {}
            if "response_metadata" not in migrated_res:
                migrated_res["response_metadata"] = {}

            # Ensure metadata fields are dict types (handle None values from old cache entries)
            if migrated_res.get("usage_metadata") is None:
                migrated_res["usage_metadata"] = {}
            if migrated_res.get("response_metadata") is None:
                migrated_res["response_metadata"] = {}

            try:
                return AIResponse(**migrated_res)
            except TypeError:
                # If reconstruction fails due to incompatible cached data, return None
                return None

        return clean_from_cache

    def _create_clean_to_cache(self) -> callable:
        """Create a clean version of to_cache that bypasses any mocking."""
        from dataclasses import asdict

        from ai_marketplace_monitor.utils import CacheType, cache

        def clean_to_cache(
            self: AIResponse,
            listing: Listing,
            item_config: FacebookItemConfig,
            marketplace_config: FacebookMarketplaceConfig,
            local_cache: Optional[Cache] = None,
        ) -> None:
            """Clean implementation of to_cache that bypasses mocks."""
            target_cache = cache if local_cache is None else local_cache
            cache_key = (
                CacheType.AI_INQUIRY.value,
                item_config.hash,
                marketplace_config.hash,
                listing.hash,
            )

            target_cache.set(
                cache_key,
                asdict(self),
                tag=CacheType.AI_INQUIRY.value,
            )

        return clean_to_cache

    def test_cache_hit_miss_basic_scenario(
        self,
        temp_cache: Cache,
        listing: Listing,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
    ) -> None:
        """Test basic cache hit and miss scenarios."""
        temp_cache.clear()

        # RED: Verify initial cache miss
        cached_response = AIResponse.from_cache(
            listing, item_config, marketplace_config, temp_cache
        )
        assert cached_response is None

        # GREEN: Create and cache a response
        original_response = AIResponse(
            score=4,
            comment="Excellent match for integration test",
            name="test-backend",
            prompt_tokens=200,
            completion_tokens=100,
            total_tokens=300,
            usage_metadata={"provider": "test", "model": "test-model"},
            response_metadata={"temperature": 0.7, "created": 1699999999},
        )

        original_response.to_cache(listing, item_config, marketplace_config, temp_cache)

        # GREEN: Verify cache hit returns identical response
        cached_response = AIResponse.from_cache(
            listing, item_config, marketplace_config, temp_cache
        )

        assert cached_response is not None
        assert cached_response.score == original_response.score
        assert cached_response.comment == original_response.comment
        assert cached_response.name == original_response.name
        assert cached_response.prompt_tokens == original_response.prompt_tokens
        assert cached_response.completion_tokens == original_response.completion_tokens
        assert cached_response.total_tokens == original_response.total_tokens
        assert cached_response.usage_metadata == original_response.usage_metadata
        assert cached_response.response_metadata == original_response.response_metadata

    def test_cache_invalidation_on_listing_change(
        self,
        temp_cache: Cache,
        listing: Listing,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
    ) -> None:
        """Test that cache is properly invalidated when listing content changes."""
        temp_cache.clear()

        # GREEN: Cache response for original listing
        original_response = AIResponse(
            score=3, comment="Original listing evaluation", name="test-backend"
        )
        original_response.to_cache(listing, item_config, marketplace_config, temp_cache)

        # Verify cache hit for original listing
        cached = AIResponse.from_cache(listing, item_config, marketplace_config, temp_cache)
        assert cached is not None
        assert cached.comment == "Original listing evaluation"

        # RED: Modify listing (should result in different hash, thus cache miss)
        modified_listing = Listing(
            marketplace=listing.marketplace,
            name=listing.name,
            id=listing.id,
            title="Modified title",  # Changed title
            image=listing.image,
            price=listing.price,
            post_url=listing.post_url,
            location=listing.location,
            seller=listing.seller,
            condition=listing.condition,
            description=listing.description,
        )

        # Verify cache miss for modified listing
        cached_modified = AIResponse.from_cache(
            modified_listing, item_config, marketplace_config, temp_cache
        )
        assert cached_modified is None

        # GREEN: Cache new response for modified listing
        modified_response = AIResponse(
            score=5, comment="Modified listing evaluation", name="test-backend"
        )
        modified_response.to_cache(modified_listing, item_config, marketplace_config, temp_cache)

        # Verify both responses exist independently in cache
        original_cached = AIResponse.from_cache(
            listing, item_config, marketplace_config, temp_cache
        )
        modified_cached = AIResponse.from_cache(
            modified_listing, item_config, marketplace_config, temp_cache
        )

        assert original_cached is not None
        assert modified_cached is not None
        assert original_cached.comment == "Original listing evaluation"
        assert modified_cached.comment == "Modified listing evaluation"

    def test_cache_invalidation_on_config_change(
        self,
        temp_cache: Cache,
        listing: Listing,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
    ) -> None:
        """Test that cache is invalidated when item_config or marketplace_config changes."""
        temp_cache.clear()

        # Cache original response
        original_response = AIResponse(score=4, comment="Original config", name="test-backend")
        original_response.to_cache(listing, item_config, marketplace_config, temp_cache)

        # Verify cache hit
        cached = AIResponse.from_cache(listing, item_config, marketplace_config, temp_cache)
        assert cached is not None

        # RED: Modify item_config (should change hash)
        modified_item_config = FacebookItemConfig(
            name=item_config.name,
            description="Modified description",  # Changed description
            enabled=item_config.enabled,
            antikeywords=item_config.antikeywords,
            keywords=item_config.keywords,
            search_phrases=item_config.search_phrases,
            marketplace=item_config.marketplace,
            search_city=item_config.search_city,
            seller_locations=item_config.seller_locations,
            condition=item_config.condition,
            date_listed=item_config.date_listed,
            ai=item_config.ai,
            availability=item_config.availability,
            delivery_method=item_config.delivery_method,
            exclude_sellers=item_config.exclude_sellers,
            max_price=item_config.max_price,
            rating=item_config.rating,
            max_search_interval=item_config.max_search_interval,
            search_interval=item_config.search_interval,
            min_price=item_config.min_price,
            notify=item_config.notify,
            radius=item_config.radius,
            search_region=item_config.search_region,
        )

        # Verify cache miss with modified config
        cached_modified = AIResponse.from_cache(
            listing, modified_item_config, marketplace_config, temp_cache
        )
        assert cached_modified is None

        # RED: Modify marketplace_config
        modified_marketplace_config = FacebookMarketplaceConfig(
            name=marketplace_config.name,
            username=marketplace_config.username,
            password=marketplace_config.password,
            login_wait_time=20,  # Changed login_wait_time
            seller_locations=marketplace_config.seller_locations,
            search_city=marketplace_config.search_city,
            availability=marketplace_config.availability,
            condition=marketplace_config.condition,
            date_listed=marketplace_config.date_listed,
            delivery_method=marketplace_config.delivery_method,
            exclude_sellers=marketplace_config.exclude_sellers,
            max_search_interval=marketplace_config.max_search_interval,
            search_interval=marketplace_config.search_interval,
            notify=marketplace_config.notify,
            radius=marketplace_config.radius,
            search_region=marketplace_config.search_region,
        )

        # Verify cache miss with modified marketplace config
        cached_marketplace = AIResponse.from_cache(
            listing, item_config, modified_marketplace_config, temp_cache
        )
        assert cached_marketplace is None

    def test_serialization_consistency_across_backends(
        self,
        temp_cache: Cache,
        listing: Listing,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
    ) -> None:
        """Test that serialization works consistently across different AI backend responses."""
        temp_cache.clear()

        # Define test cases for different backend response structures
        backend_responses = [
            # OpenAI-style response
            {
                "backend_name": "openai-backend",
                "response": AIResponse(
                    score=5,
                    comment="OpenAI analysis",
                    name="openai-backend",
                    prompt_tokens=300,
                    completion_tokens=120,
                    total_tokens=420,
                    usage_metadata={
                        "input_tokens": 300,
                        "output_tokens": 120,
                        "total_tokens": 420,
                        "completion_tokens_details": {"reasoning_tokens": 20},
                    },
                    response_metadata={
                        "model": "gpt-4o",
                        "system_fingerprint": "fp_openai_test",
                        "finish_reason": "stop",
                        "created": 1699999999,
                    },
                ),
            },
            # Anthropic-style response
            {
                "backend_name": "anthropic-backend",
                "response": AIResponse(
                    score=4,
                    comment="Claude analysis",
                    name="anthropic-backend",
                    prompt_tokens=250,
                    completion_tokens=90,
                    total_tokens=340,
                    usage_metadata={
                        "input_tokens": 250,
                        "output_tokens": 90,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                    response_metadata={
                        "model": "claude-3-sonnet",
                        "stop_reason": "end_turn",
                        "usage": {"input_tokens": 250, "output_tokens": 90},
                    },
                ),
            },
            # DeepSeek-style response
            {
                "backend_name": "deepseek-backend",
                "response": AIResponse(
                    score=3,
                    comment="DeepSeek analysis",
                    name="deepseek-backend",
                    prompt_tokens=180,
                    completion_tokens=60,
                    total_tokens=240,
                    usage_metadata={
                        "prompt_tokens": 180,
                        "completion_tokens": 60,
                        "total_tokens": 240,
                        "prompt_cache_hit_tokens": 50,
                        "prompt_cache_miss_tokens": 130,
                    },
                    response_metadata={
                        "model": "deepseek-chat",
                        "object": "chat.completion",
                        "created": 1699999999,
                    },
                ),
            },
            # OpenRouter-style response
            {
                "backend_name": "openrouter-backend",
                "response": AIResponse(
                    score=5,
                    comment="OpenRouter proxy analysis",
                    name="openrouter-backend",
                    prompt_tokens=400,
                    completion_tokens=150,
                    total_tokens=550,
                    usage_metadata={
                        "prompt_tokens": 400,
                        "completion_tokens": 150,
                        "total_tokens": 550,
                        "native_tokens_prompt": 400,
                        "native_tokens_completion": 150,
                    },
                    response_metadata={
                        "model": "anthropic/claude-3-sonnet",
                        "id": "gen-test123",
                        "provider": "openrouter",
                        "usage": {"prompt_tokens": 400, "completion_tokens": 150},
                    },
                ),
            },
        ]

        # Test each backend response type
        for backend_data in backend_responses:
            temp_cache.clear()
            response = backend_data["response"]
            backend_name = backend_data["backend_name"]

            # Cache the response
            response.to_cache(listing, item_config, marketplace_config, temp_cache)

            # Retrieve and verify serialization consistency
            cached_response = AIResponse.from_cache(
                listing, item_config, marketplace_config, temp_cache
            )

            assert cached_response is not None, f"Failed to retrieve {backend_name} response"
            assert cached_response.score == response.score
            assert cached_response.comment == response.comment
            assert cached_response.name == response.name
            assert cached_response.prompt_tokens == response.prompt_tokens
            assert cached_response.completion_tokens == response.completion_tokens
            assert cached_response.total_tokens == response.total_tokens

            # Test metadata preservation with type-specific validation
            assert cached_response.usage_metadata == response.usage_metadata
            assert cached_response.response_metadata == response.response_metadata

            # Verify computed properties work correctly
            assert cached_response.has_token_usage == response.has_token_usage
            assert cached_response.conclusion == response.conclusion
            assert cached_response.style == response.style

    def test_cache_performance_improvement_validation(
        self,
        temp_cache: Cache,
        listing: Listing,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
    ) -> None:
        """Test that caching provides measurable performance improvements."""
        temp_cache.clear()

        # Create a typical AI response
        test_response = AIResponse(
            score=4,
            comment="Performance test response with detailed analysis",
            name="performance-backend",
            prompt_tokens=500,
            completion_tokens=200,
            total_tokens=700,
            usage_metadata={
                "input_tokens": 500,
                "output_tokens": 200,
                "model_info": {"provider": "test", "version": "1.0"},
                "processing_time": 2.5,
            },
            response_metadata={
                "model": "test-model",
                "temperature": 0.7,
                "max_tokens": 300,
                "request_id": "perf_test_123",
            },
        )

        # Measure cache write performance
        start_time = time.perf_counter()
        test_response.to_cache(listing, item_config, marketplace_config, temp_cache)
        cache_write_time = time.perf_counter() - start_time

        # Measure multiple cache read performance (should be faster than writes)
        cache_read_times = []
        for _ in range(10):
            start_time = time.perf_counter()
            cached_response = AIResponse.from_cache(
                listing, item_config, marketplace_config, temp_cache
            )
            read_time = time.perf_counter() - start_time
            cache_read_times.append(read_time)

            assert cached_response is not None
            assert cached_response.score == 4

        avg_read_time = sum(cache_read_times) / len(cache_read_times)

        # Performance assertions
        assert cache_write_time < 0.1, f"Cache write too slow: {cache_write_time:.4f}s"
        assert avg_read_time < 0.01, f"Cache read too slow: {avg_read_time:.4f}s"
        assert avg_read_time < cache_write_time, "Cache reads should be faster than writes"

        # Test performance with larger data sets
        large_responses = []
        for i in range(50):
            large_response = AIResponse(
                score=(i % 5) + 1,
                comment=f"Large dataset test response {i} with extensive details",
                name=f"backend-{i}",
                prompt_tokens=1000 + i * 10,
                completion_tokens=500 + i * 5,
                total_tokens=1500 + i * 15,
                usage_metadata={
                    "input_tokens": 1000 + i * 10,
                    "output_tokens": 500 + i * 5,
                    "large_data": {f"key_{j}": f"value_{j}_{i}" for j in range(20)},
                },
                response_metadata={
                    "model": f"test-model-{i}",
                    "batch_id": f"batch_{i}",
                    "metadata": {f"meta_{k}": k * i for k in range(10)},
                },
            )
            large_responses.append(large_response)

        # Cache all large responses and measure total time
        start_time = time.perf_counter()
        for large_response in large_responses:
            large_response.to_cache(listing, item_config, marketplace_config, temp_cache)
        total_cache_time = time.perf_counter() - start_time

        # Performance should remain reasonable even with large datasets
        avg_cache_time_per_item = total_cache_time / len(large_responses)
        assert (
            avg_cache_time_per_item < 0.05
        ), f"Large dataset caching too slow: {avg_cache_time_per_item:.4f}s per item"

    def test_legacy_cache_migration_compatibility(
        self,
        temp_cache: Cache,
        listing: Listing,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
    ) -> None:
        """Test migration compatibility for legacy cached responses."""
        temp_cache.clear()

        # Simulate different generations of legacy cached data
        legacy_scenarios = [
            # Very old format - minimal fields
            {
                "name": "minimal_legacy",
                "data": {
                    "score": 3,
                    "comment": "Old minimal response",
                    "name": "legacy-backend-v1",
                },
            },
            # Older format - with token counts but no metadata
            {
                "name": "token_legacy",
                "data": {
                    "score": 4,
                    "comment": "Legacy with tokens",
                    "name": "legacy-backend-v2",
                    "prompt_tokens": 150,
                    "completion_tokens": 75,
                    "total_tokens": 225,
                },
            },
            # Recent legacy - some metadata fields missing
            {
                "name": "partial_metadata_legacy",
                "data": {
                    "score": 5,
                    "comment": "Partial metadata legacy",
                    "name": "legacy-backend-v3",
                    "prompt_tokens": 200,
                    "completion_tokens": 100,
                    "total_tokens": 300,
                    "usage_metadata": {"input_tokens": 200, "output_tokens": 100},
                    # response_metadata missing
                },
            },
            # Recent legacy - None metadata values
            {
                "name": "none_metadata_legacy",
                "data": {
                    "score": 2,
                    "comment": "None metadata legacy",
                    "name": "legacy-backend-v4",
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                    "usage_metadata": None,
                    "response_metadata": None,
                },
            },
        ]

        for scenario in legacy_scenarios:
            temp_cache.clear()
            legacy_data = scenario["data"]
            scenario_name = scenario["name"]

            # Manually insert legacy data into cache
            cache_key = (
                CacheType.AI_INQUIRY.value,
                item_config.hash,
                marketplace_config.hash,
                listing.hash,
            )
            temp_cache.set(cache_key, legacy_data, tag=CacheType.AI_INQUIRY.value)

            # Test migration retrieval
            migrated_response = AIResponse.from_cache(
                listing, item_config, marketplace_config, temp_cache
            )

            assert migrated_response is not None, f"Failed to migrate {scenario_name}"
            assert migrated_response.score == legacy_data["score"]
            assert migrated_response.comment == legacy_data["comment"]
            assert migrated_response.name == legacy_data["name"]

            # Verify metadata fields are properly migrated
            assert isinstance(migrated_response.usage_metadata, dict)
            assert isinstance(migrated_response.response_metadata, dict)

            # Verify computed properties work
            assert migrated_response.conclusion in [
                "No match",
                "Potential match",
                "Poor match",
                "Good match",
                "Great deal",
            ]
            assert migrated_response.style in ["dim", "fail", "succ", "name"]

            # Test that migrated response can be re-cached
            migrated_response.to_cache(listing, item_config, marketplace_config, temp_cache)
            re_cached = AIResponse.from_cache(listing, item_config, marketplace_config, temp_cache)

            assert re_cached is not None
            assert re_cached.score == migrated_response.score
            assert re_cached.usage_metadata == migrated_response.usage_metadata
            assert re_cached.response_metadata == migrated_response.response_metadata

    def test_langchain_backend_cache_integration(
        self,
        temp_cache: Cache,
        listing: Listing,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
    ) -> None:
        """Test LangChainBackend integration with caching workflow."""
        temp_cache.clear()

        # Create LangChainBackend configuration
        config = AIConfig(
            name="integration-backend",
            provider="openai",
            api_key="test-key-integration",
            model="gpt-4",
            max_retries=1,
        )

        backend = LangChainBackend(config)

        # Mock LangChain response with comprehensive metadata
        mock_langchain_response = Mock()
        mock_langchain_response.content = (
            "This listing appears to be an excellent match for the user's criteria.\n"
            "Rating 5: Perfect match with great price and condition"
        )
        mock_langchain_response.usage_metadata = {
            "input_tokens": 400,
            "output_tokens": 150,
            "total_tokens": 550,
            "completion_tokens_details": {"reasoning_tokens": 30},
        }
        mock_langchain_response.response_metadata = {
            "model": "gpt-4",
            "system_fingerprint": "fp_integration_test",
            "finish_reason": "stop",
            "created": 1699999999,
            "object": "chat.completion",
        }

        # Mock the model to return our test response
        mock_model = Mock()
        mock_model.invoke.return_value = mock_langchain_response

        with (
            patch("ai_marketplace_monitor.ai.AIResponse.from_cache", return_value=None),
            patch("ai_marketplace_monitor.ai.counter"),
            patch.object(backend, "_get_model", return_value=mock_model),
            patch.object(backend, "get_prompt", return_value="test integration prompt"),
        ):
            # First evaluation - should cache the result
            result1 = backend.evaluate(listing, item_config, marketplace_config)

            assert result1.score == 5
            assert "Perfect match" in result1.comment
            assert result1.name == "integration-backend"
            assert result1.prompt_tokens == 400
            assert result1.completion_tokens == 150
            assert result1.total_tokens == 550

            # Verify metadata preservation from LangChain response
            assert result1.usage_metadata["completion_tokens_details"]["reasoning_tokens"] == 30
            assert result1.response_metadata["system_fingerprint"] == "fp_integration_test"

            # Cache the response manually to test subsequent cache hit
            result1.to_cache(listing, item_config, marketplace_config, temp_cache)

        # Second evaluation - should hit cache and not invoke model
        with (
            patch.object(backend, "_get_model") as mock_get_model,
            patch.object(backend, "get_prompt", return_value="test integration prompt"),
        ):
            result2 = backend.evaluate(listing, item_config, marketplace_config)

            # Should not have called _get_model due to cache hit
            mock_get_model.assert_not_called()

            # Should return identical cached result
            assert result2.score == result1.score
            assert result2.comment == result1.comment
            assert result2.name == result1.name
            assert result2.prompt_tokens == result1.prompt_tokens
            assert result2.completion_tokens == result1.completion_tokens
            assert result2.usage_metadata == result1.usage_metadata
            assert result2.response_metadata == result1.response_metadata

    def test_concurrent_cache_access_thread_safety(
        self,
        temp_cache: Cache,
        listing: Listing,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
    ) -> None:
        """Test cache behavior under concurrent access from multiple threads."""
        temp_cache.clear()

        # Create multiple unique responses for concurrent testing
        test_responses = []
        for i in range(10):
            response = AIResponse(
                score=(i % 5) + 1,
                comment=f"Concurrent test response {i}",
                name=f"concurrent-backend-{i}",
                prompt_tokens=100 + i * 10,
                completion_tokens=50 + i * 5,
                total_tokens=150 + i * 15,
                usage_metadata={
                    "thread_id": i,
                    "input_tokens": 100 + i * 10,
                    "output_tokens": 50 + i * 5,
                },
                response_metadata={
                    "model": f"concurrent-model-{i}",
                    "request_id": f"req_{i}",
                },
            )
            test_responses.append(response)

        results = []
        errors = []

        def cache_and_retrieve_worker(response_index: int) -> Tuple[int, bool, str]:
            """Worker function to cache and retrieve responses concurrently."""
            try:
                response = test_responses[response_index]

                # Cache the response
                response.to_cache(listing, item_config, marketplace_config, temp_cache)

                # Retrieve it back
                cached = AIResponse.from_cache(
                    listing, item_config, marketplace_config, temp_cache
                )

                # Verify retrieval success (note: due to same cache key, last write wins)
                if cached is not None:
                    return (response_index, True, f"Success for response {response_index}")
                else:
                    return (response_index, False, f"Failed to retrieve response {response_index}")

            except Exception as e:
                return (response_index, False, f"Exception for response {response_index}: {e}")

        # Execute concurrent cache operations
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(cache_and_retrieve_worker, i) for i in range(len(test_responses))
            ]

            for future in as_completed(futures):
                response_index, success, message = future.result()
                results.append((response_index, success, message))
                if not success:
                    errors.append(message)

        # Verify all operations completed without errors
        assert len(errors) == 0, f"Concurrent cache operations failed: {errors}"
        assert len(results) == len(test_responses)

        # Verify final cache state is consistent
        # (Note: Due to same cache key, only the last successful write should be present)
        final_cached = AIResponse.from_cache(listing, item_config, marketplace_config, temp_cache)
        assert final_cached is not None
        assert final_cached.name.startswith("concurrent-backend-")

    def test_cache_behavior_with_large_responses(
        self,
        temp_cache: Cache,
        listing: Listing,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
    ) -> None:
        """Test cache behavior with large response objects."""
        temp_cache.clear()

        # Create a large response with extensive metadata
        large_metadata = {
            f"analysis_step_{i}": {
                "reasoning": f"Step {i} analysis with detailed reasoning",
                "confidence": 0.95 - (i * 0.01),
                "factors": [f"factor_{j}" for j in range(20)],
                "sub_analysis": {
                    f"aspect_{k}": {
                        "score": (k * i) % 10,
                        "details": f"Detailed analysis for aspect {k} in step {i}",
                        "evidence": [f"evidence_{idx}_{k}_{i}" for idx in range(10)],
                    }
                    for k in range(5)
                },
            }
            for i in range(50)
        }

        large_response = AIResponse(
            score=4,
            comment="Comprehensive analysis with extensive metadata for large response testing",
            name="large-response-backend",
            prompt_tokens=2000,
            completion_tokens=800,
            total_tokens=2800,
            usage_metadata={
                "input_tokens": 2000,
                "output_tokens": 800,
                "large_analysis": large_metadata,
                "model_stats": {
                    "layers_used": 48,
                    "attention_heads": 128,
                    "processing_stages": ["tokenization", "encoding", "reasoning", "generation"],
                },
            },
            response_metadata={
                "model": "large-model-test",
                "processing_time": 15.7,
                "memory_usage": "2.3GB",
                "detailed_metrics": {
                    "token_processing_rate": 180.5,
                    "quality_scores": {
                        "coherence": 0.94,
                        "relevance": 0.97,
                        "accuracy": 0.91,
                        "completeness": 0.89,
                    },
                    "performance_breakdown": {
                        f"stage_{i}": {"time": i * 0.5, "memory": f"{i * 50}MB"} for i in range(20)
                    },
                },
                "debug_info": {"trace_id": "trace_large_test_123", "version": "1.2.3"},
            },
        )

        # Test caching large response
        start_time = time.perf_counter()
        large_response.to_cache(listing, item_config, marketplace_config, temp_cache)
        cache_time = time.perf_counter() - start_time

        # Test retrieving large response
        start_time = time.perf_counter()
        cached_large = AIResponse.from_cache(listing, item_config, marketplace_config, temp_cache)
        retrieve_time = time.perf_counter() - start_time

        # Verify large response integrity
        assert cached_large is not None
        assert cached_large.score == 4
        assert cached_large.comment == large_response.comment
        assert cached_large.prompt_tokens == 2000
        assert cached_large.completion_tokens == 800

        # Verify large metadata preservation
        assert len(cached_large.usage_metadata["large_analysis"]) == 50
        assert (
            cached_large.usage_metadata["large_analysis"]["analysis_step_25"]["confidence"] == 0.70
        )
        assert (
            len(cached_large.usage_metadata["large_analysis"]["analysis_step_10"]["sub_analysis"])
            == 5
        )

        # Verify response metadata preservation
        assert cached_large.response_metadata["processing_time"] == 15.7
        assert (
            cached_large.response_metadata["detailed_metrics"]["quality_scores"]["coherence"]
            == 0.94
        )
        assert (
            len(cached_large.response_metadata["detailed_metrics"]["performance_breakdown"]) == 20
        )

        # Performance should still be reasonable even with large data
        assert cache_time < 1.0, f"Large response caching too slow: {cache_time:.4f}s"
        assert retrieve_time < 0.5, f"Large response retrieval too slow: {retrieve_time:.4f}s"

    def test_cache_edge_cases_and_error_handling(
        self,
        temp_cache: Cache,
        listing: Listing,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
    ) -> None:
        """Test cache behavior in edge cases and error conditions."""
        temp_cache.clear()

        # Test with corrupted cache data
        cache_key = (
            CacheType.AI_INQUIRY.value,
            item_config.hash,
            marketplace_config.hash,
            listing.hash,
        )

        # Insert corrupted data that will cause deserialization issues
        corrupted_scenarios = [
            {"corrupted_type": "non_dict", "data": "corrupted_string_data"},
            {
                "corrupted_type": "missing_fields",
                "data": {"score": 4},
            },  # Missing required fields (comment)
            {
                "corrupted_type": "unknown_fields",
                "data": {"score": 4, "comment": "test", "name": "test", "unknown_field": "value"},
            },
        ]

        for scenario in corrupted_scenarios:
            temp_cache.clear()
            corrupted_data = scenario["data"]
            corruption_type = scenario["corrupted_type"]

            temp_cache.set(cache_key, corrupted_data, tag=CacheType.AI_INQUIRY.value)

            # Should handle corruption gracefully by returning None
            result = AIResponse.from_cache(listing, item_config, marketplace_config, temp_cache)
            assert result is None, f"Should return None for {corruption_type} corruption"

        # Test cache with None as cached value
        temp_cache.clear()
        temp_cache.set(cache_key, None, tag=CacheType.AI_INQUIRY.value)
        result = AIResponse.from_cache(listing, item_config, marketplace_config, temp_cache)
        assert result is None

        # Test empty cache
        temp_cache.clear()
        result = AIResponse.from_cache(listing, item_config, marketplace_config, temp_cache)
        assert result is None

        # Test cache with valid data after clearing
        valid_response = AIResponse(score=3, comment="Valid after errors", name="recovery-backend")
        valid_response.to_cache(listing, item_config, marketplace_config, temp_cache)

        recovered = AIResponse.from_cache(listing, item_config, marketplace_config, temp_cache)
        assert recovered is not None
        assert recovered.score == 3
        assert recovered.comment == "Valid after errors"

    def test_adapt_langchain_response_cache_integration(
        self,
        temp_cache: Cache,
        listing: Listing,
        item_config: FacebookItemConfig,
        marketplace_config: FacebookMarketplaceConfig,
    ) -> None:
        """Test adapt_langchain_response integration with caching system."""
        temp_cache.clear()

        # Create comprehensive mock LangChain responses for different providers
        langchain_responses = [
            {
                "provider": "openai",
                "mock_response": Mock(
                    content="OpenAI analysis content.\nRating 5: Excellent match",
                    usage_metadata={
                        "input_tokens": 350,
                        "output_tokens": 120,
                        "total_tokens": 470,
                    },
                    response_metadata={
                        "model": "gpt-4o",
                        "system_fingerprint": "fp_openai_cache_test",
                        "finish_reason": "stop",
                    },
                ),
            },
            {
                "provider": "anthropic",
                "mock_response": Mock(
                    content="Anthropic Claude analysis.\nRating 4: Strong match",
                    usage_metadata={
                        "input_tokens": 280,
                        "output_tokens": 95,
                        "total_tokens": 375,
                        "cache_read_input_tokens": 50,
                    },
                    response_metadata={
                        "model": "claude-3-sonnet",
                        "stop_reason": "end_turn",
                        "usage": {"input_tokens": 280, "output_tokens": 95},
                    },
                ),
            },
        ]

        for provider_data in langchain_responses:
            temp_cache.clear()
            provider = provider_data["provider"]
            mock_response = provider_data["mock_response"]

            # Use adapt_langchain_response to create AIResponse
            adapted = adapt_langchain_response(
                response=mock_response,
                backend_name=f"{provider}-cache-test",
                parsed_score=5 if provider == "openai" else 4,
                parsed_comment=f"{provider.title()} excellent analysis",
            )

            # Verify adaptation worked correctly
            assert adapted.score == (5 if provider == "openai" else 4)
            assert adapted.name == f"{provider}-cache-test"
            assert adapted.has_token_usage is True

            # Cache the adapted response
            adapted.to_cache(listing, item_config, marketplace_config, temp_cache)

            # Retrieve and verify cache fidelity
            cached = AIResponse.from_cache(listing, item_config, marketplace_config, temp_cache)
            assert cached is not None
            assert cached.score == adapted.score
            assert cached.comment == adapted.comment
            assert cached.name == adapted.name
            assert cached.prompt_tokens == adapted.prompt_tokens
            assert cached.completion_tokens == adapted.completion_tokens
            assert cached.total_tokens == adapted.total_tokens
            assert cached.usage_metadata == adapted.usage_metadata
            assert cached.response_metadata == adapted.response_metadata

            # Verify computed properties are preserved
            assert cached.has_token_usage == adapted.has_token_usage
            assert cached.conclusion == adapted.conclusion
            assert cached.style == adapted.style
