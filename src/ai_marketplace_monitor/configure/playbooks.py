"""Playbooks: markdown task descriptions that tell the LLM how to configure a section.

A section playbook describes a task, never a script: its ``## Goal``, how to achieve each of
its ``## Subtasks``, and the rules for ``## Completion`` (``## Rules`` is optional).
``AGENT.md`` (``section: base``) holds the method and reply format shared by every section.
Users may add house rules in ``~/.ai-marketplace-monitor/playbooks/<name>.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Tuple

BUNDLED_DIR = Path(__file__).parent / "playbooks"
REQUIRED_HEADINGS = ("Goal", "Subtasks", "Completion")
_HEADING = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)


class PlaybookError(ValueError):
    """A playbook is malformed."""


@dataclass
class Playbook:
    name: str
    section: str
    summary: str
    body: str
    house_rules: List[Tuple[Path, str]] = field(default_factory=list)

    def headings(self: "Playbook") -> List[str]:
        return _HEADING.findall(self.body)

    def text(self: "Playbook") -> str:
        parts = [self.body.strip()]
        parts += [
            f"## House rules (from {path})\n\n{rules.strip()}" for path, rules in self.house_rules
        ]
        return "\n\n".join(parts) + "\n"


def split_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """``key: value`` lines between leading ``---`` lines, and the remaining body."""
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta: Dict[str, str] = {}
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return meta, "\n".join(lines[index + 1 :]).lstrip("\n")
        key, sep, value = line.partition(":")
        if not sep or not key.strip():
            raise PlaybookError(f"Invalid frontmatter line: {line!r}")
        meta[key.strip()] = value.strip()
    raise PlaybookError("Frontmatter is not closed with ---")


def parse_playbook(name: str, text: str) -> Playbook:
    meta, body = split_frontmatter(text)
    for key in ("section", "summary"):
        if not meta.get(key):
            raise PlaybookError(f"Playbook {name} needs a '{key}' in its frontmatter")
    playbook = Playbook(name=name, section=meta["section"], summary=meta["summary"], body=body)
    if playbook.section != "base":
        missing = [h for h in REQUIRED_HEADINGS if h not in playbook.headings()]
        if missing:
            raise PlaybookError(
                f"Playbook {name} needs the headings {', '.join('## ' + h for h in missing)}"
            )
    return playbook


def load_playbook(
    name: str, user_dir: Path | None = None, bundled_dir: Path = BUNDLED_DIR
) -> Playbook:
    """The bundled playbook ``<name>.md`` with the user's house rules appended."""
    path = bundled_dir / f"{name}.md"
    playbook = parse_playbook(name, path.read_text(encoding="utf-8"))
    user_path = user_dir / f"{name}.md" if user_dir else None
    if user_path is not None and user_path.is_file():
        meta, rules = split_frontmatter(user_path.read_text(encoding="utf-8"))
        # house rules may refine the summary, but never replace or remove bundled rules
        playbook.summary = meta.get("summary") or playbook.summary
        if rules.strip():
            playbook.house_rules.append((user_path, rules))
    return playbook


def load_playbooks(
    names: Iterable[str],
    user_dir: Path | None = None,
    bundled_dir: Path = BUNDLED_DIR,
    warn: Callable[[str], None] | None = None,
) -> Dict[str, Playbook]:
    names = list(names)
    playbooks = {name: load_playbook(name, user_dir, bundled_dir) for name in names}
    if warn is not None and user_dir is not None and user_dir.is_dir():
        for path in sorted(user_dir.glob("*.md")):
            if not (bundled_dir / path.name).is_file():
                warn(f"Ignoring playbook {path}: there is no bundled playbook {path.name}.")
    return playbooks
