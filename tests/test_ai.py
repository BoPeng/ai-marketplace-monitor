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
