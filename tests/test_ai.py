from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from ai_marketplace_monitor.ai import OpenAIBackend, OpenAIConfig, OllamaBackend, OllamaConfig
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


def test_openai_vision_message_includes_listing_image(listing: Listing) -> None:
    listing.image = "https://example.com/listing.jpg"
    ai = OpenAIBackend(
        OpenAIConfig(
            name="openai-test",
            api_key="test",
            use_images=True,
            image_detail="high",
        )
    )

    message = ai._user_message("Evaluate this listing", listing)

    assert message["role"] == "user"
    assert message["content"][0] == {"type": "text", "text": "Evaluate this listing"}
    assert message["content"][1] == {
        "type": "image_url",
        "image_url": {
            "url": "https://example.com/listing.jpg",
            "detail": "high",
        },
    }


def test_openai_vision_message_is_text_when_images_disabled(listing: Listing) -> None:
    listing.image = "https://example.com/listing.jpg"
    ai = OpenAIBackend(OpenAIConfig(name="openai-test", api_key="test", use_images=False))

    assert ai._user_message("Evaluate this listing", listing) == {
        "role": "user",
        "content": "Evaluate this listing",
    }


def test_openai_disabled_config_allows_missing_env_key() -> None:
    config = OpenAIConfig(name="openai", enabled=False, api_key=None)

    assert config.enabled is False
    assert config.api_key is None


def test_openai_evaluate_sends_image_payload(
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
) -> None:
    suffix = uuid4().hex
    listing.id = f"openai-vision-test-{suffix}"
    listing.title = f"OpenAI vision payload test {suffix}"
    listing.image = "https://example.com/listing.jpg"
    item_config.name = f"test-{suffix}"
    ai = OpenAIBackend(
        OpenAIConfig(
            name=f"openai-vision-test-{suffix}",
            api_key="test",
            use_images=True,
            image_detail="high",
            max_retries=1,
        )
    )
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Rating 1: Reject. Test evaluation.")
            )
        ]
    )
    create = MagicMock(return_value=response)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    ai.evaluate(listing, item_config, marketplace_config)

    sent_message = create.call_args.kwargs["messages"][1]
    assert sent_message["content"][1]["image_url"]["url"] == listing.image


def test_openai_evaluate_raises_provider_failure_after_retries(
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
) -> None:
    suffix = uuid4().hex
    listing.id = f"openai-failure-test-{suffix}"
    listing.title = f"OpenAI failure test {suffix}"
    item_config.name = f"test-{suffix}"
    ai = OpenAIBackend(
        OpenAIConfig(
            name=f"openai-failure-test-{suffix}",
            api_key="test",
            max_retries=1,
        )
    )
    create = MagicMock(side_effect=RuntimeError("provider rejected image"))
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    with pytest.raises(RuntimeError, match="failed to evaluate"):
        ai.evaluate(listing, item_config, marketplace_config)
