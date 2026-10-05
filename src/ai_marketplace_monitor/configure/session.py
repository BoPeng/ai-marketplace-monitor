"""A configure session: what lives across section builders (the AI, files, playbooks).

``aimm-configure marketplace`` opens a session and runs one builder; the ``aimm-configure``
router (later) opens one session and runs several builders in it. Each builder run re-reads
the config, since an earlier run in the same session may have written it.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, List, Set

from ..config import load_config_dicts
from ..normalize import NormalizeError, expand
from ..utils import amm_home
from .playbooks import PlaybookError, load_playbooks
from .sections import BuilderContext
from .ui import SetupUI

if TYPE_CHECKING:
    from ..ai import AIBackend
    from .sections import SectionBuilder


class ConfigLoadError(Exception):
    """The config could not be read for editing."""


@dataclass
class Session:
    files: List[Path]
    ai: "AIBackend"
    home: Path = field(default_factory=lambda: amm_home)
    # notes (e.g. unset environment variables) already shown in this session
    shown: Set[str] = field(default_factory=set)

    @property
    def backup_dir(self: "Session") -> Path:
        return self.home / "backups"

    async def context(self: "Session", ui: SetupUI, builder: "SectionBuilder") -> BuilderContext:
        """Read the config now and build the context for one builder run."""
        notes: List[str] = []
        try:
            system, user = load_config_dicts(self.files)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                expand(user, system, partial=True)  # the config must load before we edit it
            notes += [str(w.message) for w in caught]
            playbooks = load_playbooks(
                ["AGENT", builder.playbook], self.home / "playbooks", warn=notes.append
            )
        except (ValueError, OSError, NormalizeError, PlaybookError) as e:
            raise ConfigLoadError(f"Cannot read the configuration: {e}") from e
        for note in dict.fromkeys(notes):
            if note not in self.shown:
                self.shown.add(note)
                await ui.say(note, kind="warning")
        return BuilderContext(
            files=list(self.files),
            system_cfg=system,
            user_cfg=user,
            backup_dir=self.backup_dir,
            playbooks=playbooks,
            ai=self.ai,
        )
