"""Toolkits for the smaller section types: `[monitor]`, `[region.*]` and `[translation.*]`.

`[monitor]` holds global settings (a proxy), `[region.*]` named groups of cities that marketplaces
and items search with `search_region`, and `[translation.*]` the Facebook page labels in another
language, for users whose Facebook is not in English.
"""

from __future__ import annotations

import copy
import warnings
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

from ..config_toml import dump_config_toml
from ..normalize import NormalizeError, expand
from ..region import RegionConfig
from ..utils import MonitorConfig, TranslationConfig
from .marketplace import _plain
from .toolkits import (
    FieldGroup,
    FieldGuide,
    SectionDraft,
    Toolkit,
    location,
    unset_variable_notes,
)
from .ui import SetupUI

if TYPE_CHECKING:
    from .workspace import Workspace

# the Facebook page labels aimm looks for (see the translator(...) calls in facebook.py)
LABELS: Tuple[str, ...] = (
    "Collection of Marketplace items",
    "Browse Marketplace",
    "Condition",
    "Description",
    "Details",
    "Location is approximate",
    "About this vehicle",
    "Seller's description",
    "See more",
    "See less",
)


class _SmallToolkit(Toolkit):
    """Fields come from the guides; no field is a default for items."""

    def field_names(self: "_SmallToolkit") -> List[str]:
        return [g.name for g in self.guides]

    def group(self: "_SmallToolkit", name: str) -> FieldGroup:
        return FieldGroup.OWN

    def same_value(self: "_SmallToolkit", key: str, old: Any, new: Any) -> bool:
        return bool(old == new)

    def describe(self: "_SmallToolkit", draft: SectionDraft) -> str:
        section = {"request": draft.request} if draft.request else {}
        section.update(self.masked(draft.values))
        body: Dict[str, Any] = {draft.section_type: section}
        if draft.section_type != "monitor":
            body = {draft.section_type: {draft.name: section}}
        return f"```toml\n{dump_config_toml(body)}```"

    def _loads_with_others(
        self: "_SmallToolkit", ws: "Workspace", draft: SectionDraft
    ) -> List[str]:
        """The whole config, with this session's other drafts, must still load."""
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                expand(
                    self.apply(ws.config_with_drafts(exclude=draft.key), draft),
                    ws.system_cfg,
                    partial=True,
                )
        except NormalizeError as e:
            return [str(e)]
        return []

    def _names(self: "_SmallToolkit", ws: "Workspace") -> List[str]:
        names = list(ws.user_cfg.get(self.section_type, {}))
        return names + [n for t, n in ws.drafts if t == self.section_type and n not in names]

    def _built_in(self: "_SmallToolkit", ws: "Workspace") -> Dict[str, Any]:
        return dict(ws.system_cfg.get(self.section_type, {}))

    def companions(self: "_SmallToolkit", ws: "Workspace", name: str) -> List[Tuple[str, str]]:
        return [(self.section_type, "*")]

    async def choose_target(
        self: "_SmallToolkit", ui: SetupUI, ws: "Workspace", name: str | None
    ) -> str | None:
        """Show the user's sections and the built-in names; any section may change."""
        mine = ws.user_cfg.get(self.section_type, {})
        parts = [
            f"**[{self.section_type}.{n}]**\n\n"
            f"```toml\n{dump_config_toml({self.section_type: {n: self.masked(s)}})}```"
            for n, s in mine.items()
            if isinstance(s, dict)
        ]
        if not parts:
            parts = [f"You have no [{self.section_type}.*] section yet."]
        built_in = ", ".join(self._built_in(ws))
        if built_in:
            parts.append(f"Built in: {built_in}.")
        await ui.say("\n\n".join(parts), markdown=True)
        return name or "*"


# --- [monitor] -------------------------------------------------------------------------------
MONITOR_GUIDES: Tuple[FieldGuide, ...] = (
    FieldGuide(
        "proxy_server",
        "the proxy aimm's browser uses, from the user's proxy or VPN service",
        '`"http://proxy.example.com:8080"`, or a reference such as `"${PROXY_SERVER}"`',
        "no proxy",
        reference=True,
    ),
    FieldGuide(
        "proxy_bypass",
        "hosts that should not go through the proxy",
        'comma-separated, e.g. `"localhost,127.0.0.1"`',
        "none",
    ),
    FieldGuide(
        "proxy_username",
        "the proxy account's user name, if the proxy needs one",
        '`"${PROXY_USERNAME}"`',
        "none",
        secret=True,
    ),
    FieldGuide(
        "proxy_password",
        "the proxy account's password, if the proxy needs one",
        '`"${PROXY_PASSWORD}"`',
        "none",
        secret=True,
    ),
    FieldGuide(
        "check_updates",
        "only to stop aimm from checking PyPI once a day for a newer release (shown in the "
        "log and the web UI)",
        "`false`",
        "on",
    ),
    FieldGuide(
        "evaluation_history_days",
        "only to keep the web UI's Listings history (each evaluated listing and why it was "
        "notified, rejected or excluded) for other than 30 days",
        "a whole number of days, e.g. `14`",
        "30 days",
    ),
)


class MonitorToolkit(_SmallToolkit):
    section_type = "monitor"
    playbook = "monitor"
    config_class = MonitorConfig
    guides = MONITOR_GUIDES

    def context(self: "MonitorToolkit", ws: "Workspace") -> Dict[str, List[str]]:
        return {}

    def validate(self: "MonitorToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                MonitorConfig(name="monitor", **draft.values)
        except Exception as e:
            return [_plain(e)]
        return self._loads_with_others(ws, draft)

    def missing(self: "MonitorToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        account = draft.values.get("proxy_username") or draft.values.get("proxy_password")
        if account and not draft.values.get("proxy_server"):
            return ["proxy_server: a user name or password needs the proxy itself"]
        if bool(draft.values.get("proxy_username")) != bool(draft.values.get("proxy_password")):
            # aimm sends the account only when both are set
            return ["proxy_username and proxy_password: the proxy needs both, or neither"]
        return []

    def after_save(self: "MonitorToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        return unset_variable_notes(draft)

    def companions(self: "MonitorToolkit", ws: "Workspace", name: str) -> List[Tuple[str, str]]:
        return []

    async def choose_target(
        self: "MonitorToolkit", ui: SetupUI, ws: "Workspace", name: str | None
    ) -> str | None:
        current = ws.user_cfg.get("monitor")
        if current:
            body = dump_config_toml({"monitor": self.masked(current)})
            await ui.say(f"**[monitor]**\n\n```toml\n{body}```", markdown=True)
        else:
            await ui.say("You have no [monitor] section yet.")
        return "monitor"


# --- [region.*] ------------------------------------------------------------------------------
REGION_GUIDES: Tuple[FieldGuide, ...] = (
    FieldGuide(
        "search_city",
        "the cities of the region, as Facebook location codes from Marketplace URLs the user "
        "pastes (or codes already in the config or the built-in regions); never guessed",
        'list, e.g. `["houston", "dallas", "111979382146893"]`',
        "required for a new region",
    ),
    FieldGuide(
        "radius",
        "how far around each city to search, in the unit Facebook uses for the country",
        "one number for all cities, or a list as long as search_city",
        "500",
    ),
    FieldGuide(
        "city_name",
        "readable names of the cities, in the same order",
        'list as long as search_city, e.g. `["Houston, TX", "Dallas, TX"]`',
        "the codes, capitalized",
    ),
    FieldGuide(
        "currency",
        "the currency of listings in the region, for price limits",
        'one currency code for all cities, or a list, e.g. `"USD"`',
        "none",
    ),
    FieldGuide("full_name", "a readable name for the region", '`"Gulf Coast, Texas"`', "none"),
)


class RegionToolkit(_SmallToolkit):
    section_type = "region"
    playbook = "region"
    config_class = RegionConfig
    guides = REGION_GUIDES

    def summary(self: "RegionToolkit", ws: "Workspace", values: Dict[str, Any]) -> str | None:
        return location(values)

    def context(self: "RegionToolkit", ws: "Workspace") -> Dict[str, List[str]]:
        names = list(dict.fromkeys([*self._built_in(ws), *self._names(ws)]))
        return {"regions": names}

    def show_extra(self: "RegionToolkit", ws: "Workspace", draft: SectionDraft) -> Dict[str, Any]:
        built_in = self._built_in(ws)
        return {
            # your values are added to (and override) the built-in region of the same name
            "built_in": copy.deepcopy(built_in.get(draft.name)),
            "built_in_regions": {n: r.get("full_name", "") for n, r in built_in.items()},
        }

    def _effective(self: "RegionToolkit", ws: "Workspace", draft: SectionDraft) -> Dict[str, Any]:
        return {**self._built_in(ws).get(draft.name, {}), **draft.values}

    def validate(self: "RegionToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        if not draft.values:
            return []
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                RegionConfig(name=draft.name, **self._effective(ws, draft))
        except Exception as e:
            return [_plain(e)]
        guessed = ws.unconfirmed_cities(draft.values)
        if guessed:
            return guessed
        return self._loads_with_others(ws, draft)

    def missing(self: "RegionToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        if not self._effective(ws, draft).get("search_city"):
            return ["search_city: the cities of the region, from pasted Marketplace URLs"]
        return []


# --- [translation.*] -------------------------------------------------------------------------
TRANSLATION_GUIDES: Tuple[FieldGuide, ...] = (
    FieldGuide(
        "locale",
        "the language of the user's Facebook, in English",
        '`"German"`, `"Spanish"`',
        "required",
    ),
    FieldGuide("enabled", "only to turn this translation off", "`false`", "on"),
    *(
        FieldGuide(
            label,
            f'how Facebook shows "{label}" in this language, exactly as on the page',
            "text",
            "the English label (that part of the page is not found)",
        )
        for label in LABELS
    ),
)


class TranslationToolkit(_SmallToolkit):
    section_type = "translation"
    playbook = "translation"
    config_class = TranslationConfig
    guides = TRANSLATION_GUIDES

    def context(self: "TranslationToolkit", ws: "Workspace") -> Dict[str, List[str]]:
        return {"translations": list(dict.fromkeys([*self._built_in(ws), *self._names(ws)]))}

    def show_extra(
        self: "TranslationToolkit", ws: "Workspace", draft: SectionDraft
    ) -> Dict[str, Any]:
        using = [
            n
            for n, m in ws.user_cfg.get("marketplace", {}).items()
            if isinstance(m, dict) and m.get("language") == draft.name
        ]
        return {
            "built_in_examples": copy.deepcopy(self._built_in(ws)),
            "used_by_marketplaces": using,
        }

    def validate(self: "TranslationToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        if not draft.values:
            return []
        bad = [k for k, v in draft.values.items() if k != "enabled" and not isinstance(v, str)]
        if bad:
            return [f"`{bad[0]}` must be text."]
        if "enabled" in draft.values and not isinstance(draft.values["enabled"], bool):
            return ["`enabled` must be true or false."]
        if "locale" in draft.values:
            try:
                TranslationConfig(name=draft.name, locale=draft.values["locale"])
            except Exception as e:
                return [_plain(e)]
        return self._loads_with_others(ws, draft)

    def missing(self: "TranslationToolkit", ws: "Workspace", draft: SectionDraft) -> List[str]:
        if not draft.values.get("locale"):
            return ["locale: the language of the user's Facebook"]
        return []

    def describe(self: "TranslationToolkit", draft: SectionDraft) -> str:
        text = super().describe(draft)
        changed = [k for k in draft.unsaved_changes() if k in LABELS]
        if changed:
            text += (
                "\n\nCheck these labels against a Facebook listing in this language: they must "
                "match the page exactly."
            )
        return text
