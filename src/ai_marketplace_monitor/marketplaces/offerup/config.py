"""The options of OfferUp marketplace and item sections.

OfferUp has only the options every marketplace shares (MarketItemCommonConfig); its location
(``search_city``) is a US ZIP code.
"""

import re
from dataclasses import dataclass
from typing import ClassVar

from ...utils import hilight
from ..base import ItemConfig, MarketplaceConfig

# five ASCII digits: \d would also match other scripts' digits
ZIP_CODE = re.compile(r"[0-9]{5}")


class OfferUpLocation:
    """OfferUp's search_city: US ZIP codes (or a table's offerup value)."""

    location_type: ClassVar[str] = "offerup"
    name: str

    def check_search_city(self: "OfferUpLocation", city: str) -> None:
        if not ZIP_CODE.fullmatch(city):
            raise ValueError(
                f"{hilight(self.name)} search_city '{city}' is not a ZIP code. OfferUp "
                'searches around a US ZIP code, e.g. search_city = "77002".'
            )


@dataclass
class OfferUpMarketplaceConfig(OfferUpLocation, MarketplaceConfig):
    pass


@dataclass
class OfferUpItemConfig(OfferUpLocation, ItemConfig):
    pass
