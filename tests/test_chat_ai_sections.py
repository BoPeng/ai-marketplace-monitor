from pathlib import Path

import pytest

from ai_marketplace_monitor.ai import UnitySVCConfig
from ai_marketplace_monitor.chat.ai_sections import (
    ConfigReadError,
    env_var_name,
    load_ai_sections,
)


def write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_env_var_name() -> None:
    assert env_var_name("${UNITYSVC_API_KEY}") == "UNITYSVC_API_KEY"
    assert env_var_name("svcpass_x") is None
    assert env_var_name(None) is None


def test_merge_and_ownership(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNITYSVC_API_KEY", "svcpass_test")
    a = write(tmp_path / "a.toml", '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\n')
    b = write(tmp_path / "b.toml", '[ai.unitysvc]\nmodel = "fast"\n[ai.other]\nprovider = "openai"\napi_key = "k"\n')
    sections = load_ai_sections([a, b])
    assert [s.name for s in sections] == ["unitysvc", "other"]
    unitysvc = sections[0]
    assert unitysvc.raw == {"api_key": "${UNITYSVC_API_KEY}", "model": "fast"}
    assert unitysvc.files == [a, b]
    assert isinstance(unitysvc.config, UnitySVCConfig)
    assert unitysvc.problem is None
    assert sections[1].provider == "openai"


def test_unset_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UNITYSVC_API_KEY", raising=False)
    path = write(tmp_path / "a.toml", '[ai.unitysvc]\napi_key = "${UNITYSVC_API_KEY}"\n')
    [section] = load_ai_sections([path])
    assert section.config is None
    assert section.problem == "Set the environment variable UNITYSVC_API_KEY"


def test_missing_key_uses_provider_message(tmp_path: Path) -> None:
    [section] = load_ai_sections([write(tmp_path / "a.toml", "[ai.unitysvc]\n")])
    assert section.problem is not None
    assert "UnitySVC requires a string api_key" in section.problem


def test_unknown_provider(tmp_path: Path) -> None:
    [section] = load_ai_sections([write(tmp_path / "a.toml", '[ai.x]\nprovider = "foo"\n')])
    assert section.problem == (
        'Unknown provider "foo"; supported: anthropic, deepseek, gemini, ollama, openai, unitysvc'
    )


def test_disabled_section_not_built(tmp_path: Path) -> None:
    [section] = load_ai_sections(
        [write(tmp_path / "a.toml", '[ai.unitysvc]\nenabled = false\napi_key = "k"\n')]
    )
    assert not section.enabled
    assert section.config is None and section.problem is None


def test_unparsable_file(tmp_path: Path) -> None:
    path = write(tmp_path / "bad.toml", "[ai\n")
    with pytest.raises(ConfigReadError) as info:
        load_ai_sections([path])
    assert info.value.path == path
