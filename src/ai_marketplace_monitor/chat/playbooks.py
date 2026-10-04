"""Playbooks: Markdown instructions that become part of a chat instance."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Sequence, Tuple

BUNDLED_DIR = Path(__file__).parent / "playbooks"
CHECKS = ("none", "probe", "test_message")


class PlaybookError(ValueError):
    """A playbook file is malformed."""


@dataclass
class Playbook:
    name: str  # file stem: "AGENT", "ai", ...
    section: str
    summary: str
    body: str
    check: str = "none"
    house_rules: List[Tuple[Path, str]] = field(default_factory=list)

    def text(self: "Playbook") -> str:
        """Render playbook with house rules appended."""
        parts = [self.body.strip()]
        for path, rules in self.house_rules:
            parts.append(f"## House rules (from {path})\n\n{rules}")
        return "\n\n".join(parts)


@dataclass
class PlaybookSet:
    """Collection of bundled and user playbooks."""

    base: Playbook
    sections: Dict[str, Playbook]


def split_frontmatter(text: str, source: Path) -> Tuple[Dict[str, object], str]:
    """Return (frontmatter, body); a file without frontmatter has an empty dict."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        raise PlaybookError(f"{source}: frontmatter has no closing '---'") from None
    meta: Dict[str, object] = {}
    for line in lines[1:end]:
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise PlaybookError(f"{source}: bad frontmatter line {line!r}")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = [v.strip() for v in value[1:-1].split(",") if v.strip()]
        else:
            meta[key.strip()] = value
    return meta, "\n".join(lines[end + 1 :]).strip() + "\n"


def parse_playbook(path: Path) -> Playbook:
    """Parse a playbook file and return a Playbook instance."""
    meta, body = split_frontmatter(path.read_text(encoding="utf-8"), path)
    for key in ("section", "summary"):
        if not isinstance(meta.get(key), str) or not meta[key]:
            raise PlaybookError(f"{path}: frontmatter needs '{key}'")
    section = str(meta["section"])
    check = str(meta.get("check", "none"))
    if check not in CHECKS:
        raise PlaybookError(f"{path}: check must be one of {CHECKS}")
    return Playbook(
        name=path.stem,
        section=section,
        summary=str(meta["summary"]),
        body=body,
        check=check,
    )


def _warn(logger: logging.Logger | None, message: str) -> None:
    """Log a warning message."""
    (logger or logging.getLogger(__name__)).warning(message)


def load_playbooks(
    user_dir: Path, bundled_dir: Path = BUNDLED_DIR, logger: logging.Logger | None = None
) -> PlaybookSet:
    """Load bundled playbooks, then append user playbooks of the same name as house rules."""
    bundled = {p.stem: parse_playbook(p) for p in sorted(bundled_dir.glob("*.md"))}
    base = bundled.pop("AGENT")
    if user_dir.is_dir():
        for path in sorted(user_dir.glob("*.md")):
            target = base if path.stem == "AGENT" else bundled.get(path.stem)
            if target is None:
                _warn(
                    logger,
                    f"Ignoring playbook {path}: no bundled playbook named {path.stem}",
                )
                continue
            try:
                meta, body = split_frontmatter(path.read_text(encoding="utf-8"), path)
            except (PlaybookError, OSError, UnicodeDecodeError) as e:
                _warn(logger, f"Ignoring playbook {path}: {e}")
                continue
            for key in set(meta) - {"summary"}:
                _warn(logger, f"Ignoring '{key}' in {path}: only 'summary' can be set")
            if isinstance(meta.get("summary"), str) and meta["summary"]:
                target.summary = str(meta["summary"])
            if body.strip():
                target.house_rules.append((path, body.strip()))
    return PlaybookSet(base=base, sections={p.section: p for p in bundled.values()})


def build_instructions(
    playbooks: PlaybookSet,
    focus: Sequence[str],
    config_text: str,
    details: Mapping[str, str] | None = None,
) -> str:
    """System instructions: base rules, every summary, focused playbooks + details, config."""
    summaries = "\n".join(
        f"- `{p.section}`: {p.summary}" for p in playbooks.sections.values()
    )
    parts = [playbooks.base.text(), f"# Section playbooks\n\n{summaries}"]
    for name in focus:
        if name in playbooks.sections:
            parts.append(playbooks.sections[name].text())
        if details and name in details:
            parts.append(details[name])
    parts.append(config_text)
    return "\n\n".join(parts)
