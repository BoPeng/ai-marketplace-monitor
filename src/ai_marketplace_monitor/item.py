from dataclasses import dataclass
from typing import Tuple

from .utils import CacheType


@dataclass
class SearchedItem:
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
    description: str

    @property
    def user_notified_key(self: "SearchedItem") -> Tuple[str, str, str]:
        return (CacheType.USER_NOTIFIED.value, self.marketplace, self.id)
