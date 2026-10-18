"""The workspace of a configure session: config files, the config as on disk, and drafts.

Drafts are sections being edited; they live only here until the ``save`` tool writes them.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple

from ..config import load_config_dicts
from ..normalize import NormalizeError, expand
from .playbooks import Playbook, PlaybookError, load_playbooks
from .toolkits import SectionDraft, Toolkit
from .ui import SetupUI

SectionKey = Tuple[str, str]

# the location code in a Marketplace URL: facebook.com/marketplace/<code>/search?...
_URL_CODE = re.compile(r"facebook\.com/marketplace/([A-Za-z0-9_-]+)", re.IGNORECASE)
_NOT_A_LOCATION = {
    "search",
    "category",
    "item",
    "you",
    "create",
    "inbox",
    "saved",
    "notifications",
}


_ZIP = re.compile(r"\b[0-9]{5}\b")


def _location_values(value: Any, market_type: str) -> Set[str]:
    """The values a section of this marketplace type takes from a search_city value."""
    values = value if isinstance(value, list) else [value]
    out = set()
    for v in values:
        if isinstance(v, dict):
            v = next((x for k, x in v.items() if str(k).lower() == market_type), None)
        if v not in (None, ""):
            out.add(str(v).strip())
    return out


def _codes(value: Any) -> Set[str]:
    """The Facebook location codes of a search_city value (a table's facebook entry)."""
    values = value if isinstance(value, list) else [value]
    codes = set()
    for v in values:
        if isinstance(v, dict):
            v = next((x for k, x in v.items() if str(k).lower() == "facebook"), None)
        if v:
            codes.add(str(v))
    return codes


class ConfigLoadError(Exception):
    """The config could not be read for editing."""


@dataclass
class Workspace:
    ui: SetupUI
    files: List[Path]
    home: Path
    toolkits: Dict[str, Toolkit]  # by section type: what this command can configure
    system_cfg: Dict[str, Any] = field(default_factory=dict)
    user_cfg: Dict[str, Any] = field(default_factory=dict)  # merged user files, as written
    playbooks: Dict[str, Playbook] = field(default_factory=dict)
    drafts: Dict[SectionKey, SectionDraft] = field(default_factory=dict)
    shown: Set[str] = field(default_factory=set)  # notes already shown to the user
    user_said: List[str] = field(default_factory=list)  # the user's messages in this session
    # location codes Facebook gave for a place the user named (the find_city tool)
    found_city_codes: Set[str] = field(default_factory=set)
    ai_in_use: str | None = None  # the [ai.*] section this session runs on

    @property
    def backup_dir(self: "Workspace") -> Path:
        return self.home / "backups"

    async def load(self: "Workspace", extra_playbooks: List[str] = ()) -> None:  # type: ignore[assignment]
        """(Re)read the config and playbooks; notes such as unset variables are shown once."""
        notes: List[str] = []
        try:
            system, user = load_config_dicts(self.files)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                expand(user, system, partial=True)  # the config must load before we edit it
            notes += [str(w.message) for w in caught]
            names = ["AGENT", *extra_playbooks, *(t.playbook for t in self.toolkits.values())]
            self.playbooks = load_playbooks(
                dict.fromkeys(names), self.home / "playbooks", warn=notes.append
            )
        except (ValueError, OSError, NormalizeError, PlaybookError) as e:
            raise ConfigLoadError(f"Cannot read the configuration: {e}") from e
        self.system_cfg, self.user_cfg = system, user
        for note in dict.fromkeys(notes):
            if note not in self.shown:
                self.shown.add(note)
                await self.ui.say(note, kind="warning")

    def draft(self: "Workspace", section_type: str, name: str) -> SectionDraft:
        """The draft of a section, started from the config on first use."""
        key = (section_type, name)
        if key not in self.drafts:
            self.drafts[key] = self.toolkits[section_type].view(self, name)
        return self.drafts[key]

    def config_with_drafts(self: "Workspace", exclude: SectionKey | None = None) -> Dict[str, Any]:
        """The user config with this session's drafts applied (except ``exclude``).

        Drafts that are not ready (``Toolkit.can_apply``; a new item without search phrases,
        say) are left out: they are not saved as they are, so they must not make other sections
        fail validation.
        """
        cfg = self.user_cfg
        for key, draft in self.drafts.items():
            toolkit = self.toolkits[draft.section_type]
            if key != exclude and toolkit.can_apply(self, draft):
                cfg = toolkit.apply(cfg, draft)
        return cfg

    def known_city_codes(self: "Workspace") -> Set[str]:
        """Location codes the user gave: in their config, or in Marketplace URLs they pasted.

        A `search_city` code cannot be derived from a place name, so any other code is a guess.
        """
        codes: Set[str] = set()
        for cfg in (self.user_cfg, self.system_cfg):  # system: the built-in regions
            for section_type in ("marketplace", "item", "region"):
                for section in cfg.get(section_type, {}).values():
                    if isinstance(section, dict):
                        codes |= _codes(section.get("search_city"))
        for text in self.user_said:
            codes |= {
                m.group(1) for m in _URL_CODE.finditer(text) if m.group(1) not in _NOT_A_LOCATION
            }
        return codes | self.found_city_codes

    def known_locations(self: "Workspace", market_type: str) -> Set[str]:
        """Location values of a marketplace type that the user gave or aimm looked up.

        Facebook: its codes (known_city_codes). Other marketplaces: values the user typed, values in the
        config, and the coordinates find_city returned.
        """
        if market_type == "facebook":
            return self.known_city_codes()
        known: Set[str] = set(self.found_city_codes)
        for section_type in ("marketplace", "item", "region"):
            for section in self.user_cfg.get(section_type, {}).values():
                if isinstance(section, dict):
                    known |= _location_values(section.get("search_city"), market_type)
        for text in self.user_said:
            known |= set(_ZIP.findall(text))
        return known

    def unconfirmed_cities(
        self: "Workspace", values: Dict[str, Any], market_types: Iterable[str] = ("facebook",)
    ) -> List[str]:
        """Errors for `search_city` values the user did not give, per marketplace type."""
        errors = []
        for market_type in dict.fromkeys(market_types):
            wanted = _location_values(values.get("search_city"), market_type)
            guessed = sorted(wanted - self.known_locations(market_type))
            if not guessed:
                continue
            if market_type == "facebook":
                errors.append(
                    f"`search_city` {guessed} is not from find_city or a Facebook Marketplace URL "
                    "the user pasted. Never guess a location code: look the place up with "
                    "find_city, or ask the user to open Facebook Marketplace, set the location "
                    "and distance, search for anything, and paste the URL of the results page."
                )
            else:
                errors.append(
                    f"`search_city` {guessed} for {market_type} is not a ZIP code the user gave "
                    "nor coordinates from find_city. Ask for the ZIP code, or look the place up "
                    f"with find_city and use its `{market_type}` value."
                )
        return errors

    def section(self: "Workspace", section_type: str, name: str) -> Dict[str, Any] | None:
        """A section as drafted in this session, else as saved (None if neither)."""
        key = (section_type, name)
        if key in self.drafts:
            draft = self.drafts[key]
            if draft.is_new and not draft.values:
                return None
            return dict(draft.values)
        section = self.user_cfg.get(section_type, {}).get(name)
        return dict(section) if isinstance(section, dict) else None

    def pending(self: "Workspace") -> List[SectionDraft]:
        """Drafts with changes that are not saved yet (a new section once it has values)."""
        return [d for d in self.drafts.values() if d.has_changes()]
