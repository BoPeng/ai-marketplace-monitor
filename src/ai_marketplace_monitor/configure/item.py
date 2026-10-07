"""The item toolkit: what aimm knows about `[item.*]` sections (what to search for)."""

from __future__ import annotations

import copy
import warnings
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

from ..config_toml import dump_config_toml
from ..facebook import FacebookItemConfig
from ..normalize import NormalizeError, expand
from .marketplace import _NAME, MARKETPLACE_GUIDES, MarketplaceToolkit, _plain
from .toolkits import FieldGroup, FieldGuide, SectionDraft, Toolkit, listed, location
from .ui import Choice, SetupUI

if TYPE_CHECKING:
    from .workspace import Workspace

_LOCATION = ("search_city", "search_region")

_OWN_GUIDES: Tuple[FieldGuide, ...] = (
    FieldGuide(
        "search_phrases",
        "what the user would type in Facebook Marketplace's search box; a few short phrases "
        "for the same thing (brand, model, common names)",
        'list, e.g. `["gopro hero 12", "action camera"]`',
        "required",
    ),
    FieldGuide(
        "description",
        "what exactly the user wants, in plain words, for the AI that rates listings: model, "
        "condition, what to avoid. The most effective way to get good matches",
        "free text, a few sentences",
        "only the search phrases are used",
    ),
    FieldGuide(
        "keywords",
        "hard pre-filter: a listing is kept only if its title or description contains ANY of "
        "these (OR); only product names sellers always mention (brand, line, model), never "
        "features or specs; use sparingly (the AI judges better)",
        'list, e.g. `["gopro", "go pro"]`; case-insensitive substrings. Only inside one entry: '
        "uppercase `AND` / `OR` / `NOT` and parentheses, with multi-word terms quoted, e.g. "
        "`\"gopro AND ('hero 11' OR 'hero 12')\"`; an entry that does not parse is matched "
        "as literal text",
        "no filter",
    ),
    FieldGuide(
        "antikeywords",
        "hard pre-filter: listings whose title or description contains ANY of these (OR) are "
        "dropped, e.g. accessories or parts the user does not want",
        'list, e.g. `["case only", "for parts"]`; same logic syntax as keywords',
        "no filter",
    ),
    FieldGuide(
        "marketplace",
        "the marketplace section this item searches; set only if there are several",
        'a marketplace name from can_reference, e.g. `"facebook"`',
        "the first marketplace",
    ),
    FieldGuide("enabled", "only when the user wants to pause this item", "`false`", "enabled"),
)

# guidance for shared fields that are central to an item (others use the marketplace's text)
_ITEM_SPECIFIC: Dict[str, Tuple[str, str]] = {
    "min_price": ("the lowest price the user would consider for this item", 'e.g. `"50"`'),
    "max_price": ("the most the user would pay for this item", 'e.g. `"200"` or `"200 USD"`'),
    "extra_prompt": (
        (
            "extra requirements for judging listings that the other fields cannot express, in "
            "the user's words, e.g. 'skip listings that need repair; prefer original packaging'"
        ),
        "free text appended to the AI's evaluation instructions",
    ),
    "prompt": (
        "only if the user explicitly wants to replace how the AI evaluates listings",
        "free text replacing aimm's evaluation instructions",
    ),
    "rating_prompt": (
        "only if the user explicitly wants to replace the rating scale",
        "free text replacing aimm's rating instructions",
    ),
    "rating": (
        (
            "how good a match must be to notify (default 4): 5 for picky users, 3 to also see "
            "poor matches, 2 for anything plausible"
        ),
        "list of integers 1-5, e.g. `[4]`",
    ),
}


def _item_guides() -> Tuple[FieldGuide, ...]:
    shared = []
    for g in MARKETPLACE_GUIDES:
        if field_is_on_item(g.name):
            determine, fmt = _ITEM_SPECIFIC.get(
                g.name,
                (f"only if this item should differ from its marketplace: {g.determine}", g.format),
            )
            shared.append(
                FieldGuide(g.name, determine, fmt, "the marketplace's value", secret=g.secret)
            )
    return _OWN_GUIDES + tuple(shared)


def field_is_on_item(name: str) -> bool:
    return name in FacebookItemConfig.__dataclass_fields__ and name not in {
        "enabled",
        "name",
        "request",
    }


ITEM_GUIDES = _item_guides()


def _number(value: Any) -> bool:
    """Whether a price has no currency of its own."""
    try:
        float(str(value).replace(",", ""))
    except ValueError:
        return False
    return True


class ItemToolkit(Toolkit):
    section_type = "item"
    playbook = "item"
    config_class = FacebookItemConfig
    guides = ITEM_GUIDES
    _market = MarketplaceToolkit()

    def summary(self: "ItemToolkit", ws: "Workspace", values: Dict[str, Any]) -> str | None:
        phrases = ", ".join(listed(values.get("search_phrases"))) or "no search phrases"
        prices = [  # "$200", but "200 EUR" as written
            f"{k.split('_')[0]} {'$' if _number(values[k]) else ''}{values[k]}"
            for k in ("min_price", "max_price")
            if values.get(k)
        ]
        loc = location(values)
        return "; ".join([phrases, *prices, *([f"searches {loc}"] if loc else [])])

    # --- the item's marketplace -------------------------------------------------------------
    def bound_marketplace(self: "ItemToolkit", ws: "Workspace", values: Dict[str, Any]) -> str:
        """The marketplace an item searches: its own setting, else the first one."""
        if isinstance(values.get("marketplace"), str) and values["marketplace"]:
            return values["marketplace"]
        names = list(ws.user_cfg.get("marketplace", {}))
        names += [n for t, n in ws.drafts if t == "marketplace" and n not in names]
        return names[0] if names else "facebook"

    def _shared(self: "ItemToolkit") -> List[str]:
        return [f for f in self.field_names() if self.group(f) is not FieldGroup.OWN]

    def show_extra(self: "ItemToolkit", ws: "Workspace", draft: SectionDraft) -> Dict[str, Any]:
        name = self.bound_marketplace(ws, draft.values)
        market = ws.section("marketplace", name)
        inherited = None
        if market is not None:
            shared = set(self._shared())
            inherited = self._market.masked({k: v for k, v in market.items() if k in shared})
        return {
            "marketplace": name,
            "marketplace_exists": market is not None,
            "inherited_from_marketplace": inherited,
        }

    def companions(self: "ItemToolkit", ws: "Workspace", name: str) -> List[Tuple[str, str]]:
        return [("marketplace", self.bound_marketplace(ws, self.view(ws, name).values))]

    # --- reading and checking ----------------------------------------------------------------
    def view(self: "ItemToolkit", ws: "Workspace", name: str) -> SectionDraft:
        item = ws.user_cfg.get("item", {}).get(name)
        values = {k: copy.deepcopy(v) for k, v in (item or {}).items() if k != "request"}
        return SectionDraft(
            section_type="item",
            name=name,
            is_new=item is None,
            request=(item or {}).get("request"),
            values=values,
            original=copy.deepcopy(values),
            original_request=(item or {}).get("request"),
        )

    def context(self: "ItemToolkit", ws: "Workspace") -> Dict[str, List[str]]:
        names = self._market.context(ws)
        markets = list(ws.user_cfg.get("marketplace", {}))
        markets += [n for t, n in ws.drafts if t == "marketplace" and n not in markets]
        return {**names, "marketplaces": markets}

    def validate(self: "ItemToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        values = dict(draft.values)
        # field formats can be checked before the search phrases are known
        placeholder = not values.get("search_phrases")
        if placeholder:
            values["search_phrases"] = ["_"]
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                FacebookItemConfig(name=draft.name, **values)
        except Exception as e:
            return [_plain(e)]
        guessed = ws.unconfirmed_cities(draft.values)
        if guessed:
            return guessed
        context = self.context(ws)
        refs = {
            "notify": "users",
            "ai": "ai_services",
            "search_region": "regions",
            "marketplace": "marketplaces",
        }
        errors = []
        for key, kind in refs.items():
            value = draft.values.get(key)
            wanted = value if isinstance(value, list) else [value] if value else []
            unknown = [v for v in wanted if v not in context[kind]]
            if unknown:
                errors.append(f"`{key}` names {unknown}, which are not in can_reference.{kind}.")
        if errors or placeholder:
            return errors
        cfg = ws.config_with_drafts(exclude=draft.key)
        if self.bound_marketplace(ws, draft.values) not in cfg.get("marketplace", {}):
            return errors  # `missing` asks for the marketplace first
        try:
            # the whole config, with this session's other drafts, must still load
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                expand(self.apply(cfg, draft), ws.system_cfg, partial=True)
        except NormalizeError as e:
            errors.append(str(e))
        return errors

    def missing(self: "ItemToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        missing = []
        if not draft.values.get("search_phrases"):
            missing.append("search_phrases: what to search for")
        bound = self.bound_marketplace(ws, draft.values)
        market = ws.section("marketplace", bound)
        if market is None:
            missing.append(
                f"marketplace: create [marketplace.{bound}] with a location first "
                "(section_update with section_type='marketplace')"
            )
        elif not any(draft.values.get(k) for k in _LOCATION) and not any(
            market.get(k) for k in _LOCATION
        ):
            missing.append(
                "location: set search_city (with radius) or search_region on the item or its "
                "marketplace"
            )
        return missing

    def describe(self: "ItemToolkit", draft: SectionDraft) -> str:
        section = {"request": draft.request} if draft.request else {}
        section.update(self.masked(draft.values))
        return f"```toml\n{dump_config_toml({'item': {draft.name: section}})}```"

    # --- choosing what to edit (aimm configure item) ------------------------------------------
    async def choose_target(
        self: "ItemToolkit", ui: SetupUI, ws: "Workspace", name: str | None
    ) -> str | None:
        items = ws.user_cfg.get("item", {})
        if name is not None:
            await ui.say(
                self._summary(ws, name) if name in items else f"[item.{name}] is new.",
                markdown=name in items,
            )
            return name
        if not items:
            await ui.say("No item is configured yet; let's add one.")
            return await self._new_name(ui, ws)
        await ui.say(
            "Existing items:\n\n" + "\n\n".join(self._summary(ws, n) for n in items),
            markdown=True,
        )
        options = [Choice(n, f"Update [item.{n}]") for n in items]
        options += [Choice("__new__", "Add a new item"), Choice("__quit__", "Quit")]
        choice = await ui.choose(
            "Update one of these, or add a new item?", options, default="__new__"
        )
        if choice == "__quit__":
            return None
        if choice == "__new__":
            return await self._new_name(ui, ws)
        return choice

    def _summary(self: "ItemToolkit", ws: "Workspace", name: str) -> str:
        draft = self.view(ws, name)
        head = f"**[item.{name}]**"
        if draft.request:
            head += f"\n\nRequest: {draft.request}"
        body = dump_config_toml({"item": {name: draft.values}}) if draft.values else ""
        return "\n\n".join([head, f"```toml\n{body}```" if body else "(no settings)"])

    async def _new_name(self: "ItemToolkit", ui: SetupUI, ws: "Workspace") -> str:
        taken = set(ws.user_cfg.get("item", {}))
        suggestion = next(f"item_{i}" for i in range(1, 1000) if f"item_{i}" not in taken)
        while True:
            name = (
                await ui.ask_text("Name for the new item (a short word, e.g. gopro)", suggestion)
            ).strip()
            if _NAME.match(name) and name not in taken:
                return name
            await ui.say(
                "Use letters, digits, '_' or '-', and a name not already in use.", kind="warning"
            )
