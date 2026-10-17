"""What Facebook's listing panel and Marketplace profile show about a seller."""

import re
from typing import List

from ...seller import Seller
from ...utils import Translator


def seller_id_from_url(href: str) -> str:
    """The seller id of a ``/marketplace/profile/<id>/`` link, or ''."""
    match = re.search(r"/marketplace/profile/(\d+)", href or "")
    return match.group(1) if match else ""


def _joined_year(text: str, translator: Translator) -> int | None:
    match = re.search(re.escape(translator("Joined Facebook in")) + r"\s*(\d{4})", text)
    return int(match.group(1)) if match else None


def _rating(labels: List[str], translator: Translator) -> float | None:
    # the stars are an icon: "4.6 out of 5 stars, ..." or "4.6 out of 5 rating"
    pattern = re.compile(r"(\d(?:[.,]\d+)?)\s*" + re.escape(translator("out of 5")))
    for label in labels:
        match = pattern.search(label or "")
        if match:
            return float(match.group(1).replace(",", "."))
    return None


def parse_seller_panel(
    text: str,
    labels: List[str],
    seller_id: str,
    name: str = "",
    translator: Translator | None = None,
) -> Seller:
    """The seller as the "Seller information" panel of a listing page shows them.

    ``text`` is the panel's text and ``labels`` the aria-labels in it, where the stars are.
    """
    translator = translator or Translator()
    seller = Seller(id=seller_id, name=name)
    seller.joined_year = _joined_year(text, translator)
    seller.rating = _rating(labels, translator)
    # the number of ratings is a line of its own: "(182)"
    count = re.search(r"^\s*\((\d[\d,.]*)\)\s*$", text, re.MULTILINE)
    if count:
        seller.rating_count = int(re.sub(r"[,.]", "", count.group(1)))
    if seller.rating_count is None:
        seller.rating = None  # a stray "out of 5" elsewhere is not the seller's
    seller.highly_rated = translator("Highly rated") in text
    return seller


def parse_seller_profile(
    text: str, labels: List[str], seller_id: str, translator: Translator | None = None
) -> Seller:
    """The seller as their Marketplace profile shows them (its text and aria-labels)."""
    translator = translator or Translator()
    seller = Seller(id=seller_id, profile_checked=True)
    seller.joined_year = _joined_year(text, translator)
    listings = re.search(
        r"(\d+)(\+?)\s*" + re.escape(translator("active listing")), text, re.IGNORECASE
    )
    if listings:
        seller.active_listings = int(listings.group(1))
        seller.active_listings_capped = bool(listings.group(2))
    # the header starts with the rating: "4.6 (182)"
    header = re.search(r"^\s*(\d(?:[.,]\d+)?)\s*\((\d[\d,.]*)\)", text, re.MULTILINE)
    if header:
        seller.rating = float(header.group(1).replace(",", "."))
        seller.rating_count = int(re.sub(r"[,.]", "", header.group(2)))
    else:
        seller.rating = _rating(labels, translator)
        ratings = re.search(
            translator("Based on") + r"\s*(\d[\d,.]*)\s*" + translator("ratings"), text
        )
        seller.rating_count = int(re.sub(r"[,.]", "", ratings.group(1))) if ratings else None
        if seller.rating_count is None:
            seller.rating = None
    seller.highly_rated = translator("Highly rated") in text
    seller.strengths = _strengths(text, translator)
    seller.reviews = _reviews(text, translator)
    return seller


# a review starts after the reviewer's name with its date: "August 29, 2026"
_REVIEW_DATE = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4}$")
MAX_REVIEWS = 5
MAX_REVIEW_LENGTH = 200


def _strengths(text: str, translator: Translator) -> List[str]:
    """The "Item description (85)" lines between the strengths heading and the reviews."""
    lines = [x.strip() for x in text.splitlines()]
    start = next((i for i, x in enumerate(lines) if translator("strengths") in x), None)
    if start is None:
        return []
    strengths = []
    for line in lines[start + 1 :]:
        if line.startswith(translator("Seller reviews")):
            break
        if re.match(r"^.+\(\d+\)$", line):
            strengths.append(line)
    return strengths


def _reviews(text: str, translator: Translator) -> List[str]:
    """The first few reviews: the text after each date, up to its "Like" button."""
    lines = [x.strip() for x in text.splitlines()]
    start = next(
        (i for i, x in enumerate(lines) if x.startswith(translator("Seller reviews"))), None
    )
    if start is None:
        return []
    reviews: List[str] = []
    current: List[str] | None = None
    for line in lines[start + 1 :]:
        if _REVIEW_DATE.match(line):
            current = []
            continue
        if current is None:
            continue
        if line == translator("Like"):
            review = " ".join(x for x in current if x and x not in ("·", "・"))
            if review:
                reviews.append(review[:MAX_REVIEW_LENGTH])
            current = None
            if len(reviews) >= MAX_REVIEWS:
                break
            continue
        current.append(line.lstrip("・· ").strip())
    return reviews


def sold_grid_count(
    text: str, tiles: List[str], translator: Translator | None = None
) -> int | None:
    """The number of sold listings once the "Sold & out of stock" grid has loaded, else None.

    ``tiles`` are the first lines of the listing tiles. Sold tiles start with a "Sold" badge;
    a tile that starts with its price is an active listing still shown from before the switch.
    An empty grid says "No listings found".
    """
    translator = translator or Translator()
    if not tiles:
        return 0 if translator("No listings found") in text else None
    if any(re.search(r"\d", tile) for tile in tiles):
        return None  # still the active listings
    return sum(1 for tile in tiles if tile == translator("Sold"))
