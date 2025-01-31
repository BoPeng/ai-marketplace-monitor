from dataclasses import dataclass


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
