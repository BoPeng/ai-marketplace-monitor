"""Tests for `ai_marketplace_monitor` module."""

from typing import Generator

import pytest

import ai_marketplace_monitor
from ai_marketplace_monitor.ai import OllamaBackend, OllamaConfig
from ai_marketplace_monitor.facebook import FacebookItemConfig
from ai_marketplace_monitor.listing import Listing


@pytest.fixture
def version() -> Generator[str, None, None]:
    """Sample pytest fixture."""
    yield ai_marketplace_monitor.__version__


def test_version(version: str) -> None:
    """Sample pytest test function with the pytest fixture as an argument."""
    assert version == "0.7.1.dev"


@pytest.fixture
def listing() -> Listing:
    return Listing(
        marketplace="facebook",
        name="test",
        id="111",
        title="dddd",
        image="",
        price="$10",
        post_url="https://www.facebook.com/marketplace/item/1234567890",
        location="houston, tx",
        seller="some guy",
        condition="New",
        description="something good",
    )


@pytest.fixture
def item_config() -> FacebookItemConfig:
    return FacebookItemConfig(
        name="test",
        description="long description",
        enabled=True,
        exclude_by_description=["some exclude1", "some exclude2"],
        exclude_keywords=["exclude1", "exclude2"],
        include_keywords=["exclude1", "exclude2"],
        keywords=["search word one"],
        marketplace="facebook",
        search_city=["houston"],
        # the following are common options
        seller_locations=["city"],
        condition=["new", "used_good"],
        date_listed=[7],
        ai=["openai"],
        availability=["out", "all"],
        delivery_method=["local_pick_up"],
        exclude_sellers=["seller"],
        max_price=300,
        rating=[4],
        max_search_interval=1000,
        search_interval=12,
        min_price=200,
        notify=["user1"],
        radius=[100],
        search_region=["usa"],
    )


@pytest.fixture
def ollama_config() -> OllamaConfig:
    return OllamaConfig(
        name="ollama",
        api_key="ollama",
        provider="ollama",
        base_url="http://localhost:11434/v1",
        model="llama3.1:8b",
        max_retries=10,
    )


@pytest.mark.skipif(True, reason="Condition met, skipping this test")
def test_ai(
    ollama_config: OllamaConfig, item_config: FacebookItemConfig, listing: Listing
) -> None:
    ai = OllamaBackend(ollama_config)
    # ai.config = ollama_config
    res = ai.evaluate(listing, item_config)
    assert res.score >= 1 and res.score <= 5
