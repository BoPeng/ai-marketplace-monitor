"""The marketplace toolkit: what aimm knows about `[marketplace.*]` sections."""

from __future__ import annotations

import copy
import re
import warnings
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

from ..config_toml import dump_config_toml
from ..facebook import (
    Availability,
    Category,
    Condition,
    DateListed,
    DeliveryMethod,
    FacebookMarketplaceConfig,
    SortBy,
)
from ..marketplace import DEFAULT_RATING
from ..normalize import NormalizeError, expand
from ..normalize.pushdown import bound_marketplace
from .toolkits import FieldGuide, SectionDraft, Toolkit, location
from .ui import Choice, SetupUI

if TYPE_CHECKING:
    from .workspace import Workspace

_MARKUP = re.compile(r"\[/?[a-z ]+\]")
_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


def _values(enum: Any) -> str:
    return ", ".join(
        f"`{e.value!r}`" if isinstance(e.value, str) else f"`{e.value}`" for e in enum
    )


_TWO_VALUES = " A list of two values sets the first search and later searches separately."

MARKETPLACE_GUIDES: Tuple[FieldGuide, ...] = (
    FieldGuide(
        "enabled", "only when the user wants to pause this marketplace", "`false`", "enabled"
    ),
    FieldGuide("market_type", "always Facebook; do not set", '`"facebook"`', "facebook"),
    FieldGuide(
        "language",
        "only when listings are not in English; must be a translation name from the context",
        'a translation name, e.g. `"es"`',
        "English",
    ),
    FieldGuide(
        "login_wait_time",
        "deprecated and ignored (aimm waits until the login finishes); never set it, and "
        "remove it when the section has it",
        "do not set",
        "aimm waits until the login finishes",
    ),
    FieldGuide(
        "username",
        "required, since aimm searches only while logged in to Facebook; set it unless the "
        "user keeps it in the FACEBOOK_USERNAME environment variable",
        '`"${FACEBOOK_USERNAME}"`',
        "read from FACEBOOK_USERNAME; required",
        secret=True,
    ),
    FieldGuide(
        "password",
        "required, since aimm searches only while logged in to Facebook; set it unless the "
        "user keeps it in the FACEBOOK_PASSWORD environment variable",
        '`"${FACEBOOK_PASSWORD}"`',
        "read from FACEBOOK_PASSWORD; required",
        secret=True,
    ),
    FieldGuide(
        "search_city",
        "the code after /marketplace/ in a Facebook Marketplace URL the user pastes (a name or "
        "a numeric ID); never guessed from a city name",
        'list of codes, e.g. `["houston"]` or `["111979382146893"]`',
        "required unless search_region is set",
    ),
    FieldGuide(
        "city_name",
        "readable names of the cities in search_city, in the same order",
        'list, e.g. `["Houston"]`',
        "the slugs",
    ),
    FieldGuide(
        "radius",
        "how far around each city to search",
        "list of integers, one per city or one for all, e.g. `[40]`",
        "Facebook's default",
    ),
    FieldGuide(
        "currency",
        "only when the city uses a currency other than its default",
        'list of currency codes, one per city, e.g. `["USD"]`',
        "the city's currency",
    ),
    FieldGuide(
        "search_region",
        "when the user wants a whole country or area; replaces search_city, radius and currency",
        'list of region names from the context, e.g. `["usa"]`',
        "none",
    ),
    FieldGuide(
        "notify",
        "which users are notified; names from the context",
        'list of user names, e.g. `["me"]`',
        "all users",
    ),
    FieldGuide(
        "ai",
        "which AI services rate listings; names from the context",
        'list of AI section names, e.g. `["unitysvc"]`',
        "all AI services",
    ),
    FieldGuide(
        "exclude_sellers",
        "sellers the user never wants to see",
        "list of seller names",
        "none",
    ),
    FieldGuide(
        "seller_locations",
        "only sellers from these places",
        "list of place names",
        "any",
    ),
    FieldGuide(
        "availability",
        "whether to include listings that are out of stock",
        f"list of {_values(Availability)}.{_TWO_VALUES}",
        "all",
    ),
    FieldGuide(
        "condition",
        "which conditions the user accepts",
        f"list of {_values(Condition)}",
        "any condition",
    ),
    FieldGuide(
        "date_listed",
        "how recent listings must be, in days (0 = any time)",
        f"list of {_values(DateListed)}.{_TWO_VALUES}",
        "any time",
    ),
    FieldGuide(
        "delivery_method",
        "local pickup, shipping, or both",
        f"list of {_values(DeliveryMethod)}.{_TWO_VALUES}",
        "all",
    ),
    FieldGuide(
        "category",
        "only if everything searched here is in one Facebook category",
        f"one of {_values(Category)}",
        "all categories",
    ),
    FieldGuide("sort_by", "listing order", f"one of {_values(SortBy)}", "suggested"),
    FieldGuide(
        "min_price",
        "only if one minimum price applies to everything searched here (rare)",
        'string, e.g. `"100"` or `"100 USD"`',
        "none",
    ),
    FieldGuide(
        "max_price",
        "only if one maximum price applies to everything searched here (rare)",
        'string, e.g. `"500"` or `"500 USD"`',
        "none",
    ),
    FieldGuide(
        "search_interval",
        "how often to search",
        'duration, e.g. `"30m"`, `"1h"`, `"1h 30m"`, `"1d"`',
        "aimm's default interval",
    ),
    FieldGuide(
        "max_search_interval",
        "with search_interval, makes the interval random between the two",
        'duration, e.g. `"2h"`',
        "fixed interval",
    ),
    FieldGuide(
        "start_at",
        "fixed search times instead of an interval",
        'list of `"HH:MM"` (daily), `"*:MM"` (hourly) or `"*:*:SS"` (every minute)',
        "use search_interval",
    ),
    FieldGuide(
        "rating",
        "minimum AI rating (1-5) for a listing to be notified",
        f"list of integers, e.g. `[3]` for more notifications.{_TWO_VALUES}",
        f"{DEFAULT_RATING} (good matches)",
    ),
    FieldGuide(
        "prompt",
        "only when the user wants to change how the AI judges listings",
        "free text replacing aimm's evaluation instructions",
        "aimm's prompt",
    ),
    FieldGuide(
        "extra_prompt",
        "only when the user wants to add to how the AI judges listings",
        "free text appended to the evaluation instructions",
        "none",
    ),
    FieldGuide(
        "rating_prompt",
        "only when the user wants to change how the AI rates listings",
        "free text replacing aimm's rating instructions",
        "aimm's rating scale",
    ),
)


def _plain(e: BaseException) -> str:
    return _MARKUP.sub("", str(e))


def notify_level(rating: Any) -> str:
    """Which AI ratings are notified, and how to get more of them."""
    levels = [v for v in (rating if isinstance(rating, list) else [rating]) if isinstance(v, int)]
    first, later = (levels[0], levels[-1]) if levels else (DEFAULT_RATING, DEFAULT_RATING)
    if first != later:
        return f"notifies AI rating {first}+ on the first search, {later}+ after"
    more = f" (rating = {first - 1} for more notifications)" if first > 1 else ""
    return f"notifies AI rating {first}+{more}"


class MarketplaceToolkit(Toolkit):
    section_type = "marketplace"
    playbook = "marketplace"
    config_class = FacebookMarketplaceConfig
    guides = MARKETPLACE_GUIDES

    def summary(self: "MarketplaceToolkit", ws: "Workspace", values: Dict[str, Any]) -> str | None:
        loc = location(values)
        where = f"searches {loc}" if loc else "no search location"
        return f"{where}; {notify_level(values.get('rating'))}"

    # --- reading the user's config ---------------------------------------------------------
    def items(
        self: "MarketplaceToolkit", cfg: Dict[str, Any], name: str
    ) -> Dict[str, Dict[str, Any]]:
        """Items that search this marketplace (their own ``marketplace``, else the first one)."""
        markets = dict(cfg.get("marketplace", {}))
        markets.setdefault(name, {})
        return {
            item_name: item
            for item_name, item in cfg.get("item", {}).items()
            if bound_marketplace(item, markets) == name
        }

    def view(self: "MarketplaceToolkit", ws: "Workspace", name: str) -> SectionDraft:
        market = ws.user_cfg.get("marketplace", {}).get(name)
        values = {k: copy.deepcopy(v) for k, v in (market or {}).items() if k != "request"}
        return SectionDraft(
            section_type="marketplace",
            name=name,
            is_new=market is None,
            request=(market or {}).get("request"),
            values=values,
            original=copy.deepcopy(values),
            original_request=(market or {}).get("request"),
        )

    def context(self: "MarketplaceToolkit", ws: "Workspace") -> Dict[str, List[str]]:
        def names(section: str, *cfgs: Dict[str, Any]) -> List[str]:
            return list(dict.fromkeys(n for cfg in cfgs for n in cfg.get(section, {})))

        cfg = ws.config_with_drafts()  # sections drafted in this session count too
        return {
            "users": names("user", cfg),
            "ai_services": names("ai", cfg),
            "regions": names("region", ws.system_cfg, cfg),
            "translations": names("translation", ws.system_cfg, cfg),
        }

    # --- checks ----------------------------------------------------------------------------
    def validate(self: "MarketplaceToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        errors: List[str] = []
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                FacebookMarketplaceConfig(name=draft.name, **draft.values)
        except Exception as e:
            return [_plain(e)]
        if draft.values.get("city_name") != draft.original.get("city_name") and draft.values.get(
            "search_city"
        ) == draft.original.get("search_city"):
            return [
                (
                    "`city_name` may only change together with `search_city`; leave an existing "
                    "city as it is."
                )
            ]
        guessed = ws.unconfirmed_cities(draft.values)
        if guessed:
            return guessed
        context = self.context(ws)
        refs = {
            "notify": "users",
            "ai": "ai_services",
            "search_region": "regions",
            "language": "translations",
        }
        for key, kind in refs.items():
            value = draft.values.get(key)
            wanted = value if isinstance(value, list) else [value] if value else []
            unknown = [v for v in wanted if v not in context[kind]]
            if unknown:
                errors.append(f"`{key}` names {unknown}, which are not in can_reference.{kind}.")
        if errors:
            return errors
        try:
            # the whole config must still load (e.g. an item's cities against a new radius)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                expand(
                    self.apply(ws.config_with_drafts(exclude=draft.key), draft),
                    ws.system_cfg,
                    partial=True,
                )
        except NormalizeError as e:
            errors.append(str(e))
        return errors

    def missing(self: "MarketplaceToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        location = ("search_city", "search_region")
        if any(draft.values.get(k) for k in location):
            return []
        items = self.items(ws.user_cfg, draft.name)
        if items and all(any(item.get(k) for k in location) for item in items.values()):
            return []
        return ["location: set search_city (with radius) or search_region"]

    # --- showing ---------------------------------------------------------------------------
    def describe(self: "MarketplaceToolkit", draft: SectionDraft) -> str:
        section = {"request": draft.request} if draft.request else {}
        section.update(self.masked(draft.values))
        return f"```toml\n{dump_config_toml({'marketplace': {draft.name: section}})}```"

    # --- choosing what to edit (aimm configure marketplace) ----------------------------------
    async def choose_target(
        self: "MarketplaceToolkit", ui: SetupUI, ws: "Workspace", name: str | None
    ) -> str | None:
        markets = ws.user_cfg.get("marketplace", {})
        if name is not None:
            if name in markets:
                await ui.say(self._summary(ws, name), markdown=True)
            else:
                await ui.say(f"[marketplace.{name}] is new.")
            return name
        if not markets:
            await ui.say("No marketplace is configured yet; let's set one up.")
            return await self._new_name(ui, ws)
        await ui.say(
            "Existing marketplaces:\n\n" + "\n\n".join(self._summary(ws, n) for n in markets),
            markdown=True,
        )
        options = [Choice(n, f"Update [marketplace.{n}]") for n in markets]
        options += [Choice("__new__", "Create a new marketplace"), Choice("__quit__", "Quit")]
        choice = await ui.choose(
            "Update one of these, or create a new marketplace?",
            options,
            default=next(iter(markets)),
        )
        if choice == "__quit__":
            return None
        if choice == "__new__":
            return await self._new_name(ui, ws)
        return choice

    def _summary(self: "MarketplaceToolkit", ws: "Workspace", name: str) -> str:
        draft = self.view(ws, name)
        count = len(self.items(ws.user_cfg, name))
        head = f"**[marketplace.{name}]** ({count} item{'s' if count != 1 else ''})"
        if draft.request:
            head += f"\n\nRequest: {draft.request}"
        body = (
            dump_config_toml({"marketplace": {name: self.masked(draft.values)}})
            if draft.values
            else ""
        )
        return "\n\n".join([head, f"```toml\n{body}```" if body else "(no settings)"])

    async def _new_name(self: "MarketplaceToolkit", ui: SetupUI, ws: "Workspace") -> str:
        taken = set(ws.user_cfg.get("marketplace", {}))
        if "facebook" not in taken:
            return "facebook"
        suggestion = next(f"facebook_{i}" for i in range(2, 100) if f"facebook_{i}" not in taken)
        while True:
            name = (await ui.ask_text("Name for the new marketplace", suggestion)).strip()
            if _NAME.match(name) and name not in taken:
                return name
            await ui.say(
                "Use letters, digits, '_' or '-', and a name not already in use.", kind="warning"
            )
