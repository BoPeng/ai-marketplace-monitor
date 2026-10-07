"""The AI toolkit: [ai.*] sections set up with the AI's help, as the wizard would."""

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

from ai_marketplace_monitor.configure import ai_kit, flow
from ai_marketplace_monitor.configure.ai_kit import AIToolkit
from ai_marketplace_monitor.configure.ai_setup import AISection, ProbeResult
from ai_marketplace_monitor.configure.tools import ToolExecutor
from ai_marketplace_monitor.configure.ui import ScriptedSetupUI
from ai_marketplace_monitor.configure.writer import CommitOutcome, commit_sections
from tests.configure_util import BASE, make_ws, ui_of

A = AIToolkit()
TWO = BASE + '\n[ai.backup]\nprovider = "openai"\napi_key = "${OPENAI_API_KEY}"\n'


async def ws_for(tmp_path: Path, text: str, answers: Any = None) -> Any:
    return await make_ws(tmp_path, text, answers, toolkits={"ai": A})


@pytest.fixture(autouse=True)
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")


@pytest.fixture
def probes(monkeypatch: pytest.MonkeyPatch) -> Dict[str, ProbeResult]:
    """Probe results by section name (default: works); records nothing else."""
    results: Dict[str, ProbeResult] = {}

    async def fake(sections: List[AISection]) -> List[ProbeResult]:
        return [
            results.get(s.name, ProbeResult(True, "request", "m", "ok", ["m", "m2"]))
            for s in sections
        ]

    monkeypatch.setattr(ai_kit, "probe_sections", fake)
    return results


# --- fields and checks ------------------------------------------------------------------------
async def test_literal_keys_are_hidden(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)
    draft = A.view(ws, "unitysvc")
    assert A.masked(draft.values) == {"api_key": "<written in the file; hidden>"}
    assert "svcpass_testkey" not in A.describe(draft)


async def test_validate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    ws = await ws_for(tmp_path, BASE)
    draft = A.view(ws, "claude")
    draft.values = {"provider": "anthropic", "api_key": "${ANTHROPIC_API_KEY}"}
    [error] = A.validate(ws, draft)  # aimm could not start with an unset key
    assert "export ANTHROPIC_API_KEY=<their key>" in error
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert A.validate(ws, draft) == []
    draft.values["timeout"] = "soon"
    assert "timeout" in A.validate(ws, draft)[0]
    draft.values = {"provider": "anthropic", "api_key": "${ANTHROPIC_API_KEY}", "base_url": "x"}
    assert "https://" in A.validate(ws, draft)[0]
    openai = A.view(ws, "openai")
    openai.values = {"provider": "anthropic"}
    assert "named after a provider" in A.validate(ws, openai)[0]
    deepseek = A.view(ws, "deepseek")
    deepseek.values = {"api_key": "${DEEPSEEK_API_KEY}"}
    assert "edited by hand" in A.validate(ws, deepseek)[0]
    draft.values = {"provider": "anthropic", "api_key": "${ANTHROPIC_API_KEY}"}
    draft.values["base_url"] = "http://api.example.com/v1"  # the key would be sent unencrypted
    assert "must use https://" in A.validate(ws, draft)[0]
    local = A.view(ws, "ollama")
    local.values = {"base_url": "http://192.168.1.5:11434/v1", "model": "llama3"}
    assert A.validate(ws, local) == []
    _, problems = A.change(A.view(ws, "unitysvc"), {"api_key": "svcpass_abc"}, [], None)
    assert problems == ["`api_key` is secret: only a ${VAR} reference may be set."]


async def test_missing(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)
    draft = A.view(ws, "backup")
    assert A.missing(ws, draft) == ["provider: choose UnitySVC, OpenAI, Anthropic or Ollama"]
    draft.values = {"provider": "openai"}
    assert A.missing(ws, draft) == ["api_key: a reference such as ${OPENAI_API_KEY}"]
    local = A.view(ws, "ollama")
    assert A.missing(ws, local) == [
        "base_url: required for Ollama",
        "model: required for Ollama",
    ]


async def test_show_and_check(tmp_path: Path, probes: Dict[str, ProbeResult]) -> None:
    ws = await ws_for(tmp_path, TWO)
    ws.ai_in_use = "unitysvc"
    ex = ToolExecutor(ws)
    shown = await ex.call("section_show", {"section_type": "ai", "name": "backup"})
    assert shown["order"] == ["unitysvc", "backup"] and shown["is_default"] is False
    assert shown["in_use_by_this_session"] is False
    probes["backup"] = ProbeResult(
        False, "request", "gpt-4o", "404", ["gpt-4o"], "https://x.example/v1"
    )
    checked = await ex.call("section_check", {"section_type": "ai", "name": "backup"})
    assert checked["trial"] == {
        "works": False,
        "model": "gpt-4o",
        "message": "404",
        "available_models": ["gpt-4o"],
        "suggested_base_url": "https://x.example/v1",
    }


# --- the default and saving ---------------------------------------------------------------
async def test_new_sections_become_the_default_unless_a_backup(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)
    new = A.view(ws, "claude")
    assert A.write_first(new)
    new.values["default"] = False
    assert not A.write_first(new)
    old = A.view(ws, "unitysvc")
    assert not A.write_first(old)
    old.values["default"] = True
    assert A.write_first(old)
    assert "default" not in A.apply(ws.user_cfg, old)["ai"]["unitysvc"]


async def test_preflight_refuses_a_broken_default(
    tmp_path: Path, probes: Dict[str, ProbeResult]
) -> None:
    ws = await ws_for(tmp_path, BASE)
    draft = A.view(ws, "claude")
    draft.values = {"provider": "anthropic", "api_key": "${ANTHROPIC_API_KEY}"}
    probes["claude"] = ProbeResult(False, "config", "m", "Set the environment variable X")
    errors, warnings = await A.preflight(ws, draft)
    assert "cannot be the default AI" in errors[0] and warnings == []
    draft.values["default"] = False
    errors, warnings = await A.preflight(ws, draft)
    assert errors == [] and "does not work yet" in warnings[0]
    del probes["claude"]
    assert await A.preflight(ws, draft) == ([], [])


async def test_the_current_default_must_keep_working(
    tmp_path: Path, probes: Dict[str, ProbeResult]
) -> None:
    ws = await ws_for(tmp_path, TWO)
    default = ws.draft("ai", "unitysvc")
    default.values["model"] = "nope"
    probes["unitysvc"] = ProbeResult(False, "models", "nope", 'Model "nope" is not available')
    errors, _ = await A.preflight(ws, default)
    assert "cannot be the default AI" in errors[0]
    ws.draft("ai", "backup").values["default"] = True  # another section becomes the default
    _, [warning] = await A.preflight(ws, default)
    assert warning.startswith('[ai.unitysvc] does not work yet: Model "nope" is not available')


async def test_save_moves_the_default_first(
    tmp_path: Path, probes: Dict[str, ProbeResult]
) -> None:
    ws = await ws_for(tmp_path, TWO, ["yes"])
    ex = ToolExecutor(ws, only={("ai", "*")})
    ex.guides_read.add("ai")
    out = await ex.call(
        "section_update", {"section_type": "ai", "name": "backup", "values": {"default": True}}
    )
    assert out["ok"], out
    saved = await ex.call("save", {"message": "Making backup the default."})
    assert saved.get("saved"), (saved, ui_of(ws).said())
    written = tomllib.loads((tmp_path / "config.toml").read_text())
    assert list(written["ai"]) == ["backup", "unitysvc"]
    assert written["ai"]["backup"] == {"provider": "openai", "api_key": "${OPENAI_API_KEY}"}
    assert any("takes effect the next time" in n for n in saved["shown_to_user"])
    assert ui_of(ws).questions == ["Write these changes?"]


async def test_a_backup_is_added_after_the_default(
    tmp_path: Path, probes: Dict[str, ProbeResult]
) -> None:
    ws = await ws_for(tmp_path, BASE, ["yes"])
    ex = ToolExecutor(ws, only={("ai", "*")})
    ex.guides_read.add("ai")
    values = '{"provider": "anthropic", "api_key": "${ANTHROPIC_API_KEY}", "default": false}'
    out = await ex.call(
        "section_update", {"section_type": "ai", "name": "claude", "values": values}
    )
    assert out["ok"], out
    assert (await ex.call("save", {"message": ""}))["saved"]
    written = tomllib.loads((tmp_path / "config.toml").read_text())
    assert list(written["ai"]) == ["unitysvc", "claude"]


async def test_writer_moves_a_section_first_across_files(tmp_path: Path) -> None:
    first, second = tmp_path / "a.toml", tmp_path / "b.toml"
    first.write_text('[ai.unitysvc]\napi_key = "${K}"\n\n[user.me]\nemail = "a@b.co"\n')
    second.write_text('[ai.backup]\nprovider = "openai"\napi_key = "${O}"\n')
    old = {
        "ai": {
            "unitysvc": {"api_key": "${K}"},
            "backup": {"provider": "openai", "api_key": "${O}"},
        },
        "user": {"me": {"email": "a@b.co"}},
    }
    ui = ScriptedSetupUI(["yes"])
    outcome = await commit_sections(
        ui, old, old, [first, second], tmp_path / "backups", first=[("ai", "backup")]
    )
    assert outcome is CommitOutcome.WRITTEN
    assert list(tomllib.loads(first.read_text())["ai"]) == ["backup", "unitysvc"]
    assert "backup" not in tomllib.loads(second.read_text()).get("ai", {})


# --- commands -------------------------------------------------------------------------------
@pytest.mark.parametrize("loads, works", [(True, True), (True, False), (False, False)])
async def test_configure_ai_uses_the_ai_when_it_works(
    monkeypatch: pytest.MonkeyPatch, loads: bool, works: bool
) -> None:
    calls: List[Any] = []

    class Backend:
        config = type("C", (), {"name": "unitysvc"})()

    monkeypatch.setattr(
        flow, "default_ai", lambda files: (Backend(), "") if loads else (None, "broken")
    )

    async def tried(ui: Any, files: Any) -> bool:  # a bad key loads, but does not work
        return works

    monkeypatch.setattr(flow, "default_ai_works", tried)

    async def fake_session(ui: Any, files: Any, ai: Any, kits: Any, **kw: Any) -> int:
        calls.append(("session", sorted(kits), kw["target"]))
        return 0

    async def fake_wizard(ui: Any, files: Any, **kw: Any) -> int:
        calls.append(("wizard", kw["section_name"]))
        return 0

    monkeypatch.setattr(flow, "run_session", fake_session)
    monkeypatch.setattr(flow, "configure_ai", fake_wizard)
    assert await flow.configure_section(ScriptedSetupUI([]), [], "ai.claude") == 0
    expected = ("session", ["ai"], ("ai", "claude")) if works else ("wizard", "claude")
    assert calls == [expected]


async def test_start_lists_services_and_starts_at_the_default(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, TWO)
    assert await A.choose_target(ws.ui, ws, None) == "unitysvc"
    shown = ui_of(ws).said()[0]
    assert "**[ai.unitysvc]** (default)" in shown and "svcpass_testkey" not in shown


async def test_values_are_single_strings(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)
    draft = A.view(ws, "unitysvc")
    draft.values["model"] = ["fast"]
    assert A.validate(ws, draft) == [
        '`model` must be a single string, e.g. "balanced" (not a list).'
    ]


async def test_a_new_section_is_followed_by_a_blank_line(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[ai.unitysvc]\napi_key = "k"\n\n[user.me]\nemail = "a@b.co"\n')
    old = {"ai": {"unitysvc": {"api_key": "k"}}, "user": {"me": {"email": "a@b.co"}}}
    new = {"ai": {"unitysvc": {"api_key": "k"}, "fast": {"model": "fast"}}, "user": old["user"]}
    ui = ScriptedSetupUI(["yes"])
    assert await commit_sections(ui, new, old, [path], tmp_path / "b") is CommitOutcome.WRITTEN
    assert '[ai.fast]\nmodel = "fast"\n\n[user.me]' in path.read_text()


async def test_image_options_can_be_set(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)
    draft, problems = A.change(
        A.view(ws, "unitysvc"), {"use_images": True, "image_detail": "low"}, [], None
    )
    assert problems == [] and A.validate(ws, draft) == []
    draft.values["image_detail"] = "huge"
    assert "image_detail" in A.validate(ws, draft)[0]


async def test_summary_shows_whether_photos_are_read(tmp_path: Path) -> None:
    ws = await ws_for(tmp_path, BASE)
    assert A.summary(ws, {}) == (
        "default model; reads listing photos (use_images = false saves tokens)"
    )
    assert A.summary(ws, {"model": "gpt-4o", "use_images": False}) == (
        "model gpt-4o; text only (use_images = true lets it read listing photos)"
    )
