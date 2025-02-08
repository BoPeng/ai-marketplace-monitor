"""Tests for `ai_marketplace_monitor` module."""

from diskcache import Cache  # type: ignore

from ai_marketplace_monitor.listing import Listing


def test_version(version: str) -> None:
    """Sample pytest test function with the pytest fixture as an argument."""
    assert version == "0.7.1"


def test_listing_cache(temp_cache: Cache, listing: Listing) -> None:
    listing.to_cache(post_url=listing.post_url, local_cache=temp_cache)
    #
    new_listing = Listing.from_cache(listing.post_url, local_cache=temp_cache)

    for attr in (
        "marketplace",
        "name",
        "id",
        "title",
        "image",
        "price",
        "location",
        "seller",
        "condition",
        "description",
    ):
        assert getattr(listing, attr) == getattr(new_listing, attr)
