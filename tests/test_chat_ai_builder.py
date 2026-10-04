from dataclasses import fields
from pathlib import Path

import pytest

from ai_marketplace_monitor.ai import AIConfig
from ai_marketplace_monitor.chat.builders import BUILDERS
from ai_marketplace_monitor.chat.builders import ai as ai_module
from ai_marketplace_monitor.chat.builders.ai import ScriptedAIBuilder
from ai_marketplace_monitor.chat.playbooks import load_playbooks
from ai_marketplace_monitor.chat.probe import ProbeResult
from ai_marketplace_monitor.chat.sections import ChatContext, SectionProposal, SectionRef
from ai_marketplace_monitor.chat.ui import ScriptedChatUI


def context(tmp_path: Path, text: str | None = None) -> ChatContext:
    files = []
    if text is not None:
        path = tmp_path / "config.toml"
        path.write_text(text)
        files.append(path)
    return ChatContext(
        files=files,
        default_file=tmp_path / "home" / "config.toml",
        playbooks=load_playbooks(user_dir=tmp_path / "playbooks"),
        backup_dir=tmp_path / "backups",
    )


async def converse(
    answers: list[str], ctx: ChatContext, ref: SectionRef | None = None
) -> SectionProposal | None:
    return await ScriptedAIBuilder().converse(ScriptedChatUI(answers), ref or SectionRef("ai"), ctx)


def test_registry_and_builder_attributes() -> None:
    builder = BUILDERS["ai"]
    assert isinstance(builder, ScriptedAIBuilder)
    assert (builder.section_type, builder.playbook, builder.uses_ai) == ("ai", "ai", False)


def test_field_guides_cover_every_ai_field() -> None:
    guided = {g.name for g in ScriptedAIBuilder.fields}
    assert {f.name for f in fields(AIConfig)} - {"name"} <= guided
    inherited = {g.name for g in ScriptedAIBuilder.fields if g.inherit}
    assert inherited == {"max_retries", "timeout"}


async def test_unitysvc_new_section(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    proposal = await converse(["unitysvc", "balanced"], ctx)
    assert proposal is not None
    assert proposal.ref == SectionRef("ai", "unitysvc")
    assert proposal.values == {"api_key": "${UNITYSVC_API_KEY}", "model": "balanced"}
    assert proposal.target_file == ctx.default_file
    assert proposal.request == "Use UnitySVC (balanced) to rate listings and to chat."


async def test_new_section_inherits_shared_fields(tmp_path: Path) -> None:
    ctx = context(
        tmp_path,
        '[ai.openai]\napi_key = "${OPENAI_API_KEY}"\nmax_retries = 3\ntimeout = 30\n',
    )
    proposal = await converse(["unitysvc", "fast"], ctx)
    assert proposal is not None
    assert proposal.ref.name == "unitysvc"
    assert proposal.values == {
        "api_key": "${UNITYSVC_API_KEY}",
        "model": "fast",
        "max_retries": 3,
        "timeout": 30,
    }


async def test_openai_model_default(tmp_path: Path) -> None:
    proposal = await converse(["openai", ""], context(tmp_path))
    assert proposal is not None
    assert proposal.values == {"api_key": "${OPENAI_API_KEY}", "model": "gpt-4o"}


async def test_ollama_needs_no_key(tmp_path: Path) -> None:
    proposal = await converse(["ollama", "", "llama3"], context(tmp_path))
    assert proposal is not None
    assert proposal.values == {"base_url": "http://localhost:11434/v1", "model": "llama3"}


async def test_existing_section_updated_keeping_var(tmp_path: Path) -> None:
    ctx = context(
        tmp_path,
        '[ai.mine]\nprovider = "unitysvc"\napi_key = "${MY_KEY}"\nmodel = "fast"\ntimeout = 5\n',
    )
    proposal = await converse(["unitysvc", "premium"], ctx)
    assert proposal is not None
    assert proposal.ref.name == "mine"
    assert proposal.values == {
        "provider": "unitysvc",
        "api_key": "${MY_KEY}",
        "model": "premium",
        "timeout": 5,
    }
    assert proposal.target_file == ctx.files[0]


async def test_name_taken_by_other_provider_gets_suffix(tmp_path: Path) -> None:
    ctx = context(tmp_path, '[ai.unitysvc]\nprovider = "openai"\napi_key = "${OPENAI_API_KEY}"\n')
    proposal = await converse(["unitysvc", "balanced"], ctx)
    assert proposal is not None
    assert proposal.ref.name == "unitysvc_2"
    assert proposal.values["provider"] == "unitysvc"


async def test_named_ref_preselects_provider(tmp_path: Path) -> None:
    ctx = context(
        tmp_path, '[ai.local]\nprovider = "ollama"\nbase_url = "http://x:1/v1"\nmodel = "m"\n'
    )
    proposal = await converse(["", "", ""], ctx, SectionRef("ai", "local"))
    assert proposal is not None
    assert proposal.values == {"provider": "ollama", "base_url": "http://x:1/v1", "model": "m"}


async def test_key_like_input_refused(tmp_path: Path) -> None:
    ui = ScriptedChatUI(["openai", "sk-abcdefghijklmnop", "gpt-5"])
    proposal = await ScriptedAIBuilder().converse(ui, SectionRef("ai"), context(tmp_path))
    assert proposal is not None and proposal.values["model"] == "gpt-5"
    [warning] = ui.said("warning")
    assert "sk-abcdefghijklmnop" not in warning and "environment variable" in warning


async def test_quit(tmp_path: Path) -> None:
    assert await converse(["quit"], context(tmp_path)) is None


def written(tmp_path: Path, text: str, values: dict) -> tuple[ChatContext, SectionProposal]:
    ctx = context(tmp_path, text)
    return ctx, SectionProposal(SectionRef("ai", "unitysvc"), values, None, ctx.files[0])


async def test_after_commit_env_set_probe_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_test")
    monkeypatch.setattr(
        ai_module, "probe", lambda s: ProbeResult(True, "request", "balanced", "ok")
    )
    values = {"api_key": "${UNITYSVC_API_KEY}"}
    ctx, proposal = written(tmp_path, '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\n', values)
    outcome = await ScriptedAIBuilder().after_commit(ScriptedChatUI([]), proposal, ctx)
    assert outcome.config is not None and outcome.config.name == "unitysvc"


async def test_after_commit_env_unset_gives_instructions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("UNITYSVC_API_KEY", raising=False)
    values = {"api_key": "${UNITYSVC_API_KEY}"}
    ctx, proposal = written(tmp_path, '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\n', values)
    ui = ScriptedChatUI([])
    outcome = await ScriptedAIBuilder().after_commit(ui, proposal, ctx)
    assert outcome.config is None and not outcome.retry
    text = "\n".join(ui.said())
    assert "https://unitysvc.com" in text
    assert "export UNITYSVC_API_KEY=<your key>" in text
    assert "aimm --chat" in text


async def test_after_commit_probe_failure_offers_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        ai_module, "probe", lambda s: ProbeResult(False, "models", "m", "Can't reach http://x:1/v1")
    )
    values = {"provider": "ollama", "base_url": "http://x:1/v1", "model": "m"}
    ctx, proposal = written(
        tmp_path,
        '[ai.unitysvc]\nprovider = "ollama"\nbase_url = "http://x:1/v1"\nmodel = "m"\n',
        values,
    )
    ui = ScriptedChatUI([])
    outcome = await ScriptedAIBuilder().after_commit(ui, proposal, ctx)
    assert outcome.config is None and outcome.retry
    assert ui.said("error") == ["Can't reach http://x:1/v1"]
