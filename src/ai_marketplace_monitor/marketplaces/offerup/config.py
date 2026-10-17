"""The options of OfferUp marketplace and item sections.

OfferUp has only the options every marketplace shares (MarketItemCommonConfig); its location
(``search_city``) is a US ZIP code.
"""

import re
from dataclasses import dataclass

from ...utils import hilight
from ..base import ItemConfig, MarketplaceConfig

ZIP_CODE = re.compile(r"\d{5}")


class OfferUpLocation:
    """search_city is a list of US ZIP codes (replaces the check of Facebook's codes)."""

    name: str
    search_city: list | None

    def handle_search_city(self: "OfferUpLocation") -> None:
        if self.search_city is None:
            return
        if isinstance(self.search_city, (str, int)):
            self.search_city = [self.search_city]
        if not isinstance(self.search_city, list):
            raise ValueError(
                f"Item {hilight(self.name)} search_city must be a ZIP code or a list of them."
            )
        cities = [str(city).strip() for city in self.search_city]
        for city in cities:
            if not ZIP_CODE.fullmatch(city):
                raise ValueError(
                    f"{hilight(self.name)} search_city '{city}' is not a ZIP code. OfferUp "
                    'searches around a US ZIP code, e.g. search_city = "77002".'
                )
        self.search_city = cities


@dataclass
class OfferUpMarketplaceConfig(OfferUpLocation, MarketplaceConfig):
    pass


@dataclass
class OfferUpItemConfig(OfferUpLocation, ItemConfig):
    pass
