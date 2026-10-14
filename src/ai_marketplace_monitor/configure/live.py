"""Facebook pages for the configure chat, opened in the monitor's browser.

The monitor shares its Chromium (see ``shared_browser.py``). The chat connects to it with its
own Playwright connection, in a thread of its own (Playwright's sync API cannot run in the
chat's event loop), opens a tab in the browser's context, which is logged in to Facebook
whenever the monitor is, and closes the tab when done. It reuses the monitor's code to read a
listing, its seller and the AI's rating (``monitor.inspect_listing``).

The chat never logs in, never waits for a login and never writes the saved session: when the
browser is not logged in, it says so. Page loads take turns with the monitor's
(``navigation_slot``) and give up instead of waiting without end.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterator, List, Tuple, TypeVar

from ..ai import AIResponse
from ..config import Config, supported_marketplaces
from ..facebook import FacebookMarketplace, FacebookSellerProfilePage
from ..marketplace import DEFAULT_RATING, resolve_option
from ..seller import Seller, seller_id_from_url, seller_warnings
from ..shared_browser import BrowserBusyError, shared_endpoint
from .history import (
    COMMENT_CHARS,
    DESCRIPTION_CHARS,
    SELLER_CHARS,
    TITLE_CHARS,
    UNTRUSTED_NOTE,
    listing_id,
)

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext  # type: ignore

logger = logging.getLogger(__name__)

T = TypeVar("T")

CONNECT_TIMEOUT_MS = 10_000
PAGE_TIMEOUT_MS = 60_000  # one page load
WAIT_FOR_MONITOR = 120.0  # seconds to wait while the monitor loads a page

UNAVAILABLE = (
    "aimm's browser cannot be shared with the chat now, so Facebook pages cannot be opened "
    "from here. Warn the user and say why: the chat uses the browser of a monitor running on "
    "this computer (`aimm run`, or the web UI), and only when that browser is Chromium (when "
    "Chromium cannot be launched, aimm uses Firefox or WebKit, which cannot be shared; the "
    "monitor's log says so). A monitor in a Docker container shares its browser only with the "
    "web UI's chat, not with `aimm configure` outside the container. Then answer from aimm's "
    "records (find_listings, explain_listing), or ask the user to start the monitor."
)
NOT_LOGGED_IN = (
    "aimm's browser is not logged in to Facebook. The monitor logs in when it starts; if it is "
    "waiting for a CAPTCHA or a security code, the user finishes the login where aimm says (in "
    "the web UI, the browser view). The chat never logs in itself."
)


class LiveUnavailableError(RuntimeError):
    """The shared browser cannot be used now; the message says why, for the model."""


class ChatFacebookMarketplace(FacebookMarketplace):
    """FacebookMarketplace in the chat: never logs in, never writes the saved session."""

    def login(self: "ChatFacebookMarketplace") -> None:
        raise LiveUnavailableError(NOT_LOGGED_IN)

    def wait_for_login(self: "ChatFacebookMarketplace") -> None:
        if not self.logged_in():
            raise LiveUnavailableError(NOT_LOGGED_IN)

    def recover_login(self: "ChatFacebookMarketplace") -> bool:
        if self.page is not None and self.on_login_page():
            raise LiveUnavailableError(NOT_LOGGED_IN)
        return False

    def save_session(self: "ChatFacebookMarketplace") -> None:
        """The monitor keeps the saved session: the chat's tab must never replace it."""


def _cut(text: Any, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _seller_view(seller: Seller) -> Dict[str, Any]:
    return {
        "name": seller.name,
        "id": seller.id,
        "profile": f"https://www.facebook.com/marketplace/profile/{seller.id}/",
        "summary": _cut(seller.summary(), SELLER_CHARS),
        "warnings": seller_warnings(seller),
        "profile_read": seller.profile_checked,
    }


class LiveBrowser:
    """Opens Facebook pages for the chat in the monitor's browser, one request at a time."""

    def __init__(self: "LiveBrowser", config_files: List[Path]) -> None:
        self.config_files = list(config_files)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="aimm-chat-browser")

    def close(self: "LiveBrowser") -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def _run(self: "LiveBrowser", work: Callable[[], T]) -> T:
        return await asyncio.get_running_loop().run_in_executor(self._executor, work)

    # --- the tools ----------------------------------------------------------------------
    async def evaluate_listing(self: "LiveBrowser", listing: str, item: str) -> Dict[str, Any]:
        lid = listing_id(listing)
        if not lid:
            return {
                "ok": False,
                "errors": [
                    "Give a listing id or a Facebook Marketplace URL (/marketplace/item/<id>)."
                ],
            }
        try:
            return await self._run(lambda: self._evaluate(lid, item))
        except (LiveUnavailableError, BrowserBusyError) as e:
            return {"ok": False, "errors": [str(e)]}
        except Exception as e:
            logger.debug("evaluate_listing failed", exc_info=True)
            return {"ok": False, "errors": [f"aimm could not read listing {lid}: {e}"]}

    async def check_seller(self: "LiveBrowser", seller: str) -> Dict[str, Any]:
        seller = seller.strip()
        sid = seller if seller.isdigit() else seller_id_from_url(seller)
        lid = "" if sid else listing_id(seller)
        if not sid and not lid:
            return {
                "ok": False,
                "errors": [
                    "Give a seller's profile URL (/marketplace/profile/<id>), their id, or the "
                    "URL of one of their listings."
                ],
            }
        try:
            return await self._run(lambda: self._check_seller(sid, lid))
        except (LiveUnavailableError, BrowserBusyError) as e:
            return {"ok": False, "errors": [str(e)]}
        except Exception as e:
            logger.debug("check_seller failed", exc_info=True)
            return {"ok": False, "errors": [f"aimm could not read the seller: {e}"]}

    # --- in the worker thread -----------------------------------------------------------
    def _config(self: "LiveBrowser") -> Config:
        try:
            return Config(self.config_files, logger)
        except Exception as e:
            raise LiveUnavailableError(f"aimm's configuration cannot be loaded: {e}") from e

    def _item(self: "LiveBrowser", config: Config, item: str) -> Any:
        names = list(config.item)
        if not names:
            raise LiveUnavailableError("There is no [item.*] section to evaluate listings for.")
        if not item:
            if len(names) > 1:
                raise LiveUnavailableError(
                    f"Which item should the listing be evaluated for? Items: {', '.join(names)}."
                )
            item = names[0]
        if item not in config.item:
            raise LiveUnavailableError(f"No item {item!r}; items: {', '.join(names)}.")
        return config.item[item]

    def _marketplace_config(self: "LiveBrowser", config: Config, item_config: Any | None) -> Any:
        wanted = getattr(item_config, "marketplace", None)
        for marketplace_config in config.marketplace.values():
            if wanted is not None and marketplace_config.name != wanted:
                continue
            if wanted is None and marketplace_config.enabled is False:
                continue
            if supported_marketplaces.get(marketplace_config.name) is not FacebookMarketplace:
                continue
            return marketplace_config
        raise LiveUnavailableError("There is no Facebook [marketplace.*] section.")

    @contextmanager
    def _facebook(
        self: "LiveBrowser", config: Config, marketplace_config: Any
    ) -> Iterator[ChatFacebookMarketplace]:
        """A logged-in Facebook marketplace on a new tab of the shared browser."""
        from playwright.sync_api import sync_playwright  # type: ignore

        from ..monitor import select_translator

        endpoint = shared_endpoint()
        if endpoint is None:
            raise LiveUnavailableError(UNAVAILABLE)
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(
                    endpoint, timeout=CONNECT_TIMEOUT_MS
                )
            except Exception as e:
                raise LiveUnavailableError(f"{UNAVAILABLE} ({e})") from e
            try:
                if not browser.contexts:
                    raise LiveUnavailableError(UNAVAILABLE)
                context: "BrowserContext" = browser.contexts[0]
                marketplace = ChatFacebookMarketplace(
                    marketplace_config.name, context, None, logger
                )
                marketplace.configure(
                    marketplace_config,
                    translator=select_translator(config, marketplace_config.language, logger),
                )
                marketplace.navigation_timeout_ms = PAGE_TIMEOUT_MS
                marketplace.navigation_retries = 1
                marketplace.navigation_wait = WAIT_FOR_MONITOR
                page = context.new_page()
                try:
                    marketplace.page = page
                    if not marketplace.has_login_cookie(context):
                        raise LiveUnavailableError(NOT_LOGGED_IN)
                    yield marketplace
                finally:
                    page.close()
            finally:
                browser.close()  # disconnects; the monitor's browser keeps running

    def _evaluate(self: "LiveBrowser", lid: str, item: str) -> Dict[str, Any]:
        from ..monitor import inspect_listing, make_ai_agents

        config = self._config()
        item_config = self._item(config, item)
        marketplace_config = self._marketplace_config(config, item_config)
        agents = make_ai_agents(config, logger)
        url = f"https://www.facebook.com/marketplace/item/{lid}/"
        started = time.monotonic()
        with self._facebook(config, marketplace_config) as marketplace:
            listing, from_cache, excluded, answer = inspect_listing(
                marketplace, url, item_config, marketplace_config, agents, logger
            )
        rated = answer.comment != AIResponse.NOT_EVALUATED
        ratings = resolve_option("rating", item_config, marketplace_config)
        threshold = ratings[-1] if ratings else DEFAULT_RATING
        seller_info = listing.seller_info or {}
        return {
            "ok": True,
            "item": item_config.name,
            "listing": {
                "id": listing.id,
                "url": url,
                "title": _cut(listing.title, TITLE_CHARS),
                "price": listing.price,
                "location": listing.location,
                "condition": listing.condition,
                "description": _cut(listing.description, DESCRIPTION_CHARS),
                "from_cache": from_cache,
            },
            "seller": {
                "name": listing.seller,
                "summary": _cut(seller_info.get("summary"), SELLER_CHARS),
                "warnings": seller_info.get("warnings") or [],
            },
            "excluded_by": excluded,
            "rating": answer.score if rated else None,
            "conclusion": answer.conclusion if rated else None,
            "ai_comment": _cut(answer.comment, COMMENT_CHARS) if rated else None,
            "ai": answer.name or None,
            "notify_threshold": threshold,
            "would_notify": bool(rated and excluded is None and answer.score >= threshold),
            "seconds": round(time.monotonic() - started),
            "note": (
                "The listing as a search for this item would see it: `excluded_by` is why the "
                "search would drop it before the AI (null if it would not), and the AI rated "
                "it with the item's settings (null if no AI answered). `from_cache`: the "
                "details were read earlier, and the page was not opened again. This check is "
                "not recorded as a decision and notifies no one. " + UNTRUSTED_NOTE
            ),
        }

    def _check_seller(self: "LiveBrowser", sid: str, lid: str) -> Dict[str, Any]:
        config = self._config()
        marketplace_config = self._marketplace_config(config, None)
        with self._facebook(config, marketplace_config) as marketplace:
            if lid:
                # any item: it only names the counter of listings read
                item_config = self._item(config, next(iter(config.item), ""))
                url = f"https://www.facebook.com/marketplace/item/{lid}/"
                listing, _ = marketplace.get_listing_details(url, item_config)
                sid = listing.seller_id
                if not sid:
                    raise LiveUnavailableError(
                        f"Listing {lid} does not show a link to its seller's profile."
                    )
            seller, from_cache = self._read_seller(marketplace, sid)
        return {
            "ok": True,
            "seller": _seller_view(seller),
            "from_cache": from_cache,
            "note": (
                "What the seller's Marketplace profile shows, and warning signs at aimm's "
                "default thresholds (an item's seller_* settings may differ). `from_cache`: the "
                "profile was read in the last month and not opened again. " + UNTRUSTED_NOTE
            ),
        }

    def _read_seller(
        self: "LiveBrowser", marketplace: ChatFacebookMarketplace, sid: str
    ) -> Tuple[Seller, bool]:
        seller = Seller.from_cache(sid) or Seller(id=sid)
        if not seller.needs_profile():
            return seller, True
        assert marketplace.page is not None
        marketplace.goto_url(f"https://www.facebook.com/marketplace/profile/{sid}/")
        profile = FacebookSellerProfilePage(
            marketplace.page, marketplace.translator, logger
        ).parse(sid)
        seller.update(profile)
        seller.profile_checked = True
        seller.checked_at = time.time()
        seller.to_cache()
        return seller, False
