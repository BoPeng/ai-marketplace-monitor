from dataclasses import dataclass, field
from typing import List

from .utils import BaseConfig


@dataclass
class RegionConfig(BaseConfig):
    search_city: List[str] = field(default_factory=list)
    full_name: str = ""
    radius: List[int] = field(default_factory=list)
    city_name: List[str] = field(default_factory=list)

    def handle_search_city(self: "RegionConfig") -> None:
        if isinstance(self.search_city, str):
            self.search_city = [self.search_city]
        # check if search_city is a list of strings
        if not isinstance(self.search_city, list) or not all(
            isinstance(x, str) for x in self.search_city
        ):
            raise ValueError(f"Region {self.name} search_city must be a list of strings.")

    def handle_radius(self: "RegionConfig") -> None:
        if isinstance(self.radius, int):
            self.radius = [self.radius]
        elif not self.radius:
            self.radius = [500] * len(self.search_city)
        elif len(self.radius) != len(self.search_city):
            raise ValueError(
                f"Region {self.name} radius {self.radius} must be an integer or a list of integers with the same length as search_city {self.search_city}."
            )
        else:
            for radius in self.radius:
                if not isinstance(radius, int):
                    raise ValueError(
                        f"Region {self.name} radius must be an integer or a list of integers with the same length as search_city."
                    )

    def handle_city_name(self: "RegionConfig") -> None:
        if isinstance(self.city_name, str):
            self.city_name = [self.city_name]
        if not self.city_name:
            if not self.search_city:
                return
            self.city_name = [x.capitalize() for x in self.search_city]
            return

        # check if city_name is a list of strings
        if not isinstance(self.city_name, list) or not all(
            isinstance(x, str) for x in self.city_name
        ):
            raise ValueError(f"Region {self.name} city_name must be a list of strings.")

        if len(self.city_name) != len(self.search_city):
            raise ValueError(
                f"Region {self.name} city_name {self.city_name} must be the same length as search_city {self.search_city}."
            )
