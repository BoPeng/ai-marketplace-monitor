"""The options of Facebook marketplace and item sections."""

import os
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, List

from ...utils import (
    BaseConfig,
    convert_to_seconds,
    hilight,
)
from ..base import (
    Fallback,
    ItemConfig,
    MarketplaceConfig,
    option,
)

if TYPE_CHECKING:
    pass


class Condition(Enum):
    NEW = "new"
    USED_LIKE_NEW = "used_like_new"
    USED_GOOD = "used_good"
    USED_FAIR = "used_fair"


class DateListed(Enum):
    ANYTIME = 0
    PAST_24_HOURS = 1
    PAST_WEEK = 7
    PAST_MONTH = 30


class DeliveryMethod(Enum):
    LOCAL_PICK_UP = "local_pick_up"
    SHIPPING = "shipping"
    ALL = "all"


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


class SortBy(Enum):
    SUGGESTED = "suggested"
    NEW = "new"
    PRICE_ASCEND = "price_ascend"
    PRICE_DESCEND = "price_descend"
    DISTANCE_ASCEND = "distance_ascend"


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
    """Item options that can be defined in marketplace

    This class defines and processes options that can be specified
    in both marketplace and item sections, specific to facebook marketplace
    """

    seller_locations: List[str] | None = option(Fallback.NOT_NONE)
    availability: List[str] | None = option(Fallback.TRUTHY)
    condition: List[str] | None = option(Fallback.TRUTHY)
    date_listed: List[int] | None = option(Fallback.TRUTHY)
    delivery_method: List[str] | None = option(Fallback.TRUTHY)
    category: str | None = option(Fallback.TRUTHY)
    sort_by: str | None = option(Fallback.TRUTHY)
    # skip sellers rated below this by enough buyers; sellers without ratings are kept
    seller_min_rating: float | None = option(Fallback.NOT_NONE)

    def handle_seller_min_rating(self: "FacebookMarketItemCommonConfig") -> None:
        value = self.seller_min_rating
        if value is None:
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 5:
            raise ValueError(
                f"Item {hilight(self.name)} seller_min_rating must be a number from 0 to 5."
            )
        self.seller_min_rating = float(value)

    def handle_seller_locations(self: "FacebookMarketItemCommonConfig") -> None:
        if self.seller_locations is None:
            return

        if isinstance(self.seller_locations, str):
            self.seller_locations = [self.seller_locations]
        if not isinstance(self.seller_locations, list) or not all(
            isinstance(x, str) for x in self.seller_locations
        ):
            raise ValueError(f"Item {hilight(self.name)} seller_locations must be a list.")

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

    def handle_condition(self: "FacebookMarketItemCommonConfig") -> None:
        if self.condition is None:
            return
        if isinstance(self.condition, Condition):
            self.condition = [self.condition]
        if not isinstance(self.condition, list) or not all(
            isinstance(x, str) and x in [cond.value for cond in Condition] for x in self.condition
        ):
            raise ValueError(
                f"Item {hilight(self.name)} condition must be one or more of that can be one of 'new', 'used_like_new', 'used_good', 'used_fair'."
            )

    def handle_date_listed(self: "FacebookMarketItemCommonConfig") -> None:
        if self.date_listed is None:
            return
        if not isinstance(self.date_listed, list):
            self.date_listed = [self.date_listed]
        #
        new_values: List[int] = []
        for val in self.date_listed:
            if isinstance(val, str):
                if val.isdigit():
                    new_values.append(int(val))
                elif val.lower() == "all":
                    new_values.append(DateListed.ANYTIME.value)
                elif val.lower() == "last 24 hours":
                    new_values.append(DateListed.PAST_24_HOURS.value)
                elif val.lower() == "last 7 days":
                    new_values.append(DateListed.PAST_WEEK.value)
                elif val.lower() == "last 30 days":
                    new_values.append(DateListed.PAST_MONTH.value)
                else:
                    raise ValueError(
                        f"""Item {hilight(self.name)} date_listed must be one of 1, 7, and 30, or All, Last 24 hours, Last 7 days, Last 30 days.: {self.date_listed} provided."""
                    )
            elif isinstance(val, (int, float)):
                if int(val) not in [x.value for x in DateListed]:
                    raise ValueError(
                        f"""Item {hilight(self.name)} date_listed must be one of 1, 7, and 30, or All, Last 24 hours, Last 7 days, Last 30 days.: {self.date_listed} provided."""
                    )
                new_values.append(int(val))
            else:
                raise ValueError(
                    f"""Item {hilight(self.name)} date_listed must be one of 1, 7, and 30, or All, Last 24 hours, Last 7 days, Last 30 days.: {self.date_listed} provided."""
                )
        # new_values should have length 1 or 2
        if len(new_values) > 2:
            raise ValueError(
                f"""Item {hilight(self.name)} date_listed must have one or two values."""
            )
        self.date_listed = new_values

    def handle_delivery_method(self: "FacebookMarketItemCommonConfig") -> None:
        if self.delivery_method is None:
            return

        if isinstance(self.delivery_method, str):
            self.delivery_method = [self.delivery_method]

        if len(self.delivery_method) > 2:
            raise ValueError(
                f"Item {hilight(self.name)} delivery_method must be one or two values of 'local_pick_up' and 'shipping'."
            )

        if not isinstance(self.delivery_method, list) or not all(
            val in [x.value for x in DeliveryMethod] for val in self.delivery_method
        ):
            raise ValueError(
                f"Item {hilight(self.name)} delivery_method must be one of 'local_pick_up' and 'shipping'."
            )

    def handle_category(self: "FacebookMarketItemCommonConfig") -> None:
        if self.category is None:
            return

        if not isinstance(self.category, str) or self.category not in [x.value for x in Category]:
            raise ValueError(
                f"Item {hilight(self.name)} category must be one of {', '.join(x.value for x in Category)}."
            )

    def handle_sort_by(self: "FacebookMarketItemCommonConfig") -> None:
        if self.sort_by is None:
            return

        if not isinstance(self.sort_by, str) or self.sort_by not in [x.value for x in SortBy]:
            raise ValueError(
                f"Item {hilight(self.name)} sort_by must be one of {', '.join(x.value for x in SortBy)}."
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
