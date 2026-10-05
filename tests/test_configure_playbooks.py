from pathlib import Path
from typing import List

import pytest

from ai_marketplace_monitor.configure.playbooks import (
    BUNDLED_DIR,
    PlaybookError,
    load_playbook,
    load_playbooks,
    parse_playbook,
)

SECTION = """---
section: demo
summary: A demo section.
---
## Goal
Do it.

## Subtasks
### One
First.

## Completion
When done.
"""


def write(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_parse_section_playbook() -> None:
    playbook = parse_playbook("demo", SECTION)
    assert (playbook.section, playbook.summary) == ("demo", "A demo section.")
    assert playbook.headings() == ["Goal", "Subtasks", "Completion"]
    assert playbook.text().startswith("## Goal")


@pytest.mark.parametrize(
    "text, error",
    [
        ("## Goal\n", "section"),
        ("---\nsection: demo\n---\n## Goal\n", "summary"),
        ("---\nsection: demo\nsummary: s\n---\n## Goal\n## Subtasks\n", "## Completion"),
        ("---\nsection: demo\nsummary s\n---\n", "Invalid frontmatter"),
        ("---\nsection: demo\n", "not closed"),
    ],
)
def test_malformed_playbooks(text: str, error: str) -> None:
    with pytest.raises(PlaybookError, match=error):
        parse_playbook("demo", text)


def test_base_playbook_needs_no_task_headings() -> None:
    assert parse_playbook("AGENT", "---\nsection: base\nsummary: s\n---\nrules\n").body == "rules"


def test_house_rules_are_appended_and_may_override_summary(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    write(bundled, "demo", SECTION)
    user_path = write(
        tmp_path / "user", "demo", "---\nsummary: Mine.\n---\nAlways search Austin.\n"
    )

    playbook = load_playbook("demo", tmp_path / "user", bundled)
    assert playbook.summary == "Mine."
    assert playbook.headings()[:3] == ["Goal", "Subtasks", "Completion"]
    assert f"## House rules (from {user_path})\n\nAlways search Austin." in playbook.text()


def test_unknown_user_playbooks_are_ignored_with_a_warning(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    write(bundled, "demo", SECTION)
    write(tmp_path / "user", "other", "anything")
    warnings: List[str] = []

    playbooks = load_playbooks(["demo"], tmp_path / "user", bundled, warn=warnings.append)
    assert list(playbooks) == ["demo"]
    assert len(warnings) == 1 and "other.md" in warnings[0]


def test_bundled_playbooks_load() -> None:
    playbooks = load_playbooks(["AGENT", "marketplace"])
    assert playbooks["AGENT"].section == "base"
    assert playbooks["marketplace"].section == "marketplace"
    assert (BUNDLED_DIR / "marketplace.md").is_file()
