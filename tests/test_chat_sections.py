from pathlib import Path

import pytest

from ai_marketplace_monitor.chat.playbooks import load_playbooks
from ai_marketplace_monitor.chat.sections import (
    ChatContext,
    FieldGuide,
    SectionBuilder,
    SectionRef,
)
from ai_marketplace_monitor.chat.ui import ScriptedChatUI


class DemoBuilder(SectionBuilder):
    section_type = "ai"
    playbook = "ai"
    fields = (
        FieldGuide("model", "The model the user asked for.", ask="Which model?", inherit=False),
        FieldGuide("timeout", "Keep the default unless the user asks."),
    )


def context(tmp_path: Path) -> ChatContext:
    return ChatContext(
        files=[],
        default_file=tmp_path / "config.toml",
        playbooks=load_playbooks(user_dir=tmp_path / "playbooks"),
        backup_dir=tmp_path / "backups",
    )


def test_section_ref_parse() -> None:
    assert SectionRef.parse("ai") == SectionRef("ai", None)
    assert SectionRef.parse("ai.unitysvc") == SectionRef("ai", "unitysvc")
    assert SectionRef("ai", "unitysvc").label() == "ai.unitysvc"


def test_guide_text() -> None:
    text = DemoBuilder().guide_text()
    assert text.startswith("# Field guide for [ai.*] sections")
    assert "- `model`: The model the user asked for. Ask: Which model?" in text
    assert "- `timeout`: Keep the default unless the user asks. (shared: copied" in text


def test_instructions_combine_playbook_and_guide(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    builder = DemoBuilder()
    text = builder.instructions(ctx)
    assert text.startswith(ctx.playbooks.sections["ai"].text())
    assert text.endswith(builder.guide_text())


def test_template_values_keep_only_inherited_fields() -> None:
    template = {"model": "fast", "timeout": 30, "request": "theirs", "unknown": 1}
    assert DemoBuilder().template_values(template) == {"timeout": 30}


async def test_generic_interpret_and_converse_not_available_yet(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    with pytest.raises(NotImplementedError):
        DemoBuilder().interpret({}, "use a fast model", ctx)
    with pytest.raises(NotImplementedError):
        await DemoBuilder().converse(ScriptedChatUI([]), SectionRef("ai"), ctx)
