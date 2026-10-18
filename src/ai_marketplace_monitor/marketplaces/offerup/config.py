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
# a place's coordinates, "latitude,longitude" (e.g. from the configure chat's find_city)
COORDINATES = re.compile(r"(-?[0-9]{1,2}(?:\.[0-9]+)?),\s*(-?[0-9]{1,3}(?:\.[0-9]+)?)")


def coordinates(city: str) -> "tuple[float, float] | None":
    """The latitude and longitude of a "lat,lon" search_city, or None for a ZIP code."""
    match = COORDINATES.fullmatch(city.strip())
    if not match:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


class OfferUpLocation:
    """OfferUp's search_city: US ZIP codes or coordinates (or a table's offerup value)."""

    location_type: ClassVar[str] = "offerup"
    name: str

    def check_search_city(self: "OfferUpLocation", city: str) -> None:
        if not ZIP_CODE.fullmatch(city) and coordinates(city) is None:
            raise ValueError(
                f"{hilight(self.name)} search_city '{city}' is not a ZIP code or coordinates. "
                'OfferUp searches around a US ZIP code, e.g. search_city = "77002", or a '
                'place\'s "latitude,longitude", e.g. "29.7604,-95.3698".'
            )


@dataclass
class OfferUpMarketplaceConfig(OfferUpLocation, MarketplaceConfig):
    pass


@dataclass
class OfferUpItemConfig(OfferUpLocation, ItemConfig):
    pass
