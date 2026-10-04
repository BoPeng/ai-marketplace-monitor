import stat
from pathlib import Path
from typing import List

import pytest

from ai_marketplace_monitor.chat.commit import CommitOutcome, commit, render_section
from ai_marketplace_monitor.chat.playbooks import load_playbooks
from ai_marketplace_monitor.chat.sections import ChatContext, SectionProposal, SectionRef
from ai_marketplace_monitor.chat.ui import ScriptedChatUI

VALUES = {"api_key": "${UNITYSVC_API_KEY}", "model": "balanced"}

EXISTING = """\
# my config
[marketplace.facebook]
search_city = "houston"  # home

[ai.unitysvc]
request = "keep me"
api_key = "${OLD_KEY}"
model = "fast"

[item.bike]
search_phrases = "bike"
"""


def context(tmp_path: Path, files: List[Path]) -> ChatContext:
    return ChatContext(
        files=files,
        default_file=tmp_path / "home" / "config.toml",
        playbooks=load_playbooks(user_dir=tmp_path / "playbooks"),
        backup_dir=tmp_path / "backups",
    )


def proposal(target: Path, name: str = "unitysvc") -> SectionProposal:
    return SectionProposal(SectionRef("ai", name), dict(VALUES), "Use UnitySVC.", target)


def test_render_section() -> None:
    text = render_section(proposal(Path("x.toml")))
    assert text == '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\nmodel = "balanced"\n'


async def test_decline_writes_nothing(tmp_path: Path) -> None:
    ctx = context(tmp_path, [])
    ui = ScriptedChatUI(["no"])
    assert await commit(ui, proposal(ctx.default_file), ctx) is CommitOutcome.DECLINED
    assert not ctx.default_file.exists()
    assert "```toml" in ui.said()[0]


async def test_new_default_file_created(tmp_path: Path) -> None:
    ctx = context(tmp_path, [])
    outcome = await commit(ScriptedChatUI(["yes"]), proposal(ctx.default_file), ctx)
    assert outcome is CommitOutcome.WRITTEN
    assert ctx.default_file.read_text() == render_section(proposal(ctx.default_file))
    assert ctx.files == [ctx.default_file]
    assert not (tmp_path / "backups").exists()


async def test_update_preserves_file_and_request(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(EXISTING)
    ctx = context(tmp_path, [path])
    assert await commit(ScriptedChatUI(["yes"]), proposal(path), ctx) is CommitOutcome.WRITTEN
    text = path.read_text()
    assert text.startswith('# my config\n[marketplace.facebook]\nsearch_city = "houston"  # home')
    assert 'request = "keep me"\napi_key = "${UNITYSVC_API_KEY}"\nmodel = "balanced"' in text
    assert "[item.bike]" in text and "OLD_KEY" not in text
    [backup] = list((tmp_path / "backups").iterdir())
    assert backup.name.startswith("config.toml.")
    assert backup.read_text() == EXISTING
    assert stat.S_IMODE(backup.stat().st_mode) == 0o600


async def test_append_new_section_to_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(EXISTING)
    ctx = context(tmp_path, [path])
    outcome = await commit(ScriptedChatUI(["yes"]), proposal(path, "second"), ctx)
    assert outcome is CommitOutcome.WRITTEN
    text = path.read_text()
    assert "[ai.unitysvc]" in text and "[ai.second]" in text


async def test_override_by_later_file_detected(tmp_path: Path) -> None:
    first = tmp_path / "config.toml"
    first.write_text("")
    later = tmp_path / "later.toml"
    later.write_text('[ai.unitysvc]\nmodel = "fast"\n')
    ctx = context(tmp_path, [first, later])
    ui = ScriptedChatUI(["yes"])
    assert await commit(ui, proposal(first), ctx) is CommitOutcome.FAILED
    [error] = ui.said("error")
    assert str(later) in error and "model" in error


async def test_override_names_only_conflicting_keys(tmp_path: Path) -> None:
    first = tmp_path / "config.toml"
    first.write_text("")
    later = tmp_path / "later.toml"
    later.write_text('[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\nmodel = "fast"\n')
    ctx = context(tmp_path, [first, later])
    ui = ScriptedChatUI(["yes"])
    assert await commit(ui, proposal(first), ctx) is CommitOutcome.FAILED
    [error] = ui.said("error")
    assert "(model)" in error and "api_key" not in error


async def test_extra_key_in_earlier_file_detected(tmp_path: Path) -> None:
    earlier = tmp_path / "earlier.toml"
    earlier.write_text('[ai.unitysvc]\ntimeout = 5\n')
    target = tmp_path / "config.toml"
    target.write_text("")
    ctx = context(tmp_path, [earlier, target])
    ui = ScriptedChatUI(["yes"])
    assert await commit(ui, proposal(target), ctx) is CommitOutcome.FAILED
    [error] = ui.said("error")
    assert str(earlier) in error and "(timeout)" in error


async def test_unparsable_target_fails_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[ai.unitysvc\nbroken")
    ctx = context(tmp_path, [path])
    ui = ScriptedChatUI(["yes"])
    assert await commit(ui, proposal(path), ctx) is CommitOutcome.FAILED
    [error] = ui.said("error")
    assert str(path) in error
    assert path.read_text() == "[ai.unitysvc\nbroken"


async def test_request_replaced_when_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ai_marketplace_monitor.chat.commit.REQUEST_SUPPORTED", True)
    path = tmp_path / "config.toml"
    path.write_text(EXISTING)
    ctx = context(tmp_path, [path])
    assert await commit(ScriptedChatUI(["yes"]), proposal(path), ctx) is CommitOutcome.WRITTEN
    text = path.read_text()
    assert 'request = "Use UnitySVC."' in text and "keep me" not in text
