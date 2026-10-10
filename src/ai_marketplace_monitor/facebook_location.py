"""Find Facebook Marketplace's location code (`search_city`) for a place, without a browser.

Marketplace URLs name a location by a code: a name for some large cities (``houston``,
``sandiego``) and a number for most places (``112697245411076`` for Katy, TX). Facebook's
location dialog finds it with two queries, which Facebook also answers for visitors who are
not logged in:

1. ``MarketplaceSearchAddressDataSourceQuery``: the places matching a city, neighborhood or
   ZIP code, with their coordinates;
2. ``MarketplaceBuyLocationDialogLocationUrlQuery``: the Marketplace code at a point.

Neither changes anything on a Facebook account. The ``doc_id`` of each query is Facebook's id
for it, which can change when Facebook updates its site; the lookup then fails, and users can
still copy the code from a Marketplace URL.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List

import requests  # type: ignore

PLACES_QUERY = ("MarketplaceSearchAddressDataSourceQuery", "9660140454040174")
CODE_QUERY = ("MarketplaceBuyLocationDialogLocationUrlQuery", "9608405655935574")
# a page that gives a logged-out visitor the token GraphQL requests need
TOKEN_PAGE = "https://www.facebook.com/marketplace/"
GRAPHQL = "https://www.facebook.com/api/graphql/"
TIMEOUT = 20

# Facebook matches the start of words, so "TX" does not find "Texas"
US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin",
    "WY": "Wyoming",
}  # fmt: skip

# what a browser sends; Facebook refuses the page to clients that look like scripts
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="126", "Google Chrome";v="126", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


class LocationLookupError(RuntimeError):
    """Facebook did not answer as expected (e.g. it changed its queries)."""


@dataclass
class Place:
    """A place Facebook suggests, and its Marketplace location code."""

    name: str  # "Los Angeles, La Salle County, Texas"
    detail: str  # "City", or "San Diego, CA · 116 people checked in here"
    latitude: float
    longitude: float
    code: str = ""  # search_city: "houston" or "487995858630733"

    @property
    def label(self: "Place") -> str:
        """The place with its region, to tell it apart from others of the same name.

        Facebook often names a place only "Los Angeles" and gives the region in its detail
        ("Los Ángeles, Coahuila de Zaragoza, Mexico · 433 people checked in here").
        """
        # the detail lists a street, the region and how many checked in: the region is the
        # last part with a comma ("La Dolorosa, 2 · Los Ángeles, Spain · 9,857 people ...")
        parts = [
            part.strip()
            for part in self.detail.split("·")
            if "," in part and "checked in" not in part
        ]
        region = parts[-1] if parts else ""
        if not region or region in self.name:
            return self.name
        return f"{self.name} ({region})"


def expand_state(place: str) -> str:
    """ "Houston, TX" -> "Houston, Texas": a US state's abbreviation after a comma or space."""
    match = re.search(r"([,\s])\s*([A-Za-z]{2})\.?\s*$", place)
    if not match or match.group(2).upper() not in US_STATES:
        return place
    return place[: match.start()].rstrip(" ,") + ", " + US_STATES[match.group(2).upper()]


class FacebookLocations:
    """Anonymous lookups in Facebook Marketplace's location search."""

    def __init__(self: "FacebookLocations", session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self._token: str | None = None

    def _get_token(self: "FacebookLocations") -> str:
        if self._token is None:
            page = self.session.get(TOKEN_PAGE, headers=_HEADERS, timeout=TIMEOUT)
            match = re.search(r'"LSD",\[\],\{"token":"([^"]+)"', page.text) or re.search(
                r'name="lsd" value="([^"]+)"', page.text
            )
            if page.status_code != 200 or not match:
                raise LocationLookupError(
                    f"Facebook did not give a token for its location search (HTTP {page.status_code})"
                )
            self._token = match.group(1)
        return self._token

    def _query(
        self: "FacebookLocations", query: "tuple[str, str]", variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        name, doc_id = query
        token = self._get_token()
        response = self.session.post(
            GRAPHQL,
            data={
                "av": "0",
                "__user": "0",
                "__a": "1",
                "lsd": token,
                "fb_api_caller_class": "RelayModern",
                "fb_api_req_friendly_name": name,
                "variables": json.dumps(variables),
                "doc_id": doc_id,
                "server_timestamps": "true",
            },
            headers={
                **_HEADERS,
                "X-FB-LSD": token,
                "X-FB-Friendly-Name": name,
                "Origin": "https://www.facebook.com",
                "Referer": TOKEN_PAGE,
            },
            timeout=TIMEOUT,
        )
        try:
            data = json.loads(response.text.removeprefix("for (;;);"))
        except ValueError:
            raise LocationLookupError(f"Facebook's {name} did not answer in JSON") from None
        if not isinstance(data, dict) or "data" not in data:
            summary = data.get("errorSummary") if isinstance(data, dict) else None
            raise LocationLookupError(f"Facebook's {name} failed: {summary or data}")
        return data["data"]  # type: ignore[no-any-return]

    def places(self: "FacebookLocations", place: str) -> List[Place]:
        """The cities, neighborhoods and ZIP codes Facebook suggests for ``place``."""
        data = self._query(
            PLACES_QUERY,
            {
                "params": {
                    "caller": "MARKETPLACE",
                    "country_filter": None,
                    "integration_strategy": "STRING_MATCH",
                    "page_category": ["CITY", "SUBCITY", "NEIGHBORHOOD", "POSTAL_CODE"],
                    "query": expand_state(place.strip()),
                    "search_type": "PLACE_TYPEAHEAD",
                    "viewer_coordinates": None,
                }
            },
        )
        try:
            edges = data["city_street_search"]["street_results"]["edges"]
            return [
                Place(
                    name=e["node"]["single_line_address"],
                    detail=e["node"].get("subtitle") or "",
                    latitude=float(e["node"]["location"]["latitude"]),
                    longitude=float(e["node"]["location"]["longitude"]),
                )
                for e in edges
            ]
        except (KeyError, TypeError) as e:
            raise LocationLookupError(f"Facebook's place search answered unexpectedly: {e}") from e

    def code_at(self: "FacebookLocations", latitude: float, longitude: float) -> str:
        """The Marketplace location code at a point: what follows /marketplace/ in a URL."""
        data = self._query(
            CODE_QUERY, {"buy_location": {"latitude": latitude, "longitude": longitude}}
        )
        try:
            location = data["viewer"]["marketplace_feed_stories"]["buy_location"]
            return str(location.get("marketplace_vanity_id") or location["id"])
        except (KeyError, TypeError) as e:
            raise LocationLookupError(
                f"Facebook's location code answered unexpectedly: {e}"
            ) from e

    def find(self: "FacebookLocations", place: str, limit: int = 10) -> List[Place]:
        """The places Facebook suggests for ``place``, each with its Marketplace code."""
        found = self.places(place)[:limit]
        for p in found:
            p.code = self.code_at(p.latitude, p.longitude)
        return found
