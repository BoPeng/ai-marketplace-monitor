"""Tests for `ai_marketplace_monitor` module."""

import time

from diskcache import Cache  # type: ignore

from ai_marketplace_monitor.listing import Listing
from ai_marketplace_monitor.user import User
from ai_marketplace_monitor.utils import NotificationStatus


def test_version(version: str) -> None:
    """Sample pytest test function with the pytest fixture as an argument."""
    assert version == "0.7.2"


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


def test_notification_cache(temp_cache: Cache, user: User, listing: Listing) -> None:
    print(temp_cache)
    assert (
        user.notification_status(listing, local_cache=temp_cache)
        == NotificationStatus.NOT_NOTIFIED
    )
    assert user.time_since_notification(listing, local_cache=temp_cache) == -1
    user.to_cache(listing, local_cache=temp_cache)

    assert user.notified_key(listing) in temp_cache
    assert user.notification_status(listing, local_cache=temp_cache) == NotificationStatus.NOTIFIED
    assert user.time_since_notification(listing, local_cache=temp_cache) >= 0

    #
    user.config.remind = 1

    time.sleep(2)

    assert user.notification_status(listing, local_cache=temp_cache) == NotificationStatus.EXPIRED

    # change listing
    listing.price = "$30000"
    assert (
        user.notification_status(listing, local_cache=temp_cache)
        == NotificationStatus.LISTING_CHANGED
    )
