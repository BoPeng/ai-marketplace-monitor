"""Who sells a listing: what the marketplace shows about the seller, and signs of an unreliable one.

On Facebook, the listing page shows the seller's name, the year they joined Facebook and, for sellers
with ratings, the average and the number of ratings. The seller's Marketplace profile
(``/marketplace/profile/<id>/``) adds the number of active listings and, in its "Sold" view,
the sold ones. Profiles are cached by seller id, so each is opened at most once in a while.
"""

import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Any, Dict, List, Optional, Type

from diskcache import Cache  # type: ignore

from .utils import CacheType, cache

# a profile is opened again after about a month: ratings and account age barely change, and
# listing and sales counts a few weeks old still show a dealer or a seller who never sells
SELLER_CACHE_SECONDS = 30 * 24 * 3600
# a seller whose profile could not be read is kept this long, so that aimm tries again soon
UNCHECKED_CACHE_SECONDS = 24 * 3600

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
    # when the profile was read (seconds since the epoch); None if never
    checked_at: float | None = None
    # where the account is, for "joined <platform> in <year>"
    platform: str = "Facebook"
    # what the marketplace confirmed about the account: "Confirmed phone", "TruYou verified"
    badges: List[str] = field(default_factory=list)

    def needs_profile(self: "Seller", now: float | None = None) -> bool:
        """Whether to read the profile: never read, or read about a month ago."""
        now = time.time() if now is None else now
        return (
            not self.profile_checked
            or self.checked_at is None
            or now - self.checked_at >= SELLER_CACHE_SECONDS
        )

    def update(self: "Seller", other: "Seller") -> None:
        """Take the values ``other`` knows; 0 is known (e.g. no listings sold)."""
        for f in fields(self):
            value = getattr(other, f.name)
            # not `value in (None, "", False, [])`: 0 == False would drop a count of 0
            if value is None or value is False or value == "" or value == []:
                continue
            setattr(self, f.name, value)

    def summary(self: "Seller", reviews: bool = True) -> str:
        """The seller in a sentence, for the AI and (without reviews) for notifications."""
        parts = []
        if self.joined_year:
            parts.append(f"joined {self.platform} in {self.joined_year}")
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
        if self.badges:
            parts.append("badges: " + ", ".join(self.badges))
        text = ", ".join(parts)
        if reviews and self.reviews:
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

    def to_cache(
        self: "Seller", local_cache: Cache | None = None, now: float | None = None
    ) -> None:
        """Keep the seller until their profile is due again: writing does not extend that."""
        if not self.id:
            return
        now = time.time() if now is None else now
        if self.profile_checked and self.checked_at is not None:
            expire = max(60.0, SELLER_CACHE_SECONDS - (now - self.checked_at))
        else:
            expire = UNCHECKED_CACHE_SECONDS
        (cache if local_cache is None else local_cache).set(
            (CacheType.SELLER_INFO.value, self.id),
            asdict(self),
            expire=expire,
            tag=CacheType.SELLER_INFO.value,
        )


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
        warnings.append(f"new account (joined {seller.platform} in {seller.joined_year})")
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


def seller_from_info(seller_info: Dict[str, Any] | None) -> Seller | None:
    """The Seller stored on a listing (``seller_info["seller"]``), or None."""
    data = (seller_info or {}).get("seller")
    if not data or not data.get("id"):
        return None
    known = {f.name for f in fields(Seller)}
    try:
        return Seller(**{k: v for k, v in data.items() if k in known})
    except TypeError:
        return None


def seller_status(seller_info: Dict[str, Any] | None) -> str:
    """The seller and their warning signs, as stored on a listing, for notifications.

    It always says something, so that a notification without a word about the seller is
    not mistaken for one whose seller was checked and found fine.
    """
    seller = seller_from_info(seller_info)
    if seller is None:
        text = "not verified (no seller information)"
    elif seller.profile_checked and seller.checked_at:
        checked = datetime.fromtimestamp(seller.checked_at).strftime("%Y-%m-%d")
        text = ", ".join(
            x for x in (seller.summary(reviews=False), f"profile checked {checked}") if x
        )
    else:
        text = "; ".join(
            x
            for x in (seller.summary(reviews=False), "not verified (profile could not be read)")
            if x
        )
    if seller is not None and seller.name:
        text = f"{seller.name}: {text}"
    warnings = (seller_info or {}).get("warnings") or []
    if warnings:
        text += ". Warning signs: " + "; ".join(warnings)
    return text
