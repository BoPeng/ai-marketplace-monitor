"""The marketplace section builder: `aimm-configure marketplace` / `marketplace.NAME`."""

from __future__ import annotations

import copy
import re
import warnings
from collections import Counter
from typing import Any, Dict, List, Tuple

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
from ..normalize import NormalizeError, expand
from ..normalize.pushdown import bound_marketplace
from .sections import (
    BuilderContext,
    FieldGroup,
    FieldGuide,
    SectionBuilder,
    SectionDraft,
)
from .ui import Choice, SetupUI

_ABSENT = object()
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
        "only if the user says logging in to Facebook by hand takes long",
        "seconds, e.g. `120`",
        "a short wait",
    ),
    FieldGuide(
        "username",
        "only if the user wants aimm to log in to Facebook",
        '`"${FACEBOOK_USERNAME}"`',
        "read from FACEBOOK_USERNAME, or no login",
        secret=True,
    ),
    FieldGuide(
        "password",
        "only if the user wants aimm to log in to Facebook",
        '`"${FACEBOOK_PASSWORD}"`',
        "read from FACEBOOK_PASSWORD, or no login",
        secret=True,
    ),
    FieldGuide(
        "search_city",
        "the user's city as Facebook's URL slug (facebook.com/marketplace/<slug>/): usually the "
        "city name in lowercase without spaces",
        'list of slugs, e.g. `["houston"]`',
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
        f"list of integers, e.g. `[4]`.{_TWO_VALUES}",
        "aimm's default",
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


class MarketplaceBuilder(SectionBuilder):
    section_type = "marketplace"
    playbook = "marketplace"
    config_class = FacebookMarketplaceConfig
    guides = MARKETPLACE_GUIDES

    # --- reading the expanded config -------------------------------------------------------
    def items(
        self: "MarketplaceBuilder", cfg: Dict[str, Any], name: str
    ) -> Dict[str, Dict[str, Any]]:
        markets = cfg.get("marketplace", {})
        if name not in markets:
            return {}
        return {
            item_name: item
            for item_name, item in cfg.get("item", {}).items()
            if bound_marketplace(item, markets) == name
        }

    def shared_fields(self: "MarketplaceBuilder") -> List[str]:
        return [f for f in self.field_names() if self.group(f) is not FieldGroup.OWN]

    def location_fields(self: "MarketplaceBuilder") -> List[str]:
        return [f for f in self.field_names() if self.group(f) is FieldGroup.LOCATION]

    def view(self: "MarketplaceBuilder", ctx: BuilderContext, name: str) -> SectionDraft:
        market = ctx.expanded.get("marketplace", {}).get(name)
        values = {k: copy.deepcopy(v) for k, v in (market or {}).items() if k != "request"}
        varies: Dict[str, Dict[str, Any]] = {}
        items = self.items(ctx.expanded, name)
        if items:
            for key in self.shared_fields():
                found = {n: item.get(key, _ABSENT) for n, item in items.items()}
                distinct = {repr(v) for v in found.values()}
                if len(distinct) == 1:
                    value = next(iter(found.values()))
                    if value is not _ABSENT:
                        values[key] = copy.deepcopy(value)
                elif any(v is not _ABSENT for v in found.values()):
                    varies[key] = {n: (None if v is _ABSENT else v) for n, v in found.items()}
        # the expanded form spells out "all users" / "all AI services"; show those as unset
        defaults = {
            "notify": list(ctx.expanded.get("user", {})),
            "ai": list(ctx.expanded.get("ai", {})),
        }
        for key, everything in defaults.items():
            if values.get(key) == everything:
                values.pop(key)
        return SectionDraft(
            section_type="marketplace",
            name=name,
            is_new=market is None,
            request=(market or {}).get("request"),
            values=values,
            varies=varies,
            original=copy.deepcopy(values),
        )

    def context(
        self: "MarketplaceBuilder", ctx: BuilderContext, draft: SectionDraft
    ) -> Dict[str, Any]:
        def names(section: str, *cfgs: Dict[str, Any]) -> List[str]:
            return list(dict.fromkeys(n for cfg in cfgs for n in cfg.get(section, {})))

        return {
            "users": names("user", ctx.expanded),
            "ai_services": names("ai", ctx.expanded),
            "regions": names("region", ctx.system_cfg, ctx.expanded),
            "translations": names("translation", ctx.system_cfg, ctx.expanded),
            "other_marketplaces": [
                n for n in ctx.expanded.get("marketplace", {}) if n != draft.name
            ],
            "items_of_this_marketplace": list(self.items(ctx.expanded, draft.name)),
        }

    # --- checks ----------------------------------------------------------------------------
    def validate(
        self: "MarketplaceBuilder", ctx: BuilderContext, draft: SectionDraft
    ) -> List[str]:
        errors: List[str] = []
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                FacebookMarketplaceConfig(name=draft.name, **draft.values)
        except Exception as e:
            return [_plain(e)]
        context = self.context(ctx, draft)
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
                errors.append(f"`{key}` names {unknown}, which are not in context.{kind}.")
        if errors:
            return errors
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                expand(self.apply(ctx, draft), ctx.system_cfg, partial=True)
        except NormalizeError as e:
            errors.append(str(e))
        return errors

    def missing(self: "MarketplaceBuilder", ctx: BuilderContext, draft: SectionDraft) -> List[str]:
        location = ("search_city", "search_region")
        if any(draft.values.get(k) for k in location):
            return []
        items = self.items(ctx.expanded, draft.name)
        if items and all(any(item.get(k) for k in location) for item in items.values()):
            return []
        return ["location: set search_city (with radius) or search_region"]

    # --- showing and applying ----------------------------------------------------------------
    def describe(self: "MarketplaceBuilder", ctx: BuilderContext, draft: SectionDraft) -> str:
        section = {"request": draft.request} if draft.request else {}
        section.update(self.masked(draft.values))
        lines = [f"```toml\n{dump_config_toml({'marketplace': {draft.name: section}})}```"]
        changed = self._changed_items(ctx, draft)
        if changed:
            lines.append(
                "Items updated: "
                + "; ".join(f"{n} ({', '.join(keys)})" for n, keys in changed.items())
            )
        for key, per_item in draft.varies.items():
            if key not in draft.all_items:
                shown = ", ".join(f"{n}: {v}" for n, v in per_item.items())
                lines.append(f"`{key}` differs across items ({shown}).")
        return "\n\n".join(lines)

    def _changed_items(
        self: "MarketplaceBuilder", ctx: BuilderContext, draft: SectionDraft
    ) -> Dict[str, List[str]]:
        before = self.items(ctx.expanded, draft.name)
        after = self.items(self.apply(ctx, draft), draft.name)
        changed: Dict[str, List[str]] = {}
        for name, item in after.items():
            keys = [
                k
                for k in self.shared_fields()
                if item.get(k, _ABSENT) != before.get(name, {}).get(k, _ABSENT)
            ]
            if keys:
                changed[name] = keys
        return changed

    def apply(
        self: "MarketplaceBuilder", ctx: BuilderContext, draft: SectionDraft
    ) -> Dict[str, Any]:
        """The expanded config with this draft applied (the input is not changed)."""
        cfg = copy.deepcopy(ctx.expanded)
        markets = cfg.setdefault("marketplace", {})
        market = markets.setdefault(draft.name, {})
        own = [f for f in self.field_names() if self.group(f) is FieldGroup.OWN]
        if draft.request:
            market["request"] = draft.request
        for key in own:
            if key in draft.values:
                market[key] = copy.deepcopy(draft.values[key])
            else:
                market.pop(key, None)
        items = self.items(cfg, draft.name)
        if not items:
            for key in self.shared_fields():
                if key in draft.values:
                    market[key] = copy.deepcopy(draft.values[key])
                else:
                    market.pop(key, None)
            return cfg
        location = self.location_fields()
        groups = [[k] for k in self.shared_fields() if k not in location] + [location]
        for keys in groups:
            self._apply_group(draft, items, keys)
        for key in self.shared_fields():
            market.pop(key, None)
        return cfg

    def _apply_group(
        self: "MarketplaceBuilder",
        draft: SectionDraft,
        items: Dict[str, Dict[str, Any]],
        keys: List[str],
    ) -> None:
        """Set a field (or the location group) on the items that used the shared value."""

        def of(source: Dict[str, Any]) -> Tuple[Any, ...]:
            return tuple(repr(source.get(k, _ABSENT)) for k in keys)

        new, old = of(draft.values), of(draft.original)
        if new == old and not (draft.all_items & set(keys)):
            return
        if draft.all_items & set(keys):
            targets = list(items)
        elif any(k in draft.varies for k in keys):
            common, _ = Counter(of(item) for item in items.values()).most_common(1)[0]
            targets = [n for n, item in items.items() if of(item) == common]
        else:
            targets = [n for n, item in items.items() if of(item) == old]
        for name in targets:
            for key in keys:
                if key in draft.values:
                    items[name][key] = copy.deepcopy(draft.values[key])
                else:
                    items[name].pop(key, None)

    # --- choosing what to edit -----------------------------------------------------------------
    async def choose_target(
        self: "MarketplaceBuilder", ui: SetupUI, ctx: BuilderContext, name: str | None
    ) -> SectionDraft | None:
        shown = ctx.normalized.get("marketplace", {})
        if name is not None:
            if name in shown:
                await ui.say(self._summary(ctx, name), markdown=True)
            else:
                await ui.say(f"[marketplace.{name}] is new.")
            return self.view(ctx, name)
        if not shown:
            await ui.say("No marketplace is configured yet; let's set one up.")
            return self.view(ctx, await self._new_name(ui, ctx))
        await ui.say(
            "Existing marketplaces:\n\n" + "\n\n".join(self._summary(ctx, n) for n in shown),
            markdown=True,
        )
        options = [Choice(n, f"Update [marketplace.{n}]") for n in shown]
        options += [Choice("__new__", "Create a new marketplace"), Choice("__quit__", "Quit")]
        choice = await ui.choose(
            "Update one of these, or create a new marketplace?", options, default=next(iter(shown))
        )
        if choice == "__quit__":
            return None
        if choice == "__new__":
            return self.view(ctx, await self._new_name(ui, ctx))
        return self.view(ctx, choice)

    def _summary(self: "MarketplaceBuilder", ctx: BuilderContext, name: str) -> str:
        section = dict(ctx.normalized.get("marketplace", {}).get(name, {}))
        request = section.pop("request", None)
        count = len(self.items(ctx.expanded, name))
        head = f"**[marketplace.{name}]** ({count} item{'s' if count != 1 else ''})"
        if request:
            head += f"\n\nRequest: {request}"
        body = dump_config_toml({"marketplace": {name: self.masked(section)}}) if section else ""
        return head + (f"\n\n```toml\n{body}```" if body else "\n\n(no settings)")

    async def _new_name(self: "MarketplaceBuilder", ui: SetupUI, ctx: BuilderContext) -> str:
        taken = set(ctx.expanded.get("marketplace", {}))
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
