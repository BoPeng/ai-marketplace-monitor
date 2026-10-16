from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional, Tuple, Type

from diskcache import Cache  # type: ignore

from .utils import CacheType, cache, hash_dict


@dataclass
class Listing:
    marketplace: str
    name: str
    # unique identification
    id: str
    title: str
    image: str
    price: str
    post_url: str
    location: str
    seller: str
    condition: str
    description: str
    # the seller's id on the marketplace, and what aimm learned about them: a summary and
    # warning signs (see seller.py). Not part of the hash: they do not change the listing.
    seller_id: str = ""
    seller_info: Dict[str, Any] = field(default_factory=dict)
    # whether the page was read for seller information: False for listings cached before
    # aimm read sellers, which are read again once (an unavailable seller panel stays True)
    seller_parsed: bool = False

    @property
    def seller_state(self: "Listing") -> str:
        """How much is known about the seller: "", "listing" (the listing page) or "profile"."""
        seller = (self.seller_info or {}).get("seller") or {}
        if seller.get("profile_checked"):
            return "profile"
        return "listing" if self.seller_info else ""

    @property
    def content(self: "Listing") -> Tuple[str, str, str]:
        return (self.title, self.description, self.price)

    @property
    def hash(self: "Listing") -> str:
        # we need to normalize post_url before hashing because post_url will be different
        # each time from a search page. We also does not count image
        return hash_dict(
            {
                x: (y.split("?")[0] if x == "post_url" else y)
                for x, y in asdict(self).items()
                if x not in ("image", "seller_id", "seller_info", "seller_parsed")
            }
        )

    @classmethod
    def from_cache(
        cls: Type["Listing"],
        post_url: str,
        local_cache: Cache | None = None,
    ) -> Optional["Listing"]:
        try:
            # details could be a different datatype, miss some key etc.
            # and we have recently changed to save Listing as a dictionary
            return cls(
                **(cache if local_cache is None else local_cache).get(
                    (CacheType.LISTING_DETAILS.value, post_url.split("?")[0])
                )
            )
        except KeyboardInterrupt:
            raise
        except Exception:
            return None

    @classmethod
    def forget(cls: Type["Listing"], post_url: str, local_cache: Cache | None = None) -> None:
        """Drop the cached details, so that the page is read again."""
        (cache if local_cache is None else local_cache).delete(
            (CacheType.LISTING_DETAILS.value, post_url.split("?")[0])
        )

    def to_cache(
        self: "Listing",
        post_url: str,
        local_cache: Cache | None = None,
    ) -> None:
        (cache if local_cache is None else local_cache).set(
            (CacheType.LISTING_DETAILS.value, post_url.split("?")[0]),
            asdict(self),
            tag=CacheType.LISTING_DETAILS.value,
        )
