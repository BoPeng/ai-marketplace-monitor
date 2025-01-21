from typing import TypedDict


class SearchedItem(TypedDict):
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
