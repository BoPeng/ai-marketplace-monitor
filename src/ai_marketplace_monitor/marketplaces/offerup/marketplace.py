"""OfferUp: searched over HTTP with OfferUp's web API (client.py), without a browser or login.

The steps every marketplace shares (filters, caches, seller warnings) are in the base class;
this class reads OfferUp's search results, listings and seller profiles, and checks whether
listings sold. OfferUp's search has no filter for a listing's age or delivery, so
``date_listed`` and ``delivery_method`` are applied after the listing is read.
"""

import re
import time
from datetime import datetime, timezone
from logging import Logger
from typing import TYPE_CHECKING, Any, Dict, List, Tuple, Type
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

from currency_converter import CurrencyConverter  # type: ignore

from ...control import control
from ...evaluations import AVAILABLE, PENDING, SOLD, EvaluationRecord, update_evaluation
from ...listing import Listing
from ...seller import Seller
from ...utils import CacheType, CounterItem, KeyboardMonitor, cache, counter, hilight
from ..base import (
    Condition,
    DeliveryMethod,
    ItemConfig,
    Marketplace,
    SearchPage,
    SortBy,
    resolve_option,
)
from .client import OfferUpBlockedError, OfferUpClient
from .config import OfferUpItemConfig, OfferUpMarketplaceConfig, coordinates

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext  # type: ignore

SEARCH_URL = "https://offerup.com/search"
# the radii OfferUp's search offers, in miles
RADIUS_CHOICES = (5, 10, 20, 30, 50)
# aimm's condition values, as OfferUp's CONDITION filter values
CONDITION_PARAM = {
    Condition.NEW.value: ["NEW"],
    Condition.USED_LIKE_NEW.value: ["OPEN_BOX", "USED"],
    Condition.USED_GOOD.value: ["USED"],
    Condition.USED_FAIR.value: ["USED"],
}
# aimm's sort_by values, as OfferUp's SORT values; aimm searches newest first by default
SORT_PARAM = {
    SortBy.SUGGESTED.value: "best_match",
    SortBy.NEW.value: "-posted",
    SortBy.PRICE_ASCEND.value: "price",
    SortBy.PRICE_DESCEND.value: "-price",
    SortBy.DISTANCE_ASCEND.value: "distance",
}
# a listing's numeric condition, as OfferUp's website shows it
CONDITION_TEXT = {
    100: "New",
    80: "Refurbished",
    60: "Open box",
    40: "Used",
    20: "For parts",
    0: "Other",
}
# a listing's state, as an evaluation state; others (removed, unlisted) keep their status
STATE = {"LISTED": AVAILABLE, "PENDING": PENDING, "SOLD": SOLD}
_LISTING_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


# OfferUp user ids are numbers, as Facebook's are: sellers are cached by id, so OfferUp's
# get a prefix
SELLER_PREFIX = "offerup:"


def _user_id(seller_id: str) -> str:
    """The OfferUp user id of an aimm seller id."""
    return seller_id[len(SELLER_PREFIX) :] if seller_id.startswith(SELLER_PREFIX) else seller_id


# the same OfferUp search (phrase, place and options) runs at most this often (seconds), for
# every schedule, restart and "search now"
MIN_SEARCH_INTERVAL = 30 * 60


def nearest_radius(radius: float) -> int:
    """The radius OfferUp offers closest to ``radius``; the larger one on a tie."""
    return min(RADIUS_CHOICES, key=lambda c: (abs(c - radius), -c))


def _price(value: Any) -> str:
    """A listing's price as aimm shows prices ("$850")."""
    text = str(value or "").strip()
    return f"${text}" if text and not text.startswith("$") else text


def _posted(post_date: str) -> datetime | None:
    """When a listing was posted, in UTC; None if unknown or unreadable."""
    if not post_date:
        return None
    try:
        posted = datetime.fromisoformat(post_date.replace("Z", "+00:00"))
    except ValueError:
        return None
    return posted if posted.tzinfo else posted.replace(tzinfo=timezone.utc)


def _first_or_later(key: str, item_config: Any, marketplace_config: Any) -> Any:
    """An option with a first and a later value (date_listed, delivery_method)."""
    values = resolve_option(key, item_config, marketplace_config)
    if not values:
        return None
    # the search counts itself before its listings are checked
    return values[0 if item_config.searched_count <= 1 else -1]


class OfferUpMarketplace(Marketplace):
    market_type = "offerup"
    config_class = OfferUpMarketplaceConfig
    item_config_class = OfferUpItemConfig
    needs_browser = False
    # regions list their cities by type: { facebook = "houston", offerup = "77002" }
    supports_regions = True
    # the client spaces its requests (client.MIN_GAP): no extra waits
    search_page_delay = listing_page_delay = profile_page_delay = 0

    def __init__(
        self: "OfferUpMarketplace",
        name: str,
        browser: "Browser | BrowserContext | None" = None,
        keyboard_monitor: KeyboardMonitor | None = None,
        logger: Logger | None = None,
    ) -> None:
        super().__init__(name, None, keyboard_monitor, logger)
        self.client = OfferUpClient()

    @classmethod
    def get_config(cls: Type["OfferUpMarketplace"], **kwargs: Any) -> OfferUpMarketplaceConfig:
        return OfferUpMarketplaceConfig(**kwargs)

    @classmethod
    def get_item_config(cls: Type["OfferUpMarketplace"], **kwargs: Any) -> OfferUpItemConfig:
        return OfferUpItemConfig(**kwargs)

    def configure(
        self: "OfferUpMarketplace", config: OfferUpMarketplaceConfig, translator: Any = None
    ) -> None:
        super().configure(config, translator)
        proxy = config.monitor_config.get_proxy_options() if config.monitor_config else None
        proxies: Dict[str, str] = {}
        if proxy:
            server = proxy["server"]
            if proxy.get("username") and proxy.get("password") and "://" in server:
                scheme, rest = server.split("://", 1)
                # quoted: a character such as @ or : in a password would change the URL
                user = quote(str(proxy["username"]), safe="")
                password = quote(str(proxy["password"]), safe="")
                server = f"{scheme}://{user}:{password}@{rest}"
            proxies = {"http": server, "https": server}
        self.client.proxies = proxies

    # --- URLs -------------------------------------------------------------------------------
    @classmethod
    def listing_url(cls: Type["OfferUpMarketplace"], listing_id: str) -> str:
        return f"https://offerup.com/item/detail/{listing_id}"

    @classmethod
    def listing_id(cls: Type["OfferUpMarketplace"], listing: str) -> str:
        """The id of an OfferUp listing URL (``/item/detail/<id>``) or of an id, or ''."""
        listing = listing.strip()
        if _LISTING_ID.fullmatch(listing):
            return listing
        url = urlsplit(listing if "://" in listing else f"https://{listing}")
        host = (url.hostname or "").lower()
        if host not in ("offerup.com", "www.offerup.com"):
            return ""
        match = re.fullmatch(r"/item/detail/(" + _LISTING_ID.pattern + r")/?", url.path)
        return match.group(1) if match else ""

    @classmethod
    def seller_url(cls: Type["OfferUpMarketplace"], seller_id: str) -> str:
        return f"https://offerup.com/p/{_user_id(seller_id)}/"

    # --- searching --------------------------------------------------------------------------
    def search_pages(self: "OfferUpMarketplace", item_config: ItemConfig) -> List[SearchPage]:
        """One search per ZIP code and search phrase; its parameters are in its URL."""
        options: Dict[str, Any] = {}
        sort_by = resolve_option("sort_by", item_config, self.config)
        options["SORT"] = SORT_PARAM.get(sort_by or SortBy.NEW.value, "-posted")
        condition = resolve_option("condition", item_config, self.config)
        if condition:
            wanted = dict.fromkeys(v for c in condition for v in CONDITION_PARAM.get(c, []))
            options["CONDITION"] = ",".join(wanted)
        for key, param in (("min_price", "PRICE_MIN"), ("max_price", "PRICE_MAX")):
            price = resolve_option(key, item_config, self.config)
            if price:
                options[param] = self._dollars(price)
        zips = resolve_option("search_city", item_config, self.config) or []
        names = resolve_option("city_name", item_config, self.config) or []
        radii = resolve_option("radius", item_config, self.config) or []
        pages = []
        for i, zipcode in enumerate(zips):
            radius = nearest_radius(radii[i]) if i < len(radii) and radii[i] else None
            for phrase in item_config.search_phrases:
                point = coordinates(zipcode)
                where = {"lat": point[0], "lon": point[1]} if point else {"zipcode": zipcode}
                params = {"q": phrase, **where, **options}
                if radius:
                    params["radius"] = radius
                pages.append(
                    SearchPage(
                        city=zipcode,
                        city_name=names[i] if i < len(names) else None,
                        radius=radius,
                        phrase=phrase,
                        url=f"{SEARCH_URL}?{urlencode(params)}",
                    )
                )
        return pages

    def due_search_pages(
        self: "OfferUpMarketplace", pages: List[SearchPage], item_config: ItemConfig
    ) -> List[SearchPage]:
        """The searches not run in the last MIN_SEARCH_INTERVAL; it records them as run.

        The record is kept in the cache, so restarting aimm does not reset it.
        """
        due = []
        for page in pages:
            key = (CacheType.OFFERUP_SEARCHES.value, page.url)
            if key in cache:
                if self.logger:
                    self.logger.info(
                        f"""{hilight("[Search]", "info")} Skip OfferUp search for """
                        f"""{hilight(item_config.name)} from {page.city_name or page.city}: """
                        f"OfferUp searches run at most every {MIN_SEARCH_INTERVAL // 60} minutes."
                    )
                continue
            cache.set(
                key,
                time.time(),
                expire=MIN_SEARCH_INTERVAL,
                tag=CacheType.OFFERUP_SEARCHES.value,
            )
            due.append(page)
        return due

    def _dollars(self: "OfferUpMarketplace", price: str) -> str:
        """A price option ("300" or "300 EUR") in US dollars, as OfferUp's search takes it."""
        amount, _, currency = str(price).partition(" ")
        if currency and currency.upper() != "USD":
            amount = str(int(CurrencyConverter().convert(int(amount), currency.upper(), "USD")))
        return amount

    def read_search_page(self: "OfferUpMarketplace", search: SearchPage) -> List[Listing]:
        params = dict(parse_qsl(urlsplit(search.url).query))
        return [
            Listing(
                marketplace=self.market_type,
                name="",
                id=card["listingId"],
                title=card.get("title") or "",
                image=(card.get("image") or {}).get("url") or "",
                price=_price(card.get("price")),
                post_url=self.listing_url(card["listingId"]),
                location=card.get("locationName") or "",
                seller="",
                condition="",
                description="",
            )
            for card in self.client.search({**params, "limit": 50})
        ]

    def get_listing_details(
        self: "OfferUpMarketplace",
        post_url: str,
        item_config: ItemConfig,
        price: str | None = None,
        title: str | None = None,
    ) -> Tuple[Listing, bool]:
        details = Listing.from_cache(post_url)
        if (
            details is not None
            and details.seller_parsed
            and (price is None or details.price == price)
            and (title is None or details.title == title)
        ):
            return details, True
        lid = self.listing_id(post_url)
        if not lid:
            raise ValueError(f"{post_url} is not an OfferUp listing.")
        counter.increment(CounterItem.LISTING_QUERY, item_config.name)
        data = self.client.listing(lid)
        if data is None or data.get("isRemoved"):
            raise ValueError(f"OfferUp no longer has listing {post_url}.")
        details = self._listing(data, post_url)
        details.to_cache(post_url)
        return details, False

    def _listing(self: "OfferUpMarketplace", data: Dict[str, Any], post_url: str) -> Listing:
        owner = data.get("owner") or {}
        seller_id = f"{SELLER_PREFIX}{owner['id']}" if owner.get("id") else ""
        seller_name = (owner.get("profile") or {}).get("name") or ""
        fulfillment = data.get("fulfillmentDetails") or {}
        pickup = bool(fulfillment.get("localPickupEnabled"))
        shipping = bool(fulfillment.get("shippingEnabled"))
        photos = data.get("photos") or []
        return Listing(
            marketplace=self.market_type,
            name="",
            id=data.get("listingId") or self.listing_id(post_url),
            title=data.get("title") or "",
            image=((photos[0] if photos else {}).get("detail") or {}).get("url") or "",
            price=_price(data.get("price")),
            post_url=post_url,
            location=(data.get("locationDetails") or {}).get("locationName") or "",
            seller=seller_name,
            condition=CONDITION_TEXT.get(data.get("condition"), ""),  # type: ignore[arg-type]
            description=data.get("description") or "",
            seller_id=seller_id,
            seller_info=(
                {"seller": {"id": seller_id, "name": seller_name, "platform": "OfferUp"}}
                if seller_id
                else {}
            ),
            seller_parsed=True,
            post_date=data.get("postDate") or "",
            delivery=(
                DeliveryMethod.ALL.value
                if pickup and shipping
                else (
                    DeliveryMethod.SHIPPING.value
                    if shipping
                    else DeliveryMethod.LOCAL_PICK_UP.value if pickup else ""
                )
            ),
        )

    def read_seller_profile(
        self: "OfferUpMarketplace", seller_id: str, item_config: ItemConfig | None = None
    ) -> Seller:
        """The seller's public profile: account age, ratings, items sold, badges."""
        if item_config is not None:
            counter.increment(CounterItem.LISTING_QUERY, item_config.name)
        data = self.client.profile(_user_id(seller_id))
        if data is None:
            raise ValueError(f"OfferUp has no seller {seller_id}.")
        rating = data.get("ratingSummary") or {}
        joined = str(data.get("dateJoined") or "")
        strengths = [
            f"{a['value']} ({a['count']})"
            for a in data.get("ratingAttributes") or []
            if a.get("value") and a.get("count")
        ]
        badges = [b["label"] for b in data.get("badges") or [] if b.get("label")]
        if data.get("isTruyouVerified"):
            badges.append("TruYou verified")
        if data.get("isBusinessAccount"):
            badges.append("business account")
        sold = str(data.get("itemsSold") or "")
        return Seller(
            id=seller_id,
            platform="OfferUp",
            badges=badges,
            name=data.get("name") or "",
            joined_year=int(joined[:4]) if joined[:4].isdigit() else None,
            rating=float(rating["average"]) if rating.get("count") else None,
            rating_count=int(rating.get("count") or 0),
            sold_listings=int(sold) if sold.isdigit() else None,
            strengths=strengths,
        )

    # --- what the search cannot filter ------------------------------------------------------
    def exclusion_reason(
        self: "OfferUpMarketplace",
        item: Listing,
        item_config: ItemConfig,
        description_available: bool = True,
    ) -> str | None:
        reason = super().exclusion_reason(item, item_config, description_available)
        if reason is not None or not description_available:
            return reason
        days = _first_or_later("date_listed", item_config, self.config)
        posted = _posted(item.post_date)
        if days and posted is not None:
            age = (datetime.now(timezone.utc) - posted).total_seconds() / 86400
            if age > int(days):
                if self.logger:
                    self.logger.info(
                        f"""{hilight("[Skip]", "fail")} Exclude {hilight(item.title)}, {hilight("listed", "fail")} {age:.0f} days ago"""
                    )
                return f"listed more than {days} days ago"
        delivery = _first_or_later("delivery_method", item_config, self.config)
        offered = item.delivery
        if delivery in (DeliveryMethod.LOCAL_PICK_UP.value, DeliveryMethod.SHIPPING.value) and (
            offered and offered not in (delivery, DeliveryMethod.ALL.value)
        ):
            label = (
                "local pickup only"
                if offered == DeliveryMethod.LOCAL_PICK_UP.value
                else "shipping only"
            )
            if self.logger:
                self.logger.info(
                    f"""{hilight("[Skip]", "fail")} Exclude {hilight(item.title)}, {hilight(label, "fail")}"""
                )
            return label
        return None

    # --- whether listings sold --------------------------------------------------------------
    def check_status(
        self: "OfferUpMarketplace", records: List[EvaluationRecord], as_of: float | None = None
    ) -> int:
        """Read each listing's state: available, pending or sold; the number read."""
        read = 0
        for record in records:
            if control.is_paused() or (
                self.keyboard_monitor is not None and self.keyboard_monitor.is_paused()
            ):
                break
            lid = self.listing_id(record.url) or record.id
            try:
                data = self.client.listing(lid)
            except OfferUpBlockedError as e:
                if self.logger:
                    self.logger.warning(f"{hilight('[Status]', 'fail')} {e}")
                break
            except Exception as e:
                if self.logger:
                    self.logger.debug(f"{hilight('[Status]', 'fail')} {record.url}: {e}")
                continue
            state = STATE.get(str((data or {}).get("state")))
            if state is None:
                if self.logger:
                    self.logger.debug(
                        f"{hilight('[Status]', 'fail')} {record.url}: no state; keeping its status."
                    )
                continue
            now = time.time()
            update_evaluation(
                record.marketplace,
                record.id,
                record.item,
                state=state,
                checked=now,
                now=now if as_of is None else min(now, as_of),
            )
            read += 1
            if self.logger:
                self.logger.info(f"""{hilight("[Status]", "info")} {record.title}: {state}""")
        return read
