import time
from pathlib import Path

import pytest
from pytest_playwright.pytest_playwright import CreateContextCallback  # type: ignore

import ai_marketplace_monitor.facebook as facebook_module
from ai_marketplace_monitor.facebook import FacebookSearchResultPage, parse_listing
from ai_marketplace_monitor.listing import Listing


def test_search_page(
    new_context: CreateContextCallback, filename: str = "search_result_1.html"
) -> None:
    local_file_path = Path(__file__).parent / filename
    page = new_context(java_script_enabled=False).new_page()
    page.goto(f"file://{local_file_path}")

    for _ in range(10):
        p = FacebookSearchResultPage(page)
        page.wait_for_load_state("domcontentloaded")
        listings = p.get_listings()
        if len(listings) != 0:
            break
        time.sleep(1)

    for idx, listing in enumerate(listings):
        assert listing.marketplace == "facebook"
        assert listing.id.isnumeric(), f"wrong id for listing {idx + 1} with title {listing.title}"
        assert listing.title, f"No title is found {idx + 1} with title "
        assert listing.image, f"wrong image for listing {idx + 1} with title {listing.title}"
        assert listing.post_url, f"wrong post_url for listing {idx + 1} with title {listing.title}"
        assert listing.price, f"wrong price for listing {idx + 1} with title {listing.title}"
        if idx == 10:
            assert (
                listing.location == ""
            ), f"listing {idx + 1} with title {listing.title} has empty location"
        else:
            assert (
                listing.location
            ), f"wrong location for listing {idx + 1} with title {listing.title}"
        assert listing.seller == "", "Seller should be empty"

    assert len(listings) == 21


@pytest.mark.parametrize(
    "filename,price,seller,location",
    [
        ("regular_listing.html", "$10", "Austin Ewing", "MS"),
        ("rental_listing.html", "$150", "Perry Burton", "Houston, TX"),
        (
            "auto_with_about_and_description_listing.html",
            "**unspecified**",
            "Lily Ortiz",
            "Houston, TX",
        ),
        ("auto_with_description_listing.html", "€6,695", "Abdel Abdel", "Bergen op Zoom, NB"),
    ],
)
def test_listing_page(
    new_context: CreateContextCallback,
    filename: str,
    price: str,
    seller: str,
    location: str,
) -> None:
    local_file_path = Path(__file__).parent / filename

    page = new_context(java_script_enabled=False).new_page()
    page.goto(f"file://{local_file_path}")
    page.wait_for_load_state("domcontentloaded")
    listing = parse_listing(page, "post_url", None)

    assert listing is not None, f"Should be able to parse {filename}"
    assert listing.title, f"Title of {filename} should be {listing.title}"
    assert listing.price == price, f"Price of {filename} should be {listing.price}"
    assert listing.location == location, f"Location of {filename} should be {listing.location}"
    assert listing.seller == seller, f"Seller of {filename} should be {listing.seller}"
    assert listing.image, f"Image of {filename} should not be empty"
    assert listing.post_url, f"post_url of {filename} should not be empty"


@pytest.mark.parametrize("filename", ["flex_listing.html", "flex_listing_with_attributes.html"])
def test_flex_listing_description_follows_the_attribute_rows(
    new_context: CreateContextCallback, filename: str
) -> None:
    """Attributes after Condition (e.g. "Has Bluetooth: Yes") are not the description."""
    page = new_context(java_script_enabled=False).new_page()
    page.goto(f"file://{Path(__file__).parent / filename}")
    page.wait_for_load_state("domcontentloaded")
    listing = parse_listing(page, "post_url", None)

    assert listing is not None
    assert listing.condition == "Used - like new"
    assert listing.description == "Clean like new\n175 each"
    assert listing.price == "$175"
    assert listing.location == "Houston, TX"


def _fake_layout(description: str | None) -> type:
    """A page layout that fails (None) or parses with the given description."""

    class FakeLayout:
        def __init__(self, *args: object) -> None:
            pass

        def parse(self, post_url: str) -> Listing:
            if description is None:
                raise ValueError("Layout mismatch")
            return Listing(
                marketplace="facebook",
                name="",
                id="1",
                title="title",
                image="",
                price="$1",
                post_url=post_url,
                location="",
                condition="",
                description=description,
                seller="",
            )

    return FakeLayout


def test_parse_listing_prefers_layout_with_description(monkeypatch: pytest.MonkeyPatch) -> None:
    layouts = [_fake_layout(None), _fake_layout(""), _fake_layout("real description")]
    for name, layout in zip(
        [
            "FacebookRentalItemPage",
            "FacebookAutoItemWithAboutAndDescriptionPage",
            "FacebookAutoItemWithDescriptionPage",
        ],
        layouts,
    ):
        monkeypatch.setattr(facebook_module, name, layout)
    for name in ["FacebookFlexItemPage", "FacebookRegularItemPage"]:
        monkeypatch.setattr(facebook_module, name, _fake_layout(None))

    listing = parse_listing(None, "post_url")  # type: ignore[arg-type]

    assert listing is not None
    assert listing.description == "real description"


def test_parse_listing_falls_back_to_empty_description(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [
        "FacebookRentalItemPage",
        "FacebookAutoItemWithAboutAndDescriptionPage",
        "FacebookAutoItemWithDescriptionPage",
        "FacebookRegularItemPage",
    ]:
        monkeypatch.setattr(facebook_module, name, _fake_layout(None))
    monkeypatch.setattr(facebook_module, "FacebookFlexItemPage", _fake_layout(""))

    listing = parse_listing(None, "post_url")  # type: ignore[arg-type]

    assert listing is not None
    assert listing.description == ""


def test_parse_listing_prefers_the_specific_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ul/li layout comes before the generic one, which also matches older pages."""
    for name in [
        "FacebookRentalItemPage",
        "FacebookAutoItemWithAboutAndDescriptionPage",
        "FacebookAutoItemWithDescriptionPage",
    ]:
        monkeypatch.setattr(facebook_module, name, _fake_layout(None))
    monkeypatch.setattr(facebook_module, "FacebookRegularItemPage", _fake_layout("from ul/li"))
    monkeypatch.setattr(facebook_module, "FacebookFlexItemPage", _fake_layout("guessed"))

    listing = parse_listing(None, "post_url")  # type: ignore[arg-type]

    assert listing is not None
    assert listing.description == "from ul/li"
