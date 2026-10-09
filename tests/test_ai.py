import base64
import io
import logging
from types import SimpleNamespace
from typing import Tuple
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from PIL import Image

from ai_marketplace_monitor import ai as ai_module
from ai_marketplace_monitor.ai import (
    IMAGE_MAX_SIDE,
    IMAGE_NOTE,
    AnthropicBackend,
    AnthropicConfig,
    ListingImage,
    OllamaBackend,
    OllamaConfig,
    OpenAIBackend,
    OpenAIConfig,
    fetch_listing_image,
    token_usage,
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


def _photo(size: Tuple[int, int] = (2000, 1000)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def photo_get(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Downloads of listing photos return a 2000x1000 PNG."""
    get = MagicMock(return_value=SimpleNamespace(content=_photo(), raise_for_status=lambda: None))
    monkeypatch.setattr(ai_module.requests, "get", get)
    return get


def _decoded(image: ListingImage) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(image.data)))


def test_images_are_on_by_default() -> None:
    assert OpenAIConfig(name="openai-test", api_key="test").use_images is True


def test_listing_photo_is_downloaded_and_shrunk(photo_get: MagicMock) -> None:
    image = fetch_listing_image("https://example.com/listing.jpg")
    photo_get.assert_called_once()
    assert image.media_type == "image/jpeg"
    assert image.data_url.startswith("data:image/jpeg;base64,")
    assert _decoded(image).size == (IMAGE_MAX_SIDE, IMAGE_MAX_SIDE // 2)


def test_small_listing_photo_keeps_its_size(monkeypatch: pytest.MonkeyPatch) -> None:
    get = MagicMock(
        return_value=SimpleNamespace(content=_photo((300, 200)), raise_for_status=lambda: None)
    )
    monkeypatch.setattr(ai_module.requests, "get", get)
    assert _decoded(fetch_listing_image("https://example.com/small.png")).size == (300, 200)


def test_openai_vision_message_embeds_the_photo(listing: Listing, photo_get: MagicMock) -> None:
    listing.image = "https://example.com/listing.jpg"
    ai = OpenAIBackend(OpenAIConfig(name="openai-test", api_key="test", image_detail="high"))

    image = ai.listing_image(listing)
    assert image is not None
    message = ai._user_message("Evaluate this listing", image)

    assert message["role"] == "user"
    assert message["content"][0] == {
        "type": "text",
        "text": f"Evaluate this listing\n{IMAGE_NOTE}",
    }
    assert message["content"][1] == {
        "type": "image_url",
        "image_url": {"url": image.data_url, "detail": "high"},
    }


def test_no_photo_when_images_disabled(listing: Listing, photo_get: MagicMock) -> None:
    listing.image = "https://example.com/listing.jpg"
    ai = OpenAIBackend(OpenAIConfig(name="openai-test", api_key="test", use_images=False))

    assert ai.listing_image(listing) is None
    photo_get.assert_not_called()
    assert ai._user_message("Evaluate this listing", None) == {
        "role": "user",
        "content": "Evaluate this listing",
    }


def test_failed_photo_download_evaluates_text_only(
    listing: Listing, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing.image = "https://example.com/expired.jpg"
    monkeypatch.setattr(ai_module.requests, "get", MagicMock(side_effect=OSError("403")))
    ai = OpenAIBackend(OpenAIConfig(name="openai-test", api_key="test"))

    assert ai.listing_image(listing) is None


def test_anthropic_message_embeds_the_photo(listing: Listing, photo_get: MagicMock) -> None:
    listing.image = "https://example.com/listing.jpg"
    ai = AnthropicBackend(AnthropicConfig(name="anthropic-test", api_key="test"))

    image = ai.listing_image(listing)
    assert image is not None
    content = ai._user_message("Evaluate this listing", image)["content"]

    assert content[0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": image.data},
    }
    assert content[1] == {"type": "text", "text": f"Evaluate this listing\n{IMAGE_NOTE}"}
    assert _decoded(image).size == (400, 200)  # smaller: Anthropic charges by pixels


def test_openai_disabled_config_allows_missing_env_key() -> None:
    config = OpenAIConfig(name="openai", enabled=False, api_key=None)

    assert config.enabled is False
    assert config.api_key is None


def test_openai_evaluate_sends_image_payload(
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    photo_get: MagicMock,
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
            SimpleNamespace(message=SimpleNamespace(content="Rating 1: Reject. Test evaluation."))
        ]
    )
    create = MagicMock(return_value=response)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    ai.evaluate(listing, item_config, marketplace_config)

    sent_message = create.call_args.kwargs["messages"][1]
    assert sent_message["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


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


def test_openai_image_detail_defaults_to_low() -> None:
    assert OpenAIConfig(name="openai-test", api_key="test").image_detail == "low"


def test_openai_evaluate_falls_back_to_text_when_image_rejected(
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    photo_get: MagicMock,
) -> None:
    suffix = uuid4().hex
    listing.id = f"openai-fallback-test-{suffix}"
    listing.title = f"OpenAI image fallback test {suffix}"
    listing.image = "https://example.com/expired.jpg"
    item_config.name = f"test-{suffix}"
    ai = OpenAIBackend(
        OpenAIConfig(
            name=f"openai-fallback-test-{suffix}",
            api_key="test",
            use_images=True,
            max_retries=1,
        )
    )
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Rating 4: Good match. Test evaluation.")
            )
        ]
    )
    create = MagicMock(side_effect=[RuntimeError("image not supported"), response])
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    res = ai.evaluate(listing, item_config, marketplace_config)

    assert res.score == 4
    assert create.call_count == 2
    assert isinstance(create.call_args_list[0].kwargs["messages"][1]["content"], list)
    assert isinstance(create.call_args_list[1].kwargs["messages"][1]["content"], str)


def test_openai_response_log_is_compact(
    listing: Listing,
    item_config: FacebookItemConfig,
    marketplace_config: FacebookMarketplaceConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    suffix = uuid4().hex
    listing.id = f"openai-log-test-{suffix}"
    listing.title = f"OpenAI log test {suffix}"
    listing.image = ""
    item_config.name = f"test-{suffix}"
    logger = logging.getLogger(f"aimm.test.ai-log-{suffix}")
    ai = OpenAIBackend(
        OpenAIConfig(name=f"openai-log-test-{suffix}", api_key="test", max_retries=1),
        logger=logger,
    )
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="Rating 2: Price too high.",
                    reasoning_content="Let me evaluate this listing step by step",
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=30),
    )
    create = MagicMock(return_value=response)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        ai.evaluate(listing, item_config, marketplace_config)

    logged = [r.getMessage() for r in caplog.records if "[AI-Response]" in r.getMessage()]
    assert len(logged) == 1
    assert "Rating 2: Price too high. (120 input / 30 output tokens)" in logged[0]
    assert "reasoning" not in logged[0]
    assert "\n" not in logged[0]


def test_token_usage_formats() -> None:
    anthropic = SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=5))
    assert token_usage(anthropic) == " (10 input / 5 output tokens)"
    assert token_usage(SimpleNamespace()) == ""
    assert token_usage(SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10))) == ""


def test_openai_summarize() -> None:
    ai = OpenAIBackend(OpenAIConfig(name="openai-summary", api_key="test", model="gpt-4o"))
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="  The iPad Air looks good.  "))]
    )
    create = MagicMock(return_value=response)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    assert ai.summarize("Summarize this") == "The iPad Air looks good."
    kwargs = create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o"
    assert kwargs["messages"][0] == {"role": "system", "content": ai_module.SUMMARY_SYSTEM}
    assert kwargs["messages"][1] == {"role": "user", "content": "Summarize this"}
    assert kwargs["timeout"] == ai_module.SUMMARY_TIMEOUT


def test_anthropic_summarize() -> None:
    ai = AnthropicBackend(AnthropicConfig(name="claude-summary", api_key="test"))
    response = SimpleNamespace(content=[SimpleNamespace(text="Nothing stands out.")])
    create = MagicMock(return_value=response)
    ai.client = SimpleNamespace(messages=SimpleNamespace(create=create))

    assert ai.summarize("Summarize this") == "Nothing stands out."
    kwargs = create.call_args.kwargs
    assert kwargs["system"] == ai_module.SUMMARY_SYSTEM
    assert kwargs["messages"] == [{"role": "user", "content": "Summarize this"}]
    assert kwargs["timeout"] == ai_module.SUMMARY_TIMEOUT


def test_summarize_gives_up_after_a_few_tries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_module.time, "sleep", lambda s: None)
    ai = OpenAIBackend(OpenAIConfig(name="openai-down", api_key="test", max_retries=10))
    create = MagicMock(side_effect=RuntimeError("503"))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(ai, "connect", lambda: setattr(ai, "client", client))

    with pytest.raises(RuntimeError, match="openai-down"):
        ai.summarize("Summarize this")
    assert create.call_count == ai_module.SUMMARY_RETRIES


def test_summarize_rejects_an_empty_answer() -> None:
    ai = OpenAIBackend(OpenAIConfig(name="openai-empty", api_key="test"))
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=""))])
    create = MagicMock(return_value=response)
    ai.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(RuntimeError, match="empty"):
        ai.summarize("Summarize this")
