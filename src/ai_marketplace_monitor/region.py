from dataclasses import dataclass, field
from typing import List

from .utils import DataClassWithHandleFunc


@dataclass
class RegionConfig(DataClassWithHandleFunc):
    search_city: List[str]
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
