"""The options of Facebook marketplace and item sections."""

import os
from dataclasses import dataclass
from enum import Enum
from typing import List

from ...utils import (
    BaseConfig,
    convert_to_seconds,
    hilight,
)
from ..base import (
    Fallback,
    ItemConfig,
    MarketplaceConfig,
    SortBy,
    option,
)


class Availability(Enum):
    ALL = "all"
    INSTOCK = "in"
    OUTSTOCK = "out"


class Category(Enum):
    VEHICLES = "vehicles"
    PROPERTY_RENTALS = "propertyrentals"
    APPAREL = "apparel"
    ELECTRONICS = "electronics"
    ENTERTAINMENT = "entertainment"
    FAMILY = "family"
    FREE_STUFF = "freestuff"
    FREE = "free"
    GARDEN = "garden"
    HOBBIES = "hobbies"
    HOME_GOODS = "homegoods"
    HOME_IMPROVEMENT = "homeimprovement"
    HOME_SALES = "homesales"
    MUSICAL_INSTRUMENTS = "musicalinstruments"
    OFFICE_SUPPLIES = "officesupplies"
    PET_SUPPLIES = "petsupplies"
    SPORTING_GOODS = "sportinggoods"
    TICKETS = "tickets"
    TOYS = "toys"
    VIDEO_GAMES = "videogames"


# facebook's `sortBy` query values, keyed by the accepted config value. `suggested`
# is the marketplace default and is expressed by omitting the parameter altogether.
SORT_BY_PARAM = {
    SortBy.NEW.value: "creation_time_descend",
    SortBy.PRICE_ASCEND.value: "price_ascend",
    SortBy.PRICE_DESCEND.value: "price_descend",
    SortBy.DISTANCE_ASCEND.value: "distance_ascend",
}


@dataclass
class FacebookMarketItemCommonConfig(BaseConfig):
    """Options of Facebook marketplace and item sections that other marketplaces lack.

    The options every marketplace shares are in MarketItemCommonConfig.
    """

    availability: List[str] | None = option(Fallback.TRUTHY)
    category: str | None = option(Fallback.TRUTHY)

    def handle_availability(self: "FacebookMarketItemCommonConfig") -> None:
        if self.availability is None:
            return

        if isinstance(self.availability, str):
            self.availability = [self.availability]
        if not all(val in [x.value for x in Availability] for val in self.availability):
            raise ValueError(
                f"Item {hilight(self.name)} availability must be one or two values of 'all', 'in', and 'out'."
            )
        if len(self.availability) > 2:
            raise ValueError(
                f"Item {hilight(self.name)} availability must be one or two values of 'all', 'in', and 'out'."
            )

    def handle_category(self: "FacebookMarketItemCommonConfig") -> None:
        if self.category is None:
            return

        if not isinstance(self.category, str) or self.category not in [x.value for x in Category]:
            raise ValueError(
                f"Item {hilight(self.name)} category must be one of {', '.join(x.value for x in Category)}."
            )


@dataclass
class FacebookMarketplaceConfig(MarketplaceConfig, FacebookMarketItemCommonConfig):
    """Options specific to facebook marketplace

    This class defines and processes options that can be specified
    in the marketplace.facebook section only. None of the options are required.
    """

    login_wait_time: int | None = None  # deprecated and ignored: aimm waits for the login
    password: str | None = None
    username: str | None = None

    def handle_username(self: "FacebookMarketplaceConfig") -> None:
        if self.username is None:
            self.username = os.environ.get("FACEBOOK_USERNAME")
        if self.username is None:
            return

        if not isinstance(self.username, str):
            raise ValueError(f"Marketplace {self.name} username must be a string.")

    def handle_password(self: "FacebookMarketplaceConfig") -> None:
        if self.password is None:
            self.password = os.environ.get("FACEBOOK_PASSWORD")
        if self.password is None:
            return

        if not isinstance(self.password, str):
            raise ValueError(f"Marketplace {self.name} password must be a string.")

    def handle_login_wait_time(self: "FacebookMarketplaceConfig") -> None:
        if self.login_wait_time is None:
            return
        if isinstance(self.login_wait_time, str):
            try:
                self.login_wait_time = convert_to_seconds(self.login_wait_time)
            except KeyboardInterrupt:
                raise
            except Exception as e:
                raise ValueError(
                    f"Marketplace {self.name} login_wait_time {self.login_wait_time} is not recognized."
                ) from e
        if not isinstance(self.login_wait_time, int) or self.login_wait_time < 0:
            raise ValueError(
                f"Marketplace {self.name} login_wait_time should be a non-negative number."
            )


@dataclass
class FacebookItemConfig(ItemConfig, FacebookMarketItemCommonConfig):
    pass
