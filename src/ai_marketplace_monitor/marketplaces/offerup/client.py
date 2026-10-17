"""OfferUp's web API: the GraphQL queries its website sends, without an account.

OfferUp has no public API. Its website asks ``https://offerup.com/api/graphql`` for search
results (``GetModularFeed``), a listing (``GetListingDetailByListingId``) and a seller's
public profile (``PublicProfile``); these answer anonymous requests that look like a
browser's. aimm writes its own queries with only the fields it reads, so changes to
OfferUp's own query text do not matter; a field OfferUp removes shows as an error.

OfferUp is behind Cloudflare, which refuses clients that do not look like a browser (and,
presumably, too many requests) with HTTP 403. Requests are spaced by ``min_gap`` seconds.
OfferUp is only available in the US.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Mapping

import requests  # type: ignore

GRAPHQL = "https://offerup.com/api/graphql"
TIMEOUT = 30  # seconds
MIN_GAP = 3.0  # seconds between requests

# what a browser sends with its GraphQL requests
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "https://offerup.com",
    "Referer": "https://offerup.com/",
}

SEARCH_QUERY = """query GetModularFeed($searchParams: [SearchParam]) {
  modularFeed(params: $searchParams) {
    pageCursor
    looseTiles {
      tileType
      ... on ModularFeedTileListing {
        listing { listingId title price locationName flags conditionText image { url } }
      }
    }
  }
}"""

LISTING_QUERY = """query GetListingDetailByListingId($listingId: ID!) {
  listing(listingId: $listingId) {
    listingId title price condition description postDate state isRemoved
    locationDetails { locationName }
    fulfillmentDetails { localPickupEnabled shippingEnabled }
    photos { detail { url } }
    owner { id profile { name } }
  }
}"""

PROFILE_QUERY = """query PublicProfile($userId: Int) {
  publicProfile(userId: $userId) {
    userId name dateJoined isTruyouVerified isBusinessAccount itemsSold itemsPurchased
    ratingSummary { count average }
    ratingAttributes { count value }
    badges { label }
  }
}"""


class OfferUpError(RuntimeError):
    """OfferUp did not answer as expected (e.g. it changed or dropped a field)."""


class OfferUpBlockedError(OfferUpError):
    """OfferUp (Cloudflare) refused the request: too many requests, or outside the US."""


class OfferUpClient:
    """Sends aimm's GraphQL queries to OfferUp, one at a time, ``min_gap`` seconds apart."""

    def __init__(
        self: "OfferUpClient",
        proxies: Mapping[str, str] | None = None,
        session: Any = None,
        min_gap: float = MIN_GAP,
    ) -> None:
        self.session = session or requests.Session()
        self.proxies = dict(proxies or {})
        self.min_gap = min_gap
        self._lock = threading.Lock()
        self._last = 0.0

    def _post(self: "OfferUpClient", operation: str, query: str, variables: Dict[str, Any]) -> Any:
        with self._lock:
            wait = self._last + self.min_gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                response = self.session.post(
                    GRAPHQL,
                    json={"operationName": operation, "variables": variables, "query": query},
                    headers=_HEADERS,
                    proxies=self.proxies or None,
                    timeout=TIMEOUT,
                )
            finally:
                self._last = time.monotonic()
        if response.status_code in (403, 429):
            raise OfferUpBlockedError(
                f"OfferUp refused the request (HTTP {response.status_code}): too many requests, "
                "or a location outside the US (OfferUp is US-only; set proxy_server to a US "
                "proxy)."
            )
        try:
            body = response.json()
        except ValueError as e:
            raise OfferUpError(f"OfferUp answered HTTP {response.status_code}, not JSON.") from e
        if body.get("errors"):
            messages = "; ".join(str(e.get("message", e)) for e in body["errors"])
            raise OfferUpError(f"OfferUp {operation}: {messages}")
        if response.status_code != 200 or "data" not in body:
            raise OfferUpError(f"OfferUp answered HTTP {response.status_code} to {operation}.")
        return body["data"]

    def search(self: "OfferUpClient", params: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """The listings of a search (``q``, ``zipcode``, ``radius``, ``PRICE_MAX``, ...)."""
        search_params = [{"key": k, "value": str(v)} for k, v in params.items()]
        data = self._post("GetModularFeed", SEARCH_QUERY, {"searchParams": search_params})
        tiles = (data.get("modularFeed") or {}).get("looseTiles") or []
        # ads are mixed in: keep the listings
        return [t["listing"] for t in tiles if t.get("tileType") == "LISTING" and t.get("listing")]

    def listing(self: "OfferUpClient", listing_id: str) -> Dict[str, Any] | None:
        """A listing's details, or None if OfferUp has no such listing."""
        data = self._post("GetListingDetailByListingId", LISTING_QUERY, {"listingId": listing_id})
        return data.get("listing")

    def profile(self: "OfferUpClient", user_id: str) -> Dict[str, Any] | None:
        """A seller's public profile, or None if OfferUp has no such user."""
        data = self._post("PublicProfile", PROFILE_QUERY, {"userId": int(user_id)})
        return data.get("publicProfile")
