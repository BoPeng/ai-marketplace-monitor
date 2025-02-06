from dataclasses import asdict, dataclass
from typing import Optional, Type

from .utils import CacheType, cache


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

    @classmethod
    def from_cache(cls: Type["Listing"], post_url: str) -> Optional["Listing"]:
        try:
            # details could be a different datatype, miss some key etc.
            # and we have recently changed to save Listing as a dictionary
            return cls(**cache.get((CacheType.LISTING_DETAILS.value, post_url.split("?")[0])))
        except Exception:
            return None

    def to_cache(self: "Listing", post_url: str) -> None:
        cache.set(
            (CacheType.LISTING_DETAILS.value, post_url.split("?")[0]),
            asdict(self),
            tag=CacheType.LISTING_DETAILS.value,
        )
