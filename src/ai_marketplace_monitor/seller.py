"""Who sells a listing: what Facebook shows about the seller, and signs of an unreliable one.

The listing page shows the seller's name, the year they joined Facebook and, for sellers
with ratings, the average and the number of ratings. The seller's Marketplace profile
(``/marketplace/profile/<id>/``) adds the number of active listings and, in its "Sold" view,
the sold ones. Profiles are cached by seller id, so each is opened at most once in a while.
"""

import re
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

from diskcache import Cache  # type: ignore

from .utils import CacheType, Translator, cache

# a profile is opened again after this long: listings and ratings change slowly
SELLER_CACHE_SECONDS = 7 * 24 * 3600

# warning signs (see seller_warnings); 0 disables a threshold
DEFAULT_MIN_ACCOUNT_YEARS = 2
DEFAULT_MIN_RATING = 4.0
DEFAULT_MAX_LISTINGS = 20
# a low average from fewer ratings than this is not held against the seller
MIN_RATINGS_FOR_RATING = 3
# many listings with at most this many sold
FEW_SOLD = 1
MANY_LISTINGS_FOR_SOLD = 5


@dataclass
class Seller:
    id: str
    name: str = ""
    joined_year: int | None = None
    rating: float | None = None
    rating_count: int | None = None
    highly_rated: bool = False
    # Facebook shows "20+ active listings" beyond 20; capped is True then
    active_listings: int | None = None
    active_listings_capped: bool = False
    sold_listings: int | None = None
    # what buyers say: "Item description (85)", and a few recent reviews
    strengths: List[str] = field(default_factory=list)
    reviews: List[str] = field(default_factory=list)
    profile_checked: bool = False

    def update(self: "Seller", other: "Seller") -> None:
        """Take the values ``other`` knows; 0 is known (e.g. no listings sold)."""
        for f in fields(self):
            value = getattr(other, f.name)
            # not `value in (None, "", False, [])`: 0 == False would drop a count of 0
            if value is None or value is False or value == "" or value == []:
                continue
            setattr(self, f.name, value)

    def summary(self: "Seller") -> str:
        """The seller in a sentence, for the AI and for notifications."""
        parts = []
        if self.joined_year:
            parts.append(f"joined Facebook in {self.joined_year}")
        if self.rating is not None and self.rating_count:
            parts.append(
                f"rated {self.rating:g} out of 5 by {self.rating_count} buyer"
                + ("s" if self.rating_count != 1 else "")
            )
        elif self.profile_checked or self.joined_year:
            parts.append("no ratings")
        if self.highly_rated:
            parts.append("badge: highly rated on Marketplace")
        if self.active_listings is not None:
            count = f"{self.active_listings}{'+' if self.active_listings_capped else ''}"
            parts.append(f"{count} active listing" + ("s" if count != "1" else ""))
        if self.sold_listings is not None:
            parts.append(
                f"{self.sold_listings} sold listing" + ("s" if self.sold_listings != 1 else "")
            )
        if self.strengths:
            parts.append("buyers appreciate: " + ", ".join(self.strengths))
        text = ", ".join(parts)
        if self.reviews:
            text += ". Recent reviews: " + " | ".join(f'"{r}"' for r in self.reviews)
        return text

    @classmethod
    def from_cache(
        cls: Type["Seller"], seller_id: str, local_cache: Cache | None = None
    ) -> Optional["Seller"]:
        if not seller_id:
            return None
        try:
            return cls(
                **(cache if local_cache is None else local_cache).get(
                    (CacheType.SELLER_INFO.value, seller_id)
                )
            )
        except KeyboardInterrupt:
            raise
        except Exception:
            return None

    def to_cache(self: "Seller", local_cache: Cache | None = None) -> None:
        if not self.id:
            return
        (cache if local_cache is None else local_cache).set(
            (CacheType.SELLER_INFO.value, self.id),
            asdict(self),
            expire=SELLER_CACHE_SECONDS,
            tag=CacheType.SELLER_INFO.value,
        )


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


def count_listing_tiles(labels: List[str]) -> int:
    """The number of listings on a profile: each tile is labelled "..., listing <id>"."""
    return len({label for label in labels if re.search(r"listing \d+\s*$", label or "")})


def seller_warnings(
    seller: Seller,
    min_account_years: int | None = DEFAULT_MIN_ACCOUNT_YEARS,
    min_rating: float | None = DEFAULT_MIN_RATING,
    max_listings: int | None = DEFAULT_MAX_LISTINGS,
    year: int | None = None,
) -> List[str]:
    """Signs that the seller may be unreliable, worded for the buyer. None or 0 disables one."""
    year = year or datetime.now().year
    warnings: List[str] = []
    new_account = bool(
        min_account_years and seller.joined_year and year - seller.joined_year < min_account_years
    )
    if new_account:
        warnings.append(f"new account (joined Facebook in {seller.joined_year})")
    if (
        min_rating
        and seller.rating is not None
        and (seller.rating_count or 0) >= MIN_RATINGS_FOR_RATING
        and seller.rating < min_rating
    ):
        warnings.append(f"low rating ({seller.rating:g} out of 5 from {seller.rating_count})")
    active = seller.active_listings
    if max_listings and active is not None and active >= max_listings:
        warnings.append(
            f"{active}{'+' if seller.active_listings_capped else ''} active listings, "
            "likely a dealer or a shop"
        )
    if (
        active is not None
        and active >= MANY_LISTINGS_FOR_SOLD
        and seller.sold_listings is not None
        and seller.sold_listings <= FEW_SOLD
    ):
        sold = "none" if seller.sold_listings == 0 else f"only {seller.sold_listings}"
        warnings.append(
            f"{active}{'+' if seller.active_listings_capped else ''} active listings but {sold} sold"
        )
    if active == 1 and new_account:
        warnings.append(
            "a single listing on a new account, a pattern of bait listings: "
            "check that the price is realistic"
        )
    return warnings


def seller_context(seller_info: Dict[str, Any]) -> str:
    """The seller and their warning signs, as stored on a listing, in a line or two."""
    if not seller_info:
        return ""
    warnings = seller_info.get("warnings") or []
    text = seller_info.get("summary") or ""
    if warnings:
        text += ("; " if text else "") + "warning signs: " + "; ".join(warnings)
    return text
