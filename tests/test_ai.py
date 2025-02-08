import pytest

from ai_marketplace_monitor.ai import OllamaBackend, OllamaConfig
from ai_marketplace_monitor.facebook import FacebookItemConfig
from ai_marketplace_monitor.listing import Listing


@pytest.mark.skipif(True, reason="Condition met, skipping this test")
def test_ai(
    ollama_config: OllamaConfig, item_config: FacebookItemConfig, listing: Listing
) -> None:
    ai = OllamaBackend(ollama_config)
    # ai.config = ollama_config
    res = ai.evaluate(listing, item_config)
    assert res.score >= 1 and res.score <= 5


def test_prompt(ollama: OllamaBackend, listing: Listing, item_config: FacebookItemConfig) -> None:
    prompt = ollama.get_prompt(listing, item_config)
    assert item_config.name in prompt
    assert (item_config.description or "something weird") in prompt
    assert str(item_config.min_price) in prompt
    assert str(item_config.max_price) in prompt

    assert listing.title in prompt
    assert listing.condition in prompt
    assert listing.price in prompt
    assert listing.post_url in prompt
