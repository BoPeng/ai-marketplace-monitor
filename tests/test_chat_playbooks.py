import logging
from pathlib import Path

import pytest

from ai_marketplace_monitor.chat.playbooks import (
    BUNDLED_DIR,
    CHECKS,
    build_instructions,
    load_playbooks,
)


def test_bundled_playbooks_parse(tmp_path: Path) -> None:
    playbooks = load_playbooks(user_dir=tmp_path)
    assert playbooks.base.section == "base"
    assert "never ask for" in playbooks.base.body.lower()
    assert set(playbooks.sections) == {"ai"}
    for playbook in playbooks.sections.values():
        assert playbook.summary
        assert playbook.check in CHECKS


def test_user_playbook_appended_as_house_rules(tmp_path: Path) -> None:
    (tmp_path / "AGENT.md").write_text("Always answer in French.\n")
    (tmp_path / "ai.md").write_text("---\nsummary: My AI notes.\n---\nPrefer Ollama.\n")
    playbooks = load_playbooks(user_dir=tmp_path)
    assert "## House rules (from" in playbooks.base.text()
    assert "Always answer in French." in playbooks.base.text()
    assert playbooks.sections["ai"].summary == "My AI notes."
    assert playbooks.sections["ai"].text().endswith("Prefer Ollama.")


def test_orphan_and_malformed_user_playbooks_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "pets.md").write_text("Rules for a section that does not exist.\n")
    (tmp_path / "ai.md").write_text("---\nsummary: no closing fence\n")
    with caplog.at_level(logging.WARNING):
        playbooks = load_playbooks(user_dir=tmp_path, logger=logging.getLogger("test"))
    assert "pets.md" in caplog.text and "ai.md" in caplog.text
    assert playbooks.sections["ai"].house_rules == []


def test_missing_user_dir_is_fine(tmp_path: Path) -> None:
    assert load_playbooks(user_dir=tmp_path / "nope").sections["ai"].house_rules == []


def test_build_instructions(tmp_path: Path) -> None:
    playbooks = load_playbooks(user_dir=tmp_path)
    text = build_instructions(playbooks, ["ai"], "CONFIG-TEXT", {"ai": "FIELD-GUIDE"})
    assert text.startswith(playbooks.base.text())
    assert f"- `ai`: {playbooks.sections['ai'].summary}" in text
    body_at = text.index(playbooks.sections["ai"].body.strip())
    assert body_at < text.index("FIELD-GUIDE") < text.index("CONFIG-TEXT")
    assert text.endswith("CONFIG-TEXT")


def test_bundled_dir_is_inside_package() -> None:
    assert (BUNDLED_DIR / "AGENT.md").is_file()
