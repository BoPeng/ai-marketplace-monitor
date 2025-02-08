from dataclasses import asdict, dataclass
from typing import Optional, Type

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

    @property
    def hash(self: "Listing") -> str:
        return hash_dict(asdict(self))

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
        except Exception:
            return None

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
