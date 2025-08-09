from unittest.mock import MagicMock

import pytest

from ai_marketplace_monitor.facebook import FacebookItemConfig, FacebookMarketplace
from ai_marketplace_monitor.listing import Listing


@pytest.fixture
def facebook_marketplace() -> FacebookMarketplace:
    """Create a Facebook marketplace instance with properly mocked dependencies."""
    marketplace = FacebookMarketplace(name="facebook", browser=MagicMock(), logger=MagicMock())

    # Mock the config attribute following codebase patterns
    mock_config = MagicMock()
    mock_config.seller_locations = None
    mock_config.exclude_sellers = None
    marketplace.config = mock_config

    return marketplace


@pytest.fixture
def keyword_item_config() -> FacebookItemConfig:
    """Create item config for testing keyword filtering."""
    return FacebookItemConfig(
        name="test_item",
        search_phrases=["EMTB", "electric bike"],
        keywords=["Gen 4", "Bosch", "Bosch CX"],
        antikeywords=None,
        min_price="1000",
        max_price="5000",
    )


def test_keyword_filtering_should_skip_when_description_empty(
    facebook_marketplace: FacebookMarketplace, keyword_item_config: FacebookItemConfig
) -> None:
    """Test that demonstrates the premature keyword filtering bug.

    This test shows that listings are incorrectly rejected during the first
    check_listing() call when keywords exist in the description but the
    description hasn't been fetched yet (description="").

    The bug occurs in the workflow where check_listing() is called twice:
    1. First call (line 502): On search results with empty description
    2. Second call (line 532): After get_listing_details() populates description

    The first call incorrectly rejects listings that would pass the second call.
    """
    # Create a listing that would match keywords in description but not title
    listing_with_empty_description = Listing(
        marketplace="facebook",
        name="test_item",
        id="123456",
        title="EMTB for sale 2024 model Full suspension",  # No keywords in title
        image="https://example.com/image.jpg",
        price="$2,800",
        post_url="/marketplace/item/123456/",
        location="Roanoke, VA",
        seller="",
        condition="used",
        description="",  # Empty description (as it would be from search results)
    )

    # Same listing after description is populated
    listing_with_populated_description = Listing(
        marketplace="facebook",
        name="test_item",
        id="123456",
        title="EMTB for sale 2024 model Full suspension",
        image="https://example.com/image.jpg",
        price="$2,800",
        post_url="/marketplace/item/123456/",
        location="Roanoke, VA",
        seller="Test Seller",
        condition="used",
        description="EMTB carbon fiber, 29 inch wheels, full suspension, Bosch gen 4 motor, 800 watt/hour battery",  # Contains "Gen 4" and "Bosch" keywords
    )

    # Test the bug: First call should PASS but currently FAILS
    # This simulates the first check_listing() call at line 502
    first_check_result = facebook_marketplace.check_listing(
        listing_with_empty_description, keyword_item_config, description_available=False
    )

    # Test the correct behavior: Second call should PASS and currently DOES
    # This simulates the second check_listing() call at line 532
    second_check_result = facebook_marketplace.check_listing(
        listing_with_populated_description, keyword_item_config, description_available=True
    )

    # FAILING TEST: This demonstrates the bug
    # The first check should pass (skip keyword filtering when description is empty)
    # but currently fails because it tries to filter on empty description
    assert first_check_result, (
        "BUG: First check_listing() call incorrectly rejects listing with empty description. "
        "Keyword filtering should be skipped when description is empty."
    )

    # This should pass (and currently does)
    assert (
        second_check_result
    ), "Second check_listing() call should pass when description contains keywords"


@pytest.mark.parametrize(
    "listing_data,expected_result,test_description",
    [
        (
            {
                "id": "123456",
                "title": "Mountain bike for sale",
                "price": "$2,000",
                "description": "This bike has a Bosch gen 4 motor and excellent suspension",
            },
            True,
            "should pass when keywords are found in description",
        ),
        (
            {
                "id": "789012",
                "title": "Regular bicycle for sale",
                "price": "$500",
                "description": "Just a regular pedal bike, nothing special",
            },
            False,
            "should reject when keywords are not found in title or description",
        ),
    ],
)
def test_keyword_filtering_with_populated_description(
    facebook_marketplace: FacebookMarketplace,
    keyword_item_config: FacebookItemConfig,
    listing_data: dict,
    expected_result: bool,
    test_description: str,
) -> None:
    """Test that keyword filtering works correctly when description is populated."""
    listing = Listing(
        marketplace="facebook",
        name="test_item",
        id=listing_data["id"],
        title=listing_data["title"],
        image="https://example.com/image.jpg",
        price=listing_data["price"],
        post_url=f"/marketplace/item/{listing_data['id']}/",
        location="Test Location",
        seller="Test Seller",
        condition="used",
        description=listing_data["description"],
    )

    result = facebook_marketplace.check_listing(
        listing, keyword_item_config, description_available=True
    )
    assert result == expected_result, f"Keyword filtering {test_description}"


def test_antikeyword_filtering_with_empty_description(
    facebook_marketplace: FacebookMarketplace,
) -> None:
    """Test that antikeyword filtering works correctly when description is empty."""
    listing_with_empty_description = Listing(
        marketplace="facebook",
        name="test_item",
        id="456789",
        title="Broken EMTB for parts",  # Contains antikeyword in title
        image="https://example.com/image.jpg",
        price="$500",
        post_url="/marketplace/item/456789/",
        location="Test Location",
        seller="",
        condition="used",
        description="",  # Empty description
    )

    item_config_with_antikeywords = FacebookItemConfig(
        name="test_item",
        search_phrases=["EMTB"],
        keywords=None,
        antikeywords=["broken", "parts"],  # These should cause rejection
        min_price="100",
        max_price="5000",
    )

    # Should be rejected due to antikeywords in title, even with empty description
    result = facebook_marketplace.check_listing(
        listing_with_empty_description, item_config_with_antikeywords, description_available=False
    )
    assert (
        not result
    ), "Should reject listing when antikeywords found in title, even with empty description"
