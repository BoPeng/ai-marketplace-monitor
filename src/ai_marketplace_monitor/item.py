from dataclasses import dataclass, field
from typing import List

from .utils import DataClassWithHandleFunc


@dataclass
class SearchedItem:
    marketplace: str
    # unique identification
    id: str
    title: str
    image: str
    price: str
    post_url: str
    location: str
    seller: str
    description: str


@dataclass
class ItemConfig(DataClassWithHandleFunc):
    """Generic item config"""

    notify: List[str] = field(default_factory=list)
    search_interval: int = 30
    max_search_interval: int = 60
