import time
from pathlib import Path

import pytest
from playwright.sync_api import Page

from ai_marketplace_monitor.facebook import FacebookSearchResultPage, parse_listing


def test_search_page(page: Page, filename: str = "search_result_1.html") -> None:
    local_file_path = Path(__file__).parent / filename
    page.goto(f"file://{local_file_path}")

    # heading = page.locator('[aria-label="Collection of Marketplace items"]')
    # assert heading is not None

    for _ in range(10):
        p = FacebookSearchResultPage(page)
        page.wait_for_load_state("domcontentloaded")
        listings = p.get_listings()
        if len(listings) != 0:
            break
        time.sleep(1)

    for idx, listing in enumerate(listings):
        assert listing.marketplace == "facebook"
        assert listing.id.isnumeric(), f"wrong id for listing {idx+1} with title {listing.title}"
        assert listing.title, f"No title is found {idx+1} with title "
        assert listing.image, f"wrong image for listing {idx+1} with title {listing.title}"
        assert listing.post_url, f"wrong post_url for listing {idx+1} with title {listing.title}"
        assert listing.price, f"wrong price for listing {idx+1} with title {listing.title}"
        if idx == 10:
            assert (
                listing.location == ""
            ), f"listing {idx+1} with title {listing.title} has empty location"
        else:
            assert (
                listing.location
            ), f"wrong location for listing {idx+1} with title {listing.title}"
        assert listing.seller == "", "Seller should be empty"

    assert len(listings) == 21


@pytest.mark.parametrize(
    "filename,price,seller,location",
    [
        ("regular_listing.html", "$10", "Austin Ewing", "MS"),
        ("rental_listing.html", "$150 / Month", "Perry Burton", "Houston, TX"),
        ("auto_listing.html", "**unspecified**", "Lily Ortiz", "Houston, TX"),
    ],
)
def test_listing_page(page: Page, filename: str, price: str, seller: str, location: str) -> None:
    local_file_path = Path(__file__).parent / filename

    for _ in range(10):
        page.goto(f"file://{local_file_path}")
        page.wait_for_load_state("domcontentloaded")
        listing = parse_listing(page, "post_url", None)

        if listing is not None:
            break
        time.sleep(1)

    assert listing is not None, f"Should be able to parse {filename}"
    assert listing.title, f"Title of {filename} should be {listing.title}"
    assert listing.price == price, f"Price of {filename} should be {listing.price}"
    assert listing.location == location, f"Location of {filename} should be {listing.location}"
    assert listing.seller == seller, f"Seller of {filename} should be {listing.seller}"
    assert listing.image, f"Image of {filename} should not be empty"
    assert listing.post_url, f"post_url of {filename} should not be empty"
