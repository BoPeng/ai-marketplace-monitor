"""The workspace of a configure session: config files, the config as on disk, and drafts.

Drafts are sections being edited; they live only here until the ``save`` tool writes them.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

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


def _codes(value: Any) -> Set[str]:
    values = value if isinstance(value, list) else [value]
    return {str(v) for v in values if v}


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
        for section_type in ("marketplace", "item"):
            for section in self.user_cfg.get(section_type, {}).values():
                if isinstance(section, dict):
                    codes |= _codes(section.get("search_city"))
        for text in self.user_said:
            codes |= {
                m.group(1) for m in _URL_CODE.finditer(text) if m.group(1) not in _NOT_A_LOCATION
            }
        return codes

    def unconfirmed_cities(self: "Workspace", values: Dict[str, Any]) -> List[str]:
        """An error if `search_city` has a code the user did not give (see known_city_codes)."""
        guessed = sorted(_codes(values.get("search_city")) - self.known_city_codes())
        if not guessed:
            return []
        error = (
            f"`search_city` {guessed} is not from a Facebook Marketplace URL the user pasted. "
            "Never guess a location code: ask the user to open Facebook Marketplace, set the "
            "location and distance, search for anything, and paste the URL of the results page."
        )
        return [error]

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
